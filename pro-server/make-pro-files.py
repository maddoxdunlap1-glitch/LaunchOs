#!/usr/bin/env python3
"""Makes the files the Pro server hands out (upload them to the R2 bucket, see SETUP.md):

  pro-package.tar.gz   the Pro extras (src/pro: live backgrounds), installed to /opt/launchos-pro
  pro-update.json      its version and SHA-256, signed with the Pro signing key

and, for early access, a LaunchOS update that only Pro PCs get:

  early-update.tar.gz / early-update.json   made from a launchos-update.tar.gz (see
                                            src/build/debian/make-update.sh), marked as an early
                                            build, its manifest signed

LaunchOS only installs files signed with the Pro signing key, whose public half is signing_key=
in src/rootfs/etc/launchos/pro.conf. Make the key once with --new-key and keep the private half
safe and off the server (a password manager, plus a GitHub secret PRO_SIGNING_KEY for the
"Pro files" workflow).

  python3 make-pro-files.py --new-key launchos-pro-signing.key
  python3 make-pro-files.py OUTDIR --key launchos-pro-signing.key [--version 1.0]
          [--early launchos-update.tar.gz VERSION]
  (or the key's text in the environment variable PRO_SIGNING_KEY instead of --key)
"""
import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.join(HERE, '..', 'src', 'pro')


def add(tar, path, data, mode=0o644):
    info = tarfile.TarInfo(path)
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    tar.addfile(info, io.BytesIO(data))


def openssl(*args, data=None):
    r = subprocess.run(['openssl', *args], input=data, capture_output=True)
    if r.returncode != 0:
        sys.exit('openssl failed: ' + r.stderr.decode(errors='replace'))
    return r.stdout


def new_key(path):
    if os.path.exists(path):
        sys.exit(path + ' already exists: not overwriting a signing key')
    old = os.umask(0o077)
    try:
        openssl('genpkey', '-algorithm', 'ed25519', '-out', path)
    finally:
        os.umask(old)
    pub = openssl('pkey', '-in', path, '-pubout').decode()
    line = ''.join(l for l in pub.splitlines() if not l.startswith('-----'))
    print('Private key (keep it safe, never on the server or in the repo):', path)
    print('Public key, for signing_key= in src/rootfs/etc/launchos/pro.conf:')
    print(line)


class Signer:
    def __init__(self, keyfile):
        self.dir = tempfile.mkdtemp(prefix='pro-sign.')
        self.key = os.path.join(self.dir, 'key.pem')
        text = open(keyfile).read() if keyfile else os.environ.get('PRO_SIGNING_KEY', '')
        if 'PRIVATE KEY' not in text:
            sys.exit('no signing key: give --key FILE or set PRO_SIGNING_KEY (make one with --new-key)')
        fd = os.open(self.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(text.strip() + '\n')
        self.public = ''.join(l for l in openssl('pkey', '-in', self.key, '-pubout').decode().splitlines()
                              if not l.startswith('-----'))

    def sign(self, obj):
        payload = json.dumps(obj, indent=1).encode()
        p = os.path.join(self.dir, 'payload')
        open(p, 'wb').write(payload)
        sig = openssl('pkeyutl', '-sign', '-inkey', self.key, '-rawin', '-in', p)
        return json.dumps({'payload': base64.b64encode(payload).decode(), 'sig': base64.b64encode(sig).decode()}, indent=1)

    def close(self):
        for f in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, f))
        os.rmdir(self.dir)


def early_package(src, version):
    """A copy of a LaunchOS update package marked as an early build of VERSION."""
    out = io.BytesIO()
    with tarfile.open(src, 'r:gz') as t, tarfile.open(fileobj=out, mode='w:gz') as o:
        for m in t.getmembers():
            if m.name.lstrip('./') == 'etc/launchos-release':
                data = ('NAME="LaunchOS"\nVERSION="%s"\nBUILD_DATE="%s"\nEARLY="1"\n' % (version, time.strftime('%Y-%m-%d'))).encode()
                m.size = len(data)
                o.addfile(m, io.BytesIO(data))
            else:
                o.addfile(m, t.extractfile(m) if m.isfile() else None)
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?')
    ap.add_argument('--new-key', metavar='FILE')
    ap.add_argument('--key', metavar='FILE')
    ap.add_argument('--version', default='1.0', help='version of the Pro extras')
    ap.add_argument('--early', nargs=2, metavar=('UPDATE_TARGZ', 'VERSION'),
                    help='also make an early-access update from this launchos-update.tar.gz')
    ap.add_argument('--min-version', default='1.0', help='oldest LaunchOS the early update can update')
    ap.add_argument('--notes', default='')
    a = ap.parse_args()
    if a.new_key:
        new_key(a.new_key)
        return
    if not a.out:
        ap.error('OUTDIR is needed')
    signer = Signer(a.key)
    try:
        conf = open(os.path.join(HERE, '..', 'src', 'rootfs', 'etc', 'launchos', 'pro.conf')).read()
        if 'signing_key=' + signer.public not in conf:
            print('warning: this key isn\'t the one in src/rootfs/etc/launchos/pro.conf; LaunchOS won\'t accept these files',
                  file=sys.stderr)
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
        open(os.path.join(a.out, 'pro-update.json'), 'w').write(signer.sign(
            {'version': a.version, 'sha256': hashlib.sha256(data).hexdigest(), 'file': 'pro-package.tar.gz'}))
        if a.early:
            pkg = early_package(a.early[0], a.early[1])
            open(os.path.join(a.out, 'early-update.tar.gz'), 'wb').write(pkg)
            open(os.path.join(a.out, 'early-update.json'), 'w').write(signer.sign(
                {'version': a.early[1], 'sha256': hashlib.sha256(pkg).hexdigest(), 'file': 'early-update.tar.gz',
                 'min_version': a.min_version, 'full': False, 'apt': [], 'notes': a.notes}))
    finally:
        signer.close()
    for f in sorted(os.listdir(a.out)):
        print(f, os.path.getsize(os.path.join(a.out, f)), 'bytes')


if __name__ == '__main__':
    main()
