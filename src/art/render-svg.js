// Renders an SVG file to a PNG with a transparent background, at any size (uses Playwright's Chromium).
//   node render-svg.js in.svg out.png WIDTH [HEIGHT]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [inp, out, w, h] = process.argv.slice(2);
  let svg = fs.readFileSync(inp, 'utf8');
  const vb = /viewBox="([\d.\s-]+)"/.exec(svg)[1].split(/\s+/).map(Number);
  const W = +w, H = h ? +h : Math.round(W * vb[3] / vb[2]);
  svg = svg.replace(/<svg([^>]*?)\swidth="[^"]*"/, '<svg$1').replace(/<svg([^>]*?)\sheight="[^"]*"/, '<svg$1')
           .replace('<svg', `<svg width="${W}" height="${H}"`);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: W, height: H } });
  await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
  await p.screenshot({ path: out, omitBackground: true, clip: { x: 0, y: 0, width: W, height: H } });
  await b.close();
})();
