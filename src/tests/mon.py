import socket, sys, time

# Sends raw QEMU monitor commands, one per argument; "SLEEP:n" waits.
for arg in sys.argv[2:]:
    if arg.startswith('SLEEP:'):
        time.sleep(float(arg[6:]))
        continue
    s = socket.socket(socket.AF_UNIX)
    s.connect(sys.argv[1])
    s.recv(4096)
    s.send((arg + '\n').encode())
    time.sleep(0.3)
    s.close()
