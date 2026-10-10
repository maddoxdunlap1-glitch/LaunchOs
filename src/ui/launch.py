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

# Written once the sign-in screen has loaded: seconds from power-on (kernel start) to LaunchOS
# being ready. Shown in Settings > About, and read by the start-up speed test.
READY_FILE = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or '/run/player', 'launchos-ready')

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
    try:
        boot_s = round(float(read(READY_FILE, '0').strip() or 0), 1)
    except ValueError:
        boot_s = 0
    return {
        'boot_s': boot_s,
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
MAX_APPS = 6   # web apps kept running in the background; the least recently used one is ended past this


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
        # no right-click menu on LaunchOS's own pages (websites keep theirs)
        self.view.connect('context-menu', lambda v, *a: (v.get_uri() or '').startswith(UI))
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
        """Back to Home; the app keeps running (on its own screen) so it can be resumed or ended later."""
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
        self.launcher.front = self.app_id
        sway_ws(ws_for(self.app_id))
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
        self.launcher.on_app_hidden(self)

    def resume(self):
        self.last_used = time.monotonic()
        self.launcher.front = self.app_id
        sway_ws(ws_for(self.app_id))
        self.present()
        self.term.grab_focus()

    def shutdown(self):
        """Closing the window hangs up the shell and what runs in it."""
        if self.term is None:
            return
        self.term = None
        self.destroy()


# ---------- LaunchOS's own screens ----------

def ui_view(launcher, win_id):
    """A web view for LaunchOS's own pages: the bridge to the system (window.LOS), no right-click
    menu (no Copy, Reload or Inspect on buttons and tiles), drawn on the same navy as the pages."""
    ucm = WebKit.UserContentManager()
    holder = {}
    ucm.connect('script-message-received::launchos', lambda m, v: launcher.on_message(m, v, holder.get('view')))
    ucm.register_script_message_handler('launchos', None)
    ucm.add_script(WebKit.UserScript.new(f'window.__losHW = {"true" if HW else "false"}; window.__losWin = {json.dumps(win_id)};',
                                         WebKit.UserContentInjectedFrames.TOP_FRAME,
                                         WebKit.UserScriptInjectionTime.START, None, None))
    view = WebKit.WebView(user_content_manager=ucm, vexpand=True, hexpand=True)
    holder['view'] = view
    view.set_size_request(200, 200)   # (see Browser: never laid out at zero height)
    view.set_background_color(NAVY)
    s = view.get_settings()
    s.set_hardware_acceleration_policy(ACCEL)
    s.set_enable_developer_extras(False)
    s.set_allow_file_access_from_file_urls(True)
    s.set_media_playback_requires_user_gesture(False)   # the viewer starts a video or song you picked in Files
    view.connect('context-menu', lambda *a: True)
    return view


# LaunchOS's own apps, each a page in a window of its own
PAGES = {'files': 'Files', 'settings': 'Settings', 'store': 'Store', 'monitor': 'System monitor', 'setup': 'Setup'}


class PageWin(Gtk.ApplicationWindow):
    """Files, Settings, the Store, the system monitor or Setup: a LaunchOS page in a window of its
    own, on a screen of its own. It opens out of sight (sway.conf puts a window with this title on
    its screen) and comes to the front once its page is drawn, so opening never shows a half-drawn
    or blank screen; going Home keeps it as it was, so coming back is instant too. Home itself is
    never reloaded."""

    def __init__(self, app, page, url):
        super().__init__(application=app, title='LaunchOS ' + PAGES[page])
        self.launcher, self.page = app, page
        self.app_id, self.name = 'page:' + page, PAGES[page]
        self.started = self.last_used = time.monotonic()
        self.back = 'home'
        self.pending = 0
        self.view = ui_view(app, page)
        self.set_child(self.view)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_key)
        self.add_controller(keys)
        self.view.load_uri(url)
        self.fullscreen()
        self.present()

    def js(self, code):
        if self.view is not None:
            self.view.evaluate_javascript(code, -1, None, None, None, None, None)

    def on_key(self, ctl, keyval, code, state):
        if keyval in SUPER_KEYS and time.monotonic() < self.launcher.quiet_super:
            return True
        if keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK):
            self.js('window.__losOpts && window.__losOpts();')
            return True
        if keyval in SUPER_KEYS:
            self.js('window.__losGuide && window.__losGuide();')   # (the page goes Home)
            return True
        return False

    def page_title(self):
        return ''

    def page_uri(self):
        return ''

    def shutdown(self):
        if self.view is None:
            return
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0
        try:
            self.view.terminate_web_process()
        except Exception:
            pass
        self.view = None
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


def flatpak_argv(app):
    """How to start a Flathub app. Apps that can draw through X11 do (in Xwayland): there sway turns
    down a minimize request from the app in front, while on Wayland apps built on Chromium (Discord,
    Spotify, Heroic…) think they were minimized when their own minimize button is pressed, stop
    drawing and look frozen, because LaunchOS has nothing to minimize to."""
    sockets = ''
    try:
        with open(f'/var/lib/flatpak/app/{app}/current/active/metadata') as f:
            for line in f:
                if line.startswith('sockets='):
                    sockets = line.split('=', 1)[1]
                    break
    except OSError:
        pass
    socks = set(x.strip() for x in sockets.split(';'))
    if socks & {'x11', 'fallback-x11'}:
        return ['flatpak', 'run', '--nosocket=wayland', '--unset-env=WAYLAND_DISPLAY', app]
    return ['flatpak', 'run', app]


FIREFOX = '/usr/bin/firefox-esr'


def firefox_ok():
    return os.path.exists(FIREFOX)


def ext_command(app_id, path=None):
    """(name, argv, working folder, title) for an outside app, or None if it can't start."""
    if app_id == 'browser' and firefox_ok():
        return 'Firefox', [FIREFOX], HOME, 'Firefox'
    if app_id == 'steam' and os.path.exists('/usr/games/steam'):
        return 'Steam', ['env', 'PATH=/usr/local/lib/launchos/steam-shim:' + os.environ.get('PATH', '/usr/bin:/bin'),
                         '/usr/games/steam', '-gamepadui'], HOME, 'Steam'
    if app_id in FLATPAKS and flatpak_installed(FLATPAKS[app_id][0]):
        app, name = FLATPAKS[app_id]
        return name, flatpak_argv(app), HOME, name
    if app_id.startswith('app:') and APP_ID.fullmatch(app_id[4:]) and flatpak_installed(app_id[4:]):
        aid = app_id[4:]   # an app from the Store
        name = (_store['by_id'].get(aid) or {}).get('name') or aid.split('.')[-1]
        return name, flatpak_argv(aid), HOME, name
    if app_id == 'winprog':
        real = program_path_ok(path)
        if real and os.path.exists('/usr/bin/wine'):
            title = os.path.splitext(os.path.basename(real))[0]
            argv = ['wine', 'msiexec', '/i', real] if real.lower().endswith('.msi') else ['wine', real]
            return 'Windows program', argv, os.path.dirname(real), title
    return None


def ext_key(app_id, path=None):
    """The running app's id: the app's own id, or for Windows programs one per program (any number
    of them can run, each with its own screen)."""
    if app_id == 'winprog' and path:
        stem = re.sub(r'[^a-z0-9]+', '-', os.path.splitext(os.path.basename(str(path)))[0].lower()).strip('-')
        return 'winprog:' + (stem[:24] or 'program')
    return app_id


def proc_stat(pid):
    """(parent pid, session id) of a process, or None if it's gone."""
    s = read(f'/proc/{pid}/stat')
    try:
        f = s[s.rindex(')') + 2:].split()
        return int(f[1]), int(f[3])
    except (ValueError, IndexError):
        return None


def flatpak_of(pid):
    """The Flathub app a process belongs to ('' if none): sandboxed apps see /.flatpak-info."""
    try:
        with open(f'/proc/{int(pid)}/root/.flatpak-info') as f:
            for line in f:
                if line.startswith('name='):
                    return line[5:].strip()
    except (OSError, ValueError, TypeError):
        pass
    return ''


class ExtApp:
    """An outside app in its own process group, so End task stops all of it. Its windows are on
    a screen of its own ("x-<its id>"), so any number of them can run side by side: Discord
    while you play, Steam and a Windows program, Firefox and the Terminal."""

    def __init__(self, key, kind, name, argv, cwd, title, env=None, extra=None):
        self.key, self.kind, self.name, self.title = key, kind, name, title
        self.app_id = key
        self.argv, self.cwd, self.env = argv, cwd, env
        self.started = self.last_used = time.monotonic()
        self.waiting = self.started   # its first window brings it to the front (if you're still on Home)
        self.opened_from = 'home'
        flat = FLATPAKS.get(kind, (kind[4:] if kind.startswith('app:') else '',))[0]
        self.flatpak = flat
        # names its windows may have (Wayland app id or X11 class)
        self.names = {n.lower() for n in (flat.split('.')[-1] if flat else '', name, kind, 'firefox' if kind == 'browser' else '') if n}
        logdir = os.path.join(HOME, '.cache', 'launchos')
        os.makedirs(logdir, exist_ok=True)
        log = open(os.path.join(logdir, re.sub(r'[^\w.-]+', '_', key) + '.log'), 'ab')
        self.proc = subprocess.Popen(argv + list(extra or []), cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True, env=env)
        log.close()
        self.pgid = self.proc.pid

    def reopen(self, extra=None):
        """It's running but has no window (closed to the tray, like Discord or Steam): starting it
        again makes the running copy show its window (Firefox opens the page in a new tab). Not
        for Windows programs (that would start a second copy)."""
        if self.kind == 'winprog':
            return
        try:
            subprocess.Popen(self.argv + list(extra or []), cwd=self.cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=self.env)
        except OSError:
            pass

    def matches(self, app):
        """Whether a window's app id or X11 class looks like this app's."""
        a = (app or '').lower()
        if not a:
            return False
        return any(n == a or (len(n) >= 4 and n in a) or (len(a) >= 4 and a in n) for n in self.names)

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


def sway_windows():
    """Every window sway has: (con id, app id or X11 class, focused, in the scratchpad), or None if
    sway can't be asked."""
    try:
        tree = json.loads(subprocess.run(['swaymsg', '-t', 'get_tree', '-r'], capture_output=True, text=True,
                                         timeout=2).stdout or 'null')
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    out, todo = [], [(tree, False)] if isinstance(tree, dict) else []
    while todo:
        n, hidden = todo.pop()
        hidden = hidden or (n.get('type') == 'workspace' and n.get('name') in ('__i3_scratch', 'parked'))
        if n.get('type') in ('con', 'floating_con') and n.get('pid'):
            out.append((n.get('id'), n.get('app_id') or (n.get('window_properties') or {}).get('class') or '',
                        bool(n.get('focused')), hidden))
        todo.extend((c, hidden) for c in (n.get('nodes') or []) + (n.get('floating_nodes') or []))
    return out


def sway_cmd(cmd):
    try:
        subprocess.run(['swaymsg', cmd], capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


# Every app has a screen of its own (a sway workspace) and stays full screen on it: Home on "1"
# (where sway puts the first window of what its config started), each outside app (a game, Steam,
# Discord, Firefox…) on "x-<its id>", each of our web apps and the Terminal on "w-<its id>", and
# Files, Settings, the Store, the system monitor and Setup on "p-<page>". Windows that aren't ours
# first land on "app" (sway.conf sends them there, out of sight) and the launcher moves each to its
# app's screen. Switching apps is switching screens: nothing is hidden, shown again, reloaded or
# resized, so nothing flickers or redraws.
WS_HOME, WS_APP = '1', 'app'


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')[:30] or 'app'


def ws_for(app_id):
    return 'w-' + _slug(app_id)


def ws_ext(key):
    return 'x-' + _slug(key)


def ws_page(page):
    return 'p-' + page


def sway_ws(name):
    sway_cmd(f'workspace {name}')


def sway_ws_windows():
    """{workspace name: [(con id, app id or X11 class, focused, pid)]} and the name of the screen shown."""
    try:
        tree = json.loads(subprocess.run(['swaymsg', '-t', 'get_tree', '-r'], capture_output=True, text=True,
                                         timeout=2).stdout or 'null')
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None
    out, shown, todo = {}, None, [(tree, None)] if isinstance(tree, dict) else []
    while todo:
        n, ws = todo.pop()
        if n.get('type') == 'workspace':
            ws = n.get('name')
            out.setdefault(ws, [])
            if n.get('visible'):
                shown = ws
        if n.get('type') in ('con', 'floating_con') and n.get('pid') and ws:
            out[ws].append((n.get('id'), n.get('app_id') or (n.get('window_properties') or {}).get('class') or '',
                            bool(n.get('focused')), n.get('pid') or 0))
        todo.extend((c, ws) for c in (n.get('nodes') or []) + (n.get('floating_nodes') or []))
    return out, shown


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
                    change = ev.get('change')
                    if change == 'close' or (change in ('new', 'focus', 'fullscreen_mode') and con.get('app_id') != 'os.launch.home'):
                        GLib.idle_add(self.callback, change)
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

# ---------- LaunchOS Pro ----------

PRO_STATE = '/var/lib/launchos/pro.json'
PRO_DIR = '/opt/launchos-pro'
PRO_CONF = '/etc/launchos/pro.conf'
PRO_KEY = re.compile(r'[A-Za-z0-9-]{8,64}')
GAMING_CONF = os.path.join(HOME, '.config', 'launchos', 'gaming.json')
FPS_MODES = {   # the FPS counter's looks (MangoHud settings)
    'fps': 'fps_only,position=top-left,font_size=22,background_alpha=0.35',
    'full': 'fps,frametime,frame_timing=1,cpu_stats,cpu_temp,gpu_stats,gpu_temp,ram,vram,position=top-left,font_size=18,background_alpha=0.4',
}


def kv_file(path):
    out = {}
    for line in read(path).splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def json_obj(text):
    try:
        v = json.loads(text or '{}')
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def pro_info():
    """Whether LaunchOS Pro is on here (a checked key and the Pro extras installed)."""
    st = json_obj(read(PRO_STATE, '{}'))
    man = json_obj(read(os.path.join(PRO_DIR, 'manifest.json'), '{}'))
    conf = kv_file(PRO_CONF)
    buy = conf.get('buy', '')
    return {'active': st.get('status') == 'active' and bool(man), 'status': str(st.get('status', '')),
            'installed': bool(man),   # (status active without the extras: they still have to download)
            'key_hint': str(st.get('key_hint', ''))[:20], 'since': str(st.get('since', ''))[:10],
            'version': str(man.get('version', ''))[:20], 'on_sale': bool(conf.get('url')),
            'buy': buy if re.fullmatch(r'https://[^\s"<>]{4,300}', buy) else '',
            'job': job_status('pro'), 'fps_ok': os.path.exists('/usr/bin/mangohud'), 'saving': saving_on()}


def pro_job(payload):
    """Starts a Pro job and returns once it has really started, so the progress screen never shows
    the previous job's result."""
    path = '/run/launchos-status/pro.json'

    def stamp():
        try:
            s = os.stat(path)
            return (s.st_ino, s.st_mtime_ns)
        except OSError:
            return None
    before = stamp()
    if not helper_request(payload).get('ok'):
        return {'ok': False, 'error': 'LaunchOS couldn’t ask for that. Try again.'}
    end = time.monotonic() + 8
    while time.monotonic() < end:
        time.sleep(0.2)
        if stamp() != before:
            return {'ok': True}
    return {'ok': False, 'error': 'LaunchOS Pro didn’t start. Try again.'}


def pro_action(arg):
    arg = arg if isinstance(arg, dict) else {}
    op = str(arg.get('op', ''))
    if op == 'activate':
        key = re.sub(r'\s+', '', str(arg.get('key', '')))
        if not PRO_KEY.fullmatch(key):
            return {'ok': False, 'error': 'That doesn’t look like a Pro key. It’s in the email from your purchase.'}
        if job_running('pro', 'launchos-pro'):
            return {'ok': False, 'error': 'Wait for LaunchOS Pro to finish what it’s doing.'}
        return pro_job({'action': 'pro', 'op': 'activate', 'key': key})
    if op in ('install', 'remove'):
        if job_running('pro', 'launchos-pro'):
            return {'ok': False, 'error': 'Wait for LaunchOS Pro to finish what it’s doing.'}
        return pro_job({'action': 'pro', 'op': op})
    if op == 'check':
        helper_request({'action': 'pro', 'op': 'check'})
        return {'ok': True}
    return {'ok': False, 'error': 'unknown'}


_qr_cache = {}


def pro_qr():
    """A QR code (SVG) for the page where Pro is sold, to open it on a phone."""
    url = pro_info()['buy']
    if not url:
        return {'svg': ''}
    if url not in _qr_cache:
        try:
            import qrcode
            import qrcode.image.svg
            img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=10, border=2)
            _qr_cache[url] = img.to_string(encoding='unicode')
        except Exception:
            _qr_cache[url] = ''
    return {'svg': _qr_cache[url], 'url': url}


def gaming_get():
    try:
        g = json.loads(read(GAMING_CONF, '{}') or '{}')
    except ValueError:
        g = {}
    return {'perf': bool(g.get('perf', True)), 'fps': g.get('fps') if g.get('fps') in FPS_MODES else 'off'}


def gaming_set(arg):
    g = gaming_get()
    if isinstance(arg, dict):
        if 'perf' in arg:
            g['perf'] = bool(arg['perf'])
        if arg.get('fps') in ('off', *FPS_MODES):
            g['fps'] = arg['fps']
    os.makedirs(os.path.dirname(GAMING_CONF), exist_ok=True)
    with open(GAMING_CONF, 'w') as f:
        json.dump(g, f)
    return g


GAME_APPS = {'steam', 'winprog', 'roblox', 'minecraft', 'heroic'}


def is_game(app_id):
    """Steam, Windows programs, the game apps, and Store apps that are games or emulators."""
    if app_id in GAME_APPS:
        return True
    if not app_id.startswith('app:') or not APP_ID.fullmatch(app_id[4:]):
        return False
    aid = app_id[4:]
    desktop = f'/var/lib/flatpak/app/{aid}/current/active/export/share/applications/{aid}.desktop'
    for line in read(desktop).splitlines():
        if line.startswith('Categories='):
            cats = line.split('=', 1)[1].split(';')
            return 'Game' in cats or 'Emulator' in cats
    return 'games' in ((_store['by_id'].get(aid) or {}).get('shelves') or [])


def game_env(app_id, argv):
    """With Pro, for games: the FPS counter (MangoHud) and a bigger shader cache."""
    if not is_game(app_id) or not pro_info()['active']:
        return argv, None
    g = gaming_get()
    # (without saving, the cache lives in memory: keep it small)
    env = dict(os.environ, MESA_SHADER_CACHE_MAX_SIZE='10G' if saving_on() else '512M')
    if g['fps'] in FPS_MODES and os.path.exists('/usr/bin/mangohud'):
        env.update(MANGOHUD='1', MANGOHUD_CONFIG=FPS_MODES[g['fps']])
        if app_id == 'winprog':
            argv = ['mangohud'] + argv   # (Wine's own OpenGL drawing needs the wrapper)
    return argv, env


# What the sign-in screen may use before anyone has signed in
SIGNED_OUT_OK = {'session_state', 'sign_in', 'power', 'info', 'network', 'log_error', 'inputs', 'timezone_get', 'pro_state'}


class Launcher(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='os.launch.home')
        self.apps = {}   # app id -> Browser or Terminal window, running (shown or in the background)
        self.exts = {}   # app id -> ExtApp: outside apps (games, Steam, Discord, Firefox…), as many as you like
        self.pages = {}   # page -> PageWin: Files, Settings, the Store, the system monitor, Setup
        self.game_keys = set()   # outside apps running with gaming mode (Pro)
        self.opening_page = None   # a page window being drawn out of sight, shown when it's ready
        self.panel = None   # Discord side panel
        self.quiet_super = 0.0
        self.signed_in = False
        self.front = 'home'   # what's on screen: 'home', an outside app's id, one of our apps' ids, or 'page:<page>'
        self.fails, self.wait_until = 0, 0.0   # wrong passwords in a row, and when the next try is allowed
        self.signin_lock = threading.Lock()
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property('gtk-application-prefer-dark-theme', True)
        css = Gtk.CssProvider()
        css.load_from_data(BROWSER_CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        sway_ws(WS_HOME)   # (Home's window opens on its own screen)
        self.win = Gtk.ApplicationWindow(application=app, title='LaunchOS')
        self.view = ui_view(self, 'home')
        self.view.connect('load-changed', self.on_first_load)
        self.view.load_uri(UI + 'login.html')
        self.overlay = Gtk.Overlay()
        self.overlay.set_child(self.view)
        self.win.set_child(self.overlay)
        self.hold()   # keep running while Home is hidden behind a game
        WebKit.NetworkSession.get_default().connect('download-started', self.on_download)
        InputWatcher(self.on_global_home).start()
        SwayWatcher(self.on_new_window).start()
        sway_cmd('focus_on_window_activation urgent')
        self.start_guard()   # (it starts signed out)
        GLib.timeout_add(1500, self.check_ext)
        # Super (Windows) key on Home works like the Xbox button: the page opens or closes the side menu.
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_home_key)
        self.win.add_controller(keys)
        self.win.fullscreen()
        self.win.present()

    def on_first_load(self, view, event):
        """The first page (the sign-in screen) has loaded: note how long start-up took."""
        if event != WebKit.LoadEvent.FINISHED or getattr(self, 'ready_noted', False):
            return
        self.ready_noted = True
        try:
            up = read('/proc/uptime', '0').split()[0]
            tmp = READY_FILE + '.tmp'
            with open(tmp, 'w') as f:
                f.write(up + '\n')
            os.replace(tmp, READY_FILE)
            print(f'LaunchOS ready {up} s after start', flush=True)
        except OSError:
            pass

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

    def live_view(self, view):
        return view is self.view or any(w.view is view for w in self.pages.values())

    def reply(self, rid, data, view=None):
        view = view or self.view
        if not self.live_view(view):
            return False   # its window was closed meanwhile
        js = f'window.__losReply && window.__losReply({json.dumps(rid)}, {json.dumps(data)});'
        view.evaluate_javascript(js, -1, None, None, None, None, None)
        return False

    def page_of(self, view):
        return next((w for w in self.pages.values() if w.view is view and view is not None), None)

    def on_message(self, ucm, value, view=None):
        view = view or self.view
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
            self.reply(rid, {'error': 'signed_out'}, view)
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
                'get_app': lambda: get_app(arg), 'apps_info': apps_info, 'sign_in': lambda: self.sign_in(arg),
                'pro_qr': pro_qr, 'pro_action': lambda: pro_action(arg)}
        if action in slow:
            def work():
                try:
                    result = slow[action]()
                except Exception as e:   # never let one bad request take the launcher down
                    result = {'error': str(e)}
                GLib.idle_add(self.reply, rid, result, view)
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
            'open_browser': lambda: self.open_app({'id': 'browser', 'name': 'Browser', 'url': arg, 'navigate': True}),
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
            # LaunchOS's own apps (Files, Settings, Store, System monitor, Setup)
            'open_page': lambda: self.open_page(arg),
            'page_ready': lambda: self.page_ready(self.page_of(view)),
            'page_back': lambda: self.page_back(self.page_of(view), arg),
            'go_home': lambda: (self.bring_home(), {'ok': True})[1],

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
            'pro_state': pro_info,
            'gaming_get': gaming_get,
            'gaming_set': lambda: gaming_set(arg),
        }
        fn = handlers.get(action)
        try:
            result = fn() if fn else {'error': 'unknown action'}
        except Exception as e:  # never let one bad request take the launcher down
            result = {'error': str(e)}
        self.reply(rid, result, view)

    # ---------- sign-in ----------

    def session_state(self):
        return {'signed_in': self.signed_in, 'password': password_needed(),
                'password_set': os.path.exists('/etc/launchos/admin-set'), 'ask': signin_ask(),
                'wait_s': max(0, int(self.wait_until - time.monotonic() + 0.99)), 'running': len(self.tasks())}

    def sign_in(self, arg):
        """Runs off the main thread (checking a password takes a moment)."""
        pw = str((arg or {}).get('password', '')) if isinstance(arg, dict) else ''
        with self.signin_lock:   # one try at a time
            return self._sign_in(pw)

    def _sign_in(self, pw):
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

        def after():
            sway_cmd('focus_on_window_activation smart')
            self.sort_strays()   # windows that opened while signed out go to their apps' screens
            return False
        GLib.idle_add(after)
        return {'ok': True}

    # ---------- signed out: the sign-in screen stays in front ----------

    def guard_soon(self):
        """Checks what's in front a moment after a window event (apps often do several things in a
        row: open, go full screen, ask for focus), and brings the sign-in screen back if needed."""
        if getattr(self, 'guard_timer', 0):
            return
        self.guard_timer = GLib.timeout_add(250, self.guard_check)

    def guard_check(self):
        """Signed out: the sign-in screen is the one shown. Other apps' windows are on their own
        screens, out of sight (and can't be reached); one that turned up on Home's screen is sent to
        its app's screen. They're all there again when you sign in and go back to the app."""
        self.guard_timer = 0
        if self.signed_in:
            return False
        self.sort_strays()
        wins, shown = sway_ws_windows()
        if wins is None:
            return False
        if shown != WS_HOME or not any(app == 'os.launch.home' and f for _, app, f, _p in wins.get(WS_HOME, [])):
            self.front = 'home'
            sway_ws(WS_HOME)
            sway_cmd('[app_id="^os\\.launch\\.home$" title="^LaunchOS$"] fullscreen enable, focus')
        return False

    def guard_tick(self):
        """While signed out, every 2 seconds too (in case a window event was missed)."""
        if self.signed_in:
            self.guard_ticker = 0
            return False
        self.guard_check()
        return True

    def start_guard(self):
        if not getattr(self, 'guard_ticker', 0):
            self.guard_ticker = GLib.timeout_add(2000, self.guard_tick)

    def sign_out(self, end_apps):
        """Lock (apps keep running) or sign out (apps are closed), then show the sign-in screen.
        LaunchOS's own app windows (Files, Settings…) close either way."""
        if end_apps:
            for app_id in list(self.apps):
                self.end_app(app_id)
            for key in list(self.exts):
                self.drop_ext(key, end=True)
        if self.panel is not None:
            self.panel.set_visible(False)
        self.signed_in = False
        for e in self.exts.values():
            e.waiting = 0
        # (an app asking to be shown only gets marked, never focused, until you sign in again)
        sway_cmd('focus_on_window_activation urgent')
        self.bring_home()
        self.start_guard()
        self.guard_soon()

        def after():
            for page in list(self.pages):   # (after this reply has gone to the page that asked)
                self.close_page(page)
            self.view.load_uri(UI + 'login.html')
            return False
        GLib.idle_add(after)
        return {'ok': True}

    # ---------- running apps ----------

    def tasks(self):
        now = time.monotonic()
        return ([{'id': w.app_id, 'name': w.name, 'running_s': int(now - w.started),
                  'title': w.page_title(), 'uri': w.page_uri(), 'shown': self.front == w.app_id}
                 for w in self.apps.values()]
                + [{'id': e.key, 'name': e.name, 'running_s': int(now - e.started), 'title': e.title, 'uri': '',
                    'shown': self.front == e.key, 'outside': True}
                   for e in sorted(self.exts.values(), key=lambda e: e.started)]
                + [{'id': w.app_id, 'name': w.name, 'running_s': int(now - w.started), 'title': w.name, 'uri': '',
                    'shown': self.front == w.app_id, 'page': w.page}
                   for w in self.pages.values()])

    def push_tasks(self):
        self.js(f'window.__losTasks && window.__losTasks({json.dumps(self.tasks())});')
        return False

    def stop_waiting(self):
        """You went somewhere yourself: an app still starting doesn't jump in front when its window shows."""
        self.opening_page = None
        for e in self.exts.values():
            e.waiting = 0

    def open_app(self, arg):
        arg = arg if isinstance(arg, dict) else {}
        app_id = str(arg.get('id') or 'browser')[:40]
        name = str(arg.get('name') or 'Browser')[:60]
        url = arg.get('url') or ''
        if app_id == 'browser' and firefox_ok():   # the web browser is Firefox
            return self.open_ext({'id': 'browser', 'url': url})
        win = self.apps.get(app_id)
        if win is not None:
            if arg.get('navigate') and url:
                win.go(url)
            self.stop_waiting()
            win.resume()
            return {'ok': True, 'resumed': True}
        ended = None
        others = [w for w in self.apps.values() if not isinstance(w, TermWin)]   # never cut off what runs in the Terminal
        if len(self.apps) >= MAX_APPS and others:   # free memory: end the app used longest ago
            oldest = min(others, key=lambda w: w.last_used)
            ended = oldest.name
            self.end_app(oldest.app_id)
        self.stop_waiting()
        self.front = app_id
        sway_ws(ws_for(app_id))   # (its window opens on its own screen)
        win = Browser(self, url, app_id, name)
        win.connect('close-request', self.on_app_closed)
        self.apps[app_id] = win
        return {'ok': True, 'resumed': False, 'ended': ended}

    def open_terminal(self):
        if Vte is None:
            return {'ok': False, 'error': 'The terminal isn’t available on this system.'}
        win = self.apps.get('terminal')
        if win is not None:
            self.stop_waiting()
            win.resume()
            return {'ok': True, 'resumed': True}
        self.stop_waiting()
        self.front = 'terminal'
        sway_ws(ws_for('terminal'))
        win = TermWin(self)
        win.connect('close-request', self.on_app_closed)
        self.apps['terminal'] = win
        GLib.idle_add(self.push_tasks)
        return {'ok': True, 'resumed': False}

    def end_app(self, app_id):
        app_id = str(app_id)
        if app_id in self.exts:
            self.drop_ext(app_id, end=True)
            return {'ok': True}
        if app_id.startswith('page:'):
            return {'ok': self.close_page(app_id[5:])}
        win = self.apps.pop(app_id, None)
        if win is None:
            return {'ok': False, 'error': 'not running'}
        if self.front == win.app_id:
            self.bring_home()   # (Home first, then the window goes: no empty screen in between)
        win.shutdown()
        del win
        GLib.timeout_add(500, lambda: (gc.collect(), False)[1])
        GLib.idle_add(self.push_tasks)
        return {'ok': True}

    def on_app_closed(self, win):
        # closed from inside the app (Ctrl+W): end it the same way as End task
        if self.apps.get(win.app_id) is win:
            del self.apps[win.app_id]
        if self.front == win.app_id:
            self.bring_home()
        win.shutdown()
        GLib.timeout_add(500, lambda: (gc.collect(), False)[1])
        GLib.idle_add(self.push_tasks)
        return True   # handled: shutdown() already closed the window

    def on_app_hidden(self, win):
        self.show_home()
        GLib.idle_add(self.push_tasks)

    def show_home(self):
        GLib.idle_add(self.bring_home)

    # ---------- LaunchOS's own apps: Files, Settings, the Store, the system monitor, Setup ----------

    def open_page(self, arg):
        arg = arg if isinstance(arg, dict) else {}
        page = str(arg.get('page', ''))
        if page not in PAGES:
            return {'ok': False, 'error': 'unknown page'}
        hash_ = str(arg.get('hash') or '')[:300]
        url = UI + page + '.html' + ('#' + hash_ if hash_ else '')
        back = str(arg.get('back') or 'home')
        w = self.pages.get(page)
        self.stop_waiting()
        # (Setup opened for one step, or for all of them, starts over; the others carry on where they were)
        if w is not None and (w.view.get_uri() == url or (not hash_ and page != 'setup')):
            w.back = back if back in PAGES and back != page else 'home'
            self.show_page(w)
            return {'ok': True, 'resumed': True}
        if w is None:
            w = PageWin(self, page, url)   # (drawn out of sight; page_ready brings it in front)
            w.connect('close-request', self.on_page_closed)
            self.pages[page] = w
        else:
            w.view.load_uri(url)   # (asked for a particular place in it: e.g. one app in the Store)
        w.back = back if back in PAGES and back != page else 'home'
        self.opening_page = page
        if w.pending:
            GLib.source_remove(w.pending)
        w.pending = GLib.timeout_add(1500, lambda: (self.page_ready(w, late=True), False)[1])   # (never longer than that)
        GLib.idle_add(self.push_tasks)
        return {'ok': True, 'resumed': False}

    def page_ready(self, w, late=False):
        """The page in a page window has drawn itself: bring it in front, if it's still wanted there."""
        if w is None:
            return {'ok': False}
        if w.pending and not late:
            GLib.source_remove(w.pending)
        w.pending = 0
        if self.opening_page == w.page and self.pages.get(w.page) is w and self.signed_in:
            self.show_page(w)
        return {'ok': True}

    def show_page(self, w):
        self.opening_page = None
        w.last_used = time.monotonic()
        self.front = w.app_id
        sway_ws(ws_page(w.page))
        w.present()
        if w.view is not None:
            w.view.grab_focus()
        w.js('window.__losBack && window.__losBack();')   # (it picks up what changed elsewhere, like the colors)
        GLib.idle_add(self.push_tasks)

    def page_back(self, w, arg):
        """A page is done: back to where it was opened from (Home, or Settings). Setup closes when
        it's finished; the others stay open in the background."""
        if w is None:
            self.bring_home()
            return {'ok': True}
        target = self.pages.get(w.back)
        if target is not None:
            self.show_page(target)
        else:
            self.bring_home()
        if isinstance(arg, dict) and arg.get('close'):
            GLib.idle_add(lambda: (self.close_page(w.page), False)[1])
        return {'ok': True}

    def close_page(self, page):
        w = self.pages.pop(page, None)
        if w is None:
            return False
        if self.opening_page == page:
            self.opening_page = None
        if self.front == w.app_id:
            self.bring_home()
        w.shutdown()
        GLib.timeout_add(500, lambda: (gc.collect(), False)[1])
        GLib.idle_add(self.push_tasks)
        return True

    def on_page_closed(self, w):
        if self.pages.get(w.page) is w:
            self.close_page(w.page)
        else:
            w.shutdown()
        return True

    # ---------- outside apps: Steam, games, Discord, Firefox, Flathub apps, Windows programs ----------
    # Any number run at once, each on its own screen. Super or the Xbox button comes back Home from
    # inside one; Home lists them all and switches to any of them instantly.

    def open_ext(self, arg):
        arg = arg if isinstance(arg, dict) else {}
        kind = str(arg.get('id', ''))
        path = arg.get('path')
        url = str(arg.get('url') or '')
        key = ext_key(kind, path)
        e = self.exts.get(key)
        if e is not None and e.alive():
            if url:
                e.reopen([url])   # (Firefox: opens it in a new tab)
            self.resume_ext(key, quiet=bool(url))
            return {'ok': True, 'resumed': True}
        if e is not None:
            self.drop_ext(key)
        cmd = ext_command(kind, path)
        if not cmd:
            return {'ok': False, 'error': 'not_installed'}
        name, argv, cwd, title = cmd
        argv, env = game_env(kind, argv)
        if kind == 'browser':
            env = dict(env or os.environ, MOZ_ENABLE_WAYLAND='1')
        try:
            e = ExtApp(key, kind, name, argv, cwd, title, env, [url] if url else None)
        except OSError as err:
            return {'ok': False, 'error': str(err)}
        self.stop_waiting()
        # its first window brings it in front, if you're still where you opened it from (Home, Files, the Store)
        e.waiting, e.opened_from = time.monotonic(), self.front
        self.exts[key] = e
        if is_game(kind) and env is not None and gaming_get()['perf']:   # Pro: gaming mode while games run
            helper_request({'action': 'game', 'op': 'on', 'pid': e.proc.pid})
            self.game_keys.add(key)
        GLib.idle_add(self.push_tasks)
        return {'ok': True, 'resumed': False}

    def drop_ext(self, key, end=False):
        """An outside app ended (or End task): forget it; gaming mode ends with the last game."""
        e = self.exts.pop(key, None)
        if e is None:
            return
        if end:
            e.end()
        was_game = key in self.game_keys
        self.game_keys.discard(key)
        if was_game and not self.game_keys:
            helper_request({'action': 'game', 'op': 'off'})
        if self.front == key:
            self.bring_home()
        GLib.idle_add(self.push_tasks)

    def owner_of(self, pid, app):
        """Which running outside app a window belongs to: the process that made it was started by
        that app (or is in its sandbox); else by its name; else the app being opened, or the one
        on screen (a file chooser an app opened, for example)."""
        if not self.exts:
            return None
        by_pid = {e.proc.pid: k for k, e in self.exts.items()}
        by_sid = {e.pgid: k for k, e in self.exts.items()}
        p, hops = pid, 0
        while isinstance(p, int) and p > 1 and hops < 64:
            if p in by_pid:
                return by_pid[p]
            st = proc_stat(p)
            if not st:
                break
            if st[1] in by_sid:
                return by_sid[st[1]]
            p, hops = st[0], hops + 1
        fp = flatpak_of(pid) if pid else ''
        if fp:
            for k, e in self.exts.items():
                if e.flatpak == fp:
                    return k
        for k, e in self.exts.items():
            if e.matches(app):
                return k
        now = time.monotonic()
        starting = [e for e in self.exts.values() if e.waiting and now - e.waiting < 600]
        if starting:
            return max(starting, key=lambda e: e.waiting).key
        if self.front in self.exts:
            return self.front
        return max(self.exts.values(), key=lambda e: e.last_used).key

    def sort_strays(self):
        """Windows that aren't ours land on "app" (sway.conf), out of sight: each goes to its app's
        screen. Returns the apps that got a window."""
        self.sort_timer = 0
        wins, shown = sway_ws_windows()
        got = set()
        for ws in (WS_APP, WS_HOME):
            for cid, app, focused, pid in (wins or {}).get(ws, []):
                if app == 'os.launch.home' or not isinstance(cid, int):
                    continue
                key = self.owner_of(pid, app)
                if key is None:
                    if ws == WS_HOME:   # (never on Home's screen)
                        sway_cmd(f'[con_id={cid}] move container to workspace {WS_APP}')
                    continue
                sway_cmd(f'[con_id={cid}] move container to workspace {ws_ext(key)}')
                got.add(key)
        return got

    def on_new_window(self, change='new'):
        """A window that isn't ours appeared, or any window closed. A new window goes to its app's
        screen; the first window of an app you just opened brings it in front. When the screen in
        front loses its last window (the app closed it, or went to the tray), Home comes back right
        away. Signed out, the sign-in screen always stays in front."""
        if change == 'close':
            GLib.timeout_add(30, self.after_close)
            return False
        if not self.signed_in:
            self.guard_soon()
            return False
        if change != 'new' or getattr(self, 'sort_timer', 0):
            return False
        self.sort_timer = GLib.timeout_add(60, self.sort_and_show)
        return False

    def sort_and_show(self):
        got = self.sort_strays()
        now = time.monotonic()
        for key in got:
            e = self.exts.get(key)
            if e is not None and e.waiting and now - e.waiting < 600 and self.front in ('home', e.opened_from):
                self.resume_ext(key)
                break
        return False

    def after_close(self):
        wins, shown = sway_ws_windows()
        if wins is None or not self.signed_in:
            return False
        if shown and shown != WS_HOME and not wins.get(shown):
            self.bring_home()   # the app on screen closed its last window
        return False

    def resume_ext(self, key, quiet=False):
        e = self.exts.get(key)
        if not self.signed_in or e is None:
            return
        e.last_used = time.monotonic()
        self.sort_strays()
        wins, shown = sway_ws_windows()
        if wins is not None and not wins.get(ws_ext(key)):
            # no window (yet): it's still starting, or it went to the tray. Home stays until one shows.
            if time.monotonic() - e.started > 20 and not quiet:
                e.reopen()   # (starting it again makes the running copy show its window)
            self.stop_waiting()
            e.waiting, e.opened_from = time.monotonic(), self.front
            self.js(f'window.LOS && LOS.toast({json.dumps("Opening " + e.name + "…")}, 3000);')
            return
        self.stop_waiting()
        self.front = key
        sway_ws(ws_ext(key))
        GLib.idle_add(self.push_tasks)

    def bring_home(self):
        self.quiet_super = time.monotonic() + 0.8
        self.stop_waiting()   # you came back on purpose: an app still starting doesn't jump in front
        self.front = 'home'
        sway_ws(WS_HOME)
        if not self.win.get_visible():
            self.win.set_visible(True)
            self.win.fullscreen()
        self.win.present()
        self.view.grab_focus()
        self.js('window.__losBack && window.__losBack();')   # (it picks up what changed in Settings or Setup)
        GLib.idle_add(self.push_tasks)
        return False

    def ours_active(self):
        return (self.win.is_active() or any(w.is_active() for w in self.apps.values())
                or any(w.is_active() for w in self.pages.values()))

    def on_global_home(self):
        """Super key or Xbox button, seen on the raw input devices. Only acts when an
        outside app is in front: our own windows handle these keys themselves."""
        for w in list(self.apps.values()):   # the terminal has no page of its own to catch the Xbox button
            if isinstance(w, TermWin) and w.is_active():
                self.quiet_super = time.monotonic() + 0.8
                w.go_home()
                return False
        if self.front not in self.exts and not self.exts:
            return False
        if self.ours_active():
            return False   # (our own windows handle the key themselves)
        self.bring_home()
        return False

    def check_ext(self):
        for key, e in list(self.exts.items()):
            if e.alive():
                continue
            name, quick = e.name, time.monotonic() - e.started < 30
            self.drop_ext(key)
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
