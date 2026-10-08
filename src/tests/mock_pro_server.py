#!/usr/bin/env python3
"""A stand-in for the LaunchOS Pro server (pro-server/src/index.js), for testing LaunchOS in a VM.
Same calls and answers; keys and PC slots are kept in memory.

  python3 mock_pro_server.py FILES_DIR [PORT]     (files: pro-package.tar.gz, pro-update.json, ...)

Valid key: TEST-KEY-1234-ABCD (5 PCs). REFUND-KEY-0000 acts like a refunded key.
In the VM, set url=http://10.0.2.2:PORT in /etc/launchos/pro.conf.
"""
import hashlib, hmac, json, os, re, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

FILES = {'pro-package.tar.gz', 'pro-update.json', 'early-update.json', 'early-update.tar.gz'}
SECRET = b'test-secret'
KEYS = {'TEST-KEY-1234-ABCD': {}, 'REFUND-KEY-0000': {}}
LOG = []


class H(BaseHTTPRequestHandler):
    def reply(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        LOG.append(fmt % args)
        sys.stderr.write(fmt % args + '\n')

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == '/log':
            return self.reply(LOG[-50:])
        m = re.fullmatch(r'/v1/file/([\w.-]+)', u.path)
        if not m or m.group(1) not in FILES:
            return self.reply({'ok': False, 'error': 'not_found'}, 404)
        q = parse_qs(u.query)
        exp, sig = int((q.get('exp') or ['0'])[0]), (q.get('sig') or [''])[0]
        want = hmac.new(SECRET, f'{m.group(1)}.{exp}'.encode(), hashlib.sha256).hexdigest()
        if exp < time.time() or not hmac.compare_digest(sig, want):
            return self.reply({'ok': False, 'error': 'expired'}, 403)
        path = os.path.join(sys.argv[1], m.group(1))
        if not os.path.exists(path):
            return self.reply({'ok': False, 'error': 'not_found'}, 404)
        data = open(path, 'rb').read()
        self.send_response(200)
        self.send_header('content-type', 'application/octet-stream')
        self.send_header('content-length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            b = json.loads(self.rfile.read(int(self.headers.get('content-length') or 0)) or b'{}')
        except ValueError:
            return self.reply({'ok': False, 'error': 'bad_request'}, 400)
        key = str(b.get('key', ''))
        if self.path == '/v1/activate':
            if key not in KEYS:
                return self.reply({'ok': False, 'error': 'invalid_key'}, 403)
            if key.startswith('REFUND'):
                return self.reply({'ok': False, 'error': 'revoked'}, 403)
            if len(KEYS[key]) >= 5:
                return self.reply({'ok': False, 'error': 'pc_limit'}, 403)
            iid = str(uuid.uuid4())
            KEYS[key][iid] = b.get('pc_id')
            return self.reply({'ok': True, 'instance_id': iid})
        ok = key in KEYS and str(b.get('instance_id', '')) in KEYS[key]
        if self.path == '/v1/check':
            return self.reply({'ok': True} if ok else {'ok': False, 'error': 'invalid_key'}, 200 if ok else 403)
        if self.path == '/v1/deactivate':
            if ok:
                del KEYS[key][b['instance_id']]
            return self.reply({'ok': ok} if ok else {'ok': False, 'error': 'invalid_key'}, 200 if ok else 403)
        if self.path == '/v1/download':
            if not ok:
                return self.reply({'ok': False, 'error': 'invalid_key'}, 403)
            f = str(b.get('file', ''))
            if f not in FILES:
                return self.reply({'ok': False, 'error': 'bad_request'}, 400)
            exp = int(time.time()) + 600
            sig = hmac.new(SECRET, f'{f}.{exp}'.encode(), hashlib.sha256).hexdigest()
            host = self.headers.get('host')
            return self.reply({'ok': True, 'url': f'http://{host}/v1/file/{f}?exp={exp}&sig={sig}', 'expires_in': 600})
        self.reply({'ok': False, 'error': 'not_found'}, 404)


if __name__ == '__main__':
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()
