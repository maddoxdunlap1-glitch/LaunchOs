// Orbit: dawn breaking over a planet's edge, seen from space.
vec3 scene(vec2 fc) {
  vec2 p = (fc - .5 * R) / R.y;
  vec2 c = vec2(-.32, -1.17);          // the planet's centre, below the picture (its edge high up, above Home's tiles)
  float rad = 1.42;
  float d = length(p - c);
  vec2 n2 = (p - c) / d;
  vec2 sunDir = normalize(vec2(.5, .87));
  vec2 sunAt = c + sunDir * rad;       // where the sun peeks over the edge
  vec3 col = vec3(.004, .008, .02);
  col += stars(p, 32., .87, 11.) + stars(p, 75., .9, 12.) * .5 + stars(p, 160., .92, 13.) * .3;
  float alt = d - rad;
  // atmosphere: a thin glowing shell, brightest towards the sun
  float lit = smoothstep(-.4, 1., dot(n2, sunDir));
  float shell = exp(-max(alt, 0.) * 38.) * smoothstep(-.004, .002, alt);
  vec3 atm = mix(vec3(.12, .35, 1.), vec3(.55, .8, 1.), lit) * (.25 + 1.4 * pow(lit, 3.));
  col += atm * shell * 1.3;
  col += vec3(.2, .45, 1.) * exp(-max(alt, 0.) * 9.) * .12 * lit;
  if (alt < 0.) {
    // the planet: night side with city lights, day side lit by the rising sun
    vec2 sp = (p - c) * 3.;
    float lf = fbm(sp * 1.7 + vec2(3.1, 1.7));
    float land = smoothstep(.5, .54, lf);
    float clouds = smoothstep(.5, .85, fbm(sp * 2.6 + vec2(fbm4(sp * 2.) * 1.5, 0.)));
    float day = smoothstep(-.02, .25, dot(n2, sunDir) - .55);
    vec3 surf = mix(vec3(.02, .07, .19), mix(vec3(.12, .14, .08), vec3(.2, .17, .1), smoothstep(.55, .7, lf)), land);
    surf = mix(surf, vec3(.8, .84, .92), clouds * .85);
    float city = smoothstep(.62, .78, fbm4(sp * 18.)) * smoothstep(.55, .9, noise(sp * 140.));
    vec3 night = vec3(.004, .007, .016) + vec3(1., .72, .4) * city * land * (1. - clouds) * .9;
    vec3 ground = mix(night, surf * (.25 + .9 * day), day);
    float rim = exp(alt * 22.);                     // haze right at the edge
    ground = mix(ground, atm * .9, rim * .55 * (.3 + .7 * lit));
    col = mix(col, ground, smoothstep(.002, -.002, alt));
  }
  // the sun and its glare
  vec2 sp = p - sunAt;
  float r = length(sp);
  col += vec3(1., .93, .8) * exp(-r * r * 900.) * 2.5;
  col += vec3(1., .78, .55) * exp(-r * 9.) * .45;
  vec2 tang = vec2(sunDir.y, -sunDir.x);
  col += vec3(.9, .88, 1.) * exp(-abs(dot(sp, sunDir)) * 260.) * exp(-abs(dot(sp, tang)) * 5.) * .45;   // glare along the edge
  vec2 v = fc / R - .5;
  col *= 1. - .35 * dot(v, v);
  return aces(col * 1.1);
}
