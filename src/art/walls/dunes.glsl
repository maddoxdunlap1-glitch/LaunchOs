// Dunes: a desert at dusk under two moons. The ground is seen in perspective, and the dunes'
// slopes are lit by the low sun on the right.
vec3 skyc(float v) {
  vec3 c = vec3(.98, .6, .45);
  c = mix(c, vec3(.85, .44, .5), smoothstep(.36, .46, v));
  c = mix(c, vec3(.35, .22, .45), smoothstep(.44, .62, v));
  c = mix(c, vec3(.08, .07, .2), smoothstep(.6, .85, v));
  c = mix(c, vec3(.03, .03, .09), smoothstep(.85, 1., v));
  return c;
}
float dunesH(vec2 g) {
  // long ridges, bent and broken up by noise
  float x = g.y * .42 + g.x * .16 + 1.6 * fbm4(g * .09) + .5 * sin(g.x * .25);
  float r = 1. - abs(sin(x));
  return pow(r, 1.6) * (.7 + .5 * fbm4(g * .07 + 3.)) + .08 * fbm4(g * 1.3);
}
vec3 scene(vec2 fc) {
  float asp = R.x / R.y;
  float u = fc.x / R.x, v = fc.y / R.y;
  vec2 p = vec2((u - .5) * asp, v);
  float hz = .38;
  vec3 col = skyc(v);
  col += stars(p, 30., .88, 21.) * smoothstep(.55, .85, v);
  vec2 m1 = vec2(-.42, .74), m2 = vec2(-.2, .86);
  float d1 = length(p - m1), d2 = length(p - m2);
  vec3 moon = vec3(.98, .9, .86) * (.82 + .18 * fbm(p * 26.));
  col = mix(col, moon * (.7 + .3 * smoothstep(.1, -.05, (p - m1).x + .6 * (p - m1).y)), smoothstep(.1, .097, d1));
  col += vec3(1., .85, .75) * exp(-max(d1 - .1, 0.) * 18.) * .2;
  col = mix(col, vec3(.86, .82, .96) * .9, smoothstep(.033, .03, d2));
  col += vec3(.8, .8, 1.) * exp(-max(d2 - .033, 0.) * 30.) * .1;
  vec2 sunp = vec2(.36 * asp, hz + .015);
  col += vec3(1., .55, .35) * exp(-length((p - sunp) * vec2(.45, 1.)) * 4.) * .6;
  // distant dune line on the horizon
  float far = hz + .022 * (1. - abs(sin(p.x * 7. + 2. * fbm4(vec2(p.x * 3., 1.))))) + .012 * fbm4(vec2(p.x * 9., 2.));
  if (v < far) col = mix(skyc(.37) * .78, vec3(.5, .26, .3), .3);
  if (v < hz) {
    // the ground, in perspective
    float depth = .9 / (hz - v + .004);
    vec2 g = vec2(p.x * depth, depth);
    float e = .05 * max(1., depth * .05);
    float h = dunesH(g);
    vec2 grad = vec2(dunesH(g + vec2(e, 0.)) - h, dunesH(g + vec2(0., e)) - h) / e;
    vec3 n = normalize(vec3(-grad.x * 1.4, 1., -grad.y * .6));
    vec3 sunDir = normalize(vec3(.9, .35, .3));
    float light = clamp(dot(n, sunDir), 0., 1.);
    vec3 sand = mix(vec3(.25, .11, .2), vec3(1., .6, .42), pow(light, 1.2));
    sand += vec3(.25, .18, .35) * clamp(n.y, 0., 1.) * .15;            // purple light from the sky
    sand *= .9 + .1 * noise(g * 6.);                                    // ripples
    float fog = 1. - exp(-depth * .035);
    col = mix(sand, skyc(.37) * .85, fog * .9);
  }
  vec2 q = fc / R - .5;
  col *= 1. - .35 * dot(q, q);
  return col;
}
