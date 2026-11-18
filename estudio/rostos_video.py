"""Rostos de um vídeo para a biblioteca de personagens: os melhores rostos de frente, três quartos e perfil, para o usuário
escolher (desenho em docs/superpowers/specs/2026-11-17-rostos-do-video-design.md; validado no rascunho de 17/11/2026).

O YuNet (modelos_aux, o mesmo do troca_foto) acha o rosto e 5 pontos. O ângulo vem da posição do nariz entre os olhos
(giro) e da distância entre os olhos em relação à largura do rosto (abertura). A nitidez é a variância do Laplaciano no
rosto. Tudo na CPU: não usa a placa nem a fila.

- Legenda fixa do vídeo (texto branco que não muda): o pixel claro em quase todos os quadros vira máscara; um rosto
  coberto por ela não é oferecido.
- Confiança abaixo de 0,75: no teste o YuNet confundiu nuca com rosto.
- Em cada quadro vale só o maior rosto (num vídeo com duas pessoas, o usuário escolhe olhando).
"""
import json, re, shutil, threading, time
from pathlib import Path

import cv2
import numpy as np

import config

YUNET = config.ESTUDIO / "modelos_aux" / "face_detection_yunet_2023mar.onnx"
ANGULOS = ("frente", "tres_quartos", "perfil")
AMOSTRA_LEGENDA = 60


def classificar(l):
    """O ângulo de um rosto medido, ou None se ele não serve de referência."""
    if l["conf"] < 0.75 or l["caixa"][2] < 120 or l["legenda"] > 0.003:
        return None
    g = abs(l["giro"])
    if g < 0.12 and l["abertura"] > 0.35:
        return "frente"
    if 0.25 <= g < 0.6:
        return "tres_quartos"
    if g >= 0.6 or l["abertura"] < 0.22:
        return "perfil"
    return None


def mascara_legenda(cinzas):
    """1 onde o pixel é claro (> 225) em mais de 85% dos quadros, dilatado 15x15."""
    claro = np.mean([c > 225 for c in cinzas], axis=0)
    return cv2.dilate((claro > 0.85).astype(np.uint8), np.ones((15, 15), np.uint8))


def nota(l):
    return l["nitidez"] * l["conf"] * min(1.0, l["caixa"][2] / 300)


def escolher(linhas, por_angulo=6, distancia=1.0):
    """Os melhores de cada ângulo, a pelo menos `distancia` segundos um do outro."""
    for l in linhas:
        l["faixa"] = classificar(l)
    saida = {}
    for a in ANGULOS:
        escolhidos = []
        for l in sorted((l for l in linhas if l["faixa"] == a), key=nota, reverse=True):
            if all(abs(l["t"] - e["t"]) >= distancia for e in escolhidos):
                escolhidos.append(l)
            if len(escolhidos) == por_angulo:
                break
        saida[a] = escolhidos
    return saida


def detector():
    return cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.5)


LADO_DETECCAO = 640   # o YuNet erra mais (e demora) num quadro de 1080p; a caixa e os pontos voltam ao tamanho original
CONF_MINIMA = 0.75    # revisão de 18/11: uma detecção falsa (conf 0,67) um pouco maior venceu o rosto (0,85) num recorte real


def rostos(det, img):
    """As faces com confiança >= CONF_MINIMA, nas coordenadas da imagem original."""
    h, w = img.shape[:2]
    escala = min(1.0, LADO_DETECCAO / max(h, w))
    pequena = cv2.resize(img, (max(1, round(w * escala)), max(1, round(h * escala))), interpolation=cv2.INTER_AREA) if escala < 1 else img
    det.setInputSize((pequena.shape[1], pequena.shape[0]))
    _, faces = det.detect(pequena)
    if faces is None or len(faces) == 0:
        return []
    faces = np.array(faces, np.float32)
    faces[:, :14] /= escala
    return [f for f in faces if float(f[14]) >= CONF_MINIMA]


def maior_rosto(det, img):
    """O maior rosto confiável (num vídeo com duas pessoas, o de quem está mais perto)."""
    fs = rostos(det, img)
    return max(fs, key=lambda f: float(f[2]) * float(f[3])) if fs else None


def medir(f, cinza):
    x, y, w, h = (float(v) for v in f[:4])
    pts = np.asarray(f[4:14], np.float64).reshape(5, 2)
    meio = (pts[0] + pts[1]) / 2
    dist = float(np.linalg.norm(pts[1] - pts[0])) + 1e-6
    x0, y0 = max(0, int(x)), max(0, int(y))
    rosto = cinza[y0:y0 + int(h), x0:x0 + int(w)]
    return {"conf": float(f[14]), "caixa": [int(x), int(y), int(w), int(h)], "giro": float((pts[2][0] - meio[0]) / dist),
            "abertura": dist / max(w, 1.0), "nitidez": float(cv2.Laplacian(rosto, cv2.CV_64F).var()) if rosto.size else 0.0}


def recorte(img, caixa):
    """O rosto com margem para o cabelo e o queixo: 0,6 do tamanho nos lados e em cima, metade disso embaixo."""
    x, y, w, h = caixa
    m = int(max(w, h) * 0.6)
    return img[max(0, y - m):y + h + m // 2, max(0, x - m):x + w + m]


def pasta_do_video(video):
    return config.ENVIOS / f"rostos_{Path(video).stem}"


def _apagar_pasta(p):
    """Só apaga uma pasta rostos_* que esteja diretamente dentro de config.ENVIOS (memória "Exclusão segura")."""
    p = Path(p)
    if p.is_dir() and p.name.startswith("rostos_") and p.resolve().parent == config.ENVIOS.resolve():
        shutil.rmtree(p)


def pasta_da_foto(nome):
    """A pasta rostos_* de onde veio uma foto usada (acao_personagem_rosto_usar a copia como <pasta>_<arquivo>)."""
    m = re.fullmatch(r"(rostos_[A-Za-z0-9_.-]+?)_(?:frente|tres_quartos|perfil)_\d(?:_quadro)?\.png", nome or "")
    return m.group(1) if m else None


def apagar_pasta_de_rostos(nome):
    """Apaga config.ENVIOS/<nome> se for uma pasta rostos_* (depois de criar o personagem ela não serve mais)."""
    if nome and re.fullmatch(r"rostos_[A-Za-z0-9_.-]+", nome):
        _apagar_pasta(config.ENVIOS / nome)


def limpar_antigas(dias=1):
    if not config.ENVIOS.is_dir():
        return
    limite = time.time() - dias * 86400
    for p in config.ENVIOS.iterdir():
        if p.is_dir() and p.name.startswith("rostos_") and p.stat().st_mtime < limite:
            _apagar_pasta(p)


def caminho_candidato(pasta, arquivo):
    # Sem barras na regra, o nome não sai de ENVIOS; o resolve abaixo confere de novo ("a..b" é um nome válido de vídeo)
    if not re.fullmatch(r"rostos_[A-Za-z0-9_.-]+", pasta or ""):
        raise ValueError("Pasta desconhecida.")
    if not re.fullmatch(r"(frente|tres_quartos|perfil)_\d(_quadro)?\.png", arquivo or ""):
        raise ValueError("Arquivo desconhecido.")
    base = config.ENVIOS.resolve()
    arq = (base / pasta / arquivo).resolve()
    if not arq.is_relative_to(base) or not arq.is_file():
        raise ValueError("Imagem não encontrada.")
    return config.ENVIOS / pasta / arquivo


class Ocupado(RuntimeError):
    """A extração desse mesmo vídeo já está rodando (a segunda apagaria a pasta da primeira)."""


_extraindo, _trava = set(), threading.Lock()


def extrair(video, pasta, fps=4, det=None, max_quadros=300):
    """Lê o vídeo, mede os rostos e grava os candidatos de cada ângulo em `pasta` (recortes + candidatos.json).
    Lê no máximo `max_quadros` quadros: num vídeo longo o passo cresce (revisão de 18/11: sem isso, 10 min de vídeo
    prenderiam o processador por minutos)."""
    chave = str(pasta)
    with _trava:
        if chave in _extraindo:
            raise Ocupado("Já estou procurando rostos nesse vídeo.")
        _extraindo.add(chave)
    try:
        return _extrair(video, Path(pasta), fps, det or detector(), max_quadros)
    finally:
        with _trava:
            _extraindo.discard(chave)


def _abrir(video):
    """Abre o vídeo com o PyAV (o cv2 não abre caminho com acento no Windows). Devolve (container, stream, fps, total)."""
    import av
    try:
        c = av.open(str(video))
    except Exception as e:
        raise ValueError("O vídeo não abriu.") from e
    if not c.streams.video:
        c.close()
        raise ValueError("O arquivo não tem vídeo.")
    s = c.streams.video[0]
    fps = float(s.average_rate or s.guessed_rate or 24)
    total = int(s.frames or (float(s.duration * s.time_base) * fps if s.duration else 0))
    return c, s, fps, total


def _quadros(video, quer):
    """(índice, quadro BGR) dos quadros em que quer(índice) é verdade. Um vídeo cortado no meio termina onde dá."""
    import av
    c, s, _, _ = _abrir(video)
    try:
        for i, fr in enumerate(c.decode(s)):
            if quer(i):
                yield i, fr.to_ndarray(format="bgr24")
    except (av.error.FFmpegError, ValueError):
        return
    finally:
        c.close()


def _gravar(img, destino):
    """imencode + tofile: cv2.imwrite falha calado em caminho com acento no Windows (como em troca_foto._gravar)."""
    ok, dados = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Não consegui gravar a miniatura do rosto.")
    dados.tofile(str(destino))


def _extrair(video, pasta, fps, det, max_quadros):
    c, _, fps_origem, total = _abrir(video)
    c.close()
    passo = max(1, round(fps_origem / fps), -(-total // max_quadros) if total else 1)
    salto_amostra = max(1, (total // passo) // AMOSTRA_LEGENDA)
    # 1ª passada: amostra para a legenda e as medidas do maior rosto de cada quadro lido
    linhas, cinzas = [], []
    for lidos, (i, f) in enumerate(_quadros(video, lambda i: i % passo == 0)):
        cinza = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if lidos % salto_amostra == 0 and len(cinzas) < AMOSTRA_LEGENDA:
            cinzas.append(cinza)
        rosto = maior_rosto(det, f)
        if rosto is not None:
            linhas.append({"i": i, "t": round(i / fps_origem, 2), **medir(rosto, cinza)})
    mascara = mascara_legenda(cinzas) if cinzas else None
    for l in linhas:
        x, y, w, h = l["caixa"]
        x0, y0 = max(0, x), max(0, y)
        area = mascara[y0:y0 + h, x0:x0 + w] if mascara is not None else np.zeros(0)
        l["legenda"] = float(area.mean()) if area.size else 0.0
    escolhidos = escolher(linhas)

    # 2ª passada: grava os recortes dos escolhidos
    limpar_antigas()
    _apagar_pasta(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    quer = {l["i"]: (a, k, l) for a in ANGULOS for k, l in enumerate(escolhidos[a])}
    resultado = {a: [None] * len(escolhidos[a]) for a in ANGULOS}
    for i, f in _quadros(video, lambda i: i in quer):
        a, k, l = quer.pop(i)
        nome = f"{a}_{k}.png"
        _gravar(recorte(f, l["caixa"]), pasta / nome)
        c = {"arquivo": nome, "t": l["t"], "giro": round(l["giro"], 2), "nota": round(nota(l), 1)}
        if a == "frente":
            c["quadro"] = f"{a}_{k}_quadro.png"
            _gravar(f, pasta / c["quadro"])
        resultado[a][k] = c
        if not quer:
            break
    resultado = {a: [c for c in resultado[a] if c] for a in ANGULOS}
    resultado["legenda"] = bool(mascara is not None and mascara.any())
    (pasta / "candidatos.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado


def olha_para_direita(img, det=None):
    """True se a pessoa olha para a direita da imagem (nariz à direita do meio dos olhos); None se não acha rosto."""
    fs = rostos(det or detector(), img)
    if not fs:
        return None
    f = max(fs, key=lambda f: float(f[14]))   # numa foto, o mais confiável, não o maior
    return medir(f, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))["giro"] > 0
