#!/usr/bin/env python3
"""Renders the wallpapers at full size and saves them for the launcher (src/ui/walls/):
1920x1080 WebP pictures plus small previews for the picker in Setup.
Run from this folder:  python3 export.py [names...]"""
import os
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'ui', 'walls')
NAMES = ['liftoff', 'nebula', 'aurora', 'orbit', 'dunes', 'waves', 'grid']
CONTOUR = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720"><rect width="1280" height="720" fill="#0b1726"/><defs><path id="c" d="M-210 30 C-150 -110 120 -130 220 -10 C300 95 85 165 -50 130 C-170 100 -250 95 -210 30 Z" fill="none" stroke="#cfe6ff"/></defs><g transform="translate(420 210)"><use href="#c" transform="scale(.5)" opacity=".2" stroke-width="2"/><use href="#c" transform="scale(.8)" opacity=".17" stroke-width="1.3"/><use href="#c" transform="scale(1.15)" opacity=".14" stroke-width="1"/><use href="#c" transform="scale(1.6)" opacity=".12" stroke-width=".8"/><use href="#c" transform="scale(2.1)" opacity=".1" stroke-width=".6"/></g><g transform="translate(1040 190)"><use href="#c" transform="scale(.45)" opacity=".2" stroke-width="2"/><use href="#c" transform="scale(.8)" opacity=".16" stroke-width="1.2"/><use href="#c" transform="scale(1.2)" opacity=".13" stroke-width=".9"/><use href="#c" transform="scale(1.7)" opacity=".1" stroke-width=".7"/></g></svg>'''


def main():
    names = sys.argv[1:] or NAMES
    os.makedirs(os.path.join(OUT, 'thumbs'), exist_ok=True)
    node_path = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['node', os.path.join(HERE, 'render-walls.js'), tmp, '1920', '1080', '2', *names],
                       check=True, env=dict(os.environ, NODE_PATH=node_path))
        for n in names:
            im = Image.open(os.path.join(tmp, n + '.png')).convert('RGB')
            im.save(os.path.join(OUT, n + '.webp'), quality=88, method=6)
            im.resize((384, 216), Image.LANCZOS).save(os.path.join(OUT, 'thumbs', n + '.webp'), quality=85, method=6)
            if n == 'liftoff':   # for the website and README
                im.save(os.path.join(HERE, '..', '..', '..', 'docs', 'assets', 'wallpaper-liftoff.jpg'), quality=86, optimize=True, progressive=True)
            print(n, os.path.getsize(os.path.join(OUT, n + '.webp')) // 1024, 'KB')
        # the classic contour lines and the plain background only need previews
        svg = os.path.join(tmp, 'contour.svg')
        open(svg, 'w').write(CONTOUR)
        subprocess.run(['node', os.path.join(HERE, '..', 'render-svg.js'), svg, os.path.join(tmp, 'contour.png'), '1280', '720'],
                       check=True, env=dict(os.environ, NODE_PATH=node_path))
        Image.open(os.path.join(tmp, 'contour.png')).convert('RGB').resize((384, 216), Image.LANCZOS) \
            .save(os.path.join(OUT, 'thumbs', 'contour.webp'), quality=85, method=6)
        Image.new('RGB', (384, 216), (11, 23, 38)).save(os.path.join(OUT, 'thumbs', 'plain.webp'), quality=85)


if __name__ == '__main__':
    main()
