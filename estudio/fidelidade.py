"""Mede o rosto com os pontos do MediaPipe (FaceLandmarker, modelo em modelos_aux/face_landmarker.task), na CPU.

Nasceu em 22/11/2026 (testes_troca/reel_identico_2026-11-22), quando a troca de um reel foi aprovada por miniaturas e o
usuario viu o que elas escondiam: expressao, boca e pele. Serve a tres coisas na troca de personagem:
- o relatorio de fidelidade: a correlacao, quadro a quadro, das curvas de boca, sorriso, olhos e sobrancelha do video gerado
  com as do original (1 = a mesma curva). Entre duas versoes do mesmo reel feitas pelo criador deu de 0,80 a 0,90;
- a escolha da foto de expressao: de varias fotos da mesma pessoa, a de expressao mais perto de um quadro do video;
- os pontos da iris, para o acabamento corrigir a cor dos olhos (acabamento_rosto.py).

O MediaPipe entra no Python do ComfyUI sem dependencias (instalador/requisitos_sem_dependencias.txt): pedido inteiro, ele
traria o opencv-contrib por cima do OpenCV do portatil. Sem ele ou sem o modelo, `disponivel()` diz que nao e quem chama segue
sem medir.
"""
import config

MODELO = config.ESTUDIO / "modelos_aux" / "face_landmarker.task"
# Cada medida e a media de algumas "blendshapes" (0 a 1) do FaceLandmarker
MEDIDAS = {"boca": ["jawOpen"], "bico": ["mouthPucker", "mouthFunnel"], "sorriso": ["mouthSmileLeft", "mouthSmileRight"],
           "labios_fechados": ["mouthClose"], "piscada": ["eyeBlinkLeft", "eyeBlinkRight"], "olho_arregalado": ["eyeWideLeft", "eyeWideRight"],
           "sobrancelha": ["browInnerUp", "browOuterUpLeft", "browOuterUpRight"]}
# As que entram na comparacao de duas fotos, com o peso de cada uma (boca e sorriso contam mais: e o que o quadro pintado impoe)
PESOS = {"boca": 2.0, "sorriso": 2.0, "bico": 1.0, "piscada": 1.5, "olho_arregalado": 1.5, "sobrancelha": 1.0}
# As que a pagina mostra no resultado, na ordem
RESUMO = ("boca", "sorriso", "piscada", "sobrancelha")
# Contorno de cada olho, o centro da iris e os 4 pontos da borda dela (indices do FaceLandmarker)
OLHOS = (([33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246], 468, [469, 470, 471, 472]),
         ([362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398], 473, [474, 475, 476, 477]))
_detector = None


def disponivel():
    """O MediaPipe e o modelo estao no lugar. Nao carrega nada pesado."""
    if not MODELO.is_file():
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("mediapipe") is not None
    except (ImportError, ValueError):
        return False


def detector():
    global _detector
    if _detector is None:
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        opcoes = vision.FaceLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path=str(MODELO)), output_face_blendshapes=True, num_faces=1)
        _detector = vision.FaceLandmarker.create_from_options(opcoes)
    return _detector


def detectar(bgr):
    """(medidas, pontos) do maior rosto de uma imagem BGR (como o OpenCV le), ou (None, None) sem rosto."""
    import cv2
    import mediapipe as mp
    r = detector().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    if not r.face_blendshapes:
        return None, None
    b = {c.category_name: c.score for c in r.face_blendshapes[0]}
    return {m: sum(b[n] for n in nomes) / len(nomes) for m, nomes in MEDIDAS.items()}, r.face_landmarks[0]


def _ler(caminho):
    import cv2
    import numpy as np
    # imdecode no lugar de imread: aceita caminho com acento no Windows
    return cv2.imdecode(np.fromfile(str(caminho), np.uint8), cv2.IMREAD_COLOR)


def expressao(imagem):
    """As medidas do rosto de uma imagem (caminho), ou None sem rosto."""
    img = _ler(imagem)
    return None if img is None else detectar(img)[0]


def distancia(a, b):
    """Quao diferentes sao duas expressoes (dicionarios de `expressao`): 0 = iguais. None se faltar uma."""
    if not a or not b:
        return None
    return sum(peso * abs(a[m] - b[m]) for m, peso in PESOS.items())


def mais_parecida(alvo, candidatas):
    """De `candidatas` ({nome: expressao}), o nome da de expressao mais perto de `alvo`. Sem como medir, a primeira."""
    notas = [(d, nome) for nome, e in candidatas.items() if (d := distancia(alvo, e)) is not None]
    return min(notas)[1] if notas else next(iter(candidatas))


def curvas(video, limite=None):
    """As medidas de cada quadro do video (lista de dicionarios; um quadro sem rosto repete o anterior) e quantos ficaram sem rosto."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    linhas, sem_rosto = [], 0
    try:
        while limite is None or len(linhas) < limite:
            ok, q = cap.read()
            if not ok:
                break
            m, _ = detectar(q)
            if m is None:
                sem_rosto += 1
                m = linhas[-1] if linhas else {k: 0.0 for k in MEDIDAS}
            linhas.append(m)
    finally:
        cap.release()
    return linhas, sem_rosto


def correlacao(x, y):
    """Correlacao de Pearson de duas listas do mesmo tamanho; None se uma delas nao varia."""
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    vx, vy = sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y)
    if vx < 1e-9 or vy < 1e-9:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (vx * vy) ** 0.5


def comparar_curvas(a, b):
    """{medida: correlacao} das curvas de dois videos, nos quadros que os dois tem."""
    n = min(len(a), len(b))
    saida = {}
    for m in MEDIDAS:
        c = correlacao([l[m] for l in a[:n]], [l[m] for l in b[:n]])
        if c is not None:
            saida[m] = round(c, 2)
    return saida


def medir_video(original, gerado, limite=None):
    """O relatorio de fidelidade: {"quadros", "sem_rosto", "medidas": {medida: correlacao}, "nota"} ou None se nao der para medir
    (sem MediaPipe, video ilegivel, ou rosto em menos da metade dos quadros de um dos dois). `nota` e a media das medidas do RESUMO."""
    if not disponivel():
        return None
    a, sa = curvas(original, limite)
    b, sb = curvas(gerado, limite)
    n = min(len(a), len(b))
    if n < 12 or sa > len(a) / 2 or sb > len(b) / 2:
        return None
    medidas = comparar_curvas(a, b)
    resumo = [medidas[m] for m in RESUMO if m in medidas]
    return {"quadros": n, "sem_rosto": sb, "medidas": medidas, "nota": round(sum(resumo) / len(resumo), 2) if resumo else None}


def mascara_iris(pontos, altura, largura):
    """A iris visivel dos dois olhos (float 0 a 1): o circulo da iris dentro do contorno do olho, com a borda suave."""
    import cv2
    import numpy as np
    m = np.zeros((altura, largura), np.float32)
    for contorno, centro, borda in OLHOS:
        cx, cy = pontos[centro].x * largura, pontos[centro].y * altura
        raio = sum(((pontos[i].x * largura - cx) ** 2 + (pontos[i].y * altura - cy) ** 2) ** 0.5 for i in borda) / len(borda)
        circulo = np.zeros((altura, largura), np.uint8)
        cv2.circle(circulo, (int(round(cx)), int(round(cy))), max(1, int(round(raio * 0.95))), 255, -1)
        olho = np.zeros((altura, largura), np.uint8)
        cv2.fillPoly(olho, [np.array([[pontos[i].x * largura, pontos[i].y * altura] for i in contorno], np.int32)], 255)
        m = np.maximum(m, (cv2.bitwise_and(circulo, olho) / 255).astype(np.float32))
    return cv2.GaussianBlur(m, (0, 0), 1.0)


def mascara_olhos(pontos, altura, largura):
    """A abertura dos dois olhos (iris e branco), um pouco alargada e de borda suave (float 0 a 1)."""
    import cv2
    import numpy as np
    m = np.zeros((altura, largura), np.uint8)
    maior = 1
    for contorno, _, _ in OLHOS:
        pts = np.array([[pontos[i].x * largura, pontos[i].y * altura] for i in contorno], np.int32)
        cv2.fillPoly(m, [pts], 255)
        maior = max(maior, int(pts[:, 0].max() - pts[:, 0].min()))
    lado = max(3, int(maior * 0.12) | 1)
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado)))
    return cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), max(1.0, maior * 0.05))
