"""Draws a still of the boot animation (same layout as launchos.script) to check the artwork."""
import math, random, sys
from PIL import Image
T = '../boot-theme/plymouth-launchos/'
W, H = 1920, 1080
def frame(t, out=None):
    random.seed(3)
    f = Image.open(T + 'bg.png').resize((W, H), Image.BILINEAR).convert('RGBA')
    stars = [Image.open(T + f'star{i}.png') for i in range(3)]
    for k in range(60):
        layer = k % 3; x = random.random() * W; y0 = random.random() * H
        speed = (2.2, 1.2, 0.6)[layer]
        y = (y0 + t * speed) % (H + 20) - 10
        st = stars[layer]; f.alpha_composite(st, (int(x - st.width / 2), int(y - st.height / 2)))
    streak = Image.open(T + 'streak.png')
    for k in range(5):
        x = W * (0.2 + 0.6 * random.random()); y = (random.random() * H + t * 9) % (H + 220) - 110
        f.alpha_composite(streak, (int(x), int(y)))
    rocket = Image.open(T + 'rocket.png'); glow = Image.open(T + 'glow.png')
    cx = W // 2; top = int(H / 2 - 300 + math.sin(t * 0.05) * 4)
    nozzle = top + 320
    f.alpha_composite(glow, (cx - glow.width // 2, nozzle - glow.height // 2 + 30))
    fl = Image.open(T + f'flame{(t // 2) % 12}.png')
    f.alpha_composite(fl, (cx - fl.width // 2, nozzle - 8))
    f.alpha_composite(rocket, (cx - rocket.width // 2, top))
    return f
for t in (0, 17, 40):
    frame(t).convert('RGB').save(sys.argv[1] + f'/boot-preview-{t}.png')
