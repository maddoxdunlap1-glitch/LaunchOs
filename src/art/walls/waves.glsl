// Waves: silky ribbons of colored light on a deep blue background.
vec3 scene(vec2 fc) {
  vec2 p = (fc - .5 * R) / R.y;
  vec3 col = mix(vec3(.01, .025, .06), vec3(.02, .05, .1), smoothstep(-.5, .5, p.y));
  col += vec3(.05, .12, .2) * exp(-length(p - vec2(.3, .1)) * 2.) * .5;
  vec3 tints[5] = vec3[5](vec3(.24, .86, .42), vec3(.18, .75, .78), vec3(.25, .48, 1.), vec3(.55, .38, 1.), vec3(.15, .9, .65));
  for (int k = 0; k < 5; k++) {
    float fk = float(k);
    float y0 = -.18 + fk * .085 + .05 * sin(fk * 2.1);
    float x = p.x;
    float y = y0 + .16 * sin(x * (1.3 + fk * .17) + fk * 1.7) + .07 * sin(x * (2.9 + fk * .31) + fk * 4.1) + .04 * (fbm4(vec2(x * 1.2, fk)) - .5);
    float dy = p.y - y;
    float w = .045 + .03 * sin(x * 1.1 + fk * 2.7) + .015 * fk;      // ribbon thickness changes along it
    float inside = smoothstep(w, w * .55, abs(dy));
    // shading: a glossy highlight along one edge, darker on the other
    float sh = .45 + .55 * smoothstep(-w, w, dy);
    float gloss = exp(-pow((dy - w * .45) / (w * .18), 2.)) * .9;
    float fade = smoothstep(-1.2, -.3, x) * smoothstep(1.25, .45, x + .2 * fk);
    vec3 c = tints[k] * sh * 1.15 + vec3(1.) * gloss * .55;
    col = mix(col, c * (.55 + .45 * fade), inside * (.55 + .2 * fade) * fade);
    col += tints[k] * exp(-abs(dy) / (w * 2.2)) * .16 * fade;          // soft glow around it
  }
  vec2 v = fc / R - .5;
  col *= 1. - .4 * dot(v, v);
  return col;
}
