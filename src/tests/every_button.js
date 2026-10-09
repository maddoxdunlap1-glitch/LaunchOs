#!/usr/bin/env node
'use strict';
/*
 * Press every button: a depth-first walk over every LaunchOS page in a normal browser, with the
 * mocks in los.js standing in for the system (no Python). For each clickable thing it loads the page
 * fresh, repeats the clicks that lead to it, and presses it: with the mouse, then again with the
 * keyboard the way a controller user would (arrow keys to reach it, Enter to press it). Every
 * screen it finds is also left with Escape. After every press it fails on:
 *   page errors, console errors, unhandled promise rejections, files that are missing,
 *   a "Starting…"-style busy text that doesn't change for 5 s, a panel with no rows,
 *   row text that doesn't fit (scrollWidth > clientWidth), something clickable with no label,
 *   something in view that another element covers, a panel taller than the screen,
 *   no focus marker (.f) left, something the arrow keys can't reach, Enter doing something other
 *   than a click, and a panel or menu that Escape doesn't close.
 * The on-screen keyboard is driven with a pretend controller (a real key press closes it, by design),
 * and sliders are clicked a quarter of the way along and must move there.
 * Pages: index.html (plain, ?onsale, ?pro), login (plain, with a password), setup (whole flow,
 * ?pro#look, #controller), files, store (+ an installed app's page), monitor, view (picture, text,
 * song, video) and start, each at 1280x720 and 1024x768. The keyboard pass runs at the first size
 * (the stage is drawn at 1280x720 and scaled, so keys behave the same at both); --kbd-all for both.
 *
 * Run:  NODE_PATH=$(npm root -g) node src/tests/every_button.js [options]
 *   --pages index,files      only pages whose name (with its variant) contains one of these
 *   --vp 1280x720,1024x768   window sizes
 *   --max 6000               presses for the whole run (pages share it in order; a full run is about 5,600)
 *   --depth N                depth cap for every page (default per page: 5; Files 6; setup's wizard 12)
 *   --cap N                  presses per page variant and size (default per page; half without the keyboard pass)
 *   --workers 4              pages driven at the same time
 *   --no-kbd / --kbd-all     skip the keyboard pass / run it at every window size
 *   --out FILE               everything as JSON (default $TMPDIR/every_button.json)
 *   -v                       print every press
 * Exit code 1 when anything failed.
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const os = require('os');

const UI = path.resolve(__dirname, '../ui');

/* ---------- options ---------- */
const ARGS = process.argv.slice(2);
const arg = (n, d) => { const i = ARGS.indexOf('--' + n); return i >= 0 && ARGS[i + 1] != null ? ARGS[i + 1] : d; };
const has = n => ARGS.includes('--' + n) || ARGS.includes('-' + n);
const OPT = {
  pages: arg('pages', '').split(',').filter(Boolean),
  vps: arg('vp', '1280x720,1024x768').split(',').map(s => { const [width, height] = s.split('x').map(Number); return { width, height }; }),
  max: +arg('max', 6000),
  cap: arg('cap', null) == null ? null : +arg('cap'),
  depth: arg('depth', null) == null ? null : +arg('depth'),
  workers: Math.max(1, +arg('workers', 4)),
  kbd: !has('no-kbd'),
  kbdAll: has('kbd-all'),
  out: arg('out', path.join(os.tmpdir(), 'every_button.json')),
  verbose: has('v'),
};

/* ---------- things for the viewer to show: a short beep and a long text file ---------- */
function fixtures() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'every-button-'));
  const rate = 8000, n = rate, b = Buffer.alloc(44 + n);
  b.write('RIFF', 0); b.writeUInt32LE(36 + n, 4); b.write('WAVE', 8); b.write('fmt ', 12); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate, 28); b.writeUInt16LE(1, 32); b.writeUInt16LE(8, 34);
  b.write('data', 36); b.writeUInt32LE(n, 40);
  for (let i = 0; i < n; i++) b[44 + i] = 128 + Math.round(40 * Math.sin(i / rate * 2 * Math.PI * 440));
  fs.writeFileSync(path.join(dir, 'beep.wav'), b);
  fs.writeFileSync(path.join(dir, 'notes.txt'), 'A line of notes in a text file.\n'.repeat(300));
  return dir;
}
const FX = fixtures();
const viewSeed = (name, kind, files) => ({ name, session: { 'launchos.view': JSON.stringify({ kind, list: files.map(p => ({ name: path.basename(p), path: p, size: 1000 })), i: 0 }) } });

/* ---------- what is clickable on each page ----------
   A page is a stack of layers (a panel over the side menu over Home); the first layer whose `when`
   is true is the one on top, and only its things are pressed. Groups: `sel` finds the things;
   `kb` says how the keyboard reaches them: 'nav' (arrows move the .f marker onto it, then Enter),
   'tab' (left/right make it .on), 'tabkey' (the Tab key), 'input' (a text box that gets focus),
   'pad' (the same with a controller's D-pad and A), 'hint' (an on-screen button for a key: A = Enter, B = Escape, ≡ = M, X = the menu key),
   {key} (that key), 'none' (mouse only). `act`: 'click' (default), 'dbl', 'hover', 'outside'
   (a click on the dimmed area around a panel); `ctx`: also right-click it (app/file options). */
const HINT_KEYS = { ha: 'Enter', hb: 'Escape', hm: 'm', hx: 'ContextMenu', hy: '/', hl: 'ArrowLeft', hr: 'ArrowRight' };
const hints = { sel: '#hints button:not([hidden])', kb: 'hint', name: 'button hint' };
const osk = { name: 'on-screen keyboard', when: "document.body && document.body.classList.contains('oskon')", modal: true, box: '#osk',
  groups: [{ sel: '#osk .oskk', kb: 'pad', name: 'key', max: 7, prefer: '^(Done|Hide|Show|Hide text|⌫|#\\+=|abc|Space)$' }] };   // (controller only: a real key hides it)
const bye = { name: 'power', when: "getComputedStyle(document.querySelector('#bye')).display !== 'none'", modal: true, box: '#bye', busy: 'true', groups: [] };
const outside = { sel: '#dim', act: 'outside', kb: { key: 'Escape' }, name: 'outside' };
const panelLayer = extra => Object.assign({ name: 'panel', when: "document.querySelector('#panel').classList.contains('on')", modal: true, head: '#ph', box: '#panel', rows: '#pl > [data-k]' }, extra);

const PAGES = [
  { file: 'index.html', depth: 5, cap: 900, variants: [{ q: '', name: 'plain' }, { q: '?onsale' }, { q: '?pro' }],
    layers: [osk, bye,
      panelLayer({ under: "document.querySelector('#guide').classList.contains('on') ? 'over menu' : 'over home'",
        groups: [{ sel: '#pl > [data-k]', kb: 'nav', name: 'panel row' }, { sel: '#panel input', kb: 'input', name: 'text box' },
          { sel: '#pbody button, #panel label.pw button', kb: 'none', name: 'panel button' }, outside] }),
      { name: 'moving a tile', when: "document.querySelector('#cap').classList.contains('moving')", modal: true, box: '#stage',
        groups: [{ sel: '#r1 .t1.mv', kb: { key: 'Enter' }, name: 'lifted tile' }, { sel: '#r1 .t1:not(.mv)', kb: { key: 'Enter' }, name: 'tile', max: 1 }, hints] },
      { name: 'side menu', when: "document.querySelector('#guide').classList.contains('on')", modal: true, head: '#gh', box: '#guide',
        groups: [{ sel: '#gtabs .gt', kb: 'tab', name: 'menu tab' }, { sel: '#gl > .it', kb: 'nav', name: 'menu row', sigNorm: ['Running ·', '(a running app)'] }, outside] },
      { name: 'home', when: 'true', box: '#stage',
        groups: [{ sel: '#r1 .t1', kb: 'nav', ctx: true, ctxMax: 3, name: 'tile' }, { sel: '#r2 .t2', kb: 'nav', ctx: true, ctxMax: 2, name: 'wide tile' },
          { sel: '#tb .tb', kb: 'nav', ctx: true, ctxMax: 2, name: 'top button' }, { sel: '#me', kb: { key: 'm' }, name: 'avatar' }, hints] }] },
  { file: 'login.html', depth: 4, cap: 80, variants: [{ q: '', name: 'plain' }, { q: '', name: 'password', session: { 'launchos.mock': JSON.stringify({ admin: 'hunter22', ask: true }) } }],
    layers: [{ name: 'intro', when: "!!document.querySelector('#intro:not(.out)')", busy: 'true', box: '#intro', groups: [] }, bye,
      panelLayer({ groups: [{ sel: '#pl > [data-k]', kb: 'nav', name: 'panel row' }, outside] }),
      { name: 'sign-in', when: 'true', box: '#stage',
        groups: [{ sel: '#form [data-f], #bottom [data-f]', kb: 'nav', name: 'button' }, { sel: '#show', kb: 'none', name: 'Show button' }, hints] }] },
  { file: 'setup.html', depth: 12, cap: 400, variants: [{ q: '', name: 'whole flow' }, { q: '?pro#look', local: { 'launchos.prefs': '{"proOn":true}' } }, { q: '#controller' }],
    layers: [osk, { name: 'step', when: 'true', head: '#title', box: '#stage',
      groups: [{ sel: '#content [data-f]', kb: 'nav', name: 'choice', max: 30 }, { sel: '#nav [data-f]', kb: 'nav', name: 'step button' }, hints] }] },
  { file: 'files.html', depth: 6, cap: 900, variants: [{ q: '' }],
    layers: [osk,
      panelLayer({ groups: [{ sel: '#pl > [data-k]', kb: 'nav', name: 'panel row' }, { sel: '#panel input', kb: 'input', name: 'text box' }, outside] }),
      { name: 'files', when: 'true', head: '#crumb', box: '#stage', navOrder: 'cols', selectMode: "mode === 'select'",
        groups: [{ sel: '#side .it', kb: 'nav', ctx: true, ctxPick: '^(Downloads|USB STICK|Windows|VBOX HARDDISK)$', name: 'place or drive' },
          { sel: '#list .fr', kb: 'nav', ctx: true, ctxMax: 4, act: 'dbl', name: 'file', max: 8, nosig: true },
          { sel: '#crumb .c', kb: 'none', name: 'path part' }, { sel: '#clip button', kb: 'none', name: 'clipboard button' }, { sel: '#jobchip.on', kb: 'none', name: 'job chip' }, hints] }] },
  { file: 'store.html', depth: 5, cap: 500, variants: [{ q: '' }, { q: '#org.videolan.VLC' }],
    layers: [osk,
      { name: 'app page', when: "document.querySelector('#detail').classList.contains('on')", modal: true, box: '#detail', sigHead: false,
        groups: [{ sel: '#dbtns .btn', kb: 'nav', name: 'app button' }, hints] },
      { name: 'store', when: 'true', head: '#tabs .tab.on', box: '#stage',
        groups: [{ sel: '#q', kb: 'nav', name: 'search box' }, { sel: '#tabs .tab', kb: 'nav', name: 'shelf' }, { sel: '#grid .card', kb: 'nav', name: 'app card', max: 6, prefer: '^Show more', nosig: true }, hints] }] },   // (the shelf names the screen)
  { file: 'monitor.html', depth: 2, cap: 40, variants: [{ q: '' }],
    layers: [{ name: 'monitor', when: 'true', box: '#stage', focus: 'none', groups: [hints, { sel: '.plot', act: 'hover', kb: 'none', name: 'chart' }] }] },
  { file: 'view.html', depth: 2, cap: 40,
    variants: [viewSeed('picture', 'image', [UI + '/walls/thumbs/nebula.webp', UI + '/walls/thumbs/aurora.webp', '/home/player/Pictures/gone.png']),
      viewSeed('text', 'text', [FX + '/notes.txt']), viewSeed('song', 'audio', [FX + '/beep.wav', FX + '/beep.wav']), viewSeed('video', 'video', ['/home/player/Downloads/clip.mp4'])],
    layers: [{ name: 'viewer', when: 'true', head: '#name', box: '#stage', focus: 'none', groups: [hints] }] },
  { file: 'start.html', depth: 2, cap: 40, variants: [{ q: '' }],
    layers: [{ name: 'start page', when: 'true', box: 'main', focus: 'active',
      groups: [{ sel: 'form input', kb: 'tabkey', name: 'search box' }, { sel: 'form button', kb: 'tabkey', name: 'Search button' }, { sel: 'a.tile', kb: 'tabkey', name: 'shortcut' }] }] },
];

/* ---------- in the page: layers, items, checks (stringified into every page) ---------- */
function INPAGE() {
  if (window.__eb) return;
  const eb = window.__eb = { lastMut: performance.now() };
  addEventListener('unhandledrejection', e => console.error('UNHANDLED REJECTION: ' + (e.reason && (e.reason.stack || e.reason.message) || e.reason)));
  // when the page last changed (the clock and toasts don't count)
  new MutationObserver(list => {
    for (const m of list) {
      const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      if (t && t.closest && t.closest('#toast, #clock, #time, #date')) continue;
      eb.lastMut = performance.now(); return;
    }
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class', 'style', 'hidden'] });

  const BUSY = /\b(Starting|Checking|Looking|Connecting|Saving|Signing in|Testing|Scanning|Working|Loading|Getting|Finishing|Opening|Installing|Downloading|Removing|Measuring|Unlocking|Formatting|Ejecting|Closing|Deleting|Copying|Moving|Stopping|Updating)\b[^\n]{0,60}?(…|\.\.\.)/;
  const vis = el => !!el && el.isConnected && el.getClientRects().length > 0 && (!el.checkVisibility || el.checkVisibility({ opacityProperty: true, visibilityProperty: true }));
  const first = s => String(s || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || '';
  const STATE = /^(f|on|sel|run|mv|cur|cutting|focus|moving|dim|done|warn|crit|primary|main|get|big)$/;   // classes that come and go
  const desc = el => { if (!el) return 'nothing'; if (el === document.body) return 'body'; const c = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(x => x && !STATE.test(x)) : []; return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (c.length ? '.' + c.join('.') : ''); };
  const test = x => { try { return !!Function('return (' + x + ')')(); } catch (e) { return false; } };
  const val = x => { try { return String(Function('return (' + x + ')')()); } catch (e) { return ''; } };
  const nameOf = el => (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
  const titleOf = el => { const s = el.matches('.it') && el.querySelector('.txt > span'); return s ? first(s.innerText) : ''; };
  const boldOf = el => { const b = el.querySelector(':scope > b, :scope > .txt > b'); return b ? first(b.innerText) : ''; };
  const keyOf = el => titleOf(el) || nameOf(el) || boldOf(el) || first(el.innerText) || ((el.querySelector('img') || {}).src || '').split('/').pop() || desc(el);
  const ctr = el => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, h: r.height }; };
  // the same, in the coordinates of everything that scrolls it (a list that scrolls to keep the highlight in one place still counts as moving)
  const pos = el => { const c = ctr(el); for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) { c.x += a.scrollLeft; c.y += a.scrollTop; } return c; };
  const marked = el => el.classList.contains('f') || !!el.closest('.f') || !!el.querySelector('.f');
  const hits = (el, x, y) => { const h = document.elementFromPoint(x, y); return !!h && (h === el || el.contains(h)); };
  const layerOf = Ls => Ls.find(L => test(L.when)) || null;
  function itemsOf(L) {
    const out = [];
    L.groups.forEach((g, gi) => {
      const cnt = {};
      let i = 0;
      document.querySelectorAll(g.sel).forEach(el => {
        if (!vis(el)) return;
        let key = keyOf(el).slice(0, 80);
        cnt[key] = (cnt[key] || 0) + 1;
        if (cnt[key] > 1) key += ' #' + cnt[key];
        out.push({ el, gi, i: i++, key });
      });
    });
    return out;
  }
  const find = (L, st, items) => (items || itemsOf(L)).find(o => o.gi === st.gi && o.key === st.key) || null;
  // the part of the window an element can show in (inside every box that clips it), and the list that scrolls it
  function clipOf(el) {
    let c = { l: 0, t: 0, r: innerWidth, b: innerHeight }, scroller = null;
    const { y } = ctr(el);
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect();
      if (!scroller && /auto|scroll/.test(cs.overflowY) && a.scrollHeight > a.clientHeight + 1 && (y < ar.top + 6 || y > ar.bottom - 6))
        scroller = { x: ar.left + ar.width / 2, y: ar.top + Math.min(ar.height / 2, 80), dy: y > ar.bottom - 6 ? 1 : -1, step: Math.max(60, Math.round(ar.height * 0.6)) };
      c = { l: Math.max(c.l, ar.left), t: Math.max(c.t, ar.top), r: Math.min(c.r, ar.right), b: Math.min(c.b, ar.bottom) };
    }
    return { c, scroller };
  }
  // the text people can see on the top layer (not toasts, not things slid off screen)
  function textOf(L) {
    const root = (L.box && document.querySelector(L.box)) || document.body;
    const out = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const p = n.parentElement, s = n.textContent.trim();
      if (!s || !p || p.closest('#toast') || !vis(p)) continue;
      const r = p.getBoundingClientRect();
      if (r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) continue;
      out.push(s);
    }
    return out.join('\n');
  }
  function busyOf(L) { if (L.busy) return test(L.busy) ? L.name : ''; const m = textOf(L).match(BUSY); return m ? m[0] : ''; }

  // (the busy text is only read once the page is still: reading it costs a layout)
  eb.quiet = (Ls, idleMin) => {
    const idle = performance.now() - eb.lastMut;
    const anim = document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length;
    if (idle < idleMin || anim) return { idle, anim, busy: null };
    const L = layerOf(Ls);
    return { idle, anim, busy: !!(L && busyOf(L)), layer: L && L.name };
  };

  function audit(L, items, busy) {
    const a = { overflow: [], nolabel: [], iconOnly: [], covered: [], cut: '', zero: false, focus: '' };
    const stage = document.querySelector('#stage');
    const sr = stage ? stage.getBoundingClientRect() : { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
    for (const o of items) {
      const g = L.groups[o.gi], el = o.el;
      if (g.act === 'outside' || g.act === 'hover') continue;
      const vt = first(el.innerText), nm = nameOf(el), ts = el.matches('.it') && el.querySelector('.txt > span');
      if (!vt && !nm) a.nolabel.push({ key: o.key, el: desc(el), g: g.name, why: 'no visible text and no aria-label or title' });
      else if (ts && !ts.innerText.trim()) a.nolabel.push({ key: o.key, el: desc(el), g: g.name, why: 'the row’s title is empty' });
      else if (!vt) a.iconOnly.push(o.key);
      // text that doesn't fit its row
      const er = el.getBoundingClientRect();
      const check = n => {
        if (!n.clientWidth) return;
        const cs = getComputedStyle(n), nr = n.getBoundingClientRect();
        const spill = n !== el && (nr.right > er.right + 1 || nr.left < er.left - 1);
        if (n.scrollWidth > n.clientWidth + 1 || spill)
          a.overflow.push({ key: o.key, el: desc(n), text: first(n.innerText).slice(0, 100), sw: n.scrollWidth, cw: n.clientWidth,
            how: spill ? 'spills out of its row' : cs.textOverflow === 'ellipsis' ? 'cut off with …' : cs.overflowX !== 'visible' ? 'cut off' : 'runs past its box' });
      };
      check(el);
      el.querySelectorAll('*').forEach(n => { if ([...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) check(n); });
      // in view, but a click there lands on something else
      const { x, y } = ctr(el), { c } = clipOf(el);
      if (x > c.l + 1 && x < c.r - 1 && y > c.t + 1 && y < c.b - 1 && !hits(el, x, y)) a.covered.push({ key: o.key, by: desc(document.elementFromPoint(x, y)) });
    }
    if (L.box) {
      const b = document.querySelector(L.box);
      if (b && b !== stage && vis(b)) { const r = b.getBoundingClientRect(); if (r.top < sr.top - 1 || r.bottom > sr.bottom + 1 || r.left < sr.left - 1 || r.right > sr.right + 1) a.cut = `${desc(b)} is ${Math.round(r.height)}px tall at y=${Math.round(r.top - sr.top)}; the screen is ${Math.round(sr.bottom - sr.top)}px`; }
    }
    if (L.rows && !busy && !document.querySelectorAll(L.rows).length) a.zero = true;
    const navs = items.filter(o => /^(nav|pad|tabkey)$/.test(L.groups[o.gi].kb));
    if (L.focus !== 'none' && navs.length) {
      if (L.focus === 'active') { if (!document.activeElement || document.activeElement === document.body) a.focus = 'nothing has keyboard focus'; }
      else if (!navs.some(o => marked(o.el))) { const f = [...document.querySelectorAll('.f')].filter(vis); a.focus = 'no focus marker (.f) on anything in ' + L.name + (f.length ? '; .f is on ' + f.map(desc).join(', ') : '; nothing has .f'); }
    }
    return a;
  }

  eb.snap = (Ls, withAudit) => {
    const L = layerOf(Ls);
    if (!L) return { layer: null, sig: 'none', items: [], text: '' };
    const items = itemsOf(L);
    const head = L.head ? first((document.querySelector(L.head) || {}).innerText) : '';
    const under = L.under ? val(L.under) : '';
    const keys = [...new Set(items.filter(o => !L.groups[o.gi].nosig).map(o => { const g = L.groups[o.gi]; return g.sigNorm && (o.el.innerText || '').includes(g.sigNorm[0]) ? g.sigNorm[1] : o.key; }))].sort();
    const busy = busyOf(L);
    const s = { layer: L.name, modal: !!L.modal, head, under, busy, text: textOf(L).slice(0, 3000), url: location.href,
      sig: [L.name, L.sigHead === false ? '' : head, under, keys.join(' ¦ ')].join(' | '),
      items: items.map(o => ({ gi: o.gi, i: o.i, key: o.key, id: o.el.id || '' })), active: desc(document.activeElement) };
    if (withAudit) s.audit = audit(L, items, busy);
    return s;
  };

  // where to put the mouse to press an item, or what to do first to bring it into view
  eb.prep = (Ls, st) => {
    const L = layerOf(Ls);
    if (!L || L.name !== st.layer) return { found: false, why: 'the top layer is ' + (L ? L.name : 'nothing') + ', not ' + st.layer };
    const items = itemsOf(L), it = find(L, st, items);
    if (!it) return { found: false, why: 'no “' + st.key + '” here' };
    const el = it.el, r = el.getBoundingClientRect();
    if (st.act === 'outside') {
      for (const [fx, fy] of [[.97, .95], [.97, .5], [.03, .95], [.5, .97], [.97, .05], [.03, .05]]) {
        const x = r.left + r.width * fx, y = r.top + r.height * fy;
        if (document.elementFromPoint(x, y) === el) return { found: true, inView: true, hit: true, x, y };
      }
      return { found: true, inView: true, hit: false, by: 'no free spot outside the panel' };
    }
    const x = r.left + r.width / 2, y = r.top + r.height / 2, { c, scroller } = clipOf(el);
    const inView = x > c.l + 1 && x < c.r - 1 && y > c.t + 1 && y < c.b - 1;
    const hit = inView && hits(el, x, y);
    const by = inView && !hit ? desc(document.elementFromPoint(x, y)) : '';
    // the part of it that shows (a tile half off the edge of Home's sliding row)
    const vl = Math.max(r.left, c.l), vr = Math.min(r.right, c.r), vt = Math.max(r.top, c.t), vb = Math.min(r.bottom, c.b);
    let part = null;
    if (vr - vl >= 6 && vb - vt >= 6 && hits(el, (vl + vr) / 2, (vt + vb) / 2)) part = { x: (vl + vr) / 2, y: (vt + vb) / 2 };
    // none of it shows: hover the nearest thing in the same row that does (that slides the row)
    let sib = null;
    if (!inView && !part && !scroller) {
      const same = items.filter(o => o.gi === it.gi), k = same.indexOf(it);
      let best = null;
      same.forEach((o, j) => {
        if (o === it) return;
        const q = o.el.getBoundingClientRect(), l = Math.max(q.left, c.l), rr = Math.min(q.right, c.r), t = Math.max(q.top, c.t), b = Math.min(q.bottom, c.b);
        if (rr - l < 6 || b - t < 6 || !hits(o.el, (l + rr) / 2, (t + b) / 2)) return;
        if (!best || Math.abs(j - k) < Math.abs(best.j - k)) best = { j, x: (l + rr) / 2, y: (t + b) / 2 };
      });
      if (best) sib = { x: best.x, y: best.y };
    }
    // a slider is clicked a quarter of the way along, and must move there
    const slider = el.matches('.slider, [role=slider]') ? { x: r.left + r.width * 0.25, y, val: eb.sliderVal(el) } : null;
    return { found: true, x, y, inView, hit, by, part, scroller, sib, slider };
  };
  eb.sliderVal = el => { const k = el.querySelector('b'); return (k && k.style.left) || el.getAttribute('aria-valuenow') || ''; };
  eb.sliderNow = (Ls, st) => { const L = layerOf(Ls), it = L && find(L, st); return it ? eb.sliderVal(it.el) : null; };

  // for the keyboard: is the item reached yet, and where is the focus now
  eb.kstate = (Ls, st) => {
    const L = layerOf(Ls);
    if (!L || L.name !== st.layer) return { found: false, why: 'the top layer became ' + (L ? L.name : 'nothing') };
    const items = itemsOf(L), it = find(L, st, items);
    if (!it) return { found: false, why: '“' + st.key + '” is gone' };
    const g = L.groups[it.gi], ae = document.activeElement;
    let reached, cur;
    if (g.kb === 'tab') { reached = it.el.classList.contains('on'); cur = items.find(o => o.gi === it.gi && o.el.classList.contains('on')); }
    else if (g.kb === 'tabkey' || g.kb === 'input') { reached = ae === it.el; cur = items.find(o => o.el === ae); }
    else { reached = marked(it.el); cur = items.find(o => /^(nav|pad)$/.test(L.groups[o.gi].kb) && marked(o.el)); }
    const where = L.name + (L.head ? ' “' + first((document.querySelector(L.head) || {}).innerText) + '”' : '');
    return { found: true, where, reached, tgt: pos(it.el), cur: cur ? Object.assign({ key: cur.key }, pos(cur.el)) : null, axis: g.kb === 'tab' ? 'x' : '', cols: L.navOrder === 'cols',
      slider: it.el.classList.contains('slider'), active: desc(ae), typing: !!ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA') };
  };
}
const INPAGE_SRC = '(' + INPAGE.toString() + ')();';
/* A pretend Xbox controller, plugged in only when a test needs it (like h.js in the UI review). */
const PAD_SRC = `(() => {
  const btns = Array.from({ length: 17 }, () => ({ pressed: false, value: 0, touched: false }));
  const pad = { id: 'Fake Xbox Controller (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', axes: [0, 0, 0, 0], buttons: btns, timestamp: 0 };
  let on = false;
  try { Object.defineProperty(navigator, 'getGamepads', { value: () => on ? [pad, null, null, null] : [null, null, null, null], configurable: true }); } catch (e) {}
  window.__fakePad = { connect() { on = true; }, press(i) { btns[i].pressed = true; btns[i].value = 1; }, release(i) { btns[i].pressed = false; btns[i].value = 0; } };
})();`;
const PAD_BTN = { ArrowUp: 12, ArrowDown: 13, ArrowLeft: 14, ArrowRight: 15, A: 0, B: 1 };

/* ---------- driving one fresh page ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function ev(pg, fn, a) { try { return await pg.evaluate(fn, a); } catch (e) { return null; } }
const snap = (pg, t, withAudit) => ev(pg, ([Ls, w]) => window.__eb ? __eb.snap(Ls, w) : null, [t.layers, !!withAudit]);
const seedSrc = v => `(() => { try { if (sessionStorage.getItem('__ebSeeded')) return; sessionStorage.setItem('__ebSeeded', '1');
  ${Object.entries(v.session || {}).map(([k, x]) => `sessionStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(x)});`).join(' ')}
  ${Object.entries(v.local || {}).map(([k, x]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(x)});`).join(' ')} } catch (e) {} })();`;

let browser;
async function newPage(t, vp) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1 });
  const rec = { errs: [], fails: [], ext: [], popups: [], dialogs: [], loads: 0, navTo: '' };
  await ctx.route(/^(https?|wss?):/, r => { rec.ext.push({ url: r.request().url(), nav: r.request().isNavigationRequest() }); r.abort('blockedbyclient').catch(() => {}); });
  await ctx.addInitScript(INPAGE_SRC);
  await ctx.addInitScript(PAD_SRC);
  if (t.variant.session || t.variant.local) await ctx.addInitScript(seedSrc(t.variant));
  const pg = await ctx.newPage();
  pg.on('pageerror', e => rec.errs.push({ t: 'pageerror', msg: e.message, at: (e.stack || '').split('\n').slice(1, 3).map(s => s.trim()).join(' ← '), url: pg.url() }));
  pg.on('console', m => { if (m.type() === 'error') rec.errs.push({ t: 'console', msg: m.text(), at: (m.location() || {}).url || '', line: (m.location() || {}).lineNumber, url: pg.url() }); });
  pg.on('requestfailed', r => rec.fails.push({ url: r.url(), why: (r.failure() || {}).errorText || '' }));
  pg.on('domcontentloaded', () => { rec.loads++; });
  pg.on('framenavigated', f => { if (f === pg.mainFrame()) rec.navTo = f.url(); });
  pg.on('popup', p => { rec.popups.push(p.url()); p.close().catch(() => {}); });
  pg.on('dialog', d => { rec.dialogs.push(d.message()); d.dismiss().catch(() => {}); });
  return { ctx, pg, rec };
}

/* Wait until the page stops changing (and, with busy, until "Starting…"-style text is gone). */
async function settle(pg, t, o = {}) {
  const t0 = Date.now();
  await sleep(o.min == null ? 100 : o.min);
  for (;;) {
    const q = await ev(pg, ([Ls, m]) => window.__eb ? __eb.quiet(Ls, m) : null, [t.layers, 150]);
    const busy = o.busy && q && q.busy;
    if (q && q.idle >= 150 && !q.anim && q.busy !== null && !busy) return q;
    if (Date.now() - t0 > (busy ? 7000 : o.cap || 2500)) return q;
    await sleep(70);
  }
}

async function act(pg, x, y, a) {
  await pg.mouse.move(x, y);
  if (a === 'hover') { await pg.mouse.move(x + 3, y + 1, { steps: 2 }); return { ok: true }; }
  if (a === 'ctx') await pg.mouse.click(x, y, { button: 'right' });
  else if (a === 'dbl') await pg.mouse.dblclick(x, y);
  else await pg.mouse.click(x, y);
  return { ok: true };
}
/* Press with the mouse, scrolling a list with the wheel or sliding Home's row by hovering, as a person would. */
async function mouseAct(pg, t, st) {
  let hovered = 0, wait = 0, moved = false;
  for (let n = 0; n < 40; n++) {
    const p = await ev(pg, ([Ls, s]) => window.__eb ? __eb.prep(Ls, s) : null, [t.layers, st]);
    if (!p) { await sleep(150); if (++wait > 4) return { err: 'the page went away' }; continue; }
    if (!p.found) { if (++wait <= 4) { await sleep(200); continue; } return { err: 'can’t find it: ' + p.why, notFound: true }; }
    if (p.inView && p.hit && !moved) {   // point at it first: hovering can change the layout (a hint appearing), so look again
      moved = true; await pg.mouse.move(p.x, p.y); await sleep(60); continue;
    }
    if (p.inView && p.hit && p.slider && st.act === 'click') {
      await act(pg, p.slider.x, p.slider.y, 'click'); await settle(pg, t, { min: 150 });
      const now = await ev(pg, ([Ls, s]) => __eb.sliderNow(Ls, s), [t.layers, st]);
      return { ok: true, sliderStill: now === p.slider.val ? now : null };
    }
    if (p.inView && p.hit) return act(pg, p.x, p.y, st.act);
    if (p.inView) { if (++wait <= 4) { await sleep(200); continue; } return { err: 'covered by ' + p.by, covered: true }; }
    if (p.scroller) { await pg.mouse.move(p.scroller.x, p.scroller.y); await pg.mouse.wheel(0, p.scroller.dy * p.scroller.step); await sleep(150); continue; }
    if (p.part) { if (hovered >= 2) return act(pg, p.part.x, p.part.y, st.act); hovered++; await pg.mouse.move(p.part.x, p.part.y, { steps: 3 }); await sleep(380); continue; }
    if (p.sib) { await pg.mouse.move(p.sib.x, p.sib.y, { steps: 3 }); await sleep(380); continue; }
    return { err: 'off the screen, and nothing brings it into view', offscreen: true };
  }
  return { err: 'couldn’t bring it into view' };
}

/* Reach an item with the arrow keys: always step toward it; stuck or going round in circles = unreachable. */
const kstate = (pg, t, st) => ev(pg, ([Ls, s]) => window.__eb ? __eb.kstate(Ls, s) : null, [t.layers, st]);
async function kbdReach(pg, t, st, press) {
  press = press || (k => pg.keyboard.press(k));
  const trail = [], seen = {};
  for (let n = 0; n < 80; n++) {
    const s = await kstate(pg, t, st);
    if (!s || !s.found) return { err: s ? s.why : 'the page went away', trail };
    if (s.reached) return { ok: true, trail, slider: s.slider };
    if (!s.cur) return { err: 'nothing is selected to start from', trail, nofocus: s.where };
    seen[s.cur.key] = (seen[s.cur.key] || 0) + 1;
    if (seen[s.cur.key] > 4) return { err: 'the arrows go round in circles near “' + s.cur.key + '”', trail };
    // try the direction toward it first; keep a move that gets closer along its own axis, undo one that doesn't and try another
    const dx = s.tgt.x - s.cur.x, dy = s.tgt.y - s.cur.y;
    // (measured again after the move: a list that scrolls moves the target too)
    const closer = (k, a) => /Up|Down/.test(k) ? Math.abs(a.tgt.y - a.cur.y) < Math.abs(dy) - 1 : Math.abs(a.tgt.x - a.cur.x) < Math.abs(dx) - 1;
    const H = dx > 0 ? 'ArrowRight' : 'ArrowLeft', V = dy > 0 ? 'ArrowDown' : 'ArrowUp';
    const BACK = { ArrowRight: 'ArrowLeft', ArrowLeft: 'ArrowRight', ArrowUp: 'ArrowDown', ArrowDown: 'ArrowUp' };
    // like a person with a controller: get onto the right row first, then go along it (Files: the right column first)
    const vFirst = s.cols ? Math.abs(dx) < 4 : Math.abs(dy) > Math.max(s.cur.h, s.tgt.h) / 2;
    const main = s.axis === 'x' ? [H] : vFirst ? [V, H] : [H, V];
    const order = s.axis === 'x' ? main : main.concat([BACK[H], BACK[V]].filter(k => !main.includes(k)));
    let moved = false, fallback = null;
    for (const k of order) {
      await press(k); trail.push(k);
      await settle(pg, t, { min: 60, cap: 1500, busy: true });
      const a = await kstate(pg, t, st);
      if (!a || !a.found) return { err: a ? a.why : 'the page went away', trail };
      if (a.reached) return { ok: true, trail, slider: a.slider };
      const changed = a.cur && (a.cur.key !== s.cur.key || Math.abs(a.cur.x - s.cur.x) + Math.abs(a.cur.y - s.cur.y) > 2);
      if (!changed) continue;
      if (closer(k, a) || s.axis === 'x') { moved = true; break; }
      fallback = fallback || k;
      await press(BACK[k]); trail.push(BACK[k]);   // further away: undo it
      await settle(pg, t, { min: 60, cap: 1500, busy: true });
      const b = await kstate(pg, t, st);
      if (!b || !b.found || !b.cur || b.cur.key !== s.cur.key) { moved = true; break; }   // (couldn't undo: carry on from here)
    }
    if (!moved && fallback) { await press(fallback); trail.push(fallback); await settle(pg, t, { min: 60, cap: 1500, busy: true }); moved = true; }   // nothing gets closer: go round
    if (!moved) return { err: 'the arrows stop at “' + s.cur.key + '”', trail };
  }
  return { err: 'too many steps', trail };
}
async function kbdAct(pg, t, st) {
  const L = t.layers.find(l => l.name === st.layer), g = L.groups[st.gi];
  if (st.act === 'hover') return { skip: 'the mouse only hovers it' };
  if (st.act === 'outside') { await pg.keyboard.press('Escape'); return { ok: true, how: 'Escape' }; }
  let kb = g.kb;
  if (kb === 'hint') { if (!HINT_KEYS[st.id]) return { skip: 'no key for #' + st.id }; kb = { key: HINT_KEYS[st.id] }; }
  if (kb && kb.key) {
    if (kb.key.length === 1) { const s = await kstate(pg, t, st); if (s && s.typing) return { skip: 'a text box has focus, so “' + kb.key + '” is typed into it' }; }
    await pg.keyboard.press(kb.key); return { ok: true, how: kb.key };
  }
  if (kb === 'none') return { skip: 'mouse only' };
  if (kb === 'pad') {
    await ev(pg, () => window.__fakePad && __fakePad.connect()); await sleep(250);
    const btn = async k => { const i = PAD_BTN[k]; await ev(pg, j => __fakePad.press(j), i); await sleep(70); await ev(pg, j => __fakePad.release(j), i); await sleep(60); };
    const r = await kbdReach(pg, t, st, btn);
    if (!r.ok) return { err: r.err + ' (controller)', trail: r.trail, unreachable: true, nofocus: r.nofocus };
    await btn('A');
    return { ok: true, pad: true, how: 'controller: ' + r.trail.map(k => k.replace('Arrow', '')).concat('A').join(' ') };
  }
  if (kb === 'tabkey') {
    for (let n = 0; n < 16; n++) {
      const s = await kstate(pg, t, st);
      if (s && s.reached) { if (s.typing) return { ok: true, how: 'Tab ×' + n }; await pg.keyboard.press('Enter'); return { ok: true, how: 'Tab ×' + n + ' Enter' }; }   // (a text box: reaching it is pressing it)
      await pg.keyboard.press('Tab'); await sleep(40);
    }
    return { err: 'Tab never gets to it', unreachable: true };
  }
  if (kb === 'input') {
    for (let n = 0; n < 4; n++) {
      const s = await kstate(pg, t, st);
      if (s && s.reached) return { ok: true, how: n ? 'Tab ×' + n : 'has focus' };
      if (!s || !s.typing) return { err: 'not focused (focus is on ' + (s ? s.active : '?') + ')', unreachable: true };
      await pg.keyboard.press('Tab'); await sleep(60);
    }
    return { err: 'Tab never gets to it', unreachable: true };
  }
  const selectMode = !!(L.selectMode && await ev(pg, x => { try { return !!Function('return (' + x + ')')(); } catch (e) { return false; } }, L.selectMode));
  const r = await kbdReach(pg, t, st);
  if (!r.ok) return { err: r.err, trail: r.trail, unreachable: true, nofocus: r.nofocus };
  if (kb === 'tab') return { ok: true, how: r.trail.join(' ') || '(already on it)' };
  const key = st.act === 'ctx' ? 'ContextMenu' : r.slider ? 'ArrowRight' : 'Enter';
  await pg.keyboard.press(key);
  return { ok: true, selectMode, how: r.trail.concat(key).join(' ') };
}

/* After a press: wait, watch busy text for 5 s without change, then take the checks. */
async function observe(pg, t, rec, loads0) {
  const navd = () => rec.loads > loads0 || rec.ext.some(e => e.nav);
  const nav = async () => { await pg.waitForLoadState('load', { timeout: 5000 }).catch(() => {}); await sleep(500); const ex = rec.ext.find(e => e.nav); return { nav: ex ? ex.url : (rec.navTo || pg.url()) }; };
  await settle(pg, t);
  if (navd()) return nav();
  let s = await snap(pg, t, true), stuck = null;
  if (s && s.busy) {
    const t0 = Date.now(); let last = s.text, since = Date.now();
    while (s && s.busy && Date.now() - t0 < 9000) {
      await sleep(250);
      if (navd()) return nav();
      const n = await snap(pg, t, false); if (!n) break;
      if (n.text !== last) { last = n.text; since = Date.now(); }
      s = n;
      if (Date.now() - since >= 5000) { stuck = { busy: s.busy, layer: s.layer, head: s.head, text: s.text.replace(/\s+/g, ' ').slice(0, 160) }; break; }
    }
    await settle(pg, t);
    if (navd()) return nav();
    s = await snap(pg, t, true);
  }
  await sleep(200);   // errors that come a moment later
  if (navd()) return nav();
  return { s, stuck };
}

async function runJob(t, vp, job) {
  const { ctx, pg, rec } = await newPage(t, vp);
  const res = { via: job.via, path: job.path, errs: [], replayErrs: [] };
  const t0 = Date.now();
  try {
    await pg.goto(t.url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await settle(pg, t, { busy: true });
    const pre = job.via === 'mouse' || job.via === 'kbd' ? job.path.length - 1 : job.path.length;
    for (let k = 0; k < pre && !res.replayFail; k++) {
      const loads = rec.loads, r = await mouseAct(pg, t, job.path[k]);
      if (r.err) res.replayFail = { at: k, err: r.err };
      else { await settle(pg, t, { busy: true }); if (rec.loads > loads) res.replayFail = { at: k, err: 'it went to ' + pg.url() }; }
    }
    res.replayErrs = rec.errs.splice(0);
    if (res.replayFail) return res;
    const loads0 = rec.loads;
    if (job.via === 'root') res.o = await observe(pg, t, rec, loads0);
    else if (job.via === 'esc') {
      const b = await snap(pg, t, false);
      res.before = b && { layer: b.layer, head: b.head, sig: b.sig, modal: b.modal };
      await pg.keyboard.press('Escape');
      res.o = await observe(pg, t, rec, loads0);
    } else {
      const st = job.path[job.path.length - 1];
      res.act = job.via === 'mouse' ? await mouseAct(pg, t, st) : await kbdAct(pg, t, st);
      if (!res.act.err && !res.act.skip) res.o = await observe(pg, t, rec, loads0);
    }
  } catch (e) {
    res.crash = String(e && e.message || e).split('\n')[0];
  } finally {
    res.errs = rec.errs.splice(0);
    Object.assign(res, { fails: rec.fails, ext: rec.ext, popups: rec.popups, dialogs: rec.dialogs, ms: Date.now() - t0 });
    await ctx.close().catch(() => {});
  }
  return res;
}

/* ---------- findings ---------- */
const FIND = new Map();
const NOISE = { mockFiles: 0 };
const KIND = {
  'page-error': [1, 'Script error'], rejection: [1, 'Unhandled promise rejection'], 'console-error': [1, 'Console error'], 'missing-file': [1, 'Missing file'], dialog: [1, 'Dialog box'],
  stuck: [2, 'Busy text that never changes'], 'zero-rows': [2, 'Panel with no rows'], 'esc-no-close': [2, 'Escape doesn’t close it'], 'focus-lost': [2, 'Focus marker lost'],
  unclickable: [3, 'Can’t be clicked'], 'no-effect': [3, 'A click does nothing'], covered: [3, 'Covered by something else'], 'kbd-unreachable': [3, 'Keyboard can’t reach it'], 'kbd-differs': [3, 'Enter does something else than a click'],
  'panel-cut': [4, 'Panel bigger than the screen'], overflow: [4, 'Text doesn’t fit its row'], 'no-label': [4, 'No label'],
  replay: [9, 'Harness: couldn’t repeat the clicks'], harness: [9, 'Harness'],
};
const pageOf = u => { const m = String(u || '').match(/\/ui\/([\w.-]+\.html)/); return m ? m[1] : String(u || '').split('/').pop(); };
function add(kind, W, job, what, key, extra) {
  const k = [kind, W.t.file, key || what].join(' · ');
  let f = FIND.get(k);
  if (!f) FIND.set(k, f = { kind, page: W.t.file, what, where: [], count: 0, extra });
  f.count++;
  const w = { target: W.t.label, vp: W.vpName, via: job.via, path: job.path.map(p => p.d) };
  if (!f.where.length || (w.path.length < f.where[0].path.length && f.where.length < 2)) f.where.unshift(w); else if (f.where.length < 3 && !f.where.some(x => x.target === w.target && x.vp === w.vp)) f.where.push(w);
}
const mockPath = u => /^file:\/\/\/(home\/player|media\/player)\//.test(u) || /^(https?|wss?):/.test(u) || /^chrome-error:/.test(u) || u.startsWith('file://' + os.tmpdir());
function addErr(W, job, e, during) {
  if (/Failed to load resource/.test(e.msg)) {
    const u = e.at || '';
    if (mockPath(u)) { NOISE.mockFiles++; return; }
    add('missing-file', W, job, (u || e.msg) + (during ? ' (' + during + ')' : ''), 'file ' + u);
    return;
  }
  const kind = /^UNHANDLED REJECTION/.test(e.msg) ? 'rejection' : e.t === 'pageerror' ? 'page-error' : 'console-error';
  add(kind, W, job, e.msg.split('\n')[0].slice(0, 200) + ' — in ' + pageOf(e.url) + (e.at ? ' at ' + String(e.at).replace(/file:\/\/[^ ]*\/ui\//g, '') : '') + (during ? ' (' + during + ')' : ''), kind + ' ' + e.msg.split('\n')[0]);
}
const outcome = o => !o ? 'nothing' : o.nav ? 'went to ' + String(o.nav).replace(/^file:\/\/.*\/ui\//, '') : o.s ? o.s.sig : 'nothing';
const short = o => !o ? 'nothing' : o.nav ? 'went to ' + String(o.nav).replace(/^file:\/\/.*\/ui\//, '') : o.s ? `${o.s.layer}${o.s.head ? ' “' + o.s.head + '”' : ''}${o.s.under ? ' (' + o.s.under + ')' : ''}` : 'nothing';

function record(W, job, r) {
  const st = W.stats;
  if (r.crash) add('harness', W, job, 'crashed: ' + r.crash, 'crash ' + r.crash);
  for (const e of r.replayErrs) addErr(W, Object.assign({}, job, { path: job.path.slice(0, r.replayFail ? r.replayFail.at + 1 : job.via === 'mouse' || job.via === 'kbd' ? job.path.length - 1 : job.path.length) }), e, 'while getting there');
  if (r.replayFail) { st.replayFail++; add('replay', W, job, `step ${r.replayFail.at + 1} (${job.path[r.replayFail.at].d}): ${r.replayFail.err}`); return; }
  for (const e of r.errs) addErr(W, job, e);
  for (const f of r.fails) if (!mockPath(f.url) && /^file:/.test(f.url) && /FILE_NOT_FOUND/.test(f.why)) add('missing-file', W, job, f.url.replace(/^file:\/\/.*\/src\//, 'src/') + ' (' + f.why + ')', 'file ' + f.url);
  for (const d of r.dialogs) add('dialog', W, job, 'a dialog box: ' + d);
  if (job.via === 'mouse') st.mouse++; else if (job.via === 'kbd') st.kbd++; else if (job.via === 'esc') st.esc++;
  if (r.act && r.act.skip) { st.kbdSkipped++; return; }
  if (r.act && r.act.sliderStill != null) add('no-effect', W, job, `${job.path[job.path.length - 1].d}: clicking a quarter of the way along leaves it at ${r.act.sliderStill}`, 'slider ' + job.path[job.path.length - 1].key);
  if (r.act && r.act.err) {
    if (job.via === 'mouse') add(r.act.covered ? 'covered' : 'unclickable', W, job, `${job.path[job.path.length - 1].d}: ${r.act.err}`);
    else if (r.act.nofocus) add('focus-lost', W, job, `${r.act.nofocus}: nothing is highlighted, so the arrow keys have nowhere to start (wanted ${job.path[job.path.length - 1].d})`, 'nofocus ' + r.act.nofocus);
    else add('kbd-unreachable', W, job, `${job.path[job.path.length - 1].d}: ${r.act.err}${r.act.trail && r.act.trail.length ? ' (after ' + r.act.trail.join(' ') + ')' : ''}`);
    return;
  }
  const o = r.o; if (!o) return;
  if (o.nav) st.nav++;
  if (o.stuck) add('stuck', W, job, `“${o.stuck.busy}” on ${o.stuck.layer}${o.stuck.head ? ' “' + o.stuck.head + '”' : ''} didn’t change for 5 s: ${o.stuck.text}`, 'stuck ' + o.stuck.layer + o.stuck.head);
  const s = o.s, a = s && s.audit;
  if (a) {
    const at = s.layer + (s.head ? ' “' + s.head + '”' : '');
    for (const x of a.overflow) add('overflow', W, job, `${at}: “${x.text}” in ${x.key === x.text ? 'its row' : '“' + x.key + '”'} is ${x.how} (${x.el}, ${x.sw}px of text in ${x.cw}px)`, 'ov ' + x.key + x.el + x.text);
    const nl = {};
    for (const x of a.nolabel) (nl[x.g + '|' + x.el + '|' + x.why] = nl[x.g + '|' + x.el + '|' + x.why] || []).push(x.key);
    for (const [k, keys] of Object.entries(nl)) { const [g, el, why] = k.split('|'); add('no-label', W, job, `${s.layer}: ${keys.length} ${g}${keys.length > 1 ? 's' : ''} (${el}): ${why} — ${keys.slice(0, 6).join(', ')}${keys.length > 6 ? '…' : ''}`, 'nl ' + s.layer + g + el + why); }
    for (const x of a.covered) add('covered', W, job, `${at}: “${x.key}” is under ${x.by}`, 'cov ' + x.key + x.by);
    if (a.cut) add('panel-cut', W, job, `${at}: ${a.cut}`, 'cut ' + at);
    if (a.zero && !o.stuck) add('zero-rows', W, job, `${at} has no rows to pick`, 'zero ' + at);
    if (a.focus) add('focus-lost', W, job, `${at}: ${a.focus}`, 'focus ' + at + a.focus);
    for (const k of a.iconOnly) W.iconOnly.add(k);
  }
  if (job.via === 'esc' && r.before && r.before.modal && s && s.sig === r.before.sig)
    add('esc-no-close', W, job, `Escape leaves ${r.before.layer}${r.before.head ? ' “' + r.before.head + '”' : ''} open`, 'esc ' + r.before.layer + r.before.head);
}

/* ---------- the walk ---------- */
function stepOf(L, g, o, a) {
  const verb = a === 'ctx' ? 'right-click ' : a === 'dbl' ? 'double-click ' : a === 'hover' ? 'hover ' : '';
  return { layer: L.name, gi: o.gi, key: o.key, id: o.id, act: a, d: a === 'outside' ? 'click outside the ' + L.name : verb + (g.name || 'item') + ' “' + o.key + '”' };
}
function itemsToPress(W, s) {
  const L = W.t.layers.find(l => l.name === s.layer), out = [];
  if (!L) return out;
  L.groups.forEach((g, gi) => {
    const all = s.items.filter(o => o.gi === gi);
    let keep = all;
    if (g.max && all.length > g.max) {
      const pref = g.prefer ? new RegExp(g.prefer) : null;
      const set = new Set([...all.slice(0, Math.max(1, g.max - 2)), ...all.slice(-Math.min(2, g.max - 1)), ...(pref ? all.filter(o => pref.test(o.key)) : [])]);
      keep = all.filter(o => set.has(o));
      W.stats.sampledOut += all.length - keep.length;
    }
    keep.forEach((o, j) => {
      out.push(stepOf(L, g, o, g.act || 'click'));
      if (g.ctx && (g.ctxPick ? new RegExp(g.ctxPick).test(o.key) : !g.ctxMax || j < g.ctxMax - 1 || j === keep.length - 1)) out.push(stepOf(L, g, o, 'ctx'));
    });
  });
  return out;
}
const pathKey = p => p.map(x => [x.layer, x.gi, x.key, x.act].join(':')).join(' > ');

async function walk(t, vp, kbdOn, budget) {
  const W = { t, vp, vpName: vp.width + 'x' + vp.height, visited: new Map(), states: [], iconOnly: new Set(),
    stats: { mouse: 0, kbd: 0, esc: 0, nav: 0, replayFail: 0, kbdSkipped: 0, sampledOut: 0, states: 0, capped: 0, ms: 0 } };
  const depth = OPT.depth || t.depth, stack = [], mouseOut = new Map(), cap = OPT.cap || (kbdOn ? t.cap : Math.ceil(t.cap / 2));
  let spent = 0;
  const t0 = Date.now();
  const expand = (s, pth) => {
    if (!s || !s.layer || W.visited.has(s.sig)) return;
    W.visited.set(s.sig, pth); W.stats.states++;
    W.states.push({ layer: s.layer, head: s.head, under: s.under, items: s.items.length, path: pth.map(p => p.d) });
    const jobs = [];
    if (kbdOn) jobs.push({ via: 'esc', path: pth });
    if (pth.length < depth) for (const st of itemsToPress(W, s)) jobs.push({ via: 'mouse', path: pth.concat([st]) });
    else W.stats.capped++;
    for (let k = jobs.length - 1; k >= 0; k--) stack.push(jobs[k]);
  };
  const done = (job, r) => {
    record(W, job, r);
    if (OPT.verbose) console.log(`  ${job.via.padEnd(5)} ${(r.ms + 'ms').padStart(7)} ${job.path.map(p => p.d).join(' › ') || '(load)'} → ${r.replayFail ? 'REPLAY FAILED: ' + r.replayFail.err : r.act && (r.act.err || r.act.skip) ? (r.act.err || r.act.skip) + (r.act.trail && r.act.trail.length ? ' [' + r.act.trail.join(' ') + ']' : '') : short(r.o)}`);
    if (r.replayFail || r.crash) return;
    if (job.via === 'root') { expand(r.o && r.o.s, []); return; }
    if (job.via === 'mouse' && r.act && r.act.ok) {
      mouseOut.set(pathKey(job.path), r.o);
      if (r.o && !r.o.nav) expand(r.o.s, job.path);
      if (kbdOn) stack.push({ via: 'kbd', path: job.path });
    }
    if (job.via === 'kbd' && r.act && r.act.ok && r.o) {
      const m = mouseOut.get(pathKey(job.path));
      const meant = (r.act.pad && r.o.s && r.o.s.layer === 'on-screen keyboard') || r.act.selectMode;
      if (m && !meant && outcome(m) !== outcome(r.o)) add('kbd-differs', W, job, `${job.path[job.path.length - 1].d}: a click → ${short(m)}; the keyboard (${r.act.how}) → ${short(r.o)}`, 'kd ' + pathKey(job.path));
    }
  };
  done({ via: 'root', path: [] }, await runJob(t, vp, { via: 'root', path: [] }));
  let inflight = 0;
  await new Promise(resolve => {
    const kick = () => {
      while (inflight < OPT.workers && stack.length && budget.left > 0 && spent < cap && !STOP.now) {
        const job = stack.pop(); inflight++; budget.left--; spent++;
        runJob(t, vp, job).then(r => done(job, r), e => done(job, { via: job.via, path: job.path, errs: [], replayErrs: [], fails: [], dialogs: [], crash: String(e && e.message || e) }))
          .finally(() => { inflight--; kick(); });
      }
      if (!inflight && (!stack.length || budget.left <= 0 || spent >= cap || STOP.now)) { W.stats.unpressed = stack.length; resolve(); }
    };
    kick();
  });
  W.stats.ms = Date.now() - t0;
  return W;
}

/* ---------- main ---------- */
const STOP = { now: false };
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { if (STOP.now) process.exit(130); STOP.now = true; console.log(`\n(${sig}: finishing the presses under way, then reporting)`); });
(async () => {
  browser = await chromium.launch({ args: ['--allow-file-access-from-files', '--autoplay-policy=no-user-gesture-required'] });   // like launch.py's WebKit settings
  const targets = [];
  for (const p of PAGES) for (const v of p.variants) {
    const label = p.file + (v.q || '') + (v.name && v.name !== 'plain' && !v.q ? ' (' + v.name + ')' : '');
    if (OPT.pages.length && !OPT.pages.some(x => label.includes(x))) continue;
    targets.push(Object.assign({}, p, { variant: v, label, url: 'file://' + UI + '/' + p.file + (v.q || '') }));
  }
  const budget = { left: OPT.max };
  const walks = [];
  const T0 = Date.now();
  for (const [vi, vp] of OPT.vps.entries()) {
    for (const t of targets) {
      if (budget.left <= 0 || STOP.now) break;
      const kbdOn = OPT.kbd && (vi === 0 || OPT.kbdAll);
      process.stdout.write(`${t.label} @ ${vp.width}x${vp.height}${kbdOn ? '' : ' (mouse only)'} … `);
      const W = await walk(t, vp, kbdOn, budget);
      walks.push(W);
      const s = W.stats;
      console.log(`${s.states} screens, ${s.mouse} clicks, ${s.kbd} keyboard presses, ${s.esc} Escapes, ${s.nav} went to another page` +
        (s.replayFail ? `, ${s.replayFail} couldn’t be repeated` : '') + (s.capped ? `, ${s.capped} screens at the depth cap` : '') +
        (s.unpressed ? `, ${s.unpressed} left (budget)` : '') + ` (${Math.round(s.ms / 1000)} s)`);
    }
  }
  await browser.close();

  /* report */
  const tot = walks.reduce((a, W) => { for (const k of ['mouse', 'kbd', 'esc', 'states', 'nav', 'replayFail', 'sampledOut', 'kbdSkipped']) a[k] = (a[k] || 0) + W.stats[k]; return a; }, {});
  console.log(`\n== ${tot.mouse + tot.kbd + tot.esc} presses: ${tot.mouse} clicks, ${tot.kbd} keyboard, ${tot.esc} Escape; ${tot.states} screens; ${tot.nav} went to another page; ` +
    `${tot.sampledOut} look-alike items skipped; ${tot.kbdSkipped} mouse-only; ${Math.round((Date.now() - T0) / 60000)} min ==`);
  const byPage = {};
  for (const W of walks) { const b = byPage[W.t.file] = byPage[W.t.file] || { mouse: 0, kbd: 0, esc: 0 }; b.mouse += W.stats.mouse; b.kbd += W.stats.kbd; b.esc += W.stats.esc; }
  for (const [p, b] of Object.entries(byPage)) console.log(`  ${p.padEnd(14)} ${String(b.mouse + b.kbd + b.esc).padStart(5)}  (${b.mouse} clicks, ${b.kbd} keyboard, ${b.esc} Escape)`);
  const list = [...FIND.values()].sort((a, b) => KIND[a.kind][0] - KIND[b.kind][0] || a.kind.localeCompare(b.kind) || b.count - a.count);
  const real = list.filter(f => KIND[f.kind][0] < 9);
  console.log(`\n== ${real.length} problems${list.length - real.length ? ` (+${list.length - real.length} harness notes)` : ''} ==`);
  let lastKind = '';
  for (const f of list) {
    if (f.kind !== lastKind) { console.log(`\n-- ${KIND[f.kind][1]} --`); lastKind = f.kind; }
    const w = f.where[0];
    console.log(`[${f.page}] ${f.what}${f.count > 1 ? `  (×${f.count})` : ''}\n    ${w.target} @ ${w.vp}, ${w.via}: ${w.path.join(' › ') || '(just loading the page)'}`);
  }
  if (NOISE.mockFiles) console.log(`\n(${NOISE.mockFiles} loads of the mocks’ pretend files, like /home/player/…, failed as expected and were ignored.)`);
  const icon = new Set(); walks.forEach(W => W.iconOnly.forEach(k => icon.add(W.t.file + ': ' + k)));
  fs.writeFileSync(OPT.out, JSON.stringify({ when: new Date().toISOString(), options: OPT, totals: tot, byPage,
    walks: walks.map(W => ({ target: W.t.label, vp: W.vpName, stats: W.stats, states: W.states })), iconOnly: [...icon], findings: list }, null, 1));
  console.log(`\nDetails: ${OPT.out}`);
  process.exit(real.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
