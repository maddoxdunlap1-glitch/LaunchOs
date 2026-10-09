#!/usr/bin/env python3
"""Writes live/aurora-src.js: the Aurora wallpaper's shader source, for the Living aurora live
background. Run again after changing src/art/walls/common.glsl or aurora.glsl."""
import json, os
here = os.path.dirname(os.path.abspath(__file__))
walls = os.path.join(here, '..', 'art', 'walls')
src = open(os.path.join(walls, 'common.glsl')).read() + '\n' + open(os.path.join(walls, 'aurora.glsl')).read()
with open(os.path.join(here, 'live', 'aurora-src.js'), 'w') as f:
    f.write('/* Made by make-live-src.py from src/art/walls/common.glsl and aurora.glsl. */\nwindow.LOSAuroraSrc = ' + json.dumps(src) + ';\n')
