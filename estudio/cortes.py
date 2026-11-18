"""Cortes de camera num video: onde um plano termina e outro comeca.

Adaptado de app/shot.py do Imagination Studio (github.com/Keys-Wasserman/Imagination-Studio-by-keys-Wasserman,
Apache-2.0), que mediu os limites em 7081 pares de quadros: um corte tem correlacao com o quadro anterior abaixo de
CORRELACAO e uma mudanca CRESCIMENTO vezes maior que a mediana dos quadros em volta. Movimento rapido muda o trecho
inteiro (nao so um par) e uma fusao muda devagar, entao nenhum dos dois conta como corte.

A troca de personagem usa isto para mostrar os cortes no editor do trecho e para recomecar as janelas num corte, sem
carregar os quadros do plano anterior (como o Henge faz).
"""
from pathlib import Path

LARGURA = 160          # copias cinza pequenas: 160x90 num video 16:9
CORRELACAO = 0.70      # correlacao com o quadro anterior abaixo disto...
CRESCIMENTO = 1.75     # ...e mudanca pelo menos isto vezes a mediana dos vizinhos
VIZINHOS = 6           # quadros de cada lado
PISO = 0.5             # tons de cinza: num trecho parado, uma mudanca pequena nao vira uma razao grande
_cache = {}


def _cinzas(caminho):
    """(quadros cinza [n, h, w], fps) com o PyAV, que o ComfyUI ja tem."""
    import av
    import numpy as np
    from PIL import Image
    saida, tam = [], None
    with av.open(str(caminho)) as c:
        v = c.streams.video[0]
        fps = float(v.average_rate or 24)
        for q in c.decode(video=0):
            if tam is None:
                tam = (LARGURA, max(2, round(LARGURA * q.height / q.width)))
            saida.append(np.asarray(q.to_image().convert("L").resize(tam, Image.BILINEAR), np.float32))
    return (np.stack(saida) if saida else np.zeros((0, 2, 2), np.float32)), fps


def _parecido(a, b):
    import numpy as np
    um, dois = a - a.mean(), b - b.mean()
    escala = float(np.sqrt((um * um).sum() * (dois * dois).sum()))
    return float((um * dois).sum() / escala) if escala > 1e-6 else 0.0


def achar(quadros, fps):
    """Os cortes: cada um com o quadro e o segundo em que o novo plano comeca."""
    import numpy as np
    if len(quadros) < 3:
        return []
    mudanca = np.abs(quadros[1:] - quadros[:-1]).mean(axis=(1, 2))
    achados = []
    for i in range(len(mudanca)):
        volta = np.concatenate([mudanca[max(0, i - VIZINHOS):i], mudanca[i + 1:i + 1 + VIZINHOS]])
        razao = float(mudanca[i] / max(float(np.median(volta)) if len(volta) else 0.0, PISO))
        if razao >= CRESCIMENTO and _parecido(quadros[i], quadros[i + 1]) < CORRELACAO:
            achados.append({"quadro": i + 1, "segundos": round((i + 1) / fps, 3)})
    return achados


def cortes(caminho):
    """Os cortes de um arquivo, guardados enquanto ele nao muda."""
    caminho = Path(caminho)
    chave = (str(caminho.resolve()), caminho.stat().st_mtime_ns)
    if chave not in _cache:
        quadros, fps = _cinzas(caminho)
        _cache[chave] = achar(quadros, fps)
    return _cache[chave]
