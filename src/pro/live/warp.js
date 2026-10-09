/* Warp speed: stars stream past as if the console is flying through space. */
(function () {
  window.LOSLive.warp = (canvas, opts) => {
    const g = canvas.getContext('2d');
    const N = opts && opts.hardware ? 700 : 260;
    const stars = [];
    const spawn = s => { s.x = (Math.random() - 0.5) * 2; s.y = (Math.random() - 0.5) * 2; s.z = 0.2 + Math.random() * 1.8; s.pz = s.z; s.hue = 190 + Math.random() * 60; return s; };
    for (let i = 0; i < N; i++) stars.push(spawn({}));
    return LOSLiveLoop(canvas, opts, 1, (t, dt, W, H, resized) => {
      if (resized) { g.fillStyle = '#04070f'; g.fillRect(0, 0, W, H); }
      // fade the last frame a little: the streaks leave short trails
      g.fillStyle = 'rgba(4, 7, 15, 0.35)';
      g.fillRect(0, 0, W, H);
      const cx = W / 2 + Math.sin(t * 0.13) * W * 0.04, cy = H / 2 + Math.cos(t * 0.11) * H * 0.04, f = Math.min(W, H) * 0.6;
      const speed = 0.55 + 0.25 * Math.sin(t * 0.25);
      g.lineCap = 'round';
      for (const s of stars) {
        s.pz = s.z;
        s.z -= speed * dt;
        if (s.z <= 0.03) { spawn(s); s.z = s.pz = 2; continue; }
        const x = cx + s.x / s.z * f, y = cy + s.y / s.z * f;
        const px = cx + s.x / s.pz * f, py = cy + s.y / s.pz * f;
        if (x < -20 || x > W + 20 || y < -20 || y > H + 20) { spawn(s); s.z = s.pz = 2; continue; }
        const b = Math.min(1, (2 - s.z) / 1.6);
        g.strokeStyle = `hsla(${s.hue}, 80%, ${70 + b * 25}%, ${b})`;
        g.lineWidth = Math.max(0.6, (2.2 - s.z) * 1.3);
        g.beginPath(); g.moveTo(px, py); g.lineTo(x, y); g.stroke();
      }
      // a soft blue glow at the vanishing point
      const gr = g.createRadialGradient(cx, cy, 0, cx, cy, Math.min(W, H) * 0.35);
      gr.addColorStop(0, 'rgba(90, 150, 255, 0.05)'); gr.addColorStop(1, 'rgba(90, 150, 255, 0)');
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
    });
  };
})();
