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
  // (preview: LaunchOS Pro is on with ?pro in the address, on sale with ?onsale)
  const mockPro = { active: /[?&]pro\b/.test(location.search), onSale: /onsale|[?&]pro\b/.test(location.search), job: {}, gaming: { perf: true, fps: 'off' } };
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
    job_status: n => n === 'pro' ? mockPro.job : { step: 'Done', percent: 100, done: true, error: '' },
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
    pro_state: () => ({ active: mockPro.active, status: mockPro.active ? 'active' : '', key_hint: mockPro.active ? '38b1…4d51' : '', since: mockPro.active ? '2026-10-08' : '',
      version: mockPro.active ? '1.0' : '', on_sale: mockPro.onSale, buy: mockPro.onSale ? 'https://launchos.example/pro' : '', job: mockPro.job, fps_ok: true }),
    pro_action: a => {
      if (a.op === 'activate' && !/^[A-Za-z0-9-]{8,64}$/.test(a.key || '')) return { ok: false, error: 'That doesn’t look like a Pro key. It’s in the email from your purchase.' };
      const good = a.op !== 'activate' || a.key === 'TEST-KEY-1234';
      mockPro.job = { step: 'Checking your key', percent: 30, done: false, error: '' };
      setTimeout(() => { mockPro.job = good ? { step: a.op === 'remove' ? 'Removed LaunchOS Pro from this PC' : 'LaunchOS Pro is on', percent: 100, done: true, error: '' } : { step: '', percent: 100, done: true, error: 'That key isn’t right. Check it against the email from your purchase.' };
        if (good) mockPro.active = a.op !== 'remove'; }, 900);
      return { ok: true };
    },
    pro_qr: () => ({ svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 29 29"><path d="M2 2h7v7H2zM20 2h7v7h-7zM2 20h7v7H2zM12 12h5v5h-5z"/></svg>', url: 'https://launchos.example/pro' }),
    gaming_get: () => Object.assign({}, mockPro.gaming), gaming_set: a => Object.assign(mockPro.gaming, a || {}),
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
  const DEFAULTS = { name: 'Player 1', avatar: '#e0793a', accent: 'green', size: 'fill', pattern: true, timezone: '', setupDone: false, apps: [], order: [],
    wall: '', theme: 'midnight', proOn: false };
  function load() {
    let p;
    try { p = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem('launchos.prefs') || '{}')); }
    catch (e) { p = Object.assign({}, DEFAULTS); }
    if (!p.wall) p.wall = p.pattern === false ? 'plain' : 'liftoff';   // (before 1.0 there was only the line pattern, on or off)
    return p;
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

  /* Backgrounds: pictures for everyone, live (moving) ones with LaunchOS Pro. */
  const WALLS = [['liftoff', 'Liftoff'], ['nebula', 'Nebula'], ['aurora', 'Aurora'], ['orbit', 'Orbit'], ['dunes', 'Dunes'], ['waves', 'Waves'],
    ['grid', 'Retro'], ['contour', 'Contour lines'], ['plain', 'Plain']].map(([id, name]) => ({ id, name }));
  const LIVE = [['warp', 'Warp speed', 'nebula'], ['drift', 'Nebula drift', 'nebula'], ['sky', 'Living aurora', 'aurora'], ['launch', 'Launch day', 'liftoff']]
    .map(([id, name, still]) => ({ id: 'live:' + id, live: id, name, still, pro: true }));
  /* Color themes: Midnight for everyone, the rest with LaunchOS Pro. */
  const THEMES = {
    midnight: ['Midnight', '#0b1726 #0f1b2a #122235 #1a2b40 #22344a #1d3550 #11233a #16273b #1f3550 #2a4260'],
    carbon: ['Carbon', '#0d0e10 #141518 #1a1c20 #23262b #2c3036 #25282e #17191c #1c1e22 #262a30 #353a42'],
    ocean: ['Deep sea', '#05181c #0a2025 #0d2a30 #13363d #1b444c #134049 #0b2a30 #10313a #164049 #22535c'],
    royal: ['Royal', '#110b22 #170f2c #1d1637 #261d46 #312857 #2c2152 #1a1335 #21183f #2b2150 #3b3170'],
    ember: ['Ember', '#170d0b #1f1210 #281814 #33201a #422a22 #3a241c #241612 #2c1b16 #3a2219 #52352a'],
    oled: ['Pure black', '#000000 #0a0a0b #111214 #1a1b1e #26282c #1b1c20 #0f1012 #141518 #1d1f23 #303238'],
  };
  const THEME_VARS = ['--bg', '--panel', '--panel-2', '--chip', '--line', '--tile1', '--tile2', '--tb', '--glyph', '--line2'];
  const proOK = () => !!prefs.proOn;
  let liveStop = null, liveId = '';
  function applyWall() {
    const st = $('#stage'); if (!st || !document.body) return;
    let w = $('#wall');
    if (!w) { w = document.createElement('div'); w.id = 'wall'; w.setAttribute('aria-hidden', 'true'); st.prepend(w); }
    let id = prefs.wall;
    const live = LIVE.find(x => x.id === id);
    if (live && !proOK()) id = live.still;
    if (!live && !WALLS.some(x => x.id === id)) id = 'liftoff';
    const still = live && proOK() ? live.still : id;
    document.body.classList.toggle('wall-contour', still === 'contour');
    document.body.classList.toggle('wall-plain', still === 'plain' || still === 'contour');
    w.style.backgroundImage = still === 'contour' || still === 'plain' ? 'none' : `url("walls/${still}.webp")`;
    // a live background draws on a canvas over its still picture (which shows if it can't run).
    // Only on pages that ask for it (Home, sign-in, Setup): behind Files, the Store or a video it
    // would only cost processor time. Never when reduced motion is asked for.
    const moving = document.body.hasAttribute('data-live') &&
      !(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
    const want = live && proOK() && moving ? live.live : '';
    if (want === liveId) return;
    if (liveStop) { try { liveStop(); } catch (e) { /* already gone */ } liveStop = null; }
    w.querySelectorAll('canvas').forEach(c => c.remove());
    liveId = want;
    if (!want) return;
    const start = () => {
      const fn = window.LOSLive && window.LOSLive[want];
      if (!fn || liveId !== want) return;
      const c = document.createElement('canvas'); w.append(c);
      try { liveStop = fn(c, { hardware: !!window.__losHW }); } catch (e) { c.remove(); report(e.message, 'live ' + want); }
    };
    if (window.LOSLive && window.LOSLive[want]) { start(); return; }
    // the live backgrounds come with LaunchOS Pro: shared helpers first, then the one wanted
    const base = native ? 'file:///opt/launchos-pro/live/' : '../pro/live/';
    const files = ['common'].concat(want === 'sky' ? ['aurora-src'] : [], [want]);
    const next = () => {
      const f = files.shift();
      if (!f) { start(); return; }
      if (document.querySelector(`script[data-live="${f}"]`)) { next(); return; }
      const sc = document.createElement('script');
      sc.src = base + f + '.js'; sc.dataset.live = f;
      sc.onload = next;
      document.head.append(sc);
    };
    next();
  }
  function applyLook() {
    const a = ACCENTS[prefs.accent] || ACCENTS.green;
    const r = document.documentElement.style;
    r.setProperty('--accent', a[0]); r.setProperty('--accent-glow', a[1]); r.setProperty('--accent-ink', a[2]);
    const th = (prefs.theme !== 'midnight' && proOK() && THEMES[prefs.theme]) || THEMES.midnight;
    th[1].split(' ').forEach((c, i) => r.setProperty(THEME_VARS[i], c));
    document.body && document.body.classList.toggle('nopattern', !prefs.pattern);
    applyWall();
    fit();
  }
  /* Whether LaunchOS Pro is on (remembered, so the look is right from the first frame). */
  function checkPro() {
    // (pages redraw what depends on Pro, like the badge, when it changes: the 'los:pro' event)
    const changed = on => { save({ proOn: on }); document.dispatchEvent(new CustomEvent('los:pro', { detail: on })); };
    if (!native) { if (!!prefs.proOn !== mockPro.active) changed(mockPro.active); return Promise.resolve(); }
    return raw('pro_state').then(s => {
      if (!s || s.error) return;
      const on = !!s.active;
      if (on !== !!prefs.proOn) changed(on);
    });
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

  /* ---------- on-screen keyboard: type with a controller ----------
     Opens when A is pressed on a text box with a controller (keyboard and mouse users never see
     it). D-pad moves, A types, X deletes, Y adds a space, B or Hide closes, Menu or Done is Enter. */
  const textBox = el => !!el && el.tagName === 'INPUT' && /^(text|password|search|url|email|)$/.test(el.type || 'text') && !el.disabled && !el.readOnly;
  const OSK_ROWS = {
    abc: [['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'bksp'], ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '-'],
      ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', '@', '.'], ['shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '_', '/', 'done'],
      ['sym', 'left', 'space', 'right', 'hide']],
    sym: [['!', '"', '#', '$', '%', '&', "'", '(', ')', '*', 'bksp'], ['+', ',', ';', ':', '<', '=', '>', '?', '[', ']', '\\'],
      ['^', '`', '{', '|', '}', '~', '€', '£', '¥', '°', '.'], ['shift', '§', '¿', '¡', '«', '»', '…', '–', '_', '/', 'done'],
      ['abc', 'left', 'space', 'right', 'hide']],
  };
  const OSK_NAMES = { bksp: '⌫', shift: '⇧', done: 'Done', sym: '#+=', abc: 'abc', left: '◀', right: '▶', space: 'Space', hide: 'Hide' };
  const osk = {
    open: false, el: null, input: null, layer: 'abc', shift: false, r: 1, c: 0, pw: false,
    show(input, opts) {
      if (!textBox(input)) return;
      this.input = input; this.done = opts && opts.onDone; this.open = true; this.layer = 'abc'; this.shift = false; this.r = 1; this.c = 0;
      // a password box (or one that was a password box before Show): typed text shows as dots
      this.pw = input.type === 'password' || input.dataset.pw === '1';
      if (this.pw) input.dataset.pw = '1';
      const st = $('#stage') || document.body;
      if (!this.el) { this.el = document.createElement('div'); this.el.id = 'osk'; }
      this.el.classList.remove('top');
      st.append(this.el);
      this.el.onmousedown = ev => { ev.preventDefault(); const b = ev.target.closest('[data-r]'); if (b) { this.r = +b.dataset.r; this.c = +b.dataset.c; this.press(); } };
      this.draw();
      document.body.classList.add('oskon');
      input.focus();
      // never over the box being typed in: if it would cover it, the keyboard goes to the top
      const a = input.getBoundingClientRect(), k = this.el.getBoundingClientRect();
      if (a.bottom > k.top && a.top < k.bottom) this.el.classList.add('top');
    },
    hide() { if (!this.open) return; this.open = false; this.done = null; if (this.el) this.el.remove(); document.body.classList.remove('oskon'); },
    rows() {
      const R = OSK_ROWS[this.layer];
      if (!this.pw) return R;   // password boxes get a Show / Hide text key next to Hide
      const last = R[R.length - 1].slice(); last.splice(last.length - 1, 0, 'eye');
      return R.slice(0, -1).concat([last]);
    },
    label(k) {
      if (k === 'eye') return this.input && this.input.type === 'password' ? 'Show' : 'Hide text';
      if (OSK_NAMES[k]) return OSK_NAMES[k];
      return this.shift ? k.toUpperCase() : k;
    },
    val() {
      const i = this.input; if (!i) return '';
      return i.type === 'password' ? '•'.repeat(i.value.length) : i.value;
    },
    draw() {
      const R = this.rows();
      this.r = Math.min(this.r, R.length - 1); this.c = Math.min(this.c, R[this.r].length - 1);
      const name = this.input && (this.input.getAttribute('aria-label') || this.input.placeholder) || 'Type';
      this.el.innerHTML = `<div class="oskhead"><span>${esc(name)}</span><span class="oskval">${esc(this.val())}</span><span class="oskhelp"><u>X</u> Delete <u>Y</u> Space <u>B</u> Close <u>≡</u> Done</span></div>` +
        R.map((row, r) => `<div class="oskrow">${row.map((k, c) => `<button class="oskk k-${k.length > 1 ? k : 'ch'}${k === 'shift' && this.shift ? ' on' : ''}${r === this.r && c === this.c ? ' f' : ''}" data-r="${r}" data-c="${c}">${esc(this.label(k))}</button>`).join('')}</div>`).join('');
    },
    edit(fn) {
      const i = this.input; if (!i) return;
      const a = i.selectionStart == null ? i.value.length : i.selectionStart, b = i.selectionEnd == null ? a : i.selectionEnd;
      const r = fn(i.value, a, b);
      if (!r) return;
      const max = i.maxLength > 0 ? i.maxLength : 1e6;
      i.value = r[0].slice(0, max); const pos = Math.min(r[1], i.value.length);
      try { i.setSelectionRange(pos, pos); } catch (e) { /* some inputs have no cursor */ }
      i.dispatchEvent(new Event('input', { bubbles: true }));
      const v = this.el && this.el.querySelector('.oskval');
      if (v) v.textContent = this.val();
    },
    type(t) { this.edit((v, a, b) => [v.slice(0, a) + t + v.slice(b), a + t.length]); if (this.shift) { this.shift = false; this.draw(); } },
    press() {
      const k = this.rows()[this.r][this.c];
      if (k === 'bksp') this.edit((v, a, b) => a !== b ? [v.slice(0, a) + v.slice(b), a] : a > 0 ? [v.slice(0, a - 1) + v.slice(a), a - 1] : null);
      else if (k === 'space') this.type(' ');
      else if (k === 'shift') { this.shift = !this.shift; this.draw(); }
      else if (k === 'sym' || k === 'abc') { this.layer = k === 'sym' ? 'sym' : 'abc'; this.draw(); }
      else if (k === 'left' || k === 'right') this.edit((v, a) => [v, Math.max(0, Math.min(v.length, a + (k === 'left' ? -1 : 1)))]);
      else if (k === 'hide') this.hide();
      else if (k === 'eye') { if (this.input) this.input.type = this.input.type === 'password' ? 'text' : 'password'; this.draw(); }
      else if (k === 'done') this.enter();
      else this.type(this.label(k));
    },
    enter() {
      const i = this.input, done = this.done; this.hide();
      // the box went away (its panel was closed or replaced): nothing to finish
      if (!i || !i.isConnected || !i.offsetParent) return;
      if (done) done(i.value);
      else i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    },
    move(dr, dc) {
      const R = this.rows();
      if (dc) { this.c = (this.c + dc + R[this.r].length) % R[this.r].length; }
      if (dr) {
        const nr = this.r + dr; if (nr < 0 || nr >= R.length) return this.draw();
        const cur = this.el.querySelector(`[data-r="${this.r}"][data-c="${this.c}"]`);
        const x = cur ? cur.offsetLeft + cur.offsetWidth / 2 : 0;
        let best = 0, bd = 1e9;
        this.el.querySelectorAll(`[data-r="${nr}"]`).forEach(b => { const d = Math.abs(b.offsetLeft + b.offsetWidth / 2 - x); if (d < bd) { bd = d; best = +b.dataset.c; } });
        this.r = nr; this.c = best;
      }
      this.draw();
    },
    nav(a) {
      if (a === 'left') this.move(0, -1); else if (a === 'right') this.move(0, 1);
      else if (a === 'up') this.move(-1, 0); else if (a === 'down') this.move(1, 0);
      else if (a === 'ok') this.press();
      else if (a === 'bksp') { const k = this.rows()[this.r][this.c]; this.edit((v, s0, s1) => s0 !== s1 ? [v.slice(0, s0) + v.slice(s1), s0] : s0 > 0 ? [v.slice(0, s0 - 1) + v.slice(s0), s0 - 1] : null); }
      else if (a === 'space') this.type(' ');
      else if (a === 'menu') this.enter();
      else if (a === 'back' || a === 'guide') this.hide();
      return true;
    },
    /* a real keyboard: it types on its own, so the on-screen one steps aside */
    key(e) { if (e.key === 'Escape') { this.hide(); return true; } this.hide(); return false; },
  };
  window.addEventListener('blur', () => osk.hide());

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
  let lastPad = -Infinity;   // (no controller used yet: the on-screen keyboard doesn't pop up by itself)
  addEventListener('keydown', e => {
    hideCur();
    if (osk.open && osk.key(e)) { e.preventDefault(); return; }
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
    if (osk.open) return osk.nav(a);
    // A on a controller on a selected text box: type with the on-screen keyboard
    const ae = document.activeElement;
    if (a === 'ok' && e === null && textBox(ae) && ae.classList.contains('f')) { osk.show(ae); return true; }
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
      const S = { up: B(12) || ax[1] < -.6, down: B(13) || ax[1] > .6, left: B(14) || ax[0] < -.6, right: B(15) || ax[0] > .6, ok: B(0), back: B(1),
        opts: osk.open ? false : B(2) || B(3), bksp: osk.open && B(2), space: osk.open && B(3), menu: B(9) || B(8), guide: B(16) };
      const now = performance.now();
      if (rearm) { for (const k in S) prev[k] = S[k]; rearm = false; }
      for (const k in S) {
        const dir = ['up', 'down', 'left', 'right', 'bksp'].includes(k);
        if (S[k] && (!prev[k] || (dir && now > rep[k]))) { hideCur(); lastPad = now; rep[k] = now + (prev[k] ? 120 : 380); dispatch(k, null); }
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
    get prefs() { return prefs; }, save, ACCENTS, SIZE_NAMES, WALLS, LIVE, THEMES, get pro() { return proOK(); }, checkPro,
    osk: { show: (el, o) => osk.show(el, o), hide: () => osk.hide(), get open() { return osk.open; } },
    padRecent: () => performance.now() - lastPad < 30000,
    onNav(fn, opts) { handler = fn; guideHere = !!(opts && opts.guide); },   // opts.guide: the page handles the Super key itself
  };
  document.addEventListener('DOMContentLoaded', () => { hideCur(); applyLook(); checkPro(); });
})();
