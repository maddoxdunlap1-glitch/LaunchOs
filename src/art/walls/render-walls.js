// Renders the wallpaper shaders to PNG files:  node render-walls.js OUTDIR WIDTH HEIGHT SAMPLES name...
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
(async () => {
  const [out, W, H, SS, ...names] = process.argv.slice(2);
  const common = fs.readFileSync(path.join(__dirname, 'common.glsl'), 'utf8');
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage();
  await p.goto('file://' + path.join(__dirname, 'render.html'));
  for (const n of names) {
    const src = common + '\n' + fs.readFileSync(path.join(__dirname, n + '.glsl'), 'utf8');
    const t0 = Date.now();
    const url = await p.evaluate(([s, w, h, ss]) => window.draw(s, w, h, 0, ss), [src, +W, +H, +SS]);
    fs.writeFileSync(path.join(out, n + '.png'), Buffer.from(url.split(',')[1], 'base64'));
    console.log(n, (Date.now() - t0) / 1000 + ' s');
  }
  await b.close();
})().catch(e => { console.error(e.message); process.exit(1); });
