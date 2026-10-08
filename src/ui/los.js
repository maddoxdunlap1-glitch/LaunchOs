/* LaunchOS shared script: system bridge, saved preferences, keyboard/controller
   navigation, screen fitting, toasts and icons. Used by index.html and setup.html. */
(function () {
  const $ = (s, el) => (el || document).querySelector(s);

  /* ---------- bridge to the system (launch.py) ---------- */
  const native = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.launchos);
  let seq = 0;
  const PAGE = Math.random().toString(36).slice(2, 10);
  const pending = {};
  window.__losReply = (id, data) => { const p = pending[id]; if (p) { delete pending[id]; p(data); } };

  // Stand-ins used when the page is opened outside LaunchOS (for previews and tests).
  let mockVol = 70, mockZone = 'UTC';
  const mockApps = {};
  /* A small pretend file system for Files previews and tests. */
  const mockFs = (() => {
    const H = '/home/player', U = '/media/player/USB_STICK';
    const F = new Map(), now = Math.floor(Date.now() / 1000);
    const add = (p, size) => F.set(p, { dir: size == null, size: size || 0, mtime: now - F.size * 3600 });
    ['Downloads', 'Documents', 'Pictures', 'Videos', 'Music'].forEach(d => add(H + '/' + d));
    add(H + '/Downloads/setup.exe', 2400000); add(H + '/Downloads/photo.jpg', 820000); add(H + '/Downloads/notes.txt', 1200);
    add(H + '/Downloads/Game mods'); add(H + '/Downloads/Game mods/mod1.zip', 5e6); add(H + '/Downloads/clip.mp4', 48e6);
    for (let i = 1; i <= 40; i++) add(H + '/Pictures/Screenshot ' + String(i).padStart(2, '0') + '.png', 300000 + i * 1000);
    add(U); add(U + '/Backup'); add(U + '/song.mp3', 4.2e6); add(U + '/manual.pdf', 900000);
    const dirname = p => p.slice(0, p.lastIndexOf('/')) || '/', base = p => p.slice(p.lastIndexOf('/') + 1);
    const kind = n => { const e = n.toLowerCase().split('.').pop(); return ({ png: 'image', jpg: 'image', mp4: 'video', mp3: 'audio', exe: 'program', zip: 'archive', txt: 'text', pdf: 'doc' })[e] || 'other'; };
    const drives = [
      { id: '/dev/sdb1', dev: '/dev/sdb1', disk: '/dev/sdb', name: 'USB STICK', model: 'SanDisk Cruzer', fs: 'exFAT', size: 32e9, disk_size: 32e9, mount: U, free: 21e9, total: 32e9, removable: true, usb: true },
      { id: '/dev/sda3', dev: '/dev/sda3', disk: '/dev/sda', name: 'Windows', model: 'Samsung SSD 980', fs: 'NTFS', size: 480e9, disk_size: 500e9, mount: '', removable: false, usb: false },
      { id: '/dev/sdc', dev: '', disk: '/dev/sdc', name: 'VBOX HARDDISK', model: 'VBOX HARDDISK', fs: '', size: 64e9, disk_size: 64e9, mount: '', removable: false, usb: false, empty: true },
    ];
    const m = {
      job: null,
      places: () => ({ places: ['Downloads', 'Documents', 'Pictures', 'Videos', 'Music'].map(n => ({ id: n.toLowerCase(), name: n, path: H + '/' + n })), drives: drives.filter(d => !d.gone), home_free: 9e9, home_total: 12e9, job: m.job || {}, saving: true }),
      list: p => {
        if (!F.has(p) || !F.get(p).dir) return { error: 'That folder isn’t there any more.' };
        const entries = [...F.entries()].filter(([k]) => dirname(k) === p).map(([k, v]) => ({ name: base(k), dir: v.dir, size: v.dir ? null : v.size, mtime: v.mtime, kind: v.dir ? 'folder' : kind(k) }))
          .sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) : a.dir ? -1 : 1));
        return { path: p, entries, free: p.startsWith(U) ? 21e9 : 9e9, total: 32e9, writable: true, readonly: false, fat: p.startsWith(U), place: p.startsWith(U) ? 'USB STICK' : p.split('/')[3] };
      },
      uniq: (dir, name) => { let n = name, i = 1; const dot = name.lastIndexOf('.'); while (F.has(dir + '/' + n)) { i++; n = dot > 0 ? name.slice(0, dot) + ' (' + i + ')' + name.slice(dot) : name + ' (' + i + ')'; } return n; },
      mkdir: a => { const n = m.uniq(a.path, (a.name || 'New folder').trim()); if (n.startsWith('.')) return { ok: false, error: 'Names can’t start with a dot. That would hide it.' }; add(a.path + '/' + n); return { ok: true, name: n }; },
      rename: a => {
        const n = String(a.name || '').trim(), d = dirname(a.path);
        if (!n) return { ok: false, error: 'Type a name first.' };
        if (n.includes('/')) return { ok: false, error: 'Names can’t contain a slash (/).' };
        if (F.has(d + '/' + n)) return { ok: false, error: 'There’s already something called ' + n + ' here.' };
        for (const [k, v] of [...F.entries()]) if (k === a.path || k.startsWith(a.path + '/')) { F.delete(k); F.set(d + '/' + n + k.slice(a.path.length), v); }
        return { ok: true, name: n };
      },
      start: (op, a) => {
        if (m.job && !m.job.done) return { ok: false, error: 'Wait for the ' + m.job.op + ' that’s running to finish.' };
        const j = m.job = { op, step: op === 'delete' ? 'Deleting' : (op === 'copy' ? 'Copying' : 'Moving') + ' to ' + (a.dest || '').split('/').pop(), bytes: 0, total_bytes: 50e6, files: 0, total_files: a.paths.length, current: base(a.paths[0]), done: false, error: '', result: '', speed: 25e6, stopped: false };
        let t = 0;
        const step = () => {
          if (j.cancel) { j.done = true; j.stopped = true; j.result = 'Stopped.'; return; }
          t++; j.bytes = Math.min(j.total_bytes, t * 5e6); j.files = Math.floor(j.total_files * t / 10);
          if (t < 10) { setTimeout(step, 100); return; }
          for (const p of a.paths) {
            const items = [...F.entries()].filter(([k]) => k === p || k.startsWith(p + '/'));
            if (op !== 'delete') { const n = m.uniq(a.dest, base(p)); items.forEach(([k, v]) => F.set(a.dest + '/' + n + k.slice(p.length), Object.assign({}, v))); }
            if (op !== 'copy') items.forEach(([k]) => F.delete(k));
          }
          j.done = true; j.files = j.total_files;
          j.result = (op === 'delete' ? 'Deleted ' : op === 'copy' ? 'Copied ' : 'Moved ') + (a.paths.length === 1 ? base(a.paths[0]) : a.paths.length + ' items') + (op === 'delete' ? '.' : ' to ' + a.dest.split('/').pop() + '.');
        };
        setTimeout(step, 100);
        return { ok: true };
      },
      mount: dev => { const d = drives.find(x => x.dev === dev); if (!d) return { ok: false, error: 'That drive isn’t there any more.' }; d.mount = '/media/player/' + d.name; d.free = 120e9; d.total = d.size; add(d.mount); add(d.mount + '/Users'); return { ok: true, mount: d.mount }; },
      eject: disk => { drives.filter(x => x.disk === disk).forEach(d => { if (d.removable) d.gone = true; else d.mount = ''; }); return { ok: true, step: 'Safe to unplug' }; },
      format: a => { const d = drives.find(x => x.disk === a.disk); if (!d || a.confirm !== 'FORMAT ' + a.disk) return { ok: false, error: 'no' };
        Object.assign(d, { empty: false, dev: a.disk + '1', id: a.disk + '1', fs: { exfat: 'exFAT', fat32: 'FAT32', ntfs: 'NTFS', ext4: 'ext4' }[a.fs], name: a.label || 'DRIVE', mount: '/media/player/' + (a.label || 'DRIVE'), free: d.size, total: d.size });
        add(d.mount); return { ok: true }; },
    };
    return m;
  })();
  /* A pretend Store for previews and tests. */
  const mockStore = (() => {
    const names = ['Heroic Games Launcher', 'Prism Launcher', 'Lutris', 'Discord', 'Spotify', 'VLC', 'OBS Studio', 'RetroArch', 'Dolphin', 'Firefox', 'GIMP', 'Blender'];
    const ids = ['com.heroicgameslauncher.hgl', 'org.prismlauncher.PrismLauncher', 'net.lutris.Lutris', 'com.discordapp.Discord', 'com.spotify.Client', 'org.videolan.VLC', 'com.obsproject.Studio', 'org.libretro.RetroArch', 'org.DolphinEmu.dolphin-emu', 'org.mozilla.firefox', 'org.gimp.GIMP', 'org.blender.Blender'];
    const shelves = [['games'], ['games'], ['games'], ['internet'], ['media'], ['media'], ['media'], ['games'], ['games'], ['internet'], ['creative'], ['creative']];
    const apps = ids.map((id, i) => ({ id, name: names[i], summary: 'A pretend summary for ' + names[i] + ' that is a bit long so it wraps.', desc: 'Pretend description. '.repeat(12), dev: 'Someone', icon: '', shelves: shelves[i], shots: [] }));
    for (let i = 0; i < 230; i++) apps.push({ id: 'org.example.Game' + i, name: 'Example game ' + i, summary: 'Filler game', desc: '', dev: '', icon: '', shelves: ['games'], shots: [] });
    const m = {
      installed: { 'org.videolan.VLC': { name: 'VLC', version: '3.0.21' } }, job: {}, upd: {}, admin: '',
      info: () => ({ apps: m.empty ? [] : apps, installed: m.installed, job: m.job, free: 20e9, catalog_age_h: 2 }),
      home: () => Object.keys(m.installed).filter(id => !MOCK_APPS.some(a => a[3] === id)).map(id => ({ id, name: m.installed[id].name, icon: '' })),   // (Setup's apps have their own tiles)
      act: a => {
        if (m.job.step && !m.job.done) return { ok: false, error: 'Wait for the app to finish first.' };
        const list = a.apps || [a.app];
        const j = m.job = { op: a.op, app: list.join(','), name: a.name || a.app, step: a.op === 'remove' ? 'Removing ' + a.name : 'Downloading ' + a.name, percent: 0, done: false, error: '' };
        let t = 0;
        const step = () => { t++; j.percent = Math.min(100, t * 25); if (t < 4) { setTimeout(step, 250); return; }
          j.done = true; j.step = a.op === 'remove' ? 'Removed' : 'Installed';
          if (a.op === 'install') list.forEach(id => { m.installed[id] = { name: a.name, version: '1.0' }; }); else if (a.op === 'remove') delete m.installed[a.app]; else m.empty = false; };
        setTimeout(step, 250);
        return { ok: true };
      },
    };
    return m;
  })();
  const MOCK_APPS = [['steam', 'Steam', 'PC games'], ['discord', 'Discord', 'Chat', 'com.discordapp.Discord'], ['spotify', 'Spotify', 'Music', 'com.spotify.Client'],
    ['freetube', 'FreeTube', 'YouTube without ads', 'io.freetubeapp.FreeTube'], ['roblox', 'Roblox', 'Through Sober', 'org.vinegarhq.Sober'],
    ['minecraft', 'Minecraft', 'Prism Launcher', 'org.prismlauncher.PrismLauncher'], ['heroic', 'Heroic', 'Epic and GOG', 'com.heroicgameslauncher.hgl'],
    ['obs', 'OBS Studio', 'Record', 'com.obsproject.Studio'], ['vlc', 'VLC', 'Video', 'org.videolan.VLC'], ['winprog', 'Windows programs', 'Wine']];
  // (preview: signed in unless the page is the sign-in screen or ?signedout is in the address)
  const mockSession = { signed: !/login\.html$/.test(location.pathname) && !/signedout/.test(location.search), ask: true };
  try { const v = sessionStorage.getItem('launchos.mock'); if (v) { const o = JSON.parse(v); mockStore.admin = o.admin || ''; mockSession.ask = o.ask !== false; if (o.signed) mockSession.signed = true; } } catch (e) { /* no storage */ }
  addEventListener('pagehide', () => { try { sessionStorage.setItem('launchos.mock', JSON.stringify({ admin: mockStore.admin, ask: mockSession.ask, signed: mockSession.signed })); } catch (e) { /* no storage */ } });
  const MOCK = {
    info: () => ({ version: '0.5', build: '2026-10-05', kernel: 'preview', cpu: 'Preview CPU', cores: 2, mem_total_mb: 2048, mem_free_mb: 1200, uptime_min: 3, resolution: screen.width + ' x ' + screen.height }),
    network: () => ({ connected: true, gateway: '10.0.2.2', dns: ['10.0.2.3'], links: [{ name: 'enp0s3', up: true, mac: '08:00:27:00:00:01', ipv4: ['10.0.2.15'] }] }),
    internet_test: () => ({ online: true }),
    inputs: () => ([{ name: 'AT Translated Set 2 keyboard', kind: 'keyboard', usb: false }, { name: 'VirtualBox USB Tablet', kind: 'mouse', usb: true }]),
    volume_get: () => ({ available: true, value: mockVol, muted: false }),
    volume_set: v => { mockVol = Math.max(0, Math.min(100, v)); return { available: true, value: mockVol, muted: mockVol === 0 }; },
    sound_test: () => ({ ok: true }),
    timezones: () => ['America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/New_York', 'America/Phoenix', 'Europe/Berlin', 'Europe/London', 'Asia/Tokyo', 'Australia/Sydney'],
    timezone_get: () => ({ zone: mockZone }),
    timezone_set: z => { mockZone = z; return { ok: true }; },
    power: () => ({ ok: false }),
    stats: () => {
      const t = Date.now() / 1000, w = (a, b) => a + b * (0.5 + 0.5 * Math.sin(t / 3 + a));
      return { cpu: Math.round(w(12, 30)), cores: [w(10, 40), w(14, 25)].map(Math.round), ncores: 2, mem_total: 2147483648, mem_used: 2147483648 * (0.45 + 0.05 * Math.sin(t / 7)),
        net_down: 120000 + 900000 * Math.max(0, Math.sin(t / 4)), net_up: 20000 + 60000 * Math.max(0, Math.cos(t / 5)), disk_total: 1073741824, disk_used: 336000000,
        procs: [{ pid: 1, name: 'Web page (browser engine)', cpu: 14.2, mem: 210e6 }, { pid: 2, name: 'Display server', cpu: 6.1, mem: 48e6 }, { pid: 3, name: 'LaunchOS home and browser', cpu: 3.4, mem: 96e6 }, { pid: 4, name: 'Network', cpu: 0.2, mem: 8e6 }],
        nprocs: 71, load: ['0.42', '0.30', '0.18'], uptime_s: 754, temps: [] };
    },
    open_browser: url => { window.open(url && url.startsWith('http') ? url : 'start.html', '_blank'); return { ok: true }; },
    open_app: a => { const was = !!mockApps[a.id]; mockApps[a.id] = mockApps[a.id] || { id: a.id, name: a.name, t0: Date.now(), title: a.name, uri: a.url || 'start.html', shown: false }; return { ok: true, resumed: was }; },
    end_app: id => { const ok = !!mockApps[id]; delete mockApps[id]; return { ok }; },
    apps_info: () => {
      const apps = MOCK_APPS.map(([key, name, what, flatpak]) => ({ key, name, what, flatpak, icon: '', installed: key === 'steam' || key === 'winprog' || !!(flatpak && mockStore.installed[flatpak]) }));
      const by = k => apps.find(a => a.key === k);
      return { apps, job: mockStore.job, gpu: 'software', steam: { installed: true }, wine: { installed: true }, roblox: { installed: by('roblox').installed }, freetube: { installed: by('freetube').installed } };
    },
    get_app: keys => {
      const ids = (Array.isArray(keys) ? keys : [keys]).map(k => (MOCK_APPS.find(a => a[0] === k) || [])[3]).filter(id => id && !mockStore.installed[id]);
      if (!ids.length) return { ok: true, nothing: true };
      return mockStore.act({ op: 'install', apps: ids, name: ids.length + ' apps' });
    },
    session_state: () => ({ signed_in: mockSession.signed, password: !!mockStore.admin && mockSession.ask, password_set: !!mockStore.admin, ask: mockSession.ask, wait_s: 0, running: Object.keys(mockApps).length }),
    sign_in: a => { if (mockStore.admin && mockSession.ask && (a || {}).password !== mockStore.admin) return { ok: false, error: 'That password isn’t right.' }; mockSession.signed = true; return { ok: true }; },
    lock: () => { mockSession.signed = false; setTimeout(() => { location.href = 'login.html'; }, 10); return { ok: true }; },
    sign_out: () => { mockSession.signed = false; Object.keys(mockApps).forEach(k => delete mockApps[k]); setTimeout(() => { location.href = 'login.html'; }, 10); return { ok: true }; },
    signin_ask: on => { mockSession.ask = !!on; return { ok: true, ask: !!on }; },
    storage: () => ({ installed: false, saving: false, total: 2e9, free: 1.5e9, boot: 'usb', can_usb_saving: true, job: {} }),
    job_status: () => ({ step: 'Done', percent: 100, done: true, error: '' }),
    usb_saving: () => ({ ok: true }), mount_drives: () => ({ ok: true }), install_system: () => ({ ok: true }),
    win_programs: () => [{ name: 'setup', path: '/home/player/Downloads/setup.exe', where: 'Downloads', size: 2400000, mtime: 1 }],
    install_disks: () => [{ path: '/dev/sdb', size: 64e9, model: 'Samsung SSD', usb: false, parts: 2 }],
    wifi_status: () => ({ available: true, state: 'disconnected', scanning: false, networks: [{ name: 'Home WiFi', type: 'psk', connected: false, known: false, bars: 4 }, { name: 'Cafe', type: 'open', connected: false, known: false, bars: 2 }] }),
    wifi_scan: () => ({ ok: true }), wifi_forget: () => ({ ok: true }), wifi_disconnect: () => ({ ok: true }),
    wifi_connect: a => (a.passphrase === 'correcthorse' || a.name === 'Cafe' ? { ok: true } : { ok: false, need_password: true, error: a.passphrase ? 'Couldn’t connect. Check the password and try again.' : '' }),
    open_ext: a => ({ ok: true, resumed: false }),
    discord_panel: a => ({ ok: true, open: !!(a && a.open) }),
    fs_places: () => mockFs.places(), fs_list: p => mockFs.list(p), fs_mkdir: a => mockFs.mkdir(a), fs_rename: a => mockFs.rename(a),
    fs_copy: a => mockFs.start('copy', a), fs_move: a => mockFs.start('move', a), fs_delete: a => mockFs.start('delete', a),
    fs_job: () => mockFs.job || {}, fs_cancel: () => { if (mockFs.job) mockFs.job.cancel = true; return { ok: true }; },
    fs_mount: d => mockFs.mount(d), fs_eject: d => mockFs.eject(d), fs_format: a => mockFs.format(a),
    store_info: () => mockStore.info(), store_home: () => mockStore.home(), store_job: () => mockStore.job,
    store_action: a => mockStore.act(a), open_terminal: () => { mockApps.terminal = { id: 'terminal', name: 'Terminal', t0: Date.now(), title: 'Terminal', uri: '', shown: false }; return { ok: true }; },
    update_info: () => ({ version: '0.8', build: '2026-10-08', check: mockStore.upd, system: {}, installed: false, saving: true }),
    update_action: w => { mockStore.upd = w === 'check' ? { step: 'LaunchOS 0.9 is available', percent: 100, done: true, available: true, latest: '0.9', notes: 'Pretend notes for 0.9.' } : { step: w === 'apply' ? 'Updated to LaunchOS 0.9. Restart to finish.' : 'Up to date', percent: 100, done: true, restart: w === 'apply' }; return { ok: true }; },
    admin_set: () => ({ set: !!mockStore.admin }), admin_password: a => { if (mockStore.admin && a.old !== mockStore.admin) return { done: true, error: 'The current password isn’t right.' }; mockStore.admin = a.new; return { done: true, step: 'Saved', error: '' }; },
    tasks: () => Object.values(mockApps).map(a => ({ id: a.id, name: a.name, running_s: Math.round((Date.now() - a.t0) / 1000), title: a.title, uri: a.uri, shown: false })),
  };

  /* Signed out (locked) while on a page other than the sign-in screen: go there. */
  const guard = r => { if (r && r.error === 'signed_out' && !/login\.html$/.test(location.pathname)) location.href = 'login.html'; return r; };
  function call(action, arg) {
    if (!native) {
      const fn = MOCK[action];
      const quiet = ['session_state', 'sign_in', 'power', 'info', 'network', 'log_error', 'inputs', 'timezone_get'];
      return new Promise(r => setTimeout(() => r(guard(!mockSession.signed && !quiet.includes(action) ? { error: 'signed_out' } : fn ? fn(arg) : { error: 'unknown' })), action === 'internet_test' ? 600 : 30));
    }
    return raw(action, arg).then(guard);
  }
  function raw(action, arg) {
    return new Promise(resolve => {
      const id = PAGE + '-' + (++seq);   // unique to this page, so a late reply can't answer another page's request
      pending[id] = resolve;
      const wait = { wifi_connect: 50000, fs_eject: 200000, fs_mount: 50000, fs_format: 20000, fs_list: 30000,   // drives can be slow
        store_info: 120000, store_home: 120000, store_action: 30000, update_action: 30000, admin_password: 30000,   // so is reading Flathub's list
        get_app: 30000, sign_in: 30000 }[action] || 15000;
      setTimeout(() => { if (pending[id]) { delete pending[id]; resolve({ error: 'timeout' }); } }, wait);
      window.webkit.messageHandlers.launchos.postMessage(JSON.stringify({ id, action, arg }));
    });
  }

  /* Script errors go to a log file (~/.cache/launchos/ui-errors.log), so problems can be found later. */
  let reported = 0;
  function report(msg, where) {
    if (!native || reported++ > 20) return;
    try { window.webkit.messageHandlers.launchos.postMessage(JSON.stringify({ id: 0, action: 'log_error', arg: { page: location.pathname.split('/').pop(), msg: String(msg).slice(0, 500), where: String(where || '').slice(0, 300) } })); } catch (e) { /* nothing more to do */ }
  }
  addEventListener('error', e => report(e.message, (e.filename || '').split('/').pop() + ':' + e.lineno));
  addEventListener('unhandledrejection', e => report(e.reason && (e.reason.stack || e.reason.message) || e.reason, 'promise'));

  /* ---------- saved preferences ---------- */
  const DEFAULTS = { name: 'Player 1', avatar: '#e0793a', accent: 'green', size: 'fill', pattern: true, timezone: '', setupDone: false, apps: [], order: [] };
  function load() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem('launchos.prefs') || '{}')); }
    catch (e) { return Object.assign({}, DEFAULTS); }
  }
  let prefs = load();
  function save(patch) {
    prefs = Object.assign(prefs, patch || {});
    try { localStorage.setItem('launchos.prefs', JSON.stringify(prefs)); } catch (e) { /* storage unavailable: keep in memory */ }
    applyLook();
    return prefs;
  }

  const ACCENTS = {
    green: ['#3ddc6b', '61, 220, 107', '#0b1726'],
    blue: ['#5fb8ff', '95, 184, 255', '#0b1726'],
    purple: ['#9d8cff', '157, 140, 255', '#0b1726'],
    orange: ['#ff9a4d', '255, 154, 77', '#0b1726'],
    pink: ['#ff6fae', '255, 111, 174', '#0b1726'],
  };
  // Screen size: how much of the screen the interface uses. "TV safe area" leaves
  // a border for TVs that crop the edges of the picture.
  const SIZES = { fill: 1, tv: 0.93, compact: 0.85 };
  const SIZE_NAMES = { fill: 'Fill screen', tv: 'TV safe area', compact: 'Compact' };

  function applyLook() {
    const a = ACCENTS[prefs.accent] || ACCENTS.green;
    const r = document.documentElement.style;
    r.setProperty('--accent', a[0]); r.setProperty('--accent-glow', a[1]); r.setProperty('--accent-ink', a[2]);
    document.body && document.body.classList.toggle('nopattern', !prefs.pattern);
    fit();
  }

  /* ---------- fit the 1280x720 stage to any screen ---------- */
  function fit() {
    const wr = $('#wrap');
    if (!wr) return;
    const s = Math.min(innerWidth / 1280, innerHeight / 720) * (SIZES[prefs.size] || 1);
    wr.style.transformOrigin = '50% 50%';
    wr.style.transform = `translate(-50%,-50%) scale(${s})`;
  }
  addEventListener('resize', fit);

  /* ---------- toast ---------- */
  let tm;
  function toast(s, ms) {
    const t = $('#toast'); if (!t) return;
    t.textContent = s; t.style.visibility = ''; t.classList.add('on'); clearTimeout(tm);
    // hidden for good once it has faded: software drawing can leave the last faint frame on screen
    tm = setTimeout(() => { t.classList.remove('on'); tm = setTimeout(() => { t.style.visibility = 'hidden'; }, 320); }, ms || 2400);
  }

  /* ---------- navigation input: keyboard + game controller ---------- */
  let handler = () => false;
  const hideCur = () => document.body.classList.add('nocur');
  // Hover only counts when the mouse really moved, so items sliding under a resting
  // cursor during keyboard or controller navigation don't steal the selection.
  let lastMove = 0, lastXY = '';
  addEventListener('mousemove', e => {
    const xy = e.clientX + ',' + e.clientY;
    if (xy === lastXY) return;
    lastXY = xy; lastMove = performance.now();
    document.body.classList.remove('nocur');
  }, { capture: true });   // capture: runs before any element's own mousemove handler
  const mouseRecent = () => performance.now() - lastMove < 300;
  addEventListener('keydown', e => {
    hideCur();
    const k = e.key, typing = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA');
    let a = null;
    if (k === 'ArrowLeft') a = 'left'; else if (k === 'ArrowRight') a = 'right';
    else if (k === 'ArrowUp') a = 'up'; else if (k === 'ArrowDown') a = 'down';
    else if (k === 'Enter') a = 'ok'; else if (k === 'Escape') a = 'back';
    else if (!typing && (k === ' ')) a = 'ok';
    else if (!typing && (k === 'Backspace' || k === 'b')) a = 'back';
    else if (!typing && (k === 'm' || k === 'Tab' || k === 'g')) a = 'menu';
    else if (k === 'Meta' || k === 'OS' || k === 'Super') a = 'guide';           // Super (Windows) key = Xbox button
    else if (k === 'ContextMenu' || (k === 'F10' && e.shiftKey)) a = 'opts';     // app options, like right-click
    if (typing && (a === 'left' || a === 'right')) return;   // let the cursor move inside text boxes
    if (a && dispatch(a, e) !== false) e.preventDefault();
  });
  /* "guide" (Super key or the Xbox button) goes Home from any page; Home itself uses it for the side menu. */
  let guideHere = false;
  function dispatch(a, e) {
    if (panelOpen) { if (a === 'guide' || a === 'back') call('discord_panel', { open: false }); return true; }
    if (a === 'guide' && !guideHere) { location.href = 'index.html'; return true; }
    return handler(a, e);
  }
  window.__losGuide = () => dispatch('guide', { key: 'Super' });   // the system sends the Super key here
  window.__losOpts = () => dispatch('opts', { key: 'ContextMenu' });   // and the Menu key / Shift+F10
  /* While the Discord panel is open beside Home, Home ignores the controller and a click on Home closes the panel. */
  let panelOpen = false;
  window.__losPanel = on => { panelOpen = !!on; document.body.classList.toggle('panelopen', panelOpen); };
  addEventListener('mousedown', e => { if (panelOpen) { e.preventDefault(); e.stopPropagation(); call('discord_panel', { open: false }); } }, true);
  const prev = {}, rep = {};
  // When this page comes back (from an app or a game), buttons already held down don't count as new presses.
  // (Only after being covered: on a fresh page the controller shows up with the very press that should count.)
  let rearm = false, away = false;
  addEventListener('blur', () => { away = true; });
  addEventListener('focus', () => { if (away) rearm = true; away = false; });
  document.addEventListener('visibilitychange', () => { if (document.hidden) away = true; else if (away) { rearm = true; away = false; } });
  function pad() {
    const gp = navigator.getGamepads ? [...navigator.getGamepads()].find(x => x) : null;
    if (gp) {
      const B = i => gp.buttons[i] && gp.buttons[i].pressed, ax = gp.mapping === 'standard' ? (gp.axes || []) : [];   // sticks only on known layouts
      const S = { up: B(12) || ax[1] < -.6, down: B(13) || ax[1] > .6, left: B(14) || ax[0] < -.6, right: B(15) || ax[0] > .6, ok: B(0), back: B(1), opts: B(2) || B(3), menu: B(9) || B(8), guide: B(16) };
      const now = performance.now();
      if (rearm) { for (const k in S) prev[k] = S[k]; rearm = false; }
      for (const k in S) {
        const dir = ['up', 'down', 'left', 'right'].includes(k);
        if (S[k] && (!prev[k] || (dir && now > rep[k]))) { hideCur(); rep[k] = now + (prev[k] ? 120 : 380); dispatch(k, null); }
        prev[k] = S[k];
      }
    }
    // every frame while a controller is present; otherwise a cheap check 10 times a second
    if (gp) requestAnimationFrame(pad); else setTimeout(pad, 100);
  }
  pad();
  addEventListener('gamepadconnected', () => toast('Controller connected'));

  /* ---------- icons (simple outline glyphs) ---------- */
  const P = {
    globe: 'M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
    wand: 'M5 19L15 9M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 11l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z',
    search: 'M11 4a7 7 0 100 14 7 7 0 000-14zM16 16l5 5',
    pad: 'M7 8h10a4 4 0 014 4v2a3 3 0 01-5 2l-1-1H9l-1 1a3 3 0 01-5-2v-2a4 4 0 014-4z',
    gear: 'M12 9a3 3 0 100 6 3 3 0 000-6zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1',
    home: 'M4 11l8-7 8 7M6 10v9h12v-9',
    chat: 'M4 5h16v11H10l-4 4v-4H4z',
    bell: 'M6 17V11a6 6 0 0112 0v6l2 2H4zM10 21h4',
    play: 'M8 5l11 7-11 7z',
    power: 'M12 3v8M7 6.5a7 7 0 1010 0',
    wifi: 'M3 9a14 14 0 0118 0M6 12.5a9 9 0 0112 0M9 16a4 4 0 016 0M12 19.5h.01',
    sound: 'M4 9h4l5-4v14l-5-4H4zM17 9a4 4 0 010 6M19.5 6.5a8 8 0 010 11',
    display: 'M3 5h18v11H3zM8 20h8M12 16v4',
    clock: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2',
    info: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v6M12 7.5h.01',
    keyboard: 'M3 7h18v10H3zM7 10h.01M10 10h.01M13 10h.01M16 10h.01M8 14h8',
    mouse: 'M12 3a5 5 0 015 5v8a5 5 0 01-10 0V8a5 5 0 015-5zM12 7v3',
    usb: 'M12 3v14M8 7l4-4 4 4M7 12v2l5 3 5-3v-3M12 21a1.5 1.5 0 100-3 1.5 1.5 0 000 3z',
    palette: 'M12 3a9 9 0 100 18c1 0 1.5-.8 1.5-1.6 0-1.3-1-1.4-1-2.4 0-.9.7-1.5 1.6-1.5H17a4 4 0 004-4c0-4.7-4-8.5-9-8.5zM7.5 11h.01M10 7h.01M15 7h.01',
    user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6',
    check: 'M5 12l5 5L20 7',
    refresh: 'M20 11a8 8 0 10-2.3 5.7M20 5v6h-6',
    grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
    chart: 'M4 19h16M6 15l4-5 3 3 5-7',
    close: 'M6 6l12 12M18 6L6 18',
    move: 'M5 12h14M8 9l-3 3 3 3M16 9l3 3-3 3',
    folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z',
    file: 'M6 3h8l4 4v14H6zM14 3v4h4',
    image: 'M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5M15.5 9.5h.01',
    film: 'M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M4 15h4M16 9h4M16 15h4',
    music: 'M9 18V6l11-2v12M9 18a3 3 0 11-6 0 3 3 0 016 0zM20 16a3 3 0 11-6 0 3 3 0 016 0z',
    archive: 'M4 4h16v4H4zM5 8v12h14V8M10 12h4',
    doc: 'M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6',
    text: 'M6 3h8l4 4v14H6zM14 3v4h4M9 11h6M9 14h6M9 17h4',
    drive: 'M3 13l3-8h12l3 8v5H3zM3 13h18M17 16h.01',
    eject: 'M6 14l6-8 6 8zM6 18h12',
    trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
    copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
    cut: 'M6 6a2 2 0 100 4 2 2 0 000-4zM6 14a2 2 0 100 4 2 2 0 000-4zM8 9l12 8M8 15l12-8',
    paste: 'M9 4h6v3H9zM7 5H5v16h14V5h-2M9 12h6M9 16h4',
    edit: 'M4 20h4L19 9l-4-4L4 16zM13 7l4 4',
    plus: 'M12 5v14M5 12h14',
    select: 'M4 4h16v16H4zM8 12l3 3 5-6',
    up: 'M12 19V5M6 11l6-6 6 6',
    download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
    bag: 'M5 8h14l-1 12H6zM9 8V6a3 3 0 016 0v2',
    terminal: 'M4 5h16v14H4zM7 9l3 3-3 3M12 15h5',
  };
  /* Full-color icons (Papirus icon theme, in icons/) for LaunchOS's own apps and settings,
     and the apps' own icons for Steam, Discord and everything from Flathub. */
  const fileUrl = p => 'file://' + String(p).split('/').map(encodeURIComponent).join('/');
  const pic = (n, cls) => `<img class="pic ${cls || ''}" src="icons/${n}.svg" alt="" draggable="false">`;
  const appPic = (path, fallback, cls) => path ? `<img class="pic ${cls || ''}" src="${esc(fileUrl(path))}" alt="" draggable="false">` : fallback ? pic(fallback, cls) : '';
  const icon = (n, cls) => `<svg class="ic ${cls || ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[n] || P.grid}"/></svg>`;

  /* ---------- clock in the chosen time zone ---------- */
  function clockText() {
    const opts = { hour: 'numeric', minute: '2-digit' };
    if (prefs.timezone) opts.timeZone = prefs.timezone;
    try { return new Intl.DateTimeFormat('en-US', opts).format(new Date()).toLowerCase().replace(' ', ' '); }
    catch (e) { delete opts.timeZone; return new Intl.DateTimeFormat('en-US', opts).format(new Date()).toLowerCase(); }
  }

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  window.LOS = {
    $, call, native, toast, icon, pic, appPic, fileUrl, esc, fit, clockText, mouseRecent,
    get prefs() { return prefs; }, save, ACCENTS, SIZE_NAMES,
    onNav(fn, opts) { handler = fn; guideHere = !!(opts && opts.guide); },   // opts.guide: the page handles the Super key itself
  };
  document.addEventListener('DOMContentLoaded', () => { hideCur(); applyLook(); });
})();
