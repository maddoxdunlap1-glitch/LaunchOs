from PIL import Image
import math, sys
W,H=640,400; R=150; s=H/1080*1.6
bg=(11,23,38,255)
wheel=Image.open('wheel.png'); stand=Image.open('stand.png'); glow=Image.open('glow.png'); gs=[Image.open(f'gondola{i}.png') for i in range(8)]
sc=lambda im: im.resize((max(1,round(im.width*s)),max(1,round(im.height*s))),Image.LANCZOS)
wheel,stand,glow=sc(wheel),sc(stand),sc(glow); gs=[sc(g) for g in gs]
cx,cy=W/2,H/2-30*s
def frame(angle):
    f=Image.new('RGBA',(W,H),bg)
    f.alpha_composite(glow,(round(cx-glow.width/2),round(cy-glow.height/2)))
    f.alpha_composite(stand,(round(cx-stand.width/2),round(cy-18*s)))
    w=wheel.rotate(-math.degrees(angle),resample=Image.BICUBIC)
    f.alpha_composite(w,(round(cx-w.width/2),round(cy-w.height/2)))
    for i,g in enumerate(gs):
        a=angle+i*math.pi/4; x=cx+math.cos(a)*R*s; y=cy+math.sin(a)*R*s
        f.alpha_composite(g,(round(x-g.width/2),round(y)))
    return f.convert('RGB')
frames=[frame(k*2*math.pi/8/40) for k in range(40)]  # 45 degrees = one gondola period, loops seamlessly
frames[0].save('preview.png')
frames[0].save('preview.gif',save_all=True,append_images=frames[1:],duration=40,loop=0,optimize=True)
