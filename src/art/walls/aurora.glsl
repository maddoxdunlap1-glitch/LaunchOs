// Aurora: curtains of green and violet light over snowy peaks, mirrored in a still lake.
float mountain(float u) {
  float r = ridge(vec2(u * 2.2 + 5.3, 3.7));
  return .31 + .02 + .26 * pow(r, 3.2);
}
vec3 sky(vec2 p, float v) {
  vec3 col = mix(vec3(.02, .06, .085), vec3(.004, .01, .03), smoothstep(.3, 1., v));
  col += vec3(.03, .12, .09) * exp(-(v - .31) * 9.) * .6;          // faint green glow low in the sky
  col += stars(p, 34., .86, 7.) * smoothstep(.36, .7, v) + stars(p, 80., .9, 8.) * .45 * smoothstep(.36, .8, v);
  for (int k = 0; k < 2; k++) {
    float fk = float(k);
    float x = p.x * (1.05 + fk * .45) + fk * 2.7;
    float base = .66 - .09 * p.x + fk * .07 + .085 * sin(x * 2.3 + .4 + fk * 2.) + .06 * (fbm4(vec2(x * 1.6, fk * 4.)) - .5);
    float h = v - base;
    float strength = smoothstep(.35, .62, fbm4(vec2(x * .75 + 2. + fk * 5., fk * 7.))) * (1. - fk * .3);
    float len = .05 + .3 * pow(noise(vec2(x * 23., fk * 5. + 1.)), 2.);      // each ray its own height
    float fine = noise(vec2(x * 70. + fbm4(vec2(x * 5., 1.)) * 4., fk * 3.));
    float a = smoothstep(-.06, .01, h) * exp(-max(h, 0.) / len) * (.3 + .9 * fine) * strength;
    a += exp(-abs(h) * 45.) * strength * .55;    // the bright lower edge
    vec3 c = mix(vec3(.3, 1., .62), vec3(.25, .9, .85), smoothstep(.0, .07, h));
    c = mix(c, vec3(.56, .36, 1.), smoothstep(.06, .24, h));
    col += c * a * 1.1;
  }
  return col;
}
vec3 land(float u, float v, vec3 col) {
  float hm = mountain(u);
  if (v > hm) return col;
  float rock = ridge(vec2(u * 36., v * 26.));
  float snow = smoothstep(hm - .045, hm - .012, v + .03 * (rock - .5)) * smoothstep(.36, .44, hm);
  vec3 m = vec3(.01, .022, .032) + rock * .012;
  m = mix(m, vec3(.3, .44, .5) * (.7 + .4 * rock), snow * .75);
  m += vec3(.08, .4, .26) * snow * .12;
  return m;
}
vec3 scene(vec2 fc) {
  float asp = R.x / R.y;
  float u = fc.x / R.x, v = fc.y / R.y;
  vec2 p = vec2((u - .5) * asp, v);
  float shore = .31;
  vec3 col;
  if (v > shore) {
    col = land(u, v, sky(p, v));
    float tx = u * 80.;
    float th = .01 + .03 * h21(vec2(floor(tx), 3.)) * (.6 + .4 * noise(vec2(u * 6., 2.)));
    float tri = th * (1. - abs(fract(tx) - .5) * 2.);
    if (v < shore + tri) col = vec3(.004, .01, .014);
  } else {
    float d = shore - v;
    float ru = u + .006 * (noise(vec2(u * 30., v * 260.)) - .5) * (1. + d * 3.);
    float rv = shore + d;
    vec3 refl = land(ru, rv, sky(vec2((ru - .5) * asp, rv), rv));
    float tx = ru * 80.;
    float th = .01 + .03 * h21(vec2(floor(tx), 3.)) * (.6 + .4 * noise(vec2(ru * 6., 2.)));
    if (rv < shore + th * (1. - abs(fract(tx) - .5) * 2.)) refl = vec3(.004, .01, .014);
    col = refl * (.45 - d * .4) + vec3(.002, .006, .01);
  }
  vec2 q = fc / R - .5;
  col *= 1. - .4 * dot(q, q);
  return aces(col * 1.25);
}
