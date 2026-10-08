#!/usr/bin/env python3
"""Draws LaunchOS's rocket artwork: the boot animation's images, the launcher's copies and the
app icon. Run from this folder:  python3 make-art.py
Needs numpy, Pillow and Node with Playwright (for the SVG drawings)."""
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
THEME = os.path.join(SRC, 'boot-theme', 'plymouth-launchos')
UIIMG = os.path.join(SRC, 'ui', 'img')
NODE_PATH = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()


def svg(name, out, width, height=None):
    args = ['node', os.path.join(HERE, 'render-svg.js'), os.path.join(HERE, name), out, str(width)]
    if height:
        args.append(str(height))
    subprocess.run(args, check=True, env=dict(os.environ, NODE_PATH=NODE_PATH))


def save(im, *paths):
    for p in paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        im.save(p, optimize=True)


# ---------- noise ----------

def tile_noise(h, w, cells_y, cells_x, rng):
    """Smooth random field (bicubic-interpolated random grid) that repeats every h rows."""
    g = rng.random((cells_y, cells_x)).astype(np.float32)
    g3 = np.vstack([g, g, g])
    im = Image.fromarray((g3 * 255).astype(np.uint8)).resize((w, 3 * h), Image.BICUBIC)
    return (np.asarray(im, dtype=np.float32) / 255.0)[h:2 * h]


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def lerp_colors(t, stops):
    """t in 0..1 -> RGB from (position, (r,g,b)) stops."""
    out = np.zeros(t.shape + (3,), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (t >= p0) & (t <= p1)
        k = ((t - p0) / (p1 - p0))[m][:, None]
        out[m] = np.array(c0) * (1 - k) + np.array(c1) * k
    out[t > stops[-1][0]] = stops[-1][1]
    return out


# ---------- flame frames ----------

def flame_frames(w, h, n=12, seed=7):
    """Rocket exhaust: white-hot core, yellow, orange, fading to red; flickers and flows downward.
    The frames loop: the noise moves exactly one repeat over n frames."""
    rng = np.random.default_rng(seed)
    nh = h * 2                                   # the noise repeats every nh rows
    n1 = tile_noise(nh, w, 8, 6, rng)
    n2 = tile_noise(nh, w, 20, 12, rng)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    v = y / h                                    # 0 at the nozzle, 1 at the tip
    u = (x - w / 2) / (w / 2)                    # -1..1 across
    frames = []
    for f in range(n):
        off = int(round(f / n * nh))
        rows = (np.arange(h) - off) % nh
        a1, a2 = n1[rows], n2[rows]
        uu = u + (a1 - 0.5) * 0.34 * v + (a2 - 0.5) * 0.16 * v
        length = 0.86 + 0.14 * math.sin(2 * math.pi * f / n) * 0.5 + 0.07 * math.sin(4 * math.pi * f / n + 1)
        vv = v / length
        half = 0.40 * np.clip(1 - vv ** 1.6, 0, 1) ** 0.7 + 0.03
        d = np.abs(uu) / half                    # 0 at the centre line, 1 at the edge
        core = np.clip(1 - d, 0, 1)
        fade = np.clip(1 - vv, 0, 1) ** 0.5
        heat = np.clip(core ** 0.75 * fade * (0.88 + 0.28 * (a2 - 0.5)), 0, 1)
        col = lerp_colors(heat, [(0.0, (255, 55, 80)), (0.18, (255, 85, 64)), (0.4, (255, 146, 64)),
                                 (0.6, (255, 205, 100)), (0.8, (255, 243, 210)), (1.0, (255, 255, 255))])
        blue = smoothstep(0.09, 0.0, v) * smoothstep(0.7, 0.0, d)   # a hint of blue at the nozzle
        col = col * (1 - blue[..., None] * 0.55) + np.array((150, 210, 255), np.float32) * blue[..., None] * 0.55
        alpha = smoothstep(0.03, 0.34, heat)
        # a soft orange haze around the flame
        haze = np.clip(1 - np.abs(uu) / (half * 2.1), 0, 1) ** 1.6 * fade ** 0.9 * 0.42
        hcol = np.array((255, 118, 58), np.float32)
        out_a = alpha + haze * (1 - alpha)
        col = (col * alpha[..., None] + hcol * (haze * (1 - alpha))[..., None]) / np.maximum(out_a, 1e-4)[..., None]
        alpha = out_a
        rgba = np.dstack([col, alpha * 255]).clip(0, 255).astype(np.uint8)
        frames.append(Image.fromarray(rgba, 'RGBA').filter(ImageFilter.GaussianBlur(max(0.6, w / 150))))
    return frames


def radial(size, color, alpha, power=2.0):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(x - size / 2 + 0.5, y - size / 2 + 0.5) / (size / 2)
    a = np.clip(1 - r, 0, 1) ** power * alpha
    rgba = np.zeros((size, size, 4), np.float32)
    rgba[..., :3] = color
    rgba[..., 3] = a * 255
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), 'RGBA')


def star(size, core):
    """A star: a bright core with a soft halo."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(x - size / 2 + 0.5, y - size / 2 + 0.5)
    a = np.exp(-(r / core) ** 2) + 0.35 * np.exp(-(r / (core * 2.6)) ** 2)
    rgba = np.zeros((size, size, 4), np.float32)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 225, 238, 255
    rgba[..., 3] = np.clip(a, 0, 1) * 255
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), 'RGBA')


def streak(w, h):
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    a = np.sin(np.pi * y) ** 2 * 0.55
    xs = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    a = a * np.clip(1 - np.abs(xs), 0, 1)
    rgba = np.zeros((h, w, 4), np.float32)
    rgba[..., :3] = (200, 225, 255)
    rgba[..., 3] = a * 255
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), 'RGBA')


def background(w=96, h=54):
    """The space behind the rocket: lighter navy in the middle, darker at the edges."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot((x - w / 2) / (w / 2), (y - h * 0.46) / (h / 2))
    t = np.clip(r / 1.25, 0, 1)
    c = np.array((17, 37, 60), np.float32) * (1 - t[..., None]) + np.array((5, 11, 21), np.float32) * t[..., None]
    return Image.fromarray(c.clip(0, 255).astype(np.uint8), 'RGB')


def main():
    # rocket: 1x for 1080p screens (300 px tall drawing area), 2x for bigger ones
    for scale, tag in ((1, ''), (2, '@2x')):
        svg('rocket.svg', os.path.join(THEME, f'rocket{tag}.png'), 210 * scale, 350 * scale)
        for i, fr in enumerate(flame_frames(128 * scale, 260 * scale)):
            fr.save(os.path.join(THEME, f'flame{i}{tag}.png'), optimize=True)
        radial(440 * scale, (255, 150, 77), 0.42, 2.2).save(os.path.join(THEME, f'glow{tag}.png'), optimize=True)
        radial(30 * scale, (205, 216, 232), 0.55, 1.6).save(os.path.join(THEME, f'puff{tag}.png'), optimize=True)
        star(14 * scale, 1.5 * scale).save(os.path.join(THEME, f'star0{tag}.png'), optimize=True)
        star(10 * scale, 1.0 * scale).save(os.path.join(THEME, f'star1{tag}.png'), optimize=True)
        star(6 * scale, 0.7 * scale).save(os.path.join(THEME, f'star2{tag}.png'), optimize=True)
        streak(3 * scale, 110 * scale).save(os.path.join(THEME, f'streak{tag}.png'), optimize=True)
    background().save(os.path.join(THEME, 'bg.png'), optimize=True)
    # the launcher's copies (its intro and sign-in screen draw the same rocket)
    for name in ['rocket@2x.png', 'glow@2x.png'] + [f'flame{i}@2x.png' for i in range(12)]:
        Image.open(os.path.join(THEME, name)).save(os.path.join(UIIMG, name.replace('@2x', '')), optimize=True)
    print('done')


if __name__ == '__main__':
    main()
