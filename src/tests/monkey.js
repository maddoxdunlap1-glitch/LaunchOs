const { chromium } = require('/opt/npm-tools/node_modules/playwright');
const U = process.argv[2], N = +(process.argv[3] || 500), seed0 = +(process.argv[4] || 1);
let seed = seed0; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const pick = a => a[Math.floor(rnd() * a.length)];
const KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowDown', 'ArrowRight', 'Enter', 'Enter', 'Escape', 'm', 'b', ' ', 'ContextMenu', 'Shift+F10', 'F2', 'Delete', 'Control+c', 'Control+v', 'Control+x', 'Control+a', 'Backspace', 'Home', 'End', 'PageDown', 'Tab', 'x', 'Meta', 'F5', 'Control+Shift+N'];
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 720 } });
  const pg = await ctx.newPage();
  ctx.on('page', p => { if (p !== pg) p.close().catch(() => {}); });
  const errs = [], visits = {};
  pg.on('pageerror', e => errs.push(pg.url().split('/').pop() + ': ' + e.message + ' ' + (e.stack || '').split('\n')[1]));
  pg.on('dialog', d => d.dismiss());
  for (const page of ['store.html', 'files.html', 'index.html', 'setup.html', 'monitor.html', 'view.html', 'start.html']) {
    await pg.goto('file://' + U + '/' + page); await pg.waitForTimeout(600);
    for (let i = 0; i < N; i++) {
      const r = rnd();
      try {
        if (r < 0.62) await pg.keyboard.press(pick(KEYS));
        else if (r < 0.8) await pg.mouse.click(rnd() * 1280, rnd() * 720, { modifiers: rnd() < 0.15 ? ['Control'] : rnd() < 0.1 ? ['Shift'] : [] });
        else if (r < 0.86) await pg.mouse.click(rnd() * 1280, rnd() * 720, { button: 'right' });
        else if (r < 0.9) await pg.mouse.dblclick(rnd() * 1280, rnd() * 720);
        else if (r < 0.95) { await pg.mouse.move(rnd() * 1280, rnd() * 720); await pg.mouse.wheel(0, (rnd() - 0.5) * 800); }
        else await pg.keyboard.type(pick(['hello', 'a/b', '.x', 'New', 'GAMES', '<>?']));
      } catch (e) { /* page navigating */ }
      await pg.waitForTimeout(rnd() < 0.1 ? 400 : 25);
      const cur = pg.url().split('/').pop().split('#')[0];
      visits[cur] = (visits[cur] || 0) + 1;
      if (!cur.endsWith('.html') && !cur.startsWith('view')) { await pg.goto('file://' + U + '/' + page).catch(() => {}); }
      if (rnd() < 0.02 && cur !== page) { await pg.goto('file://' + U + '/' + page).catch(() => {}); await pg.waitForTimeout(300); }
    }
  }
  console.log('visits', JSON.stringify(visits));
  console.log('ERRORS', errs.length); [...new Set(errs)].slice(0, 30).forEach(e => console.log('  ' + e));
  await b.close();
})();
