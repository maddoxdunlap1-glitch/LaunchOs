import json, socket, sys, time

# Precise mouse input for the test VM through QMP (USB tablet, absolute position).
#   qmp.py SOCK click X Y [ctrl|right]     click at screen pixel X,Y (1280x800 screen)
#   qmp.py SOCK move X Y
W, H = 1280, 800
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); f = s.makefile('rw')
f.readline()
def cmd(c, a=None):
    f.write(json.dumps({'execute': c, **({'arguments': a} if a else {})}) + '\n'); f.flush()
    while True:
        r = json.loads(f.readline())
        if 'return' in r or 'error' in r:
            return r
cmd('qmp_capabilities')
def ev(events): return cmd('input-send-event', {'events': events})
def pos(x, y): return [{'type': 'abs', 'data': {'axis': 'x', 'value': int(x * 32767 / W)}},
                       {'type': 'abs', 'data': {'axis': 'y', 'value': int(y * 32767 / H)}}]
def key(k, down): return {'type': 'key', 'data': {'down': down, 'key': {'type': 'qcode', 'data': k}}}
def btn(b, down): return {'type': 'btn', 'data': {'down': down, 'button': b}}
op, x, y = sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
mod = sys.argv[5] if len(sys.argv) > 5 else ''
# wiggle in so the page sees real movement
ev(pos(x - 6, y - 6)); time.sleep(0.15); ev(pos(x, y)); time.sleep(0.3)
if op == 'click':
    b = 'right' if mod == 'right' else 'left'
    if mod == 'ctrl': ev([key('ctrl', True)]); time.sleep(0.15)
    ev([btn(b, True)]); time.sleep(0.12); ev([btn(b, False)])
    if mod == 'ctrl': time.sleep(0.15); ev([key('ctrl', False)])
print('ok')
