import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.settimeout(1)
t0 = time.time(); buf = b''
s.send(sys.argv[2].encode() + b'\n')
end = time.time() + float(sys.argv[3])
while time.time() < end:
    try:
        d = s.recv(4096)
        if not d: break
        buf += d
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            l = line.decode(errors='replace').strip()
            if l: print(f'{time.time()-t0:6.1f} {l[:150]}', flush=True)
    except socket.timeout: pass
    except OSError: break
print('reader ended at', round(time.time()-t0, 1))
