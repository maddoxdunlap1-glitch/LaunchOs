"""Signed files from the LaunchOS Pro server (the Pro extras' and early-access updates' manifests).

The server only stores and hands out files; they're signed beforehand with the LaunchOS Pro
signing key (Ed25519, kept off the server), whose public half is signing_key= in
/etc/launchos/pro.conf. So whoever gets into the server can't push anything to Pro PCs.

A signed file is JSON: {"payload": base64 of the real JSON, "sig": base64 Ed25519 signature}.
"""
import base64
import json
import os
import re
import subprocess
import tempfile

CONF = '/etc/launchos/pro.conf'
# an Ed25519 public key in the usual one-line form (base64 of its 44-byte DER encoding)
KEY_RE = re.compile(r'MCowBQYDK2VwAyEA[A-Za-z0-9+/]{43}=')


def public_key(conf_path=None):
    try:
        for line in open(conf_path or CONF):
            if line.strip().startswith('signing_key='):
                k = line.split('=', 1)[1].strip()
                return k if KEY_RE.fullmatch(k) else ''
    except OSError:
        pass
    return ''


def verify(blob, conf_path=None):
    """The JSON object inside a signed file, or ValueError if it isn't signed with our key."""
    key = public_key(conf_path)
    if not key:
        raise ValueError('no signing key')
    try:
        w = json.loads(blob)
        payload = base64.b64decode(str(w['payload']), validate=True)
        sig = base64.b64decode(str(w['sig']), validate=True)
    except (ValueError, KeyError, TypeError):
        raise ValueError('not a signed file')
    if len(sig) != 64 or len(payload) > (1 << 20):
        raise ValueError('not a signed file')
    with tempfile.TemporaryDirectory(prefix='launchos-sig.') as d:
        kp, pp, sp = os.path.join(d, 'key.pem'), os.path.join(d, 'payload'), os.path.join(d, 'sig')
        with open(kp, 'w') as f:
            f.write('-----BEGIN PUBLIC KEY-----\n' + key + '\n-----END PUBLIC KEY-----\n')
        with open(pp, 'wb') as f:
            f.write(payload)
        with open(sp, 'wb') as f:
            f.write(sig)
        r = subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', kp, '-rawin', '-in', pp, '-sigfile', sp],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            raise ValueError('bad signature')
    m = json.loads(payload)
    if not isinstance(m, dict):
        raise ValueError('not a signed file')
    return m
