"""LaunchOS launcher.

Shows the home screen (a local web page) full screen, gives that page a small
bridge to the system (window.LOS in los.js), and provides a lightweight browser
window built on the same WebKit engine.
"""
import gc
import glob
import json
import os
import re
import select
import signal
import socket
import subprocess
import threading
import time
import wave
import math
import struct
import sys
import zoneinfo

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('WebKit', '6.0')
from gi.repository import Gtk, Gdk, GLib, Gio, WebKit  # noqa: E402

UI = 'file:///opt/launcher/'
START_PAGE = UI + 'start.html'
REQDIR = '/run/launchos/requests'
SEARCH = 'https://duckduckgo.com/?q='

HOME = os.path.expanduser('~')
# launchos-session sets this: real AMD/Intel/NVIDIA graphics get full acceleration, VMs draw in software
HW = os.environ.get('LAUNCHOS_GPU') == 'hardware'
ACCEL = WebKit.HardwareAccelerationPolicy.ALWAYS if HW else WebKit.HardwareAccelerationPolicy.NEVER

NAVY = Gdk.RGBA()
NAVY.parse('#0b1726')
WHITE = Gdk.RGBA()
WHITE.parse('#ffffff')


# ---------- system information ----------

def read(path, default=''):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def release():
    info = {}
    for line in read('/etc/launchos-release').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k.strip()] = v.strip().strip('"')
    return info


def system_info():
    mem = {}
    for line in read('/proc/meminfo').splitlines():
        parts = line.split()
        if len(parts) >= 2:
            mem[parts[0].rstrip(':')] = int(parts[1])
    cpu = ''
    for line in read('/proc/cpuinfo').splitlines():
        if line.startswith('model name'):
            cpu = line.split(':', 1)[1].strip()
            break
    up = float(read('/proc/uptime', '0').split()[0] or 0)
    rel = release()
    return {
        'version': rel.get('VERSION', '?'),
        'build': rel.get('BUILD_DATE', ''),
        'kernel': os.uname().release,
        'cpu': re.sub(r'\s+', ' ', cpu),
        'cores': os.cpu_count(),
        'mem_total_mb': mem.get('MemTotal', 0) // 1024,
        'mem_free_mb': mem.get('MemAvailable', 0) // 1024,
        'uptime_min': int(up // 60),
        'resolution': screen_size(),
    }


def screen_size():
    try:
        mons = Gdk.Display.get_default().get_monitors()
        if mons.get_n_items():
            g = mons.get_item(0).get_geometry()
            return f'{g.width} x {g.height}'
    except Exception:
        pass
    return ''


def ip_json(*args):
    try:
        out = subprocess.run(['ip', '-j', *args], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out or '[]')
    except Exception:
        return []


def network_status():
    links = []
    for link in ip_json('addr', 'show'):
        name = link.get('ifname', '')
        if name == 'lo':
            continue
        v4 = [a['local'] for a in link.get('addr_info', []) if a.get('family') == 'inet']
        links.append({'name': name, 'up': 'UP' in link.get('flags', []) and 'LOWER_UP' in link.get('flags', []),
                      'mac': link.get('address', ''), 'ipv4': v4})
    gateway = ''
    for r in ip_json('route', 'show', 'default'):
        gateway = r.get('gateway', '')
        break
    dns = re.findall(r'^nameserver\s+(\S+)', read('/run/systemd/resolve/resolv.conf'), re.M)
    connected = any(l['up'] and l['ipv4'] for l in links)
    return {'links': links, 'gateway': gateway, 'dns': dns, 'connected': connected}


def internet_test():
    """Checks DNS and an HTTPS connection to a well-known host."""
    try:
        addr = socket.getaddrinfo('example.com', 443, proto=socket.IPPROTO_TCP)[0][4]
    except OSError:
        return {'online': False, 'reason': 'Can’t look up websites (DNS isn’t working).'}
    try:
        with socket.create_connection(addr[:2], timeout=4):
            return {'online': True}
    except OSError:
        return {'online': False, 'reason': 'Websites are found but can’t be reached.'}


def input_devices():
    skip = ('Power Button', 'Sleep Button', 'PC Speaker', 'Video Bus', 'Lid Switch', 'Macintosh mouse button emulation',
            'Consumer Control', 'System Control', 'WMI', 'hotkeys', 'Hotkeys', 'Intel HID events', 'HDA ', 'HDMI/DP',
            'Headphone', 'Mic', 'Front Headphone', 'Line Out', 'Wireless Radio Control', 'UVC Camera', 'Webcam')
    devices, cur = [], {}
    for line in read('/proc/bus/input/devices').splitlines() + ['']:
        if not line.strip():
            if cur:
                devices.append(cur)
            cur = {}
            continue
        if line.startswith('I:'):
            cur['usb'] = 'Bus=0003' in line
        elif line.startswith('N:'):
            cur['name'] = line.split('=', 1)[1].strip().strip('"')
        elif line.startswith('H:'):
            cur['handlers'] = line.split('=', 1)[1].split()
        elif line.startswith('B: KEY='):
            bits = 0
            for w in line.split('=', 1)[1].split():
                bits = (bits << 64) | int(w, 16)
            cur['gamepad'] = bool(bits >> 0x130 & 1)   # BTN_SOUTH: the A button
    out = []
    for d in devices:
        name, h = d.get('name', ''), d.get('handlers', [])
        if not name or any(s in name for s in skip):
            continue
        if d.get('gamepad') or any(x.startswith('js') for x in h):
            kind = 'controller'
        elif any(x.startswith('mouse') for x in h):
            kind = 'mouse'
        elif 'kbd' in h:
            kind = 'keyboard'
        else:
            continue
        out.append({'name': name, 'kind': kind, 'usb': d.get('usb', False)})
    return out


def amixer(*args):
    try:
        return subprocess.run(['amixer', *args], capture_output=True, text=True, timeout=3)
    except Exception:
        return None


def wpctl(*args):
    try:
        return subprocess.run(['wpctl', *args], capture_output=True, text=True, timeout=3)
    except Exception:
        return None


def volume_get():
    r = wpctl('get-volume', '@DEFAULT_AUDIO_SINK@')
    if r and r.returncode == 0:
        m = re.search(r'Volume:\s*([\d.]+)', r.stdout)
        if m:
            return {'available': True, 'value': round(min(1.0, float(m.group(1))) * 100), 'muted': 'MUTED' in r.stdout}
    for ctl in ('Master', 'PCM'):
        r = amixer('-M', 'sget', ctl)
        if r and r.returncode == 0:
            m = re.search(r'\[(\d+)%\]', r.stdout)
            muted = '[off]' in r.stdout
            if m:
                return {'available': True, 'value': int(m.group(1)), 'muted': muted}
    return {'available': False}


def volume_set(value):
    v = max(0, min(100, int(value)))
    r = wpctl('set-volume', '@DEFAULT_AUDIO_SINK@', f'{v / 100:.2f}')
    if r and r.returncode == 0:
        wpctl('set-mute', '@DEFAULT_AUDIO_SINK@', '1' if v == 0 else '0')
        return volume_get()
    for ctl in ('Master', 'PCM'):   # first control that exists
        r = amixer('-q', '-M', 'sset', ctl, f'{v}%', 'unmute' if v > 0 else 'mute')
        if r and r.returncode == 0:
            break
    return volume_get()


def play_test_sound():
    path = '/tmp/launchos-chime.wav'
    if not os.path.exists(path):
        rate = 44100
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            frames = bytearray()
            for freq, dur in ((660, 0.12), (880, 0.12), (1320, 0.22)):
                n = int(rate * dur)
                for i in range(n):
                    env = min(1, i / 400) * min(1, (n - i) / 2000)
                    frames += struct.pack('<h', int(9000 * env * math.sin(2 * math.pi * freq * i / rate)))
            w.writeframes(bytes(frames))
    subprocess.Popen(['aplay', '-q', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'ok': True}


def timezones():
    zones = sorted(z for z in zoneinfo.available_timezones()
                   if '/' in z and z.split('/')[0] in ('Africa', 'America', 'Asia', 'Atlantic', 'Australia', 'Europe', 'Pacific', 'Indian'))
    return zones


def timezone_get():
    try:
        return os.path.realpath('/etc/localtime').split('/zoneinfo/', 1)[1]
    except (IndexError, OSError):
        return 'UTC'


def log_error(arg):
    """A script error on one of LaunchOS's own pages, kept for finding problems later."""
    arg = arg if isinstance(arg, dict) else {}
    path = os.path.join(HOME, '.cache', 'launchos', 'ui-errors.log')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            os.replace(path, path + '.old')
        with open(path, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + ' | '.join(str(arg.get(k, ''))[:500].replace('\n', ' ') for k in ('page', 'where', 'msg')) + '\n')
    except OSError:
        pass
    return {'ok': True}


_req_lock = threading.Lock()
_req_seq = [0]


def helper_request(payload):
    """Hands a request to the root helper: each one is its own file in the queue folder
    (written under a temporary name and renamed in, so it's never seen half-written)."""
    with _req_lock:
        _req_seq[0] += 1
        name = f'{time.time_ns():020d}-{os.getpid()}-{_req_seq[0]}.json'
    tmp = os.path.join(os.path.dirname(REQDIR), '.' + name)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # may hold a password
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps(payload))
        os.replace(tmp, os.path.join(REQDIR, name))
        return {'ok': True}
    except OSError as e:
        return {'ok': False, 'error': str(e)}



# ---------- system monitor ----------

CLK = os.sysconf('SC_CLK_TCK')
_prev = {'t': None, 'cpu': None, 'net': None, 'procs': {}}

FRIENDLY = {
    # /proc/<pid>/stat names are cut to 15 characters
    'cage': 'Display server', 'WebKitWebProces': 'Page renderer (web engine)', 'WebKitNetworkPr': 'Web engine networking',
    'WebKitGPUProces': 'Web engine graphics', 'Xwayland': 'App compatibility (X11)', 'pipewire': 'Sound server',
    'wireplumber': 'Sound session', 'sd-pam': 'Login session', 'agetty': 'Text login', 'login': 'Text login',
    'systemd': 'System manager', 'systemd-journal': 'System log', 'systemd-udevd': 'Device manager', 'systemd-network': 'Network',
    'systemd-resolve': 'Name lookup (DNS)', 'systemd-timesyn': 'Network time', 'systemd-logind': 'Login manager',
    'dbus-daemon': 'Message bus', 'seatd': 'Seat manager', 'plymouthd': 'Boot screen', 'bash': 'Text console', 'aplay': 'Sound player',
}


def _cpu_times():
    out = []
    for line in read('/proc/stat').splitlines():
        if line.startswith('cpu'):
            parts = line.split()
            vals = list(map(int, parts[1:9]))
            idle = vals[3] + vals[4]
            out.append((parts[0], sum(vals), idle))
    return out


def _net_bytes():
    rx = tx = 0
    for line in read('/proc/net/dev').splitlines()[2:]:
        name, data = line.split(':', 1)
        if name.strip() == 'lo':
            continue
        f = data.split()
        rx += int(f[0]); tx += int(f[8])
    return rx, tx


def _proc_name(pid, comm):
    if comm.startswith('python'):
        cmd = read(f'/proc/{pid}/cmdline').replace('\0', ' ')
        if 'launch.py' in cmd:
            return 'LaunchOS home and browser'
        if 'launchos-helper' in cmd:
            return 'LaunchOS helper'
    if comm == 'systemd' and pid != '1':
        return 'User session manager'
    return FRIENDLY.get(comm.strip('()'), comm)


def system_stats():
    now = time.monotonic()
    dt = (now - _prev['t']) if _prev['t'] else None
    # CPU: total and per core, as percent busy since the last sample
    cpu = _cpu_times()
    total, cores = None, []
    if _prev['cpu'] and dt:
        for (name, tot, idle), (_, ptot, pidle) in zip(cpu, _prev['cpu']):
            d = tot - ptot
            busy = 0 if d <= 0 else max(0.0, min(100.0, 100.0 * (d - (idle - pidle)) / d))
            if name == 'cpu':
                total = round(busy, 1)
            else:
                cores.append(round(busy, 1))
    _prev['cpu'] = cpu
    # Memory
    mem = {}
    for line in read('/proc/meminfo').splitlines():
        parts = line.split()
        if len(parts) >= 2:
            mem[parts[0].rstrip(':')] = int(parts[1]) * 1024
    mt, ma = mem.get('MemTotal', 0), mem.get('MemAvailable', 0)
    # Network speed
    rx, tx = _net_bytes()
    down = up = None
    if _prev['net'] and dt:
        down = max(0, (rx - _prev['net'][0]) / dt)
        up = max(0, (tx - _prev['net'][1]) / dt)
    _prev['net'] = (rx, tx)
    # Storage: on the live system this is the in-memory overlay
    try:
        st = os.statvfs('/')
        disk_total = st.f_blocks * st.f_frsize
        disk_used = (st.f_blocks - st.f_bfree) * st.f_frsize
    except OSError:
        disk_total = disk_used = 0
    # Processes: CPU percent (of one core) since the last sample, and memory
    procs, seen = [], {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        stat = read(f'/proc/{pid}/stat')
        if not stat:
            continue
        try:
            comm = stat[stat.index('(') + 1:stat.rindex(')')]
            fields = stat[stat.rindex(')') + 2:].split()
            ticks = int(fields[11]) + int(fields[12])
            rss = int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, IndexError):
            continue
        seen[pid] = ticks
        prev = _prev['procs'].get(pid)
        pcpu = round(100.0 * (ticks - prev) / CLK / dt, 1) if (prev is not None and dt) else 0.0
        if rss > 0:
            procs.append({'pid': int(pid), 'name': _proc_name(pid, comm), 'cpu': max(0.0, pcpu), 'mem': rss})
    _prev['procs'] = seen
    _prev['t'] = now
    procs.sort(key=lambda x: (x['cpu'], x['mem']), reverse=True)
    load = read('/proc/loadavg', '0 0 0').split()[:3]
    temps = []
    for z in sorted(os.listdir('/sys/class/thermal')) if os.path.isdir('/sys/class/thermal') else []:
        t = read(f'/sys/class/thermal/{z}/temp').strip()
        if t.lstrip('-').isdigit():
            temps.append(round(int(t) / 1000, 1))
    return {
        'cpu': total, 'cores': cores, 'ncores': os.cpu_count(),
        'mem_total': mt, 'mem_used': mt - ma,
        'net_down': down, 'net_up': up,
        'disk_total': disk_total, 'disk_used': disk_used,
        'procs': procs[:8], 'nprocs': len(seen),
        'load': load, 'uptime_s': int(float(read('/proc/uptime', '0').split()[0] or 0)),
        'temps': temps,
    }

# ---------- browser ----------

BROWSER_CSS = b"""
.losbar { background: #0f1b2a; padding: 8px 10px; border-bottom: 1px solid #22344a; }
.losbar button { background: #16273b; color: #dce6f0; border: none; border-radius: 18px; min-height: 34px; min-width: 34px; padding: 0 12px; box-shadow: none; }
.losbar button:hover { background: #1f3550; }
.losbar button:disabled { color: #4f6378; }
.losbar button.home { background: #3ddc6b; color: #0b1726; font-weight: bold; }
.losbar entry { background: #16273b; color: #f2f4f3; border: 1px solid #22344a; border-radius: 18px; min-height: 34px; padding: 0 14px; caret-color: #3ddc6b; }
.losbar entry:focus-within { border-color: #3ddc6b; }
.losnote { background: #16273b; color: #dce6f0; padding: 8px 14px; }
window, window.background { background: #0b1726; }
.lospanel { background: #0f1b2a; border-radius: 14px; border: 1px solid #2a4260; box-shadow: 0 0 0 10px rgba(95,184,255,.05), 0 10px 60px rgba(0,0,0,.6); }
.lospanel .losbar { border-radius: 14px 14px 0 0; }
.lostitle { color: #f2f4f3; font-weight: bold; font-size: 16px; padding-left: 6px; }
"""


def to_url(text):
    t = text.strip()
    if not t:
        return START_PAGE
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', t) or t.startswith('about:'):
        return t
    if ' ' not in t and re.match(r'^[^/\s]+\.[a-zA-Z]{2,}(/.*)?$', t):
        return 'https://' + t
    if re.match(r'^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(/.*)?$', t):
        return 'http://' + t
    return SEARCH + GLib.uri_escape_string(t, None, True)


PAD_EXIT_JS = """
(function () {
  if (!navigator.getGamepads) return;
  let held = false;
  setInterval(function () {
    const g = Array.from(navigator.getGamepads()).find(function (x) { return x; });
    if (!g) return;
    const b = function (i) { return g.buttons[i] && g.buttons[i].pressed; };
    if (b(16) || (b(8) && b(9))) {
      if (!held) { held = true; window.webkit.messageHandlers.losbrowser.postMessage('home'); }
    } else { held = false; }
  }, 100);
})();
"""


SUPER_KEYS = (Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R)
MAX_APPS = 3   # web apps kept running in the background; the least recently used one is ended past this


class Browser(Gtk.ApplicationWindow):
    """A web app window. Going Home hides it and keeps it running; ending it closes it."""

    def __init__(self, app, url, app_id='browser', name='Browser'):
        super().__init__(application=app, title=name)
        self.launcher = app
        self.app_id, self.name = app_id, name
        self.started = self.last_used = time.monotonic()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8)
        bar.add_css_class('losbar')

        def btn(label, tip, cb, css=None):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.connect('clicked', lambda *_: cb())
            if css:
                b.add_css_class(css)
            bar.append(b)
            return b

        btn('⌂  Home', 'Back to Home, keeps running (Super key)', self.go_home, 'home')
        self.back = btn('←', 'Back (Alt+Left)', lambda: self.view.go_back())
        self.fwd = btn('→', 'Forward (Alt+Right)', lambda: self.view.go_forward())
        btn('↻', 'Reload (F5)', lambda: self.view.reload())
        self.entry = Gtk.Entry(hexpand=True, placeholder_text='Search or type a web address')
        self.entry.connect('activate', lambda e: self.go(e.get_text()))
        bar.append(self.entry)
        btn('Start page', 'Start page', lambda: self.go(START_PAGE))

        self.note = Gtk.Label(xalign=0)
        self.note.add_css_class('losnote')
        self.note.set_visible(False)

        # Lets a controller leave the browser: the Guide (Xbox) button, or View + Menu together.
        ucm = WebKit.UserContentManager()
        ucm.connect('script-message-received::losbrowser', lambda m, v: self.go_home())
        ucm.register_script_message_handler('losbrowser', None)
        ucm.add_script(WebKit.UserScript.new(PAD_EXIT_JS, WebKit.UserContentInjectedFrames.TOP_FRAME,
                                             WebKit.UserScriptInjectionTime.END, None, None))
        # Apps share the engine's default context: it keeps at most one spare process, reused by the next app.
        self.view = WebKit.WebView(vexpand=True, user_content_manager=ucm)
        # never laid out at zero height: WebKit (2.48+, software drawing) doesn't recover from a first
        # frame of 0 pixels and the page stays blank
        self.view.set_size_request(200, 200)
        self.view.set_background_color(NAVY)
        s = self.view.get_settings()
        s.set_hardware_acceleration_policy(ACCEL)
        s.set_enable_developer_extras(False)
        s.set_enable_page_cache(False)   # no extra processes parked for Back; keeps background apps small
        s.set_user_agent_with_application_details('LaunchOS', release().get('VERSION', '0'))
        self.view.connect('load-changed', self.on_load)
        self.view.connect('notify::uri', lambda *_: self.sync())
        self.view.connect('create', self.on_create)
        self.view.connect('decide-policy', self.on_policy)
        self.view.connect('permission-request', lambda v, req: (req.deny(), True)[1])
        self.view.connect('load-failed', self.on_failed)

        box.append(bar)
        box.append(self.note)
        box.append(self.view)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_key)
        self.add_controller(keys)

        self.go(url or START_PAGE)
        self.fullscreen()
        self.present()

    def go_home(self):
        """Back to Home; the app keeps running so it can be resumed or ended later."""
        if self.get_visible():
            self.set_visible(False)
            self.launcher.on_app_hidden(self)

    def shutdown(self):
        """End the app: stop its page process, close the window and let go of everything it held."""
        if self.view is None:
            return
        try:
            self.view.terminate_web_process()
        except Exception:
            pass
        self.destroy()
        self.view = None

    def resume(self):
        self.last_used = time.monotonic()
        self.set_visible(True)
        self.fullscreen()
        self.present()
        self.view.grab_focus()

    def page_title(self):
        return self.view.get_title() or '' if self.view else ''

    def page_uri(self):
        return self.view.get_uri() or '' if self.view else ''

    def go(self, text):
        self.note.set_visible(False)
        self.view.load_uri(to_url(text))
        self.view.grab_focus()

    def sync(self):
        if self.view is None:   # app already ended
            return
        uri = self.view.get_uri() or ''
        if not (self.entry.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN):
            self.entry.set_text('' if uri.startswith(UI) else uri)
        self.back.set_sensitive(self.view.can_go_back())
        self.fwd.set_sensitive(self.view.can_go_forward())

    def on_load(self, view, event):
        if self.view is None:
            return
        if event == WebKit.LoadEvent.COMMITTED:
            # Websites that set no background expect white, like any browser; the start page stays navy.
            uri = self.view.get_uri() or ''
            self.view.set_background_color(NAVY if uri.startswith(UI) else WHITE)
        self.sync()

    def on_failed(self, view, event, uri, error):
        quiet = [(WebKit.NetworkError, 'CANCELLED'), (WebKit.PolicyError, 'FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE'),
                 (getattr(WebKit, 'MediaError', None), 'WILL_HANDLE_LOAD')]
        for domain, code in quiet:   # downloads and media aren't failures
            if domain is not None and hasattr(domain, code) and error.matches(domain.quark(), getattr(domain, code)):
                return False
        self.show_note('Couldn’t open that page. Check your connection in Settings → Network.')
        return False

    def on_create(self, view, action):
        # A site asked for a new window: open it here instead (one page per app),
        # but never blank pop-ups or local files.
        uri = action.get_request().get_uri() or ''
        if uri.startswith(('http://', 'https://')):
            GLib.idle_add(lambda: (self.view is not None and self.view.load_uri(uri), False)[1])
        return None

    def on_policy(self, view, decision, kind):
        if kind == WebKit.PolicyDecisionType.RESPONSE and not decision.is_mime_type_supported():
            if (decision.get_request().get_uri() or '').startswith('file:'):
                decision.ignore()   # a file from Files that can't be shown here: don't copy it into Downloads
                self.show_note('LaunchOS can’t open this kind of file.')
                return True
            decision.download()   # saved to Downloads (see Launcher.on_download)
            return True
        return False

    def show_note(self, text):
        self.note.set_text(text)
        self.note.set_visible(True)

    def on_key(self, ctl, keyval, code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        alt = state & Gdk.ModifierType.ALT_MASK
        if keyval in SUPER_KEYS:
            self.go_home(); return True
        if ctrl and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.entry.grab_focus(); self.entry.select_region(0, -1); return True
        if ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.close(); return True
        if alt and keyval == Gdk.KEY_Left:
            self.view.go_back(); return True
        if alt and keyval == Gdk.KEY_Right:
            self.view.go_forward(); return True
        if keyval == Gdk.KEY_F5:
            self.view.reload(); return True
        return False


# ---------- terminal ----------

try:
    gi.require_version('Vte', '3.91')
    gi.require_version('Pango', '1.0')
    from gi.repository import Vte, Pango  # noqa: E402
except (ValueError, ImportError):   # the terminal is simply missing if the library isn't there
    Vte = None

TERM_COLORS = ['#1a2b40', '#e66767', '#3ddc6b', '#e6c75a', '#5fb8ff', '#b48cff', '#4fd1c5', '#dce6f0',
               '#4f6378', '#ff8a8a', '#7cf09a', '#ffe08a', '#8fd0ff', '#d0b8ff', '#8ff0e4', '#ffffff']


def rgba(hexcolor):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return c


class TermWin(Gtk.ApplicationWindow):
    """A terminal, full screen like the other apps. Going Home keeps it (and what's running
    in it) going; End task closes it."""

    def __init__(self, app, app_id='terminal', name='Terminal'):
        super().__init__(application=app, title=name)
        self.launcher = app
        self.app_id, self.name = app_id, name
        self.started = self.last_used = time.monotonic()
        self.view = None
        self.font_size = 13
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8)
        bar.add_css_class('losbar')

        def btn(label, tip, cb, css=None):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.connect('clicked', lambda *_: (cb(), self.term.grab_focus()))
            if css:
                b.add_css_class(css)
            bar.append(b)
            return b

        btn('⌂  Home', 'Back to Home, keeps running (Super key)', self.go_home, 'home')
        self.title = Gtk.Label(label='Terminal', xalign=0, hexpand=True)
        self.title.add_css_class('lostitle')
        bar.append(self.title)
        btn('Copy', 'Copy (Ctrl+Shift+C)', lambda: self.term.copy_clipboard_format(Vte.Format.TEXT))
        btn('Paste', 'Paste (Ctrl+Shift+V)', lambda: self.term.paste_clipboard())
        btn('A−', 'Smaller text (Ctrl+minus)', lambda: self.zoom(-1))
        btn('A+', 'Bigger text (Ctrl+plus)', lambda: self.zoom(1))

        self.term = Vte.Terminal(vexpand=True, hexpand=True)
        self.term.set_colors(rgba('#dce6f0'), rgba('#0b1726'), [rgba(c) for c in TERM_COLORS])
        self.term.set_color_cursor(rgba('#3ddc6b'))
        self.term.set_color_cursor_foreground(rgba('#0b1726'))
        self.term.set_scrollback_lines(10000)
        self.term.set_mouse_autohide(True)
        self.term.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)   # no constant redrawing on software graphics
        self.term.connect('window-title-changed', self.on_title)
        self.term.connect('child-exited', self.on_exit)
        self.zoom(0)
        self.term.set_margin_start(10)
        self.term.set_margin_top(6)
        box.append(bar)
        box.append(self.term)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_key)
        self.add_controller(keys)

        env = [f'{k}={v}' for k, v in os.environ.items() if k not in ('LIBGL_ALWAYS_SOFTWARE',)]
        env += ['TERM=xterm-256color', 'COLORTERM=truecolor']
        self.term.spawn_async(Vte.PtyFlags.DEFAULT, HOME, ['/bin/bash', '-l'], env, GLib.SpawnFlags.DEFAULT,
                              None, None, -1, None, self.on_spawned, None)
        self.fullscreen()
        self.present()
        self.term.grab_focus()

    # the same small interface as the browser windows
    def page_title(self):
        return self.title.get_label()

    def page_uri(self):
        return ''

    def on_spawned(self, term, pid, error, *data):
        if error is not None and self.term is not None:
            self.term.feed(b'\r\n  The terminal couldn\'t start. Press Super to go back to Home.\r\n')

    def zoom(self, d):
        self.font_size = max(8, min(32, self.font_size + d))
        self.term.set_font(Pango.FontDescription(f'DejaVu Sans Mono {self.font_size}'))

    def on_title(self, term):
        t = term.get_window_title() or ''
        self.title.set_label(t[:80] or 'Terminal')

    def on_exit(self, term, status):
        # "exit" typed: the app ends, like closing it
        if self.term is not None and self.launcher.apps.get(self.app_id) is self:
            GLib.idle_add(lambda: (self.launcher.end_app(self.app_id), False)[1])

    def on_key(self, ctl, keyval, code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        if keyval in SUPER_KEYS:
            self.go_home(); return True
        if ctrl and shift and keyval in (Gdk.KEY_C, Gdk.KEY_c):
            self.term.copy_clipboard_format(Vte.Format.TEXT); return True
        if ctrl and shift and keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self.term.paste_clipboard(); return True
        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.zoom(1); return True
        if ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom(-1); return True
        return False

    def go_home(self):
        if self.get_visible():
            self.set_visible(False)
            self.launcher.on_app_hidden(self)

    def resume(self):
        self.last_used = time.monotonic()
        self.set_visible(True)
        self.fullscreen()
        self.present()
        self.term.grab_focus()

    def shutdown(self):
        """Closing the window hangs up the shell and what runs in it."""
        if self.term is None:
            return
        self.term = None
        self.destroy()


# ---------- outside apps ----------

# Apps LaunchOS offers in Setup and shows on Home. Apps with a Flathub id install from Flathub
# (picked in Setup, or the first time you open them); Steam and Windows programs come with LaunchOS.
APPS = [
    {'key': 'steam', 'name': 'Steam', 'what': 'PC games, with Proton for Windows games'},
    {'key': 'discord', 'name': 'Discord', 'what': 'Chat, voice and video with friends', 'flatpak': 'com.discordapp.Discord'},
    {'key': 'spotify', 'name': 'Spotify', 'what': 'Music and podcasts', 'flatpak': 'com.spotify.Client'},
    {'key': 'freetube', 'name': 'FreeTube', 'what': 'Watch YouTube without ads', 'flatpak': 'io.freetubeapp.FreeTube'},
    {'key': 'roblox', 'name': 'Roblox', 'what': 'Through Sober, made for Linux', 'flatpak': 'org.vinegarhq.Sober'},
    {'key': 'minecraft', 'name': 'Minecraft', 'what': 'Java Edition, through Prism Launcher', 'flatpak': 'org.prismlauncher.PrismLauncher'},
    {'key': 'heroic', 'name': 'Heroic', 'what': 'Your Epic Games, GOG and Amazon games', 'flatpak': 'com.heroicgameslauncher.hgl'},
    {'key': 'obs', 'name': 'OBS Studio', 'what': 'Record and stream your games', 'flatpak': 'com.obsproject.Studio'},
    {'key': 'vlc', 'name': 'VLC', 'what': 'Plays any video or music file', 'flatpak': 'org.videolan.VLC'},
    {'key': 'winprog', 'name': 'Windows programs', 'what': 'Run .exe files with Wine'},
]
APP_BY_KEY = {a['key']: a for a in APPS}
FLATPAKS = {a['key']: (a['flatpak'], a['name']) for a in APPS if a.get('flatpak')}
CURATED_IDS = {a['flatpak'] for a in APPS if a.get('flatpak')}
FLATPAK_ICONS = '/var/lib/flatpak/exports/share/icons/hicolor'
PROGRAM_ROOTS = [os.path.join(HOME, d) for d in ('Downloads', 'Desktop', 'Documents')] + ['/media/player']   # searched by Windows programs


def flatpak_installed(app):
    return os.path.isdir(os.path.join('/var/lib/flatpak/app', app))


def app_icon(app_id):
    """The app's own icon: from the installed app, else from Flathub's catalog. '' if none."""
    if not APP_ID.fullmatch(app_id or ''):
        return ''
    for size in ('256x256', '128x128', '512x512', 'scalable', '64x64'):
        for ext in ('png', 'svg'):
            p = os.path.join(FLATPAK_ICONS, size, 'apps', f'{app_id}.{ext}')
            if os.path.exists(p):
                return p
    for size in ('128x128', '64x64'):
        p = os.path.join(APPSTREAM, 'icons', size, app_id + '.png')
        if os.path.exists(p):
            return p
    return ''


def steam_icon():
    """Steam's own icon, which Steam puts in place the first time it runs. (Debian's icon is
    for the Steam installer; until then the page shows the icon theme's Steam icon.)"""
    for size in ('256x256', '128x128', '48x48'):
        p = os.path.join(HOME, '.local/share/icons/hicolor', size, 'apps/steam.png')
        if os.path.exists(p):
            return p
    return ''


def apps_info():
    """The apps LaunchOS offers, whether each is on this PC, and its icon."""
    apps = []
    for a in APPS:
        x = dict(a)
        if a.get('flatpak'):
            x['installed'] = flatpak_installed(a['flatpak'])
            x['icon'] = app_icon(a['flatpak'])
        elif a['key'] == 'steam':
            x['installed'] = os.path.exists('/usr/games/steam')
            x['icon'] = steam_icon()
        else:
            x['installed'] = os.path.exists('/usr/bin/wine')
            x['icon'] = ''
        apps.append(x)
    by = {a['key']: a for a in apps}
    return {'apps': apps, 'job': job_status('store'), 'gpu': 'hardware' if HW else 'software',
            # older pages ask by name
            'steam': {'installed': by['steam']['installed']}, 'wine': {'installed': by['winprog']['installed']},
            'roblox': {'installed': by['roblox']['installed']}, 'freetube': {'installed': by['freetube']['installed']}}


def program_path_ok(path):
    try:
        real = os.path.realpath(str(path))
    except (TypeError, ValueError):
        return None
    if not real.lower().endswith(('.exe', '.msi')) or not os.path.isfile(real):
        return None
    try:
        fs_real(real)   # anywhere in your folders (not hidden ones) or on an open drive
    except FsError:
        return None
    return real


def ext_command(app_id, path=None):
    """(name, argv, working folder, title) for an outside app, or None if it can't start."""
    if app_id == 'steam' and os.path.exists('/usr/games/steam'):
        return 'Steam', ['env', 'PATH=/usr/local/lib/launchos/steam-shim:' + os.environ.get('PATH', '/usr/bin:/bin'),
                         '/usr/games/steam', '-gamepadui'], HOME, 'Steam'
    if app_id in FLATPAKS and flatpak_installed(FLATPAKS[app_id][0]):
        app, name = FLATPAKS[app_id]
        return name, ['flatpak', 'run', app], HOME, name
    if app_id.startswith('app:') and APP_ID.fullmatch(app_id[4:]) and flatpak_installed(app_id[4:]):
        aid = app_id[4:]   # an app from the Store
        name = (_store['by_id'].get(aid) or {}).get('name') or aid.split('.')[-1]
        return name, ['flatpak', 'run', aid], HOME, name
    if app_id == 'winprog':
        real = program_path_ok(path)
        if real and os.path.exists('/usr/bin/wine'):
            title = os.path.splitext(os.path.basename(real))[0]
            argv = ['wine', 'msiexec', '/i', real] if real.lower().endswith('.msi') else ['wine', real]
            return 'Windows program', argv, os.path.dirname(real), title
    return None


class ExtApp:
    """An outside app in its own process group, so End task stops all of it."""

    def __init__(self, app_id, name, argv, cwd, title):
        self.app_id, self.name, self.title = app_id, name, title
        self.started = self.last_used = time.monotonic()
        logdir = os.path.join(HOME, '.cache', 'launchos')
        os.makedirs(logdir, exist_ok=True)
        log = open(os.path.join(logdir, app_id + '.log'), 'ab')
        self.proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        log.close()
        self.pgid = self.proc.pid

    def alive(self):
        if self.proc.poll() is None:
            return True
        try:   # the starter may exit while the app it launched keeps running (Steam does this)
            os.killpg(self.pgid, 0)
            return True
        except OSError:
            return False

    def end(self):
        try:
            os.killpg(self.pgid, signal.SIGTERM)
        except OSError:
            return
        pgid = self.pgid

        def kill():
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
            return False
        GLib.timeout_add(5000, kill)


class SwayWatcher(threading.Thread):
    """Tells the launcher when a window that isn't ours appears (sway's window events)."""

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback

    def run(self):
        while True:
            try:
                p = subprocess.Popen(['swaymsg', '-t', 'subscribe', '-m', '["window"]'],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in p.stdout:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    con = ev.get('container') or {}
                    if ev.get('change') == 'new' and con.get('app_id') != 'os.launch.home':
                        GLib.idle_add(self.callback)
                p.wait()
            except Exception:
                pass
            time.sleep(3)   # sway not ready yet, or restarted


KEY_LEFTMETA, KEY_RIGHTMETA, BTN_MODE = 125, 126, 316
EVENT = struct.Struct('llHHi')


def has_keys(event_path, codes):
    """Does this input device have any of these keys? (from its sysfs key bitmap)"""
    name = os.path.basename(event_path)
    words = read(f'/sys/class/input/{name}/device/capabilities/key').split()
    if not words:
        return False
    bits = 0
    for w in words:
        bits = (bits << 64) | int(w, 16)
    return any(bits >> c & 1 for c in codes)


class InputWatcher(threading.Thread):
    """Watches keyboards and controllers for Super / the Xbox button, so they work even
    when an outside app (a game) has the screen."""

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback

    def run(self):
        fds, last_scan = {}, 0.0
        while True:
            now = time.monotonic()
            if now - last_scan > 3:
                last_scan = now
                for path in glob.glob('/dev/input/event*'):
                    if path not in fds and has_keys(path, (KEY_LEFTMETA, KEY_RIGHTMETA, BTN_MODE)):
                        try:
                            fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                        except OSError:
                            pass
            if not fds:
                time.sleep(1)
                continue
            try:
                ready, _, _ = select.select(list(fds.values()), [], [], 1.0)
            except (OSError, ValueError):
                ready = []
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:   # unplugged
                    for p, f in list(fds.items()):
                        if f == fd:
                            del fds[p]
                    os.close(fd)
                    continue
                for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, value = EVENT.unpack_from(data, off)
                    if typ == 1 and value == 1 and code in (KEY_LEFTMETA, KEY_RIGHTMETA, BTN_MODE):
                        GLib.idle_add(self.callback)


def job_status(name):
    name = str(name or '')
    if not re.fullmatch(r'[a-z\-]{1,30}', name):
        return {}
    try:
        with open(f'/run/launchos-status/{name}.json') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get_app(arg):
    """Install apps from Setup or Home: one key ('discord') or a list of keys."""
    keys = arg if isinstance(arg, list) else [arg]
    ids = [FLATPAKS[k][0] for k in keys if isinstance(k, str) and k in FLATPAKS and not flatpak_installed(FLATPAKS[k][0])]
    if not ids:
        return {'ok': True, 'nothing': True}
    names = [FLATPAKS[k][1] for k in keys if isinstance(k, str) and k in FLATPAKS and FLATPAKS[k][0] in ids]
    return store_action({'op': 'install', 'apps': ids, 'name': and_list(names)})


def and_list(names):
    names = list(names)
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def win_programs():
    """Windows programs (.exe/.msi) in Downloads, Desktop, Documents and on USB drives."""
    found = []
    for root in PROGRAM_ROOTS:
        base_depth = root.rstrip('/').count('/')
        for dirpath, dirs, files in os.walk(root):
            if dirpath.count('/') - base_depth >= 4:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in ('windows', '$recycle.bin', 'system volume information')]
            for f in files:
                if f.lower().endswith(('.exe', '.msi')) and not f.lower().startswith('unins'):
                    full = os.path.join(dirpath, f)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    where = 'USB drive' if root == '/media/player' else os.path.basename(root)
                    found.append({'name': os.path.splitext(f)[0], 'path': full, 'where': where,
                                  'size': st.st_size, 'mtime': st.st_mtime})
            if len(found) > 300:
                break
    found.sort(key=lambda x: -x['mtime'])
    return found[:100]


# ---------- Wi-Fi (iwd over D-Bus) ----------

IWD = 'net.connman.iwd'


def iwd_bus():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def iwd_call(path, iface, method, args=None, reply='()', timeout=5000):
    res = iwd_bus().call_sync(IWD, path, iface, method, args, GLib.VariantType(reply),
                              Gio.DBusCallFlags.NONE, timeout, None)
    return res.unpack()


def iwd_objects():
    return iwd_call('/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', reply='(a{oa{sa{sv}}})')[0]


def iwd_station(objs):
    for path, ifaces in sorted(objs.items()):
        if IWD + '.Station' in ifaces:
            return path, ifaces
    return None, None


def wifi_status():
    try:
        objs = iwd_objects()
    except GLib.Error:
        return {'available': False, 'reason': 'Wi-Fi isn’t running.'}
    path, ifaces = iwd_station(objs)
    if not path:
        devices = [i for i in objs.values() if IWD + '.Device' in i]
        if devices and not devices[0][IWD + '.Device'].get('Powered', True):
            return {'available': False, 'reason': 'Wi-Fi is turned off on this PC.'}
        return {'available': False, 'reason': 'No Wi-Fi adapter found. VirtualBox shares your PC’s connection as wired.'}
    st = ifaces[IWD + '.Station']
    try:
        ordered = iwd_call(path, IWD + '.Station', 'GetOrderedNetworks', reply='(a(on))')[0]
    except GLib.Error:
        ordered = []
    nets, seen = [], set()
    for npath, signal_level in ordered:
        n = objs.get(npath, {}).get(IWD + '.Network')
        if not n or n.get('Name') in seen:
            continue
        seen.add(n.get('Name'))
        dbm = signal_level / 100
        bars = 4 if dbm >= -60 else 3 if dbm >= -67 else 2 if dbm >= -75 else 1
        nets.append({'name': n.get('Name', ''), 'type': n.get('Type', ''), 'connected': bool(n.get('Connected')),
                     'known': 'KnownNetwork' in n, 'bars': bars})
    return {'available': True, 'state': st.get('State', ''), 'scanning': bool(st.get('Scanning')), 'networks': nets[:25]}


def wifi_scan():
    objs = iwd_objects()
    path, _ = iwd_station(objs)
    if path:
        try:
            iwd_call(path, IWD + '.Station', 'Scan')
        except GLib.Error:
            pass   # already scanning
    return {'ok': bool(path)}


def find_network(objs, name):
    for path, ifaces in objs.items():
        n = ifaces.get(IWD + '.Network')
        if n and n.get('Name') == name:
            return path, n
    return None, None


def known_network(objs, name):
    for path, ifaces in objs.items():
        k = ifaces.get(IWD + '.KnownNetwork')
        if k and k.get('Name') == name:
            return path
    return None


def wifi_connect(arg):
    arg = arg if isinstance(arg, dict) else {}
    name, pw = str(arg.get('name', '')), arg.get('passphrase')
    try:
        objs = iwd_objects()
    except GLib.Error:
        return {'ok': False, 'error': 'Wi-Fi isn’t running.'}
    path, net = find_network(objs, name)
    if not path:
        return {'ok': False, 'error': 'That network is out of range. Try scanning again.'}
    kind = net.get('Type')
    if kind == '8021x':
        return {'ok': False, 'error': 'Work or school networks (802.1X) aren’t supported yet.'}
    if kind == 'psk' and 'KnownNetwork' not in net:
        if not pw:
            return {'ok': False, 'need_password': True}
        pw = str(pw)
        if not (8 <= len(pw) <= 63):
            return {'ok': False, 'need_password': True, 'error': 'Wi-Fi passwords are 8 to 63 characters.'}
        helper_request({'action': 'wifi_save', 'ssid': name, 'passphrase': pw})
        for _ in range(30):   # iwd picks the saved password up from its folder
            time.sleep(0.25)
            try:
                if known_network(iwd_objects(), name):
                    break
            except GLib.Error:
                pass
    try:
        iwd_call(path, IWD + '.Network', 'Connect', timeout=30000)
        return {'ok': True}
    except GLib.Error as e:
        msg = e.message or ''
        if kind == 'psk' and ('Failed' in msg or 'Aborted' in msg or 'InvalidFormat' in msg):
            try:   # forget the wrong password so the next try asks again
                k = known_network(iwd_objects(), name)
                if k:
                    iwd_call(k, IWD + '.KnownNetwork', 'Forget')
            except GLib.Error:
                pass
            return {'ok': False, 'need_password': True, 'error': 'Couldn’t connect. Check the password and try again.'}
        return {'ok': False, 'error': 'Couldn’t connect to that network.'}


def wifi_forget(name):
    try:
        k = known_network(iwd_objects(), str(name))
        if k:
            iwd_call(k, IWD + '.KnownNetwork', 'Forget')
            return {'ok': True}
    except GLib.Error:
        pass
    return {'ok': False}


def wifi_disconnect():
    try:
        path, _ = iwd_station(iwd_objects())
        if path:
            iwd_call(path, IWD + '.Station', 'Disconnect')
            return {'ok': True}
    except GLib.Error:
        pass
    return {'ok': False}


# ---------- storage, saving, installing ----------

def lsblk(*args):
    try:
        out = subprocess.run(['lsblk', '-J', '-b', *args], capture_output=True, text=True, timeout=5).stdout
        return json.loads(out or '{}').get('blockdevices', [])
    except Exception:
        return []


def findmnt_source(target):
    try:
        return subprocess.run(['findmnt', '-no', 'SOURCE', target], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ''


def parent_disk(dev):
    for d in lsblk('-o', 'PATH,PKNAME', dev):
        if d.get('pkname'):
            return '/dev/' + d['pkname']
    return dev


LIVE_MEDIUM = '/run/live/medium'   # where Debian's live system mounts the LaunchOS disc or USB stick
SAVE_LABELS = ('persistence',)      # the partition (or VirtualBox save disk) that holds your saves


def save_device():
    """The partition or disk holding the saves: labelled 'persistence' (the VirtualBox save disk,
    or the space LaunchOS sets aside on its USB stick)."""
    for label in SAVE_LABELS:
        path = f'/dev/disk/by-label/{label}'
        if os.path.exists(path):
            return os.path.realpath(path)
    return ''


def saving_on():
    """Installed on a drive, or running live with a save area in use."""
    if os.path.exists('/etc/launchos/installed'):
        return True
    return any(m.startswith('/run/live/persistence/') for m in mount_table())


def storage_info():
    installed = os.path.exists('/etc/launchos/installed')
    has_cow = bool(save_device())
    saving = saving_on()
    try:
        st = os.statvfs('/')
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    except OSError:
        total = free = 0
    src = findmnt_source(LIVE_MEDIUM)
    boot, usb = 'drive' if installed else 'disc', False
    if src.startswith('/dev/'):
        disk = parent_disk(src)
        info = (lsblk('-d', '-o', 'PATH,TRAN,RM,TYPE', disk) or [{}])[0]
        usb = info.get('tran') == 'usb' or bool(info.get('rm')) and info.get('type') == 'disk'
        if usb:
            boot = 'usb'
    return {'installed': installed, 'saving': saving, 'total': total, 'free': free, 'boot': boot,
            'can_usb_saving': usb and not has_cow, 'job': job_status('usb-saving')}


def install_disks():
    """Drives LaunchOS can be installed on: whole drives of 16 GB or more that aren't
    in use, aren't the drive it started from and don't hold the LaunchOS saves."""
    src = findmnt_source(LIVE_MEDIUM)
    boot = parent_disk(src) if src.startswith('/dev/') else ''
    cow = save_device()
    cow_disk = parent_disk(cow) if cow else ''
    out = []
    for d in lsblk('-o', 'NAME,PATH,SIZE,TYPE,TRAN,MODEL,RM,RO,MOUNTPOINTS'):
        path = d.get('path', '')
        if d.get('type') != 'disk' or d.get('ro') or path in (boot, cow, cow_disk):
            continue
        if not re.fullmatch(r'/dev/(sd[a-z]{1,2}|vd[a-z]{1,2}|nvme\d+n\d+|mmcblk\d+)', path):
            continue
        size = int(d.get('size') or 0)
        if size < 16_000_000_000:
            continue
        def mounted(node):
            # open in Files (/media/player) is fine: the installer closes it first
            if any(m and not m.startswith(MEDIA + '/') for m in (node.get('mountpoints') or [])):
                return True
            return any(mounted(c) for c in node.get('children', []))
        if mounted(d):
            continue
        out.append({'path': path, 'size': size, 'model': (d.get('model') or '').strip() or 'Drive',
                    'usb': d.get('tran') == 'usb', 'parts': len(d.get('children', []))})
    return out


# ---------- Files: your folders and drives ----------
# Everything here stays inside your home folder (not its hidden system folders) and the
# drives opened at /media/player. Copying, moving and deleting run in the background with
# progress; mounting, ejecting and formatting are done by the root helper.

from fsops import MEDIA, PLACES, FsError, mount_table, human, fs_real, fs_mkdir, fs_rename  # noqa: E402
import fsops  # noqa: E402

FSOPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fsops.py')


def fs_list(path):
    return fsops.fs_list(path, busy=fs_busy())


class FsJobProc:
    """A copy, move or delete running as its own process (fsops.py); this keeps its latest progress."""

    def __init__(self, op, paths, dest):
        self.op, self.stopping = op, False
        self.state = {'op': op, 'step': 'Getting ready', 'bytes': 0, 'total_bytes': 0, 'files': 0, 'total_files': 0,
                      'current': '', 'done': False, 'error': '', 'result': '', 'speed': 0, 'stopped': False}
        self.proc = subprocess.Popen([sys.executable, FSOPS], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, cwd='/')
        self.proc.stdin.write(json.dumps({'op': op, 'paths': paths, 'dest': dest}) + '\n')
        self.proc.stdin.close()
        threading.Thread(target=self.follow, daemon=True).start()

    def follow(self):
        for line in self.proc.stdout:
            try:
                st = json.loads(line)
            except ValueError:
                continue
            if isinstance(st, dict):
                st['done'] = False   # only once the process has ended
                self.state = st
        self.proc.wait()
        st = dict(self.state)
        if not (st.get('result') or st.get('error') or st.get('stopped')):
            if self.stopping:   # stopped before it got going
                st.update(stopped=True, result='Stopped. Nothing was changed.')
            else:
                st['error'] = 'The ' + ('delete' if self.op == 'delete' else self.op) + ' stopped unexpectedly.'
        st['done'] = True
        self.state = st

    def info(self):
        return dict(self.state)

    def stop(self):
        self.stopping = True
        try:
            self.proc.send_signal(signal.SIGTERM)
        except OSError:
            pass


FS_STATE = {'job': None, 'mount_tried': set(), 'drive_lock': threading.Lock()}


def fs_job():
    job = FS_STATE['job']
    return job.info() if job else {}


def fs_start(op, arg):
    arg = arg if isinstance(arg, dict) else {}
    job = FS_STATE['job']
    if job and not job.state['done']:
        return {'ok': False, 'error': 'Wait for the ' + ('delete' if job.op == 'delete' else job.op) + ' that’s running to finish.'}
    paths = arg.get('paths')
    if not isinstance(paths, list) or not paths or len(paths) > 10000:
        return {'ok': False, 'error': 'Nothing selected.'}
    try:
        FS_STATE['job'] = FsJobProc(op, [str(p) for p in paths], arg.get('dest'))
    except OSError as e:
        return {'ok': False, 'error': 'Couldn’t start: ' + str(e)}
    return {'ok': True}


def fs_cancel():
    job = FS_STATE['job']
    if job and not job.state['done']:
        job.stop()
    return {'ok': True}


def fs_busy():
    job = FS_STATE['job']
    return bool(job and not job.state['done'])


_sysdisks = {'t': -99.0, 'v': set()}


def system_disks():
    """Drives (and their parts) LaunchOS runs from, saves to, or is installed on: never shown in Files.
    Worked out at most every 20 seconds: starting programs is slow on a busy or emulated PC."""
    if time.monotonic() - _sysdisks['t'] < 20:
        return _sysdisks['v']
    table = mount_table()
    devs = [table.get(t, ('',))[0] for t in (LIVE_MEDIUM, '/', '/boot/efi', '/var/log', '/home')]
    devs += [v[0] for m, v in table.items() if m.startswith('/run/live/')]   # the live system's own disks
    for d in lsblk('-o', 'PATH,LABEL'):   # every save label: a second stick may carry the same one
        if d.get('label') in SAVE_LABELS:
            devs.append(d.get('path', ''))
    out = set()
    for dev in devs:
        if dev.startswith('/dev/'):
            out.add(dev)
            try:   # down to the physical drive, through partitions, device-mapper and loop devices
                out |= set(subprocess.run(['lsblk', '-nsrpo', 'NAME', dev], capture_output=True, text=True,
                                          timeout=5).stdout.split())
            except Exception:
                out.add(parent_disk(dev))
    _sysdisks.update(t=time.monotonic(), v=out)
    return out


SYSTEM_PARTTYPES = ('c12a7328-f81f-11d2-ba4b-00a0c93ec93b', 'de94bba4-06d1-4d40-a16a-bfd50179d6ac',
                    'e3c9e316-0b5c-4db8-817d-f92df00215ae', '21686148-6449-6e6f-744e-656564454649', '0xef', '0x27')
DRIVE_FS = ('vfat', 'exfat', 'ntfs', 'ext4', 'ext3', 'ext2', 'btrfs', 'xfs')
FS_NAMES = {'vfat': 'FAT32', 'exfat': 'exFAT', 'ntfs': 'NTFS', 'ext4': 'ext4', 'ext3': 'ext3', 'ext2': 'ext2', 'btrfs': 'Btrfs', 'xfs': 'XFS'}


def ejected_uuids():
    return set(read('/run/launchos-status/ejected').split())


def fs_drives():
    """Drives in and plugged into this PC, except the ones LaunchOS itself uses."""
    sysd = system_disks()
    table = mount_table()
    out, want_mount = [], False
    skip = ejected_uuids()
    cols = 'NAME,PATH,TYPE,FSTYPE,LABEL,UUID,RM,TRAN,RO,MOUNTPOINTS,PARTTYPE,SIZE,MODEL,VENDOR'   # NAME: lsblk only nests partitions under their drive with it
    for disk in lsblk('-o', cols):
        path = disk.get('path', '')
        if disk.get('type') != 'disk' or path in sysd or not re.fullmatch(r'/dev/(sd[a-z]{1,2}|vd[a-z]{1,2}|nvme\d+n\d+|mmcblk\d+)', path):
            continue
        size = int(disk.get('size') or 0)
        if size <= 0:
            continue   # card reader with no card in it
        removable = bool(disk.get('rm')) or disk.get('tran') == 'usb'
        vendor, mdl = (disk.get('vendor') or '').strip(), (disk.get('model') or '').strip()
        if re.fullmatch(r'0x[0-9a-fA-F]+|ATA', vendor) or vendor.lower() in mdl.lower():
            vendor = ''   # a PCI id or a generic bus name tells you nothing
        model = ' '.join((vendor + ' ' + mdl).split()) or ('USB drive' if removable else 'Drive')
        base = {'disk': path, 'disk_size': size, 'model': model, 'removable': removable, 'usb': disk.get('tran') == 'usb',
                'readonly_disk': bool(disk.get('ro'))}
        kids = []
        stack = list(disk.get('children') or [])
        while stack:
            k = stack.pop(0)
            if k.get('type') == 'part':
                kids.append(k)
            stack.extend(k.get('children') or [])
        nodes = kids or ([disk] if disk.get('fstype') else [])
        in_use = any(m and not m.startswith(MEDIA + '/') for n in [disk] + kids for m in (n.get('mountpoints') or []))
        found = 0
        for n in nodes:
            fs = n.get('fstype') or ''
            if fs not in DRIVE_FS or n.get('path') in sysd or (n.get('parttype') or '').lower() in SYSTEM_PARTTYPES:
                continue
            if n.get('label') in SAVE_LABELS:
                continue
            psize = int(n.get('size') or 0)
            if len(nodes) > 1 and psize < 64 << 20:
                continue
            points = [m for m in (n.get('mountpoints') or []) if m]
            if points and not any(m.startswith(MEDIA + '/') for m in points):
                continue   # used by the system
            mnt = next((m for m in points if m.startswith(MEDIA + '/')), '')
            d = dict(base, id=n.get('path'), dev=n.get('path'), fs=FS_NAMES.get(fs, fs), size=psize,
                     name=(n.get('label') or '').strip() or f'{model} ({human(psize)})', mount=mnt)
            if mnt:
                try:
                    st = os.statvfs(mnt)
                    d.update(free=st.f_bavail * st.f_frsize, total=st.f_blocks * st.f_frsize)
                except OSError:
                    pass
                d['readonly'] = table.get(mnt, ('', '', False))[2]
            elif removable and n.get('uuid') not in skip and (n.get('path'), n.get('uuid')) not in FS_STATE['mount_tried']:
                FS_STATE['mount_tried'].add((n.get('path'), n.get('uuid')))   # asked once; Open in Files tries again
                want_mount = True
            d['ejected'] = n.get('uuid') in skip
            out.append(d)
            found += 1
        if not found and not in_use:   # nothing LaunchOS can open: offer to format it
            out.append(dict(base, id=path, dev='', fs='', size=size, mount='', name=f'{model} ({human(size)})',
                            empty=not (disk.get('children') or disk.get('fstype'))))
    # a USB drive that was just plugged in and not opened yet (the system normally does this by itself)
    if want_mount:
        helper_request({'action': 'mount_drives'})
    return out


def fs_places():
    places = []
    for name in PLACES:
        p = os.path.join(HOME, name)
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            continue
        places.append({'id': name.lower(), 'name': name, 'path': p})
    try:
        st = os.statvfs(HOME)
        home_free, home_total = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
    except OSError:
        home_free = home_total = 0
    return {'places': places, 'drives': fs_drives(), 'home_free': home_free, 'home_total': home_total,
            'job': fs_job(), 'saving': saving_on()}


def helper_wait(payload, name, timeout, until_done=True):
    """Asks the root helper for a drive job and waits for its answer in /run/launchos-status/<name>.json."""
    path = f'/run/launchos-status/{name}.json'

    def stamp():
        try:
            s = os.stat(path)
            return (s.st_ino, s.st_mtime_ns)
        except OSError:
            return None
    before = stamp()
    r = helper_request(payload)
    if not r.get('ok'):
        return {'done': True, 'error': 'LaunchOS couldn’t ask for that. Try again.'}
    end = time.monotonic() + timeout
    changed = False
    while time.monotonic() < end:
        time.sleep(0.2)
        if not changed and stamp() == before:
            continue
        changed = True
        st = job_status(name)
        if st.get('done') or not until_done:
            return st
    if changed:   # still going (a format): Files keeps showing its progress
        return job_status(name)
    return {'done': True, 'error': 'The drive didn’t answer. Try again.'}


def drive_job(fn):
    """Open and Eject share one answer file: one drive job at a time."""
    if not FS_STATE['drive_lock'].acquire(blocking=False):
        return {'ok': False, 'error': 'Another drive is being opened or ejected. Try again in a moment.'}
    try:
        return fn()
    finally:
        FS_STATE['drive_lock'].release()


def fs_mount(dev):
    return drive_job(lambda: _fs_mount(dev))


def _fs_mount(dev):
    dev = str(dev or '')
    st = helper_wait({'action': 'mount_part', 'dev': dev}, 'drive', 40)
    if st.get('error'):
        return {'ok': False, 'error': st['error']}
    for d in fs_drives():
        if d.get('dev') == dev and d.get('mount'):
            return {'ok': True, 'mount': d['mount']}
    return {'ok': False, 'error': 'Couldn’t open the drive.'}


def fs_eject(disk):
    if fs_busy():
        return {'ok': False, 'error': 'Wait for the copy that’s running to finish first.'}
    return drive_job(lambda: _fs_eject(disk))


def _fs_eject(disk):
    st = helper_wait({'action': 'eject', 'disk': str(disk or '')}, 'drive', 180)
    return {'ok': not st.get('error'), 'error': st.get('error', ''), 'step': st.get('step', '')}


def fs_format(arg):
    arg = arg if isinstance(arg, dict) else {}
    if fs_busy():
        return {'ok': False, 'error': 'Wait for the copy that’s running to finish first.'}
    disk = str(arg.get('disk', ''))
    running = job_status('format')
    if running and not running.get('done'):
        return {'ok': False, 'error': 'A drive is being formatted. Wait for it to finish.'}
    st = helper_wait({'action': 'format', 'disk': disk, 'fs': str(arg.get('fs', '')), 'label': str(arg.get('label', ''))[:11],
                      'confirm': str(arg.get('confirm', ''))}, 'format', 10, until_done=False)
    if st.get('done') and st.get('error'):
        return {'ok': False, 'error': st['error']}
    return {'ok': True}


# ---------- Store: apps from Flathub ----------
# The app list comes from Flathub's catalog, which the system downloads into
# /var/lib/flatpak/appstream; installing and removing is done by the root helper.

APPSTREAM = '/var/lib/flatpak/appstream/flathub/x86_64/active'
APP_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}')
STORE_CACHE = os.path.join(HOME, '.cache', 'launchos', 'store.json')
CATEGORY_MAP = {   # Flathub's categories, grouped into a few simple shelves
    'Game': 'games', 'Emulator': 'games',
    'Network': 'internet', 'WebBrowser': 'internet', 'Chat': 'internet', 'InstantMessaging': 'internet', 'Email': 'internet',
    'AudioVideo': 'media', 'Audio': 'media', 'Video': 'media', 'Music': 'media', 'Player': 'media',
    'Graphics': 'creative', '2DGraphics': 'creative', '3DGraphics': 'creative', 'Photography': 'creative', 'VideoEditing': 'creative',
    'Office': 'work', 'Education': 'work', 'Development': 'work', 'Science': 'work',
    'Utility': 'tools', 'System': 'tools', 'Settings': 'tools',
}
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
_store = {'mtime': None, 'apps': [], 'by_id': {}, 'lock': threading.Lock()}


def store_catalog_file():
    for name in ('appstream.xml.gz', 'appstream.xml'):
        p = os.path.join(APPSTREAM, name)
        if os.path.exists(p):
            return p
    return ''


def _text(el):
    return re.sub(r'\s+', ' ', ''.join(el.itertext())).strip() if el is not None else ''


def store_parse(path, icons=APPSTREAM):
    """Flathub's catalog (AppStream XML) to a small list of apps."""
    import gzip
    import xml.etree.ElementTree as ET
    opener = gzip.open if path.endswith('.gz') else open
    apps = []
    with opener(path, 'rb') as f:
        for _, el in ET.iterparse(f, events=('end',)):
            if el.tag != 'component':
                continue
            try:
                if el.get('type') not in ('desktop', 'desktop-application'):
                    continue
                aid = (el.findtext('id') or '').strip()
                if aid.endswith('.desktop'):
                    aid = aid[:-8]
                if not APP_ID.fullmatch(aid):
                    continue
                name = next((_text(n) for n in el.findall('name') if not n.get(XML_LANG)), '')
                summary = next((_text(n) for n in el.findall('summary') if not n.get(XML_LANG)), '')
                desc_el = el.find('description')
                paras = [p for p in desc_el.findall('p') if not p.get(XML_LANG)] if desc_el is not None else []
                desc = ' '.join(_text(p) for p in paras[:3])
                cats = [c.text for c in el.findall('categories/category') if c.text]
                dev = _text(el.find('developer/name')) or _text(el.find('developer_name'))
                icon = ''
                for size in ('128x128', '64x64'):
                    p = os.path.join(icons, 'icons', size, aid + '.png')
                    if os.path.exists(p):
                        icon = p
                        break
                shots = []
                for sc in el.findall('screenshots/screenshot'):
                    imgs = sc.findall('image')
                    big = next((i.text for i in imgs if i.get('type') == 'source'), None) or (imgs[0].text if imgs else None)
                    if big and big.strip().startswith('https://'):
                        shots.append(big.strip())
                    if len(shots) >= 3:
                        break
                shelves = sorted({CATEGORY_MAP[c] for c in cats if c in CATEGORY_MAP})
                apps.append({'id': aid, 'name': (name or aid.split('.')[-1])[:60], 'summary': summary[:160],
                             'desc': desc[:1200], 'dev': dev[:80], 'icon': icon, 'shelves': shelves, 'shots': shots})
            finally:
                el.clear()
    apps.sort(key=lambda a: a['name'].casefold())
    return apps


def store_apps():
    """The whole catalog, read once and kept (Flathub has a few thousand apps)."""
    path = store_catalog_file()
    if not path:
        return []
    with _store['lock']:   # the first read of Flathub's whole list is slow: never do it twice at once
        return _store_apps(path)


def _store_apps(path):
    real = os.path.realpath(path)
    mtime = os.stat(real).st_mtime
    key = real + ':' + str(mtime)
    if _store['mtime'] != key:
        apps = None
        try:   # a quick copy from last time, if the catalog hasn't changed
            with open(STORE_CACHE) as f:
                cached = json.load(f)
            if cached.get('mtime') == key:
                apps = cached['apps']
        except (OSError, ValueError, KeyError):
            pass
        if apps is None:
            apps = store_parse(path)
            try:
                os.makedirs(os.path.dirname(STORE_CACHE), exist_ok=True)
                tmp = f'{STORE_CACHE}.{os.getpid()}.tmp'
                with open(tmp, 'w') as f:
                    json.dump({'mtime': key, 'apps': apps}, f)
                os.replace(tmp, STORE_CACHE)
            except OSError:
                pass
        _store.update(mtime=key, apps=apps, by_id={a['id']: a for a in apps})
    return _store['apps']


def store_installed():
    """Apps installed from the Store: {id: {name, version}}."""
    out = {}
    try:
        r = subprocess.run(['flatpak', 'list', '--app', '--system', '--columns=application,name,version'],
                           capture_output=True, text=True, timeout=20)
        for line in r.stdout.splitlines():
            p = line.split('\t')
            if p and APP_ID.fullmatch(p[0]):
                out[p[0]] = {'name': p[1] if len(p) > 1 else p[0], 'version': p[2] if len(p) > 2 else ''}
    except Exception:
        pass
    return out


def store_info():
    """What the Store page needs: the catalog (or that it isn't here yet), what's installed,
    the job that's running and the free space."""
    apps = store_apps()
    inst = store_installed()
    try:
        st = os.statvfs('/var/lib/flatpak' if os.path.isdir('/var/lib/flatpak') else '/')
        free = st.f_bavail * st.f_frsize
    except OSError:
        free = 0
    path = store_catalog_file()
    saving = saving_on()
    return {'apps': apps, 'installed': inst, 'job': job_status('store'), 'free': free, 'saving': saving,
            'catalog_age_h': int((time.time() - os.stat(path).st_mtime) / 3600) if path else None}


def store_home_apps():
    """Installed Store apps for the Home screen: name and icon."""
    inst = store_installed()
    if not inst:
        return []
    by_id = _store['by_id'] or {a['id']: a for a in store_apps()}
    out = []
    for aid, v in sorted(inst.items(), key=lambda kv: kv[1]['name'].casefold()):
        if aid in CURATED_IDS:
            continue   # these have their own tiles (Discord, Roblox, FreeTube…)
        a = by_id.get(aid, {})
        out.append({'id': aid, 'name': a.get('name') or v['name'], 'icon': a.get('icon', '')})
    return out


def unit_running(unit):
    try:
        return subprocess.run(['systemctl', 'is-active', '--quiet', unit + '.service'], timeout=5).returncode == 0
    except Exception:
        return False


def job_running(name, unit):
    """Is this job really going? (A job that was killed leaves its last 'working' status behind.)"""
    st = job_status(name)
    return bool(st and st.get('step') and not st.get('done') and unit_running(unit))


def store_action(arg):
    arg = arg if isinstance(arg, dict) else {}
    op = str(arg.get('op', ''))
    # one app, or (installing from Setup) several at once
    ids = arg.get('apps') if op == 'install' and isinstance(arg.get('apps'), list) else [str(arg.get('app', ''))]
    ids = [str(i) for i in ids][:12]
    if op not in ('install', 'remove', 'refresh') or (op != 'refresh' and not (ids and all(APP_ID.fullmatch(i) for i in ids))):
        return {'ok': False, 'error': 'That isn’t a Store app.'}
    if job_running('store', 'launchos-store'):
        return {'ok': False, 'error': 'Wait for ' + (job_status('store').get('name') or 'the app') + ' to finish first.'}
    a = _store['by_id'].get(ids[0], {}) if len(ids) == 1 else {}
    name = re.sub(r'[^\w .,:+&()\'-]', '', str(a.get('name') or arg.get('name') or ids[0]))[:60]
    # wait until the job has really started, so the page never reads the last job's result
    st = helper_wait({'action': 'store', 'op': op, 'app': ','.join(ids) if op != 'refresh' else '', 'name': name},
                     'store', 15, until_done=False)
    if st.get('error') == 'The drive didn’t answer. Try again.':
        return {'ok': False, 'error': 'LaunchOS didn’t answer. Try again.'}
    return {'ok': True}


# ---------- updates and admin password ----------

def update_info():
    rel = release()
    return {'version': rel.get('VERSION', '?'), 'build': rel.get('BUILD_DATE', ''),
            'check': job_status('update'), 'system': job_status('sysupdate'), 'apps': job_status('appupdate'),
            'installed': os.path.exists('/etc/launchos/installed'),
            'saving': saving_on()}


def update_action(arg):
    what = str(arg or '')
    if what not in ('check', 'apply', 'system', 'apps'):
        return {'ok': False}
    for name, unit in (('update', 'launchos-update'), ('appupdate', 'launchos-update'), ('sysupdate', 'launchos-sysupdate')):
        if job_running(name, unit):
            return {'ok': False, 'error': 'An update is already running.'}
    job = {'system': 'sysupdate', 'apps': 'appupdate'}.get(what, 'update')
    st = helper_wait({'action': 'update', 'what': what}, job, 15, until_done=False)
    if st.get('done') and st.get('error') == 'The drive didn’t answer. Try again.':
        return {'ok': False, 'error': 'LaunchOS didn’t answer. Try again.'}
    return {'ok': True}


def admin_password(arg):
    arg = arg if isinstance(arg, dict) else {}
    new, old = str(arg.get('new', '')), str(arg.get('old', ''))
    if not (6 <= len(new) <= 128) or any(ord(c) < 32 for c in new):
        return {'done': True, 'error': 'Use 6 or more characters.'}
    # returns as soon as the job has started: the page then follows it (it may ask for a key press)
    st = helper_wait({'action': 'admin_password', 'new': new, 'old': old}, 'admin', 20, until_done=False)
    if st.get('error') == 'The drive didn’t answer. Try again.':
        st['error'] = 'LaunchOS didn’t answer. Try again.'
    return st


def admin_set():
    """Has an admin password been set? (Setting one makes the player an administrator.)"""
    return {'set': os.path.exists('/etc/launchos/admin-set')}


# ---------- sign-in ----------
# LaunchOS starts at the sign-in screen. With a password set (Settings > Password) it asks
# for it, unless you turned that off; the password is checked by the system's own helper.

SIGNIN_CONF = os.path.join(HOME, '.config', 'launchos', 'signin.json')
CHKPWD = '/usr/sbin/unix_chkpwd'


def signin_ask():
    try:
        with open(SIGNIN_CONF) as f:
            return bool(json.load(f).get('ask', True))
    except (OSError, ValueError, AttributeError):
        return True


def set_signin_ask(on):
    os.makedirs(os.path.dirname(SIGNIN_CONF), exist_ok=True)
    with open(SIGNIN_CONF + '.tmp', 'w') as f:
        json.dump({'ask': bool(on)}, f)
    os.replace(SIGNIN_CONF + '.tmp', SIGNIN_CONF)
    return {'ok': True, 'ask': bool(on)}


def password_needed():
    return os.path.exists('/etc/launchos/admin-set') and signin_ask()


def password_ok(pw):
    """Checks the player's password with unix_chkpwd, which may check your own password
    without being root (the same way the lock screens of other systems do)."""
    if not pw or len(pw) > 128 or '\0' in pw:
        return False
    user = os.environ.get('USER') or 'player'
    try:
        r = subprocess.run([CHKPWD, user, 'nonull'], input=pw.encode() + b'\0', capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


# ---------- home screen ----------

# What the sign-in screen may use before anyone has signed in
SIGNED_OUT_OK = {'session_state', 'sign_in', 'power', 'info', 'network', 'log_error', 'inputs', 'timezone_get'}


class Launcher(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='os.launch.home')
        self.apps = {}   # app id -> Browser window, running (shown or in the background)
        self.ext = None   # the one outside app (game, Steam, FreeTube…) that may run, like a console
        self.panel = None   # Discord side panel
        self.quiet_super = 0.0
        self.signed_in = False
        self.fails, self.wait_until = 0, 0.0   # wrong passwords in a row, and when the next try is allowed
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property('gtk-application-prefer-dark-theme', True)
        css = Gtk.CssProvider()
        css.load_from_data(BROWSER_CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = Gtk.ApplicationWindow(application=app, title='LaunchOS')
        ucm = WebKit.UserContentManager()
        ucm.connect('script-message-received::launchos', self.on_message)
        ucm.register_script_message_handler('launchos', None)
        self.view = WebKit.WebView(user_content_manager=ucm)
        self.view.set_background_color(NAVY)
        s = self.view.get_settings()
        s.set_hardware_acceleration_policy(ACCEL)
        s.set_enable_developer_extras(False)
        s.set_allow_file_access_from_file_urls(True)
        s.set_media_playback_requires_user_gesture(False)   # the viewer starts a video or song you picked in Files
        self.view.connect('context-menu', lambda *a: True)
        self.view.load_uri(UI + 'login.html')
        self.overlay = Gtk.Overlay()
        self.overlay.set_child(self.view)
        self.win.set_child(self.overlay)
        self.hold()   # keep running while Home is hidden behind a game
        WebKit.NetworkSession.get_default().connect('download-started', self.on_download)
        InputWatcher(self.on_global_home).start()
        SwayWatcher(self.on_new_window).start()
        GLib.timeout_add(1500, self.check_ext)
        # Super (Windows) key on Home works like the Xbox button: the page opens or closes the side menu.
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_home_key)
        self.win.add_controller(keys)
        self.win.fullscreen()
        self.win.present()

    def js(self, code):
        self.view.evaluate_javascript(code, -1, None, None, None, None, None)

    def on_home_key(self, ctl, keyval, code, state):
        if keyval in SUPER_KEYS and time.monotonic() < self.quiet_super:
            return True   # the same press that just brought Home back from a game
        if keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK):
            # app options, instead of the toolkit's own Cut/Copy/Paste menu
            if not (self.panel is not None and self.panel.get_visible()):
                self.js('window.__losOpts && window.__losOpts();')
                return True
        if keyval in SUPER_KEYS:
            if self.panel is not None and self.panel.get_visible():
                self.discord_panel({'open': False})
            else:
                self.js('window.__losGuide && window.__losGuide();')
            return True
        return False

    def reply(self, rid, data):
        js = f'window.__losReply && window.__losReply({json.dumps(rid)}, {json.dumps(data)});'
        self.view.evaluate_javascript(js, -1, None, None, None, None, None)
        return False

    def on_message(self, ucm, value):
        try:
            msg = json.loads(value.to_string())
        except Exception:
            # Older pages sent plain "poweroff" / "reboot".
            text = value.to_string() if value else ''
            if text in ('poweroff', 'reboot'):
                helper_request({'action': text})
            return
        rid, action, arg = msg.get('id', 0), msg.get('action'), msg.get('arg')
        if not self.signed_in and action not in SIGNED_OUT_OK:
            self.reply(rid, {'error': 'signed_out'})
            return

        slow = {'internet_test': internet_test, 'wifi_connect': lambda: wifi_connect(arg),
                'win_programs': win_programs, 'install_disks': install_disks,
                # Files: a slow or unplugged drive must never freeze Home
                'fs_places': fs_places, 'fs_list': lambda: fs_list(arg), 'fs_mkdir': lambda: fs_mkdir(arg),
                'fs_rename': lambda: fs_rename(arg), 'fs_mount': lambda: fs_mount(arg), 'fs_eject': lambda: fs_eject(arg),
                'fs_format': lambda: fs_format(arg),
                # Store: reading Flathub's catalog the first time takes a few seconds
                'store_info': store_info, 'store_home': store_home_apps, 'admin_password': lambda: admin_password(arg),
                'store_action': lambda: store_action(arg), 'update_action': lambda: update_action(arg),
                'get_app': lambda: get_app(arg), 'apps_info': apps_info, 'sign_in': lambda: self.sign_in(arg)}
        if action in slow:
            def work():
                try:
                    result = slow[action]()
                except Exception as e:   # never let one bad request take the launcher down
                    result = {'error': str(e)}
                GLib.idle_add(self.reply, rid, result)
            threading.Thread(target=work, daemon=True).start()
            return

        handlers = {
            'info': system_info,
            'network': network_status,
            'inputs': input_devices,
            'volume_get': volume_get,
            'volume_set': lambda: volume_set(arg),
            'sound_test': play_test_sound,
            'timezones': timezones,
            'timezone_get': lambda: {'zone': timezone_get()},
            'timezone_set': lambda: helper_request({'action': 'timezone', 'value': str(arg)}),
            'power': lambda: helper_request({'action': 'poweroff' if arg == 'poweroff' else 'reboot'}),
            'open_browser': lambda: self.open_app({'id': 'browser', 'name': 'Browser', 'url': arg}),
            'open_app': lambda: self.open_app(arg),
            'end_app': lambda: self.end_app(arg),
            'tasks': self.tasks,
            'stats': system_stats,
            'open_ext': lambda: self.open_ext(arg),
            'job_status': lambda: job_status(arg),
            'wifi_status': wifi_status,
            'wifi_scan': wifi_scan,
            'wifi_forget': lambda: wifi_forget(arg),
            'wifi_disconnect': wifi_disconnect,
            'storage': storage_info,
            'usb_saving': lambda: helper_request({'action': 'usb_saving'}),
            'mount_drives': lambda: helper_request({'action': 'mount_drives'}),
            'install_system': lambda: helper_request({'action': 'install_system', 'disk': str((arg or {}).get('disk', '')),
                                                      'confirm': str((arg or {}).get('confirm', ''))}),
            'discord_panel': lambda: self.discord_panel(arg),
            'open_terminal': self.open_terminal,

            'store_job': lambda: job_status('store'),
            'update_info': update_info,

            'admin_set': admin_set,
            'fs_copy': lambda: fs_start('copy', arg),
            'fs_move': lambda: fs_start('move', arg),
            'fs_delete': lambda: fs_start('delete', arg),
            'fs_job': fs_job,
            'fs_cancel': fs_cancel,
            'log_error': lambda: log_error(arg),
            'session_state': self.session_state,
            'lock': lambda: self.sign_out(end_apps=False),
            'sign_out': lambda: self.sign_out(end_apps=True),
            'signin_ask': lambda: set_signin_ask(bool(arg)),
        }
        fn = handlers.get(action)
        try:
            result = fn() if fn else {'error': 'unknown action'}
        except Exception as e:  # never let one bad request take the launcher down
            result = {'error': str(e)}
        self.reply(rid, result)

    # ---------- sign-in ----------

    def session_state(self):
        return {'signed_in': self.signed_in, 'password': password_needed(),
                'password_set': os.path.exists('/etc/launchos/admin-set'), 'ask': signin_ask(),
                'wait_s': max(0, int(self.wait_until - time.monotonic() + 0.99)), 'running': len(self.tasks())}

    def sign_in(self, arg):
        """Runs off the main thread (checking a password takes a moment)."""
        pw = str((arg or {}).get('password', '')) if isinstance(arg, dict) else ''
        if password_needed():
            now = time.monotonic()
            if now < self.wait_until:
                return {'ok': False, 'error': f'Wait {int(self.wait_until - now + 0.99)} seconds, then try again.'}
            if not password_ok(pw):
                self.fails += 1
                # after a few wrong tries, each try waits longer
                self.wait_until = time.monotonic() + (0 if self.fails < 3 else min(60, 5 * 2 ** (self.fails - 3)))
                return {'ok': False, 'error': 'That password isn’t right.' if self.fails < 3
                        else 'That password isn’t right. Wait a moment before trying again.'}
        self.fails, self.wait_until = 0, 0.0
        self.signed_in = True
        return {'ok': True}

    def sign_out(self, end_apps):
        """Lock (apps keep running) or sign out (apps are closed), then show the sign-in screen."""
        if end_apps:
            for app_id in list(self.apps):
                self.end_app(app_id)
            if self.ext is not None:
                self.ext.end()
                self.ext = None
        for w in self.apps.values():
            if w.get_visible():
                w.set_visible(False)
        if self.panel is not None:
            self.panel.set_visible(False)
        self.signed_in = False
        self.ext_waiting = 0
        self.bring_home()
        GLib.idle_add(lambda: (self.view.load_uri(UI + 'login.html'), False)[1])
        return {'ok': True}

    # ---------- running apps ----------

    def tasks(self):
        now = time.monotonic()
        return [{'id': w.app_id, 'name': w.name, 'running_s': int(now - w.started),
                 'title': w.page_title(), 'uri': w.page_uri(), 'shown': w.get_visible()}
                for w in self.apps.values()] + ([{
                    'id': self.ext.app_id, 'name': self.ext.name, 'running_s': int(now - self.ext.started),
                    'title': self.ext.title, 'uri': '', 'shown': not self.win.get_visible(), 'outside': True}]
                    if self.ext is not None else [])

    def push_tasks(self):
        self.js(f'window.__losTasks && window.__losTasks({json.dumps(self.tasks())});')
        return False

    def open_app(self, arg):
        arg = arg if isinstance(arg, dict) else {}
        app_id = str(arg.get('id') or 'browser')[:40]
        name = str(arg.get('name') or 'Browser')[:60]
        url = arg.get('url') or ''
        win = self.apps.get(app_id)
        if win is not None:
            if arg.get('navigate') and url:
                win.go(url)
            win.resume()
            return {'ok': True, 'resumed': True}
        ended = None
        others = [w for w in self.apps.values() if not isinstance(w, TermWin)]   # never cut off what runs in the Terminal
        if len(self.apps) >= MAX_APPS and others:   # free memory: end the app used longest ago
            oldest = min(others, key=lambda w: w.last_used)
            ended = oldest.name
            self.end_app(oldest.app_id)
        win = Browser(self, url, app_id, name)
        win.connect('close-request', self.on_app_closed)
        self.apps[app_id] = win
        return {'ok': True, 'resumed': False, 'ended': ended}

    def open_terminal(self):
        if Vte is None:
            return {'ok': False, 'error': 'The terminal isn’t available on this system.'}
        win = self.apps.get('terminal')
        if win is not None:
            win.resume()
            return {'ok': True, 'resumed': True}
        ended = None
        if len(self.apps) >= MAX_APPS:
            oldest = min(self.apps.values(), key=lambda w: w.last_used)
            ended = oldest.name
            self.end_app(oldest.app_id)
        win = TermWin(self)
        win.connect('close-request', self.on_app_closed)
        self.apps['terminal'] = win
        GLib.idle_add(self.push_tasks)
        return {'ok': True, 'resumed': False, 'ended': ended}

    def end_app(self, app_id):
        if self.ext is not None and self.ext.app_id == str(app_id):
            self.ext.end()
            self.ext = None
            self.bring_home()
            return {'ok': True}
        win = self.apps.pop(str(app_id), None)
        if win is None:
            return {'ok': False, 'error': 'not running'}
        visible = win.get_visible()
        win.shutdown()
        del win
        GLib.timeout_add(500, lambda: (gc.collect(), False)[1])
        if visible:
            self.show_home()
        GLib.idle_add(self.push_tasks)
        return {'ok': True}

    def on_app_closed(self, win):
        # closed from inside the app (Ctrl+W): end it the same way as End task
        if self.apps.get(win.app_id) is win:
            del self.apps[win.app_id]
        win.shutdown()
        GLib.timeout_add(500, lambda: (gc.collect(), False)[1])
        self.show_home()
        GLib.idle_add(self.push_tasks)
        return True   # handled: shutdown() already closed the window

    def on_app_hidden(self, win):
        self.show_home()
        GLib.idle_add(self.push_tasks)

    def show_home(self):
        # (sway takes full screen away from Home while an app is full screen: give it back)
        GLib.idle_add(lambda: (self.win.fullscreen(), self.win.present(), self.view.grab_focus(), False)[3])

    # ---------- outside apps: Steam, games, FreeTube, Windows programs ----------
    # Only one runs at a time, like a console. It draws its own window on top of Home.
    # Going Home re-shows the Home window on top; resuming hides Home so the app is
    # in front again. Super or the Xbox button comes back Home from inside the app.

    def open_ext(self, arg):
        arg = arg if isinstance(arg, dict) else {}
        app_id = str(arg.get('id', ''))
        if self.ext is not None and self.ext.alive():
            if self.ext.app_id == app_id and not arg.get('path'):
                self.resume_ext()
                return {'ok': True, 'resumed': True}
            return {'ok': False, 'busy': self.ext.name, 'busy_id': self.ext.app_id}
        cmd = ext_command(app_id, arg.get('path'))
        if not cmd:
            return {'ok': False, 'error': 'not_installed'}
        name, argv, cwd, title = cmd
        try:
            self.ext = ExtApp(app_id, name, argv, cwd, title)
        except OSError as e:
            return {'ok': False, 'error': str(e)}
        self.ext_waiting = time.monotonic()   # Home steps aside when the app's first window shows
        GLib.idle_add(self.push_tasks)
        return {'ok': True, 'resumed': False}

    def on_new_window(self):
        """A window that isn't ours appeared. If it's the first one from the app just
        started, Home steps aside so it (and any dialog it shows) is in front."""
        if not self.signed_in:   # signed out: the sign-in screen stays in front
            if self.win.get_visible():
                GLib.idle_add(self.bring_home)
            return False
        waiting = getattr(self, 'ext_waiting', 0)
        if self.ext is not None and waiting and time.monotonic() - waiting < 600 and self.win.get_visible():
            self.ext_waiting = 0
            self.resume_ext()
        return False

    def resume_ext(self):
        if not self.signed_in:
            return
        for w in self.apps.values():
            if w.get_visible():
                w.set_visible(False)
        self.ext.last_used = time.monotonic()
        self.win.set_visible(False)   # the app's own window is the one left on screen
        GLib.idle_add(self.push_tasks)

    def bring_home(self):
        self.quiet_super = time.monotonic() + 0.8
        self.ext_waiting = 0   # the player came back on purpose: don't jump to the app again
        if not self.win.get_visible():
            self.win.set_visible(True)
            self.win.fullscreen()
        else:   # Home is mapped but under the app: map it again so it comes to the front
            self.win.set_visible(False)
            self.win.set_visible(True)
            self.win.fullscreen()
        self.win.present()
        self.view.grab_focus()
        GLib.idle_add(self.push_tasks)
        return False

    def on_global_home(self):
        """Super key or Xbox button, seen on the raw input devices. Only acts when an
        outside app is in front: our own windows handle these keys themselves."""
        for w in list(self.apps.values()):   # the terminal has no page of its own to catch the Xbox button
            if isinstance(w, TermWin) and w.get_visible() and w.is_active():
                self.quiet_super = time.monotonic() + 0.8
                w.go_home()
                return False
        if self.ext is None:
            return False
        # (a hidden window can still report itself active, so only shown windows count)
        if (self.win.get_visible() and self.win.is_active()) or \
                any(w.get_visible() and w.is_active() for w in self.apps.values()):
            return False
        self.bring_home()
        return False

    def check_ext(self):
        if self.ext is not None and not self.ext.alive():
            name, quick = self.ext.name, time.monotonic() - self.ext.started < 30
            self.ext = None
            self.bring_home()
            msg = (f'{name} closed right away. The first time, it needs an internet connection.' if quick and name in ('Steam', 'Roblox', 'FreeTube')
                   else f'{name} closed')
            self.js(f'window.LOS && LOS.toast({json.dumps(msg)}, 4500);')
        return True

    # ---------- Discord side panel ----------

    def discord_panel(self, arg):
        want = (arg or {}).get('open', True) if isinstance(arg, dict) else True
        if want and self.panel is None:
            self.panel = self.build_panel()
        if self.panel is None:
            return {'ok': True, 'open': False}
        if want:
            w = self.win.get_width() or 1280
            self.panel.set_size_request(max(400, min(560, int(w * 0.36))), -1)
            self.panel.set_visible(True)
            self.panel_view.grab_focus()
        else:
            self.panel.set_visible(False)
            self.view.grab_focus()
        self.js(f'window.__losPanel && window.__losPanel({json.dumps(bool(want))});')
        return {'ok': True, 'open': bool(want)}

    def build_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.END, valign=Gtk.Align.FILL)
        box.add_css_class('lospanel')
        for side in ('top', 'bottom', 'end'):
            getattr(box, 'set_margin_' + side)(22)
        head = Gtk.Box(spacing=8)
        head.add_css_class('losbar')
        title = Gtk.Label(label='Discord', xalign=0, hexpand=True)
        title.add_css_class('lostitle')
        close = Gtk.Button(label='Close  (Super)')
        close.connect('clicked', lambda *_: self.discord_panel({'open': False}))
        head.append(title)
        head.append(close)
        ucm = WebKit.UserContentManager()
        ucm.connect('script-message-received::losbrowser', lambda m, v: self.discord_panel({'open': False}))
        ucm.register_script_message_handler('losbrowser', None)
        ucm.add_script(WebKit.UserScript.new(PAD_EXIT_JS, WebKit.UserContentInjectedFrames.TOP_FRAME,
                                             WebKit.UserScriptInjectionTime.END, None, None))
        self.panel_view = WebKit.WebView(vexpand=True, user_content_manager=ucm)
        self.panel_view.set_size_request(200, 200)   # (see Browser: never zero height)
        self.panel_view.set_background_color(NAVY)
        st = self.panel_view.get_settings()
        st.set_hardware_acceleration_policy(ACCEL)
        st.set_user_agent_with_application_details('LaunchOS', release().get('VERSION', '0'))
        self.panel_view.connect('permission-request', lambda v, req: (req.deny(), True)[1])
        self.panel_view.connect('load-failed', self.on_panel_failed)
        self.panel_view.load_uri('https://discord.com/app')
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', lambda c, k, code, st: (self.discord_panel({'open': False}), True)[1] if k in SUPER_KEYS else False)
        box.add_controller(keys)
        box.append(head)
        box.append(self.panel_view)
        self.overlay.add_overlay(box)
        return box

    def on_panel_failed(self, view, event, uri, error):
        if error.matches(WebKit.NetworkError.quark(), WebKit.NetworkError.CANCELLED):
            return False
        html = ('<body style="margin:0;height:100vh;display:grid;place-items:center;background:#0f1b2a;color:#dce6f0;'
                'font:16px Inter,sans-serif;text-align:center"><div><p style="font-size:20px;font-weight:600">Couldn’t open Discord</p>'
                '<p>Check your connection in Settings, then <a style="color:#3ddc6b" href="https://discord.com/app">try again</a>.</p></div></body>')
        view.load_alternate_html(html, uri, None)
        return True

    # ---------- downloads from web apps ----------

    def on_download(self, session, download):
        view = download.get_web_view()
        win = next((w for w in self.apps.values() if w.view is view), None)
        note = win.show_note if win else (lambda t: None)
        state = {'name': 'file', 'failed': False}

        def decide(d, suggested):
            folder = os.path.join(HOME, 'Downloads')
            os.makedirs(folder, exist_ok=True)
            base = os.path.basename(suggested or '') or 'download'
            name, n = base, 1
            while os.path.exists(os.path.join(folder, name)):
                stem, ext = os.path.splitext(base)
                n += 1
                name = f'{stem} ({n}){ext}'
            state['name'] = name
            d.set_destination(os.path.join(folder, name))
            note(f'Downloading {name}…')
            return True

        def finished(d):
            if state['failed']:
                return
            extra = '  Open it from Windows programs on Home.' if state['name'].lower().endswith(('.exe', '.msi')) else ''
            note(f'Saved {state["name"]} to Downloads.{extra}')

        def failed(d, err):
            state['failed'] = True
            note('The download didn’t finish.')

        download.connect('decide-destination', decide)
        download.connect('finished', finished)
        download.connect('failed', failed)


if __name__ == '__main__':
    Launcher().run()
