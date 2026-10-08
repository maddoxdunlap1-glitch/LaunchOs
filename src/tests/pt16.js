const { chromium } = require('/opt/npm-tools/node_modules/playwright');
const U = process.argv[2];
(async () => {
  const b = await chromium.launch(); const pg = await b.newPage({ viewport: { width: 1280, height: 720 } });
  const errs = []; pg.on('pageerror', e => errs.push(e.message)); pg.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  const shot = n => pg.screenshot({ path: 'shots/fl-' + n + '.png' });
  const st = () => pg.evaluate(() => ({ mode, focus, si, li, path: cur && cur.path, n: entries.length, sel: [...sel], clip: clip && clip.paths.length, panel: document.querySelector('#panel').classList.contains('on') && document.querySelector('#ph').textContent }));
  const k = async (key, n) => { for (let i = 0; i < (n || 1); i++) { await pg.keyboard.press(key); await pg.waitForTimeout(120); } await pg.waitForTimeout(250); };
  await pg.goto('file://' + U + '/files.html'); await pg.waitForTimeout(900);
  console.log('start', JSON.stringify(await st())); await shot(1);
  await k('Enter'); console.log('open Downloads', JSON.stringify(await st())); await shot(2);
  await k('ArrowDown', 2); await k('Escape'); console.log('Esc at root -> side', JSON.stringify(await st()));
  await k('ArrowRight'); console.log('right -> list', JSON.stringify(await st()));
  await k('Home'); await k('Enter'); console.log('enter folder', JSON.stringify(await st()));
  await k('Backspace'); console.log('up', JSON.stringify(await st()));
  // copy notes.txt and photo.jpg to USB
  await pg.evaluate(() => { li = entries.findIndex(e => e.name === 'notes.txt'); showRow(); });
  await k(' '); await pg.evaluate(() => { li = entries.findIndex(e => e.name === 'photo.jpg'); showRow(); }); await k(' ');
  console.log('selected', JSON.stringify(await st())); await shot(3);
  await k('Control+c'); console.log('clip', JSON.stringify(await st()));
  await k('ArrowLeft'); await k('ArrowDown', 5); console.log('side on USB', JSON.stringify(await st()));
  await k('Enter'); await k('Control+v'); await pg.waitForTimeout(300); await shot(4);
  console.log('paste running', JSON.stringify(await st()));
  await pg.waitForTimeout(1800); console.log('after paste', JSON.stringify(await st()), await pg.evaluate(() => entries.map(e => e.name).join('|'))); await shot(5);
  // options panel via X (ContextMenu)
  await k('ContextMenu'); console.log('options', JSON.stringify(await st()), await pg.evaluate(() => P.rows.map(r => r.t).join('|'))); await shot(6);
  await k('Escape');
  // rename
  await pg.evaluate(() => { li = entries.findIndex(e => e.name === 'notes.txt'); showRow(); });
  await k('F2'); await pg.keyboard.press('Control+a'); await pg.keyboard.type('readme.txt'); await shot(7); await k('Enter');
  console.log('renamed', JSON.stringify(await st()), await pg.evaluate(() => entries.map(e => e.name).join('|')));
  // rename with slash -> error stays in panel
  await k('F2'); await pg.keyboard.press('Control+a'); await pg.keyboard.type('a/b'); await k('Enter');
  console.log('bad rename', JSON.stringify(await st()), await pg.evaluate(() => document.querySelector('#pp').textContent)); await k('Escape');
  // new folder
  await k('Control+Shift+N'); await k('Enter'); console.log('new folder', JSON.stringify(await st()));
  // delete
  await pg.evaluate(() => { li = entries.findIndex(e => e.name === 'readme.txt'); showRow(); });
  await k('Delete'); console.log('delete confirm default', JSON.stringify(await st()), await pg.evaluate(() => P.rows[P.i].t)); await shot(8);
  await k('ArrowDown'); await k('Enter'); await pg.waitForTimeout(1600); console.log('deleted', await pg.evaluate(() => entries.map(e => e.name).join('|')));
  // drive options on internal NTFS: open (mount)
  await k('ArrowLeft'); await pg.evaluate(() => { si = sideRows.findIndex(r => r.kind === 'drive' && r.d.name === 'Windows'); paintSide(); }); await k('Enter');
  await pg.waitForTimeout(500); console.log('mounted windows', JSON.stringify(await st()));
  // empty drive -> format flow
  await k('ArrowLeft'); await pg.evaluate(() => { si = sideRows.findIndex(r => r.kind === 'drive' && r.d.empty); paintSide(); }); await k('Enter');
  console.log('empty drive opts', JSON.stringify(await st()), await pg.evaluate(() => P.rows.map(r => r.t).join('|'))); await shot(9);
  await pg.evaluate(() => { P.i = P.rows.findIndex(r => r.t.startsWith('Format')); rp(); }); await k('Enter'); await shot(10);
  await k('Enter'); /* exFAT */ await pg.keyboard.press('Control+a'); await pg.keyboard.type('GAMES'); await k('Enter');
  console.log('confirm1', JSON.stringify(await st()), await pg.evaluate(() => P.rows[P.i].t)); await shot(11);
  await k('ArrowDown'); await k('Enter'); console.log('confirm2', JSON.stringify(await st()), await pg.evaluate(() => P.rows[P.i].t));
  await k('ArrowDown'); await k('Enter'); await pg.waitForTimeout(1800);
  console.log('formatted', JSON.stringify(await st()), await pg.evaluate(() => drives.map(d => d.name + ':' + d.fs + ':' + (d.mount || '-')).join('|'))); await shot(12);
  // eject USB while viewing it
  await pg.evaluate(() => { si = sideRows.findIndex(r => r.kind === 'drive' && r.d.name === 'USB STICK'); paintSide(); focus = 'side'; openSide(si, true); }); await pg.waitForTimeout(400);
  await k('ArrowLeft'); await k('ContextMenu'); console.log('usb opts', await pg.evaluate(() => P.rows.map(r => r.t).join('|')));
  await pg.evaluate(() => { P.i = P.rows.findIndex(r => r.t === 'Eject'); rp(); }); await k('Enter'); await pg.waitForTimeout(600);
  console.log('ejected', JSON.stringify(await st()), await pg.evaluate(() => drives.map(d => d.name).join('|'))); await shot(13);
  // mouse: double click a folder, right click
  await pg.mouse.move(700, 300); await pg.evaluate(() => goPlace(0)); await pg.waitForTimeout(400);
  const row = pg.locator('#list .fr').first(); await row.dblclick(); await pg.waitForTimeout(400); console.log('dblclick', JSON.stringify(await st()));
  await pg.locator('#crumb .c').first().click(); await pg.waitForTimeout(300);
  await pg.locator('#list .fr').nth(2).click({ button: 'right' }); await pg.waitForTimeout(300); console.log('right click', JSON.stringify(await st())); await shot(14);
  await k('Escape');
  // pictures: 40 items, virtual list
  await pg.evaluate(() => { si = 2; openSide(2, true); }); await pg.waitForTimeout(400); await k('End'); console.log('end of pictures', JSON.stringify(await st()), await pg.evaluate(() => document.querySelectorAll('#list .fr').length)); await shot(15);
  await k('Enter'); await pg.waitForTimeout(600); console.log('viewer url', pg.url().split('/').pop()); await shot(16);
  await k('ArrowRight'); console.log('viewer next', await pg.evaluate(() => document.querySelector('#count').textContent));
  await k('Escape'); await pg.waitForTimeout(800); console.log('back from viewer', JSON.stringify(await st()));
  await k('m'); await pg.waitForTimeout(400); console.log('menu -> ', pg.url().split('/').pop());
  console.log('ERRORS', JSON.stringify(errs)); await b.close();
})();
