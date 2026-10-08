// Retro: a striped sunset sun, neon mountains and a glowing grid floor.
vec3 scene(vec2 fc) {
  float asp = R.x / R.y;
  vec2 p = (fc - .5 * R) / R.y;
  float hz = -.06;                         // the horizon
  vec3 col;
  if (p.y > hz) {
    float v = (p.y - hz) / (.5 - hz);
    col = mix(vec3(.55, .12, .45), vec3(.18, .05, .3), smoothstep(0., .45, v));
    col = mix(col, vec3(.03, .02, .1), smoothstep(.4, 1., v));
    col += stars(p, 40., .9, 31.) * smoothstep(.35, .8, v);
    // the sun, with stripes cut out of its lower half
    vec2 s = p - vec2(0., .13);
    float r = length(s);
    float stripes = step(.5, fract((s.y + .3) * 22. - pow(max(-s.y, 0.) * 6., 1.2)));
    float cut = s.y < -.01 ? stripes : 1.;
    vec3 sun = mix(vec3(1., .2, .55), vec3(1., .85, .3), smoothstep(-.2, .2, s.y));
    col = mix(col, sun, smoothstep(.205, .2, r) * cut);
    col += vec3(1., .3, .5) * exp(-max(r - .2, 0.) * 10.) * .35;
    // mountains in front of the sun
    float m = hz + .1 * pow(ridge(vec2(p.x * 2.2 + 1.3, 5.)), 2.4) + .03 * smoothstep(.4, .9, abs(p.x));
    if (p.y < m) {
      col = vec3(.05, .02, .12);
      float edge = exp(-(m - p.y) * 90.);
      col += vec3(1., .3, .8) * edge * .8;
    }
  } else {
    // the floor: perspective grid lines
    float z = .14 / (hz - p.y + .002);
    float gx = p.x * z * 1.6, gz = z + 0.;
    float lx = abs(fract(gx + .5) - .5), lz = abs(fract(gz + .5) - .5);
    float wx = fwidth(gx), wz = fwidth(gz);
    float line = max(smoothstep(wx * 1.6, 0., lx), smoothstep(wz * 1.6, 0., lz));
    float glow = max(exp(-lx / (wx * 4.)), exp(-lz / (wz * 4.))) * .35;
    float fade = exp(-z * .08);
    col = vec3(.03, .01, .08) + vec3(.4, .08, .5) * exp(-(hz - p.y) * 6.) * .4;
    col += vec3(.25, .85, 1.) * (line + glow) * fade * .9 + vec3(1., .2, .7) * line * fade * .25;
    col += vec3(1., .3, .6) * exp(-(hz - p.y) * 40.) * .5;     // glow at the horizon
  }
  vec2 v = fc / R - .5;
  col *= 1. - .45 * dot(v, v);
  return col;
}
