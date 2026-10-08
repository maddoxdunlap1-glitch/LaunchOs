/* Nebula drift: the Nebula picture slowly drifts and turns, with twinkling stars in front. */
(function () {
  window.LOSLive.drift = (canvas, opts) => {
    const g = canvas.getContext('2d');
    const img = new Image(); img.src = 'walls/nebula.webp';
    const stars = Array.from({ length: opts && opts.hardware ? 160 : 70 }, () => ({ x: Math.random(), y: Math.random(), r: 0.4 + Math.random() * 1.4, p: Math.random() * 6.28, s: 0.6 + Math.random() * 2, d: 0.2 + Math.random() * 0.8 }));
    return LOSLiveLoop(canvas, opts, 1, (t, dt, W, H) => {
      if (!img.complete || !img.naturalWidth) return;
      const z = 1.12 + 0.04 * Math.sin(t * 0.05), a = Math.sin(t * 0.03) * 0.025;
      const dx = Math.sin(t * 0.021) * W * 0.03, dy = Math.cos(t * 0.017) * H * 0.03;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = '#02050b'; g.fillRect(0, 0, W, H);
      g.translate(W / 2 + dx, H / 2 + dy); g.rotate(a); g.scale(z, z);
      g.drawImage(img, -W / 2, -H / 2, W, H);
      g.setTransform(1, 0, 0, 1, 0, 0);
      for (const s of stars) {
        const tw = 0.55 + 0.45 * Math.sin(t * s.s + s.p);
        const x = ((s.x + Math.sin(t * 0.021) * 0.012 * s.d) % 1) * W, y = ((s.y + Math.cos(t * 0.017) * 0.012 * s.d) % 1) * H;
        g.fillStyle = `rgba(225, 238, 255, ${0.25 + 0.75 * tw * s.d})`;
        g.beginPath(); g.arc(x, y, s.r * (W / 1280), 0, 6.283); g.fill();
      }
    });
  };
})();
