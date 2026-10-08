#!/usr/bin/env python3
"""Makes the files the Pro server hands out (upload them to the R2 bucket, see SETUP.md):

  pro-package.tar.gz   the Pro extras (src/pro: live backgrounds), installed to /opt/launchos-pro
  pro-update.json      its version and SHA-256 (LaunchOS checks the download against it)

and, for early access, a LaunchOS update that only Pro PCs get:

  early-update.tar.gz / early-update.json   a copy of a launchos-update.tar.gz/.json pair

  python3 make-pro-files.py OUTDIR [--version 1.0] [--early launchos-update.json launchos-update.tar.gz]
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.join(HERE, '..', 'src', 'pro')


def add(tar, path, data, mode=0o644):
    info = tarfile.TarInfo(path)
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    tar.addfile(info, io.BytesIO(data))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--version', default='1.0')
    ap.add_argument('--early', nargs=2, metavar=('JSON', 'TARGZ'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for d in ('opt', 'opt/launchos-pro', 'opt/launchos-pro/live'):
            info = tarfile.TarInfo(d)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
            tar.addfile(info)
        add(tar, 'opt/launchos-pro/manifest.json', json.dumps({'version': a.version, 'made': time.strftime('%Y-%m-%d')}).encode())
        for name in sorted(os.listdir(os.path.join(PRO, 'live'))):
            if name.endswith('.js'):
                add(tar, 'opt/launchos-pro/live/' + name, open(os.path.join(PRO, 'live', name), 'rb').read())
    data = buf.getvalue()
    open(os.path.join(a.out, 'pro-package.tar.gz'), 'wb').write(data)
    json.dump({'version': a.version, 'sha256': hashlib.sha256(data).hexdigest(), 'file': 'pro-package.tar.gz'},
              open(os.path.join(a.out, 'pro-update.json'), 'w'), indent=1)
    if a.early:
        shutil.copy(a.early[0], os.path.join(a.out, 'early-update.json'))
        shutil.copy(a.early[1], os.path.join(a.out, 'early-update.tar.gz'))
    for f in sorted(os.listdir(a.out)):
        print(f, os.path.getsize(os.path.join(a.out, f)), 'bytes')


if __name__ == '__main__':
    main()
