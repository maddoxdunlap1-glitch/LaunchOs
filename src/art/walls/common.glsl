// Shared helpers for the LaunchOS wallpapers (WebGL 2 / GLSL ES 3.00).
precision highp float;
uniform vec2 R;      // picture size in pixels
uniform float T;     // time in seconds (0 for the still pictures)
out vec4 fragColor;

float h11(float p) { p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
float h21(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec2 h22(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * vec3(.1031, .1030, .0973)); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.xx + p3.yz) * p3.zy); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * f * (f * (f * 6. - 15.) + 10.);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), u.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), u.x), u.y);
}
const mat2 ROT = mat2(1.6, 1.2, -1.2, 1.6);
float fbm(vec2 p) { float v = 0., a = .5; for (int i = 0; i < 7; i++) { v += a * noise(p); p = ROT * p; a *= .5; } return v; }
float fbm4(vec2 p) { float v = 0., a = .5; for (int i = 0; i < 4; i++) { v += a * noise(p); p = ROT * p; a *= .5; } return v; }
float ridge(vec2 p) { float v = 0., a = .5; for (int i = 0; i < 6; i++) { v += a * (1. - abs(noise(p) * 2. - 1.)); p = ROT * p; a *= .5; } return v; }

// Stars: one maybe-star per grid cell. thresh: share of empty cells (higher = fewer stars).
vec3 stars(vec2 p, float scale, float thresh, float seed) {
  vec2 g = p * scale, id = floor(g), f = fract(g) - .5;
  vec3 c = vec3(0);
  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
    vec2 o = vec2(x, y), cid = id + o + seed * 17.;
    float r = h21(cid);
    if (r < thresh) continue;
    vec2 pos = o + h22(cid) - .5;
    float d = length(f - pos);
    float b = pow((r - thresh) / (1. - thresh), 3.);
    float sz = mix(.035, .085, b);
    float tw = .75 + .25 * sin(T * (1. + 2. * h21(cid + 3.)) + 6.28 * h21(cid + 5.));
    vec3 tint = mix(vec3(.72, .83, 1.), vec3(1., .86, .72), h21(cid + 9.));
    c += tint * (exp(-d * d / (sz * sz * .25)) * (.35 + 1.4 * b) + exp(-d / (sz * 1.6)) * b * .25) * tw;
  }
  return c;
}
// A bright star with a soft cross-shaped glare.
vec3 glare(vec2 p, vec2 at, float size, vec3 tint) {
  vec2 d = p - at;
  float r = length(d);
  float core = exp(-r * r / (size * size * .02));
  float halo = exp(-r / (size * .35)) * .35;
  float spikes = (exp(-abs(d.x) / (size * .01)) * exp(-abs(d.y) / (size * .28)) + exp(-abs(d.y) / (size * .01)) * exp(-abs(d.x) / (size * .28))) * .4;
  return tint * (core + halo + spikes);
}
vec3 aces(vec3 x) { return clamp((x * (2.51 * x + .03)) / (x * (2.43 * x + .59) + .14), 0., 1.); }
// dithering: removes banding in the dark gradients
vec3 dither(vec3 c, vec2 fc) { return c + (h21(fc + fract(T)) - .5) / 255.; }

float dot2(vec2 v) { return dot(v, v); }
// Distance to a quadratic Bezier curve, and where along it (Inigo Quilez's method). Returns (distance, t).
vec2 sdBezier(vec2 pos, vec2 A, vec2 B, vec2 C) {
  vec2 a = B - A, b = A - 2. * B + C, c = a * 2., d = A - pos;
  float kk = 1. / dot(b, b), kx = kk * dot(a, b), ky = kk * (2. * dot(a, a) + dot(d, b)) / 3., kz = kk * dot(d, a);
  float p = ky - kx * kx, p3 = p * p * p, q = kx * (2. * kx * kx - 3. * ky) + kz, h = q * q + 4. * p3;
  float res, tt;
  if (h >= 0.) {
    h = sqrt(h);
    vec2 x = (vec2(h, -h) - q) / 2.;
    vec2 uv = sign(x) * pow(abs(x), vec2(1. / 3.));
    tt = clamp(uv.x + uv.y - kx, 0., 1.);
    res = dot2(d + (c + b * tt) * tt);
  } else {
    float z = sqrt(-p), v = acos(q / (p * z * 2.)) / 3., m = cos(v), n = sin(v) * 1.732050808;
    vec3 t = clamp(vec3(m + m, -n - m, n - m) * z - kx, 0., 1.);
    float r1 = dot2(d + (c + b * t.x) * t.x), r2 = dot2(d + (c + b * t.y) * t.y);
    if (r1 < r2) { res = r1; tt = t.x; } else { res = r2; tt = t.y; }
  }
  return vec2(sqrt(res), tt);
}
