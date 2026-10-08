import base64, socket, sys, time, zlib
# push.py SOCK LOCAL REMOTE : copies a file into the VM over the serial console
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.settimeout(0.2)
def drain():
    o = b''
    try:
        while True: o += s.recv(65536)
    except socket.timeout: pass
    return o
data = base64.b64encode(zlib.compress(open(sys.argv[2], 'rb').read(), 9)).decode()
drain()
s.send(b"stty -echo; python3 -c \"import sys,base64,zlib;open(sys.argv[1],'wb').write(zlib.decompress(base64.b64decode(sys.stdin.read())))\" " + sys.argv[3].encode() + b" <<'ZZZ'\n")
time.sleep(0.5)
for i in range(0, len(data), 1000):
    s.send(data[i:i+1000].encode() + b'\n'); time.sleep(0.12); drain()
s.send(b"ZZZ\nstty echo; echo PUSHED_$?\n")
o = b''; e = time.time() + 30
while time.time() < e and b'PUSHED_' not in o:
    o += drain()
print(o.decode(errors='replace')[-60:])
