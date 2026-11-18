"""Monta uma folha de quadros de um video para inspecao. Uso: folha_quadros.py video.mp4 saida.jpg q1 q2 ... (negativos contam do fim)"""
import sys

import av
from PIL import Image, ImageDraw

c = av.open(sys.argv[1])
q = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]
idx = [int(x) if int(x) >= 0 else len(q) + int(x) for x in sys.argv[3:]]
h, w = q[0].shape[:2]
W = 300
H = int(W * h / w)
col = 4
lin = (len(idx) + col - 1) // col
F = Image.new("RGB", (col * W, lin * H))
D = ImageDraw.Draw(F)
for k, i in enumerate(idx):
    x, y = (k % col) * W, (k // col) * H
    F.paste(Image.fromarray(q[i]).resize((W, H)), (x, y))
    D.rectangle((x, y, x + 50, y + 14), fill="black")
    D.text((x + 3, y + 1), f"q{i}", fill="white")
F.save(sys.argv[2], quality=86)
print(len(q), "quadros", w, "x", h)
