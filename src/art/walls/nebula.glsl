// Nebula: soft glowing gas with dark dust lanes across a deep star field.
float fbm5(vec2 p) { float v = 0., a = .5; for (int i = 0; i < 5; i++) { v += a * noise(p); p = ROT * p; a *= .5; } return v; }
vec3 scene(vec2 fc) {
  vec2 p = (fc - .5 * R) / R.y;
  vec2 pr = mat2(.88, -.47, .47, .88) * p;
  vec2 q = vec2(fbm5(pr * 1.3 + vec2(1.3, 2.1)), fbm5(pr * 1.3 + vec2(5.2, 1.3)));
  float f = fbm(pr * 1.5 + 1.4 * q);
  float g = fbm5(pr * 2.6 + 2. * q + vec2(3.1, 7.4));
  float band = exp(-pow(pr.y * 2.4 + .22 * sin(pr.x * 2.2 + .6) + .1, 2.));
  float gas = smoothstep(.38, .82, f) * band;
  vec3 teal = vec3(.08, .55, .62), mag = vec3(.62, .16, .52), blue = vec3(.12, .2, .6), warm = vec3(1., .6, .38);
  vec3 c = mix(blue, teal, smoothstep(.35, .7, q.x));
  c = mix(c, mag, smoothstep(.45, .75, q.y) * .9);
  c = mix(c, warm, smoothstep(.62, .85, g) * .5);
  vec3 col = vec3(.006, .012, .03) + vec3(.025, .03, .07) * band * band;
  col += c * gas * .9 + c * pow(gas, 2.5) * 1.3;
  col += c * pow(band, 3.) * .1;                   // faint glow around the whole cloud
  float dust = smoothstep(.5, .78, fbm(pr * 2.8 + q * 1.6 + vec2(4.2, 1.1)));
  col *= 1. - dust * .7 * smoothstep(.1, .6, band);
  col += stars(p, 30., .88, 4.) * (.5 + .6 * band) + stars(p, 70., .91, 5.) * .45 + stars(p, 150., .9, 6.) * .25 * (1. + 2. * band);
  col += glare(p, vec2(-.5, .22), .15, vec3(.8, .9, 1.)) * .85;
  col += glare(p, vec2(.58, -.2), .11, vec3(1., .86, .72)) * .65;
  col += glare(p, vec2(.12, .36), .06, vec3(.85, .92, 1.)) * .5;
  vec2 v = fc / R - .5;
  col *= 1. - .5 * dot(v, v);
  return aces(col * 1.1);
}
