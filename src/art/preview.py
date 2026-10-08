"""Draws the boot animation the way launchos.script does, for previews: python3 preview.py OUT.gif
(also used to check the artwork without starting a PC)."""
import math
import random
import sys

from PIL import Image

T = '../boot-theme/plymouth-launchos/'
W, H = 1280, 720
S = H / 1080


def load(name, scale=S):
    im = Image.open(T + name + '@2x.png')
    k = scale / 2
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def main(out):
    random.seed(3)
    bg = Image.open(T + 'bg.png').resize((W, H), Image.BILINEAR).convert('RGBA')
    stars = [load(f'star{i}') for i in range(3)]
    rocket, glow, puff, streak = load('rocket'), load('glow'), load('puff'), load('streak')
    flames = [load(f'flame{i}') for i in range(12)]
    st = [[random.random() * W, random.random() * H, k % 3, (0.6 + 0.8 * random.random()) * S * (2.6 - (k % 3) * 0.9)] for k in range(54)]
    sk = [[W * (0.15 + 0.7 * random.random()), random.random() * H, (7 + 5 * random.random()) * S] for _ in range(5)]
    puffs = [[-1 - i * 7, 0, 0, 0, 0] for i in range(10)]
    cx, top = W / 2, H / 2 - 300 * S
    frames = []
    for tick in range(1, 97):
        f = bg.copy()
        for s in st:
            s[1] += s[3]
            if s[1] > H + 10:
                s[1] = -10
                s[0] = random.random() * W
            f.alpha_composite(stars[s[2]], (int(s[0]), int(s[1])))
        for k in sk:
            k[1] += k[2]
            if k[1] > H + 20:
                k[1] = -streak.height - random.random() * H * 0.5
                k[0] = W * (0.12 + 0.76 * random.random())
            f.alpha_composite(streak, (int(k[0]), int(k[1])))
        y = top + math.sin(tick * 0.045) * 6 * S + math.sin(tick * 1.7) * 0.6 * S
        noz = 320 * S
        g = glow.copy()
        g.putalpha(g.getchannel('A').point(lambda a: int(a * (0.8 + 0.2 * math.sin(tick * 0.31)))))
        f.alpha_composite(g, (int(cx - g.width / 2), int(y + noz - g.height / 2 + 40 * S)))
        for p in puffs:
            p[0] += 1
            if p[0] == 0:
                p[1], p[2] = cx + (random.random() - 0.5) * 30 * S, y + noz + 150 * S
                p[3], p[4] = (random.random() - 0.5) * 2.2 * S, (2.2 + random.random() * 1.4) * S
            if p[0] >= 0:
                p[1] += p[3]
                p[2] += p[4]
                o = max(0, 0.55 * (1 - p[0] / 70))
                pi = puff.copy()
                pi.putalpha(pi.getchannel('A').point(lambda a: int(a * o)))
                f.alpha_composite(pi, (int(p[1] - pi.width / 2), int(p[2])))
                if p[0] > 70:
                    p[0] = -int(random.random() * 8)
        fl = flames[(tick // 2) % 12]
        f.alpha_composite(fl, (int(cx - fl.width / 2), int(y + noz - 8 * S)))
        f.alpha_composite(rocket, (int(cx - rocket.width / 2), int(y)))
        if tick % 2 == 0:
            frames.append(f.convert('RGB').resize((640, 360), Image.LANCZOS))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=40, loop=0, optimize=True)


if __name__ == '__main__':
    main(sys.argv[1])
