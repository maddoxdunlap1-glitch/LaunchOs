/* LaunchOS Pro live backgrounds: shared helpers. Each background registers
   window.LOSLive[name] = (canvas, opts) => stop, draws on the canvas behind Home and the
   sign-in screen, and stops when asked. They draw less often on PCs without graphics
   acceleration, and not at all while the page is hidden (a game is on screen). */
(function () {
  window.LOSLive = window.LOSLive || {};
  window.LOSLiveLoop = function (canvas, opts, scale, draw) {
    const hw = !!(opts && opts.hardware);
    const fpsCap = hw ? 60 : 12;            // software drawing: a gentle 12 frames a second
    const res = (hw ? 1 : 0.5) * (scale || 1);
    let raf = 0, last = 0, t0 = performance.now(), stopped = false;
    function size() {
      const r = canvas.getBoundingClientRect();
      const w = Math.max(64, Math.round(r.width * res)), h = Math.max(36, Math.round(r.height * res));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; return true; }
      return false;
    }
    function frame(now) {
      if (stopped) return;
      raf = requestAnimationFrame(frame);
      if (document.hidden || now - last < 1000 / fpsCap - 2) return;
      const dt = Math.min(0.1, (now - (last || now)) / 1000);
      last = now;
      const resized = size();
      draw((now - t0) / 1000, dt, canvas.width, canvas.height, resized);
    }
    size();
    raf = requestAnimationFrame(frame);
    return () => { stopped = true; cancelAnimationFrame(raf); };
  };
})();
