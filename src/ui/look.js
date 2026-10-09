/* LaunchOS look: the saved colors, background and screen size, applied before a page is first
   drawn. Loaded in each page's <head>, so moving between pages never shows a frame of plain blue
   or a screen laid out at the wrong size: the new page starts with the same background picture
   and its content shows once it's ready (los.js: LOS.holdReady / LOS.ready). */
(function () {
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
  const DEFAULTS = { name: 'Player 1', avatar: '#e0793a', accent: 'green', size: 'fill', pattern: true, timezone: '', setupDone: false, apps: [], order: [],
    wall: '', theme: 'midnight', proOn: false };
  // darker at the top and bottom, so the clock, names and buttons stay easy to read (as #wall::after)
  const SHADE = 'linear-gradient(180deg, rgba(3, 7, 13, .5), rgba(3, 7, 13, .08) 20%, rgba(3, 7, 13, 0) 42%, rgba(3, 7, 13, .2) 62%, rgba(3, 7, 13, .62))';

  function loadPrefs() {
    let p;
    try { p = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem('launchos.prefs') || '{}')); }
    catch (e) { p = Object.assign({}, DEFAULTS); }
    if (!p.wall) p.wall = p.pattern === false ? 'plain' : 'liftoff';   // (before 1.0 there was only the line pattern, on or off)
    return p;
  }
  // which wallpaper is shown: { id, still, live } (a live one only with Pro; its still picture otherwise)
  function wallOf(p, pro) {
    let id = p.wall;
    const live = LIVE.find(x => x.id === id);
    if (live && !pro) id = live.still;
    if (!live && !WALLS.some(x => x.id === id)) id = 'liftoff';
    const still = live && pro ? live.still : id;
    return { still, live: live && pro ? live.live : '' };
  }
  function scaleOf(p) { return Math.min(innerWidth / 1280, innerHeight / 720) * (SIZES[p.size] || 1); }
  // colors, background picture and scale as CSS variables on the page (los.css uses them)
  function paint(p, pro) {
    const r = document.documentElement.style;
    const a = ACCENTS[p.accent] || ACCENTS.green;
    r.setProperty('--accent', a[0]); r.setProperty('--accent-glow', a[1]); r.setProperty('--accent-ink', a[2]);
    const th = (p.theme !== 'midnight' && pro && THEMES[p.theme]) || THEMES.midnight;
    th[1].split(' ').forEach((c, i) => r.setProperty(THEME_VARS[i], c));
    const w = wallOf(p, pro), pic = w.still !== 'contour' && w.still !== 'plain';
    r.setProperty('--wallimg', pic ? `url("walls/${w.still}.webp")` : 'none');
    r.setProperty('--wallshade', pic ? SHADE : 'none');
    r.setProperty('--fit', String(scaleOf(p)));
  }
  window.LOSLOOK = { ACCENTS, SIZES, SIZE_NAMES, WALLS, LIVE, THEMES, THEME_VARS, DEFAULTS, loadPrefs, wallOf, scaleOf, paint };
  const p = loadPrefs();
  paint(p, !!p.proOn);
})();
