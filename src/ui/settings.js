/* LaunchOS settings: the settings themselves (sound, network, Wi-Fi, saving, install, updates,
   password, LaunchOS Pro, gaming, power, about), shared by the Settings app (settings.html) and
   Home's side menu (index.html). Each page shows them its own way: it provides panel(), rp(),
   closePanel(), the P and mode state, and refreshNet(), refreshAll(), refreshTasks(), closeAll(),
   rg(), renderHome() and goSetup(). Classic script: these names are shared with the page's own. */

/* what the settings know about the system (filled in as they're opened) */
let net = null, vol = null, info = null, zone = '', storage = null, appsInfo = null;
let adminSet = false, session = null, pro = null;

/* Shows a background job's progress (downloads, saving, installing) until it's done. */
function progressPanel(job, title, onDone, doneRows, isUpdate, onRetry) {
  const paint = st => {
    const pct = Math.max(0, Math.min(100, st.percent || 0));
    return `<div class="meterbar"><i style="width:${pct}%"></i></div><p class="pnote">${esc(st.step || 'Starting…')}${st.done ? '' : ' · ' + pct + '%'}</p>`;
  };
  panel(title, 'You can leave this open or go back to Home. It keeps going.', [row('Hide', 'Keep going in the background', 'check', () => closePanel())], { body: paint({}) });
  const myP = P;
  const tick = async () => {
    if (P !== myP) return;   // the panel was closed or replaced
    const st = await call('job_status', job);
    if (P !== myP) return;
    if (st && st.done) {
      if (st.error) panel(title, st.error, [row('Try again', '', 'refresh', () => { if (onRetry) onRetry(); else closePanel(); }), row('Close', '', 'check', () => closePanel())]);
      else if (isUpdate) updatesPanel(st.step);
      else if (onDone) { closePanel(); onDone(); }
      else panel(title, st.step, doneRows || [row('Done', '', 'check', () => closePanel())]);
      return;
    }
    $('#pbody').innerHTML = paint(st || {});
    setTimeout(tick, 1000);
  };
  setTimeout(tick, 800);
}

const row = (t, s, glyph, a, extra) => Object.assign({ t, s, glyph, a }, extra || {});
/* a row's icon: the app's own (img), a full-color one (pic), or a simple glyph for actions */
const rowIcon = o => (o.img || o.pic) ? `<span class="glyph p">${o.img && o.img.startsWith('/opt/launcher/') ? `<img class="pic" src="${esc(o.img.slice(14))}" alt="">` : appPic(o.img, o.pic)}</span>` : `<span class="glyph">${icon(o.glyph || 'check')}</span>`;

/* Typing with a controller: the on-screen keyboard goes through the panel's text boxes in order,
   then does the panel's main thing. Opens by itself when the panel was opened with a controller. */
function typeAll(ids, finish) {
  const go = k => { const el = $('#' + ids[k]); if (!el) return; el.focus(); LOS.osk.show(el, { onDone: () => k + 1 < ids.length ? go(k + 1) : finish() }); };
  go(0);
}
function typeRow(label, ids, finish) { return Object.assign(row(label, 'With the on-screen keyboard', 'keyboard', () => typeAll(ids, finish), { pic: 'keyboard' }), { typing: true }); }
function autoType(ids, finish) { if (LOS.padRecent()) setTimeout(() => { if (P) typeAll(ids, finish); }, 120); }
function dropInput() { const a = document.activeElement; if (a && a.closest && a.closest('#panel')) a.blur(); }

async function volPanel() {
  vol = await call('volume_get');
  if (!vol.available) { panel('Sound', 'No sound device was found. In VirtualBox, check Settings → Audio is enabled.', [row('Close', '', 'check', () => closePanel())]); return; }
  const s = { slider: vol.value, async adjust(d) { this.slider = Math.max(0, Math.min(100, this.slider + d * 10)); rp(); vol = await call('volume_set', this.slider); } };
  panel('Sound', 'Use left and right to change the volume.', [s, row('Play a test sound', '', 'sound', () => call('sound_test')), row('Done', '', 'check', () => closePanel())]);
}
function sizePanel() {
  const pick = k => () => { LOS.save({ size: k }); toast('Screen size: ' + LOS.SIZE_NAMES[k]); closePanel(); };
  panel('Screen size', 'Pick TV safe area if the edges of the screen are cut off on your TV.', Object.keys(LOS.SIZE_NAMES).map(k => row(LOS.SIZE_NAMES[k], k === LOS.prefs.size ? 'Current' : '', k === LOS.prefs.size ? 'check' : 'display', pick(k))));
}
async function netPanel() {
  await refreshNet();
  const l = (net.links || []).find(x => x.ipv4.length) || (net.links || [])[0] || {};
  const body = `<dl class="kv"><dt>Status</dt><dd>${net.connected ? 'Connected' : 'Not connected'}</dd><dt>Adapter</dt><dd>${esc(l.name || 'None found')}</dd><dt>IP address</dt><dd>${esc((l.ipv4 || []).join(', ') || '—')}</dd><dt>Router</dt><dd>${esc(net.gateway || '—')}</dd><dt>DNS</dt><dd>${esc((net.dns || []).join(', ') || '—')}</dd></dl>`;
  panel('Network', net.connected ? 'Wired network. For Wi-Fi, use Settings → Wi-Fi.' : 'No connection. In VirtualBox, check Settings → Network: Adapter 1 enabled, attached to NAT.', [
    row('Test internet connection', '', 'globe', async () => { toast('Testing…'); const r = await call('internet_test'); toast(r.online ? 'You’re online' : (r.reason || 'Can’t reach the internet'), 3600); }),
    row('Done', '', 'check', () => closePanel()),
  ], { body });
}
async function aboutPanel() {
  info = await call('info');
  const body = `<dl class="kv"><dt>Version</dt><dd>${esc(info.version)} (${esc(info.build)})</dd><dt>Processor</dt><dd>${esc(info.cpu)}, ${info.cores} cores</dd><dt>Memory</dt><dd>${info.mem_free_mb} MB free of ${info.mem_total_mb} MB</dd><dt>Screen</dt><dd>${esc(info.resolution)}</dd><dt>Running for</dt><dd>${info.uptime_min} min</dd></dl>`;
  storage = await call('storage'); appsInfo = await call('apps_info');
  const body2 = body.replace('</dl>', `<dt>Graphics</dt><dd>${appsInfo.gpu === 'hardware' ? 'Hardware accelerated' : 'Software (no acceleration)'}</dd><dt>Saving</dt><dd>${storage.installed ? 'Installed on a drive' : storage.saving ? 'On' : 'Off'}</dd></dl>`);
  panel('About LaunchOS', storage.installed ? 'Installed on this PC.' : storage.saving ? 'Running live, with saving on.' : 'Running live: nothing you change is saved after you shut down.', [
    row('Open-source credits', 'The projects LaunchOS is built on', 'info', () => creditsPanel()), row('Done', '', 'check', () => closePanel())], { body: body2 });
}
const CREDITS = [['Debian 13', 'The base system. LaunchOS isn’t made or endorsed by Debian.'], ['Linux', 'GPL-2.0'], ['sway and wlroots', 'MIT'],
  ['GTK, WebKitGTK and VTE', 'LGPL'], ['Wine', 'LGPL-2.1'], ['Flatpak', 'LGPL-2.1'], ['PipeWire', 'MIT'], ['Papirus icons', 'GPL-3.0'], ['Inter and Noto fonts', 'OFL-1.1']];
function creditsPanel() {
  const body = `<dl class="kv">${CREDITS.map(([n, l]) => `<dt>${esc(n)}</dt><dd>${esc(l)}</dd>`).join('')}</dl><p class="pnote">Every package’s license is in /usr/share/doc on this system, and its source code is on sources.debian.org. Steam is Valve’s own app; Discord, Spotify and other apps from Flathub belong to their makers.</p>`;
  panel('Open-source credits', 'LaunchOS is built on free, open-source software.', [row('Back', '', 'check', () => aboutPanel())], { body });
}
/* ---------- Wi-Fi ---------- */
async function wifiPanel(msg) {
  const w = await call('wifi_status');
  if (!w || !w.available) { panel('Wi-Fi', (w && w.reason) || 'Wi-Fi isn’t available.', [row('Done', '', 'check', () => closePanel())]); return; }
  const bars = n => '▂▄▆█'.slice(0, n.bars);
  const rows = w.networks.map(n => row(n.name, [n.connected ? 'Connected' : n.known ? 'Saved' : '', n.type === 'open' ? 'Open' : 'Secured', bars(n)].filter(Boolean).join(' · '), 'wifi', () => wifiNetwork(n)));
  rows.push(row('Scan again', w.scanning ? 'Scanning…' : 'Look for networks', 'refresh', async () => {
    await call('wifi_scan'); toast('Scanning…');
    const myP = P;   // (only refresh the list if it's still what's open: not a password being typed)
    setTimeout(() => { if (mode === 'panel' && P === myP) wifiPanel(); }, 3500);
  }));
  rows.push(row('Done', '', 'check', () => closePanel()));
  panel('Wi-Fi', msg || (w.networks.length ? (w.state === 'connected' ? 'Connected.' : 'Pick a network.') : 'No networks found yet.'), rows);
}
function wifiNetwork(n) {
  if (n.connected) {
    panel(n.name, 'Connected.', [row('Disconnect', '', 'close', async () => { await call('wifi_disconnect'); wifiPanel('Disconnected.'); }),
      row('Forget this network', 'Removes the saved password', 'close', async () => { await call('wifi_forget', n.name); wifiPanel('Forgotten.'); }),
      row('Back', '', 'check', () => wifiPanel())]);
  } else if (n.known || n.type === 'open') wifiJoin(n);
  else wifiPassword(n);
}
function wifiPassword(n, err) {
  const body = `<label class="pw"><input id="wpw" type="password" maxlength="63" autocomplete="off" spellcheck="false" placeholder="Wi-Fi password" aria-label="Wi-Fi password for ${esc(n.name)}"><button id="wshow" type="button">Show</button></label>`;
  const join = () => wifiJoin(n, $('#wpw').value);
  panel(n.name, err || 'Type the Wi-Fi password, then press Enter.', [typeRow('Type the password', ['wpw'], join), row('Connect', '', 'wifi', join), row('Cancel', '', 'check', () => wifiPanel())], { body, enter: join });
  const i = $('#wpw');
  $('#wshow').onclick = () => { i.type = i.type === 'password' ? 'text' : 'password'; i.focus(); };
  setTimeout(() => i.focus(), 50);
  autoType(['wpw'], join);
}
async function wifiJoin(n, pw) {
  panel(n.name, 'Connecting…', []);
  const r = await call('wifi_connect', { name: n.name, passphrase: pw });
  if (r && r.ok) { toast('Connected to ' + n.name); wifiPanel('Connected to ' + n.name + '.'); refreshNet(); }
  else if (r && r.need_password) wifiPassword(n, r.error);
  else wifiPanel((r && r.error) || 'Couldn’t connect.');
}

/* ---------- saving ---------- */
async function savingPanel() {
  storage = await call('storage');
  const gb = n => (n / 1073741824).toFixed(1) + ' GB';
  const done = [row('Done', '', 'check', () => closePanel())];
  if (storage.installed) { panel('Saving', 'LaunchOS is installed on this PC’s drive, so everything is kept. ' + gb(storage.free) + ' free of ' + gb(storage.total) + '.', done); return; }
  if (storage.saving) { panel('Saving is on', (storage.boot === 'usb' ? 'Saves go in the free space on this USB stick. ' : '') + 'Your settings, sign-ins, downloads and games are kept between restarts. ' + gb(storage.free) + ' free of ' + gb(storage.total) + '.', done); return; }
  if (storage.job && storage.job.done && !storage.job.error) { panel('Saving', 'Saving is set up. Restart LaunchOS to start using it.', [row('Restart now', '', 'refresh', () => call('power', 'reboot')), ...done]); return; }
  if (storage.can_usb_saving) {
    panel('Saving is off', 'LaunchOS can keep your stuff in the free space on this USB stick. Nothing already on it is changed.', [
      row('Turn on saving', 'Uses the free space on this USB stick', 'usb', async () => {
        await call('usb_saving');
        progressPanel('usb-saving', 'Turning on saving', null, [row('Restart now', 'Saving starts after a restart', 'refresh', () => call('power', 'reboot')), ...done]);
      }), ...done]);
    return;
  }
  panel('Saving is off', storage.boot === 'usb' ? 'This USB stick has no free space for saves.'
    : 'Nothing you change is kept after you shut down. In VirtualBox, use LaunchOS.vbox from the download: it comes with a save disk. On a PC, start LaunchOS from a USB stick and turn saving on, or install it.', done);
}

/* ---------- install to a drive ---------- */
async function installPanel() {
  const job = await call('job_status', 'install');
  if (job && job.step && !job.done) { progressPanel('install', 'Installing LaunchOS', null, installDone()); return; }
  panel('Install LaunchOS', 'Looking for drives…', []);
  const disks = await call('install_disks');
  const gb = n => Math.round(n / 1e9) + ' GB';
  if (!Array.isArray(disks) || !disks.length) {
    panel('Install LaunchOS', 'No drive to install on. LaunchOS needs a spare drive of 16 GB or more that isn’t the USB stick it’s running from.', [row('Done', '', 'check', () => closePanel())]);
    return;
  }
  panel('Install LaunchOS', 'Pick the drive to install on. Everything on it will be erased.', disks.map(d => row(d.model + ' · ' + gb(d.size),
    (d.usb ? 'USB drive' : 'Drive inside this PC') + (d.parts ? ' · has ' + d.parts + ' partition' + (d.parts > 1 ? 's' : '') + ' with files' : ' · empty'), 'usb', () => confirmInstall(d)))
    .concat([row('Cancel', '', 'check', () => closePanel())]));
}
function confirmInstall(d, second) {
  const name = d.model + ' (' + Math.round(d.size / 1e9) + ' GB)';
  panel(second ? 'Last chance' : 'Erase ' + name + '?',
    second ? 'Installing will erase everything on ' + name + ' and replace it with LaunchOS. This can’t be undone.'
      : 'Every file, program and operating system on ' + name + ' will be deleted. Back up anything you want to keep first.', [
      row('Cancel', 'Keep everything on this drive', 'check', () => closePanel()),
      row(second ? 'Erase and install' : 'Continue', '', 'close', async () => {
        if (!second) { confirmInstall(d, true); return; }
        await call('install_system', { disk: d.path, confirm: 'ERASE ' + d.path });
        progressPanel('install', 'Installing LaunchOS', null, installDone());
      })]);
}
const installDone = () => [row('Restart now', 'Remove the USB stick or disc first', 'refresh', () => call('power', 'reboot')), row('Done', '', 'check', () => closePanel())];

/* ---------- updates ---------- */
async function updatesPanel(msg) {
  const u = await call('update_info');
  if (!u || u.error) { panel('Updates', 'Updates work when running as LaunchOS.', [row('Done', '', 'check', () => closePanel())]); return; }
  const c = u.check || {}, rows = [];
  if (c.done && c.restart) rows.push(row('Restart now', 'Finishes the LaunchOS update', 'refresh', () => call('power', 'reboot')));
  else if (c.done && c.available) rows.push(row('Update to LaunchOS ' + c.latest, c.full ? 'Needs a fresh download from GitHub' : u.saving ? 'Downloads from GitHub, then restart' : 'Needs saving turned on', 'usb', () => runUpdate('apply', 'update', 'Updating LaunchOS')));
  else rows.push(row('Check for LaunchOS updates', c.done && !c.error ? c.step : 'From LaunchOS on GitHub', 'refresh', () => runUpdate('check', 'update', 'Checking for updates')));
  rows.push(row('Update your apps', u.saving ? 'Apps from the Store' : 'Needs saving turned on', 'bag', () => runUpdate('apps', 'appupdate', 'Updating your apps')));
  rows.push(row('Update the system', u.saving ? 'Debian security fixes' : 'Needs saving turned on', 'gear', () => runUpdate('system', 'sysupdate', 'Updating the system')));
  rows.push(row('Done', '', 'check', () => closePanel()));
  const notes = c.done && c.available && c.notes ? `<p class="pnote">${esc(c.notes.slice(0, 400))}${c.notes.length > 400 ? '…' : ''}</p>` : '';
  panel('Updates', msg || ('You have LaunchOS ' + u.version + (u.build ? ' (' + u.build + ')' : '') + '.'), rows, { body: notes });
}
async function runUpdate(what, job, title) {
  const r = await call('update_action', what);
  if (!r || !r.ok) { toast((r && r.error) || 'Updates work when running as LaunchOS', 3600); return; }
  progressPanel(job, title, null, null, true);
}
/* ---------- admin password (sudo in the Terminal) ---------- */
async function adminPanel(err) {
  const r = await call('admin_set'); adminSet = !!(r && r.set);
  const body = (adminSet ? `<label class="pw"><input id="apo" type="password" maxlength="128" autocomplete="off" placeholder="Current password" aria-label="Current password"></label>` : '')
    + `<label class="pw"><input id="apn" type="password" maxlength="128" autocomplete="off" placeholder="New password" aria-label="New password"></label>`
    + `<label class="pw"><input id="apn2" type="password" maxlength="128" autocomplete="off" placeholder="Type it again" aria-label="New password again"></label>`;
  session = await call('session_state');
  const askRow = adminSet ? [row('Ask for it at sign-in: ' + (session && session.ask ? 'On' : 'Off'), session && session.ask ? 'Turn off to sign in by pressing A' : 'Turn on so only you can sign in', 'user', async () => {
    await call('signin_ask', !(session && session.ask)); adminPanel(); }, { pic: 'lock' })] : [];
  const ids = adminSet ? ['apo', 'apn', 'apn2'] : ['apn', 'apn2'];
  const save = async () => {
    const n = $('#apn').value, n2 = $('#apn2').value, o = adminSet ? $('#apo').value : '';
    if (n.length < 6) { adminPanel('Use 6 or more characters.'); return; }
    if (n !== n2) { adminPanel('The two passwords don’t match.'); return; }
    panel('Password', 'Saving…', [], { busy: true });
    let res = await call('admin_password', { new: n, old: o });
    // the first time, LaunchOS asks for a key press, so only someone at the PC can do this
    for (let i = 0; i < 90 && res && !res.done && !res.error; i++) {
      $('#pp').textContent = res.step || 'Saving…';
      await new Promise(r => setTimeout(r, 1000));
      res = await call('job_status', 'admin');
    }
    if (res && res.done && !res.error) { adminSet = true; if (P) P.from = 'guide'; panel('Password', 'Saved. You’ll type it when you sign in. In the Terminal, type sudo before a command and enter this password.', [row('Done', '', 'check', () => closePanel())]); }
    else adminPanel((res && res.error) || 'Couldn’t save the password.');
  };
  panel('Password', err || (adminSet ? 'Change your password. It’s asked for when you sign in, and for admin commands (sudo) in the Terminal.' : 'Set a password so only you can sign in, and to run admin commands (sudo) in the Terminal. Keep it somewhere safe.'), [
    typeRow('Type the passwords', ids, save),
    row('Save', 'Or press Enter', 'check', save),
    ...askRow,
    row('Cancel', '', 'close', () => closePanel())], { body, enter: save });
  setTimeout(() => { const i = $(adminSet ? '#apo' : '#apn'); if (i) i.focus(); }, 60);
  autoType(ids, save);
}
/* ---------- LaunchOS Pro ---------- */
const PRO_FEATS = ['Live backgrounds that move', 'Five color themes, like Carbon and Pure black', 'Gaming mode: full speed while you play', 'An FPS counter in games', 'Early access to new versions', 'A supporter badge'];
async function proPanel(msg) {
  pro = await call('pro_state');
  if (!pro || pro.error) { panel('LaunchOS Pro', 'LaunchOS Pro works when running as LaunchOS.', [row('Done', '', 'check', () => closePanel())]); return; }
  const done = row('Done', '', 'check', () => closePanel());
  const list = `<ul class="feats">${PRO_FEATS.map(f => `<li>${esc(f)}</li>`).join('')}</ul>`;
  if (pro.status === 'active' && !pro.installed) {   // the key is fine, the extras didn't download
    panel('LaunchOS Pro', msg || 'Your key is unlocked. The Pro extras still have to download.', [
      row('Get the Pro extras', 'Needs an internet connection', 'check', () => proJob('install', 'Getting the Pro extras'), { pic: 'updates' }),
      row('Remove Pro from this PC', 'Frees this PC’s slot for another one', 'close', () => proJob('remove', 'Removing LaunchOS Pro')),
      done]);
    return;
  }
  if (pro.active) {
    const body = `<dl class="kv"><dt>Status</dt><dd>On${pro.since ? ' since ' + esc(pro.since) : ''}</dd><dt>Key</dt><dd>${esc(pro.key_hint || '—')}</dd><dt>Pro extras</dt><dd>Version ${esc(pro.version || '?')}</dd></dl>`;
    panel('LaunchOS Pro', msg || 'Thanks for supporting LaunchOS!', [
      row('Gaming', 'Performance mode and FPS counter', 'pad', () => gamingPanel(), { pic: 'controller' }),
      row('Live backgrounds and themes', 'In Customize your Home', 'palette', goSetup('look'), { pic: 'look' }),
      row('Check for Pro updates', 'Gets newer Pro extras', 'refresh', () => proJob('install', 'Checking for Pro updates'), { pic: 'updates' }),
      row('Remove Pro from this PC', 'Frees this PC’s slot for another one', 'close', () => panel('Remove Pro from this PC?', 'Pro turns off here, and this PC’s slot on your key is freed. You can enter the key again later.', [
        row('Cancel', 'Keep Pro on this PC', 'check', () => proPanel()), row('Remove Pro', '', 'close', () => proJob('remove', 'Removing LaunchOS Pro'))])),
      done], { body });
    return;
  }
  if (!pro.on_sale) {
    panel('LaunchOS Pro', 'LaunchOS Pro is coming soon: a $5, one-time unlock that adds extras. Everything LaunchOS does now stays free.', [done], { body: list });
    return;
  }
  const qr = pro.buy ? await call('pro_qr') : null;
  const buy = pro.buy ? `<div class="buy">${qr && qr.svg ? `<div class="qr">${qr.svg}</div>` : ''}<span>Buy Pro on your phone or another PC: scan the code or go to<br><b>${esc(pro.buy.replace(/^https:\/\//, ''))}</b><br>You get a key by email.</span></div>` : '';
  const why = pro.status === 'revoked' ? 'This PC’s Pro key was refunded, so Pro is off. ' : '';
  panel('LaunchOS Pro', msg || why + 'A $5, one-time unlock. One key works on up to 5 PCs.', [
    row('Enter your key', 'From the email you got', 'check', () => keyPanel(), { pic: 'pro' }),
    row('Open the Pro page', 'In the Browser', 'globe', () => { closeAll(); call('open_app', { id: 'browser', name: 'Browser', url: pro.buy, navigate: true }).then(refreshTasks); }, { pic: 'browser' }),
    done], { body: list + buy });
}
function keyPanel(err, typed) {
  const body = `<label class="pw"><input id="pkey" type="text" maxlength="64" autocomplete="off" spellcheck="false" autocapitalize="off" placeholder="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" aria-label="Your LaunchOS Pro key"></label>`;
  const go = async () => {
    const key = $('#pkey').value.replace(/\s+/g, '');
    if (key.length < 8) { keyPanel('Type the whole key. It’s in the email from your purchase.', key); return; }
    const r = await call('pro_action', { op: 'activate', key });
    if (!r || !r.ok) { keyPanel((r && r.error) || 'Couldn’t check the key. Try again.', key); return; }
    proProgress('Unlocking LaunchOS Pro', () => keyPanel('', key));   // (Try again keeps what was typed)
  };
  // without saving, this PC forgets the key at the next start (it keeps its one slot on the key)
  const hint = pro && pro.saving === false ? 'Saving is off, so you’ll enter it again after a restart.' : 'Letters, numbers and dashes.';
  panel('Enter your Pro key', err || 'Type the key from your email. ' + hint, [
    typeRow('Type the key', ['pkey'], go), row('Unlock Pro', 'Needs an internet connection', 'check', go), row('Cancel', '', 'close', () => proPanel())], { body, enter: go });
  if (typed) $('#pkey').value = typed;
  setTimeout(() => { const i = $('#pkey'); if (i) i.focus(); }, 60);
  if (!typed) autoType(['pkey'], go);
}
async function proJob(op, title) {
  const r = await call('pro_action', { op });
  if (!r || !r.ok) { toast((r && r.error) || 'Couldn’t start. Try again.', 3600); return; }
  proProgress(title, () => proJob(op, title));
}
function proProgress(title, retry) {
  progressPanel('pro', title, null, [row('Done', '', 'check', async () => { await LOS.checkPro(); await refreshAll(); proPanel(); })], false, retry);
  // the look follows Pro being on or off once the job is done
  const watch = async () => { const st = await call('job_status', 'pro'); if (st && st.done) { LOS.checkPro(); setTimeout(() => renderHome(), 600); } else setTimeout(watch, 1500); };
  setTimeout(watch, 1500);
}
/* ---------- Gaming (LaunchOS Pro) ---------- */
const FPS_NAMES = { off: 'Off', fps: 'Just the FPS', full: 'Detailed (FPS, CPU, GPU, memory)' };
async function gamingPanel() {
  pro = await call('pro_state');
  if (!pro || !pro.active) {
    panel('Gaming', 'With LaunchOS Pro, games run in gaming mode: the processor runs at full speed, games get priority over everything else, and an FPS counter can show how smoothly they run.', [
      row('About LaunchOS Pro', pro && pro.on_sale ? 'Extras for $5, once' : 'Coming soon', 'info', () => proPanel(), { pic: 'pro' }), row('Done', '', 'check', () => closePanel())]);
    return;
  }
  const g = await call('gaming_get');
  const order = ['off', 'fps', 'full'];
  panel('Gaming', 'For Steam, Windows programs and games from the Store. Changes count from the next game you start (if Steam is open, close it first).', [
    row('Performance mode: ' + (g.perf ? 'On' : 'Off'), 'Full speed and top priority while a game runs', 'chart', async () => { await call('gaming_set', { perf: !g.perf }); gamingPanel(); }, { pic: 'monitor' }),
    row('FPS counter: ' + FPS_NAMES[g.fps], pro.fps_ok ? 'In Steam games and Windows programs' : 'Not available on this system', 'chart', async () => {
      if (!pro.fps_ok) return;
      await call('gaming_set', { fps: order[(order.indexOf(g.fps) + 1) % order.length] }); gamingPanel(); }, { pic: 'display' }),
    row('Done', '', 'check', () => closePanel())]);
}
function powerPanel() {
  const go = a => async () => {
    const b = $('#bye'); b.textContent = a === 'poweroff' ? 'Shutting down' : 'Restarting'; b.style.display = 'flex';
    const r = await call('power', a);
    if (!r || !r.ok) setTimeout(() => { b.style.display = 'none'; toast('Power controls work when running as LaunchOS'); }, 1200);
  };
  const n = Object.keys(running).length;
  panel('Power', 'Lock, sign out, or turn off your console.', [
    ...(adminSet ? [row('Lock', n ? 'Your apps keep running' : 'Go to the sign-in screen', 'user', () => call('lock'), { pic: 'lock' })] : []),
    row('Sign out', n ? 'Closes your apps first' : 'Go to the sign-in screen', 'user', () => call('sign_out'), { pic: 'signout' }),
    row('Shut down', 'Turn off the console', 'power', go('poweroff'), { pic: 'power' }),
    row('Restart', 'Turn it off and back on', 'refresh', go('reboot'), { pic: 'restart' }),
    row('Cancel', 'Go back', 'check', () => closePanel())]);
}
