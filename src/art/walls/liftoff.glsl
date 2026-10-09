// Liftoff: a rocket's trail climbing out of a sunset, over layered mountains.
vec3 ramp(float v) {
  vec3 c = vec3(1., .54, .36);
  c = mix(c, vec3(.91, .38, .48), smoothstep(.26, .34, v));
  c = mix(c, vec3(.48, .25, .53), smoothstep(.33, .47, v));
  c = mix(c, vec3(.17, .17, .41), smoothstep(.45, .64, v));
  c = mix(c, vec3(.05, .086, .22), smoothstep(.62, .86, v));
  c = mix(c, vec3(.02, .04, .11), smoothstep(.85, 1., v));
  return c;
}
vec3 scene(vec2 fc) {
  float asp = R.x / R.y;
  float u = fc.x / R.x, v = fc.y / R.y;
  vec2 p = vec2((u - .5) * asp, v);
  vec3 col = ramp(v);
  // the set sun's glow, low on the right
  vec2 sun = vec2(.22 * asp, .24);
  float sd = length((p - sun) * vec2(.6, 1.));
  col += vec3(1., .55, .3) * exp(-sd * 3.2) * .55 + vec3(1., .75, .5) * exp(-sd * 11.) * .5;
  // thin clouds, lit from below
  float band = smoothstep(.3, .36, v) * (1. - smoothstep(.42, .5, v));
  float cl = smoothstep(.5, .78, fbm(vec2(u * 2.4, v * 16.) + vec2(fbm4(vec2(u * 3., v * 6.)) * 1.5, 0.)));
  col = mix(col, mix(vec3(1., .66, .55), vec3(.95, .45, .55), smoothstep(.32, .46, v)) * 1.05, cl * band * .55);
  // stars, fading in higher up
  float sv = smoothstep(.42, .8, v);
  col += (stars(p, 26., .86, 1.) + stars(p, 52., .9, 2.) * .6 + stars(p, 110., .93, 3.) * .35) * sv;
  // the rocket's trail
  vec2 A = vec2(.1 * asp, .27), B = vec2(.11 * asp, .58), C = vec2(.21 * asp, .775);
  vec2 bt = sdBezier(p, A, B, C);
  float d = bt.x, t = bt.y;
  float w = mix(.075, .004, pow(t, .55));
  vec2 wq = p * 18. + vec2(fbm4(p * 9.) * 2., -t * 4.);
  float turb = fbm(wq);
  float smoke = exp(-pow(d / w, 2.) * 1.4) * (.35 + .9 * turb) * smoothstep(1., .9, t);
  vec3 scol = mix(vec3(1., .72, .6), vec3(.82, .76, .92), smoothstep(.05, .6, t));
  scol *= mix(1.1, .7, t);
  col = mix(col, scol, clamp(smoke, 0., 1.) * .8);
  float hot = exp(-pow(d / mix(.006, .0022, t), 2.)) * smoothstep(.45, .98, t);
  col += vec3(1., .82, .58) * hot * 1.6;
  col += vec3(1., .5, .3) * exp(-d / .02) * smoothstep(.6, 1., t) * .25;
  col += glare(p, C, .2, vec3(1., .9, .75)) * 1.25;
  col += vec3(1., .62, .38) * exp(-length(p - C) / .05) * .35;
  // light at the launch site, behind the hills
  col += vec3(1., .62, .4) * exp(-length((p - A) * vec2(.8, 1.6)) / .05) * .5;
  // mountains: far, middle and near, hazier with distance
  float hf = .27 + .085 * pow(ridge(vec2(u * 3.2 + 7., 1.3)), 1.6);
  float hm = .2 + .11 * pow(ridge(vec2(u * 2.1 + 2., 4.1)), 1.8);
  float hn = .1 + .12 * pow(ridge(vec2(u * 1.5 + 11., 8.7)), 2.0);
  vec3 far = mix(ramp(.3), vec3(.33, .22, .44), .55);
  vec3 mid = vec3(.16, .12, .27);
  vec3 near = vec3(.045, .05, .1);
  float e = 1.5 / R.y;
  col = mix(col, far + vec3(.08, .04, .03) * smoothstep(hf - .02, hf, v), smoothstep(hf + e, hf - e, v));
  col = mix(col, mid + vec3(.12, .05, .05) * smoothstep(hm - .012, hm, v) * (.6 + .4 * u), smoothstep(hm + e, hm - e, v));
  col = mix(col, near + vec3(.1, .05, .06) * smoothstep(hn - .01, hn, v) * u, smoothstep(hn + e, hn - e, v));
  // a little mist between the layers
  col += vec3(.55, .32, .42) * exp(-abs(v - hm + .02) * 30.) * .05;
  // vignette
  vec2 q = fc / R - .5;
  col *= 1. - .35 * dot(q, q) * 1.6;
  return col;
}
