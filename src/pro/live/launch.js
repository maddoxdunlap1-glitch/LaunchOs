/* Launch day: rockets keep lifting off from behind the hills of the Liftoff picture. */
(function () {
  window.LOSLive.launch = (canvas, opts) => {
    const g = canvas.getContext('2d');
    const img = new Image(); img.src = 'walls/liftoff.webp';
    // the same curve as in the picture (in screen fractions; y down)
    const A = [0.5 + 0.1, 0.73], B = [0.5 + 0.11 * 1.0, 0.42], C = [0.5 + 0.21, 0.225];
    const P = (t, s) => { const k = 1 - t; return [(k * k * A[0] + 2 * k * t * B[0] + t * t * C[0]) * s[0], (k * k * A[1] + 2 * k * t * B[1] + t * t * C[1]) * s[1]]; };
    const stars = Array.from({ length: 90 }, () => ({ x: Math.random(), y: Math.random() * 0.5, p: Math.random() * 6.28, s: 0.8 + Math.random() * 2.5 }));
    return LOSLiveLoop(canvas, opts, 1, (t, dt, W, H) => {
      if (!img.complete || !img.naturalWidth) return;
      g.drawImage(img, 0, 0, W, H);
      // the still picture's trail stays; a new rocket climbs it every 14 seconds
      const cyc = (t % 14) / 9;
      if (cyc <= 1) {
        const e = cyc * cyc * (3 - 2 * cyc);
        const s = [W, H];
        g.lineCap = 'round';
        for (let i = 0; i < 26; i++) {
          const a = Math.max(0, e - i * 0.012), b = Math.max(0, e - (i + 1) * 0.012);
          const p1 = P(a, s), p2 = P(b, s);
          g.strokeStyle = `rgba(255, ${200 - i * 4}, ${150 - i * 4}, ${0.9 * (1 - i / 26)})`;
          g.lineWidth = (W / 1280) * (3.2 - i * 0.1);
          g.beginPath(); g.moveTo(p1[0], p1[1]); g.lineTo(p2[0], p2[1]); g.stroke();
        }
        const tip = P(e, s), r = (W / 1280) * (14 + 6 * Math.sin(t * 30));
        const gr = g.createRadialGradient(tip[0], tip[1], 0, tip[0], tip[1], r * 3);
        gr.addColorStop(0, 'rgba(255, 245, 225, 1)'); gr.addColorStop(0.25, 'rgba(255, 190, 120, 0.6)'); gr.addColorStop(1, 'rgba(255, 140, 80, 0)');
        g.fillStyle = gr; g.beginPath(); g.arc(tip[0], tip[1], r * 3, 0, 6.283); g.fill();
      }
      for (const st of stars) {
        const tw = Math.max(0, Math.sin(t * st.s + st.p));
        g.fillStyle = `rgba(230, 240, 255, ${0.6 * tw * tw})`;
        g.beginPath(); g.arc(st.x * W, st.y * H, (W / 1280) * 1.1, 0, 6.283); g.fill();
      }
    });
  };
})();
