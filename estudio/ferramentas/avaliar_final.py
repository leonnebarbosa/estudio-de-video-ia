"""Avalia o video final de um projeto: duracao, audio, deriva de cor, saltos e folha de quadros.
Uso: avaliar_final.py projeto saida.jpg"""
import json, sys
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

if sys.stdout is not None:  # no pythonw.exe nao ha console
    sys.stdout.reconfigure(encoding="utf-8")
pasta = config.PROJETOS / sys.argv[1]
c = av.open(str(pasta / "final.mp4"))
v = c.streams.video[0]
a = c.streams.audio[0] if c.streams.audio else None
print(f"{v.width}x{v.height} {float(v.average_rate)} fps | {c.duration / 1e6:.2f} s | audio {a.codec_context.name if a else 'nao'} {a.rate if a else ''} | {(pasta / 'final.mp4').stat().st_size / 1e6:.1f} MB")
q = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]
print("quadros", len(q))
c.close()
c = av.open(str(pasta / "final.mp4"))
amostras = np.concatenate([f.to_ndarray().mean(axis=0) for f in c.decode(audio=0)])
sr = c.streams.audio[0].rate
print("audio rms por 5 s:", [round(float((amostras[i:i + 5 * sr] ** 2).mean() ** 0.5), 4) for i in range(0, len(amostras), 5 * sr)])
print("audio duracao", round(len(amostras) / sr, 2))
c.close()
d = np.array([float(np.abs(q[i + 1].astype(np.int16) - q[i].astype(np.int16)).mean()) for i in range(len(q) - 1)])
med = float(np.median(d))
print(f"dif. entre quadros: mediana {med:.2f} | max {d.max():.2f} no {int(d.argmax())}")
print("cor media a cada 90 quadros:", [[round(float(x), 1) for x in np.mean([f.mean(axis=(0, 1)) for f in q[i:i + 8]], axis=0)] for i in range(0, len(q), 90)])
e = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
soma = 0
fronteiras = []
for i, r in enumerate(e["rodadas"]):
    pular = r["pular"]
    fim = r["total"] - (0 if i == len(e["rodadas"]) - 1 else r["sobreposicao"])
    soma += fim - pular
    fronteiras.append(soma)
print("fronteiras:", fronteiras)
for f in fronteiras[:-1]:
    if f < len(d) - 2:
        print(f"  q{f}: dif {[round(float(x), 1) for x in d[f - 2:f + 3]]} | luz antes {np.mean([x.mean() for x in q[f - 8:f]]):.1f} depois {np.mean([x.mean() for x in q[f:f + 8]]):.1f}")
idx = list(np.linspace(0, len(q) - 1, 24).astype(int))
W, H = 240, int(240 * v.height / v.width)
col = 6
F = Image.new("RGB", (col * W, (len(idx) // col) * H))
D = ImageDraw.Draw(F)
for k, i in enumerate(idx):
    x, y = (k % col) * W, (k // col) * H
    F.paste(Image.fromarray(q[i]).resize((W, H)), (x, y))
    D.rectangle((x, y, x + 62, y + 14), fill="black")
    D.text((x + 3, y + 1), f"{i / 24:.1f}s", fill="white")
F.save(sys.argv[2], quality=86)
