import socket,time,sys
s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.settimeout(1)
log=open(sys.argv[1]+'.log','ab')
def rd(t):
    o=b''; e=time.time()+t
    while time.time()<e:
        try:
            d=s.recv(4096); o+=d; log.write(d); log.flush()
        except socket.timeout: pass
    return o
o=b''; e=time.time()+float(sys.argv[2])
s.send(b'\n')
while time.time()<e and b'login:' not in o and b'# ' not in o: o+=rd(3); s.send(b'\n')
if b'login:' in o:
    s.send(b'root\n'); rd(4); s.send(b'launchos\n'); rd(8)
for cmd in sys.argv[3:]:
    s.send((cmd+'; echo DONE_MARK\n').encode())
    o=b''; e=time.time()+150
    while time.time()<e and b'DONE_MARK\r\n' not in o.split(b'echo DONE_MARK',1)[-1]: o+=rd(2)
    print(o.decode(errors='replace').replace('\r',''))
