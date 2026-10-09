/* Living aurora: the Aurora picture, with curtains of light that ripple and drift, drawn by the
   graphics card (aurora-src.js holds the picture's shader). Without graphics acceleration it
   keeps the still picture instead. */
(function () {
  window.LOSLive.sky = (canvas, opts) => {
    if (!(opts && opts.hardware)) return () => {};       // keep the still picture
    const gl = canvas.getContext('webgl2', { premultipliedAlpha: false });
    if (!gl) return () => {};
    const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, '#version 300 es\nin vec2 a;void main(){gl_Position=vec4(a,0.,1.);}'));
    if (!window.LOSAuroraSrc) return () => {};
    gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, '#version 300 es\n' + window.LOSAuroraSrc + '\nvoid main() { fragColor = vec4(scene(gl_FragCoord.xy), 1.); }'));
    gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return () => {};
    gl.useProgram(pr);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const uR = gl.getUniformLocation(pr, 'R'), uT = gl.getUniformLocation(pr, 'T');
    return LOSLiveLoop(canvas, opts, 0.6, (t, dt, W, H) => {
      gl.viewport(0, 0, W, H); gl.uniform2f(uR, W, H); gl.uniform1f(uT, t); gl.drawArrays(gl.TRIANGLES, 0, 3);
    });
  };
})();
