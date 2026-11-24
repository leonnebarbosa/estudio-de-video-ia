"""Fundo novo para a troca de personagem (ideia do Henge, "moving plate", de crinklypaper/Banodoco): antes da troca, o
cenario do video vira a foto escolhida, que acompanha o movimento da camera.

1. O BiRefNet separa as pessoas em cada quadro (o mesmo no do grafo da troca, ComfyUI-RMBG).
2. O OpenCV segue pontos do cenario (fora das pessoas) de um quadro para o outro e estima o movimento da camera
   (translacao, giro e escala). Num corte de camera, o movimento recomeca.
3. A foto, ampliada para nunca faltar borda, anda com esse movimento; as pessoas vao por cima.
O video assim montado vira o guia da troca, com o audio original. Fica no projeto como fundo_novo.mp4 para conferir.
"""
import shutil, uuid
from pathlib import Path

import config
import entrada

MARGEM = 1.35        # a foto fica este tanto maior que o quadro, para o movimento nao mostrar a borda
APROXIMA = 0.03      # um pouco de aproximacao ao longo do trecho (o Henge faz um "push-in" leve)
ALTURA_MASCARA = 512


def _mascaras(video, total, largura, altura, rodar):
    """O alfa (0 a 1) das pessoas em cada quadro, pelo BiRefNet, no tamanho do quadro."""
    import numpy as np
    from PIL import Image
    w = round(ALTURA_MASCARA * largura / altura / 2) * 2
    g = {"1": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": video, "force_rate": 24, "custom_width": w, "custom_height": ALTURA_MASCARA,
                                                               "frame_load_cap": total, "start_time": 0, "format": "None"}},
         "2": {"class_type": "BiRefNetRMBG", "inputs": {"image": ["1", 0], "model": "BiRefNet-general", "sensitivity": 1.0, "mask_blur": 1, "mask_offset": 0,
                                                        "invert_output": False, "refine_foreground": False, "unload_model": True, "background": "Alpha", "background_color": "#222222"}},
         "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 2], "filename_prefix": f"troca/fundo_{uuid.uuid4().hex[:8]}"}}}
    r = rodar(g, 1800)
    if r["status"] != "success":
        raise RuntimeError(f"o BiRefNet não separou as pessoas ({r['status']} {r['erro'][:300]})")
    arqs = [config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get("3") or {}).get("images", [])]
    alfas = []
    for a in arqs:
        alfas.append(np.asarray(Image.open(a).convert("L").resize((largura, altura), Image.BILINEAR), np.float32) / 255)
        a.unlink(missing_ok=True)
    while len(alfas) < total:
        alfas.append(alfas[-1])
    return so_pessoas(alfas[:total], video, total, largura, altura, w, rodar)


# O BiRefNet separa "o que esta na frente", e num quarto isso leva junto a cama ou o sofa encostado na pessoa (22/11/2026,
# testes_troca/reel_identico_2026-11-22: a colcha verde ficava no video com o fundo novo). O alfa dele e multiplicado pelo que o
# SAM 3.1 chama de pessoa. So "person" apagava a mao levantada perto do rosto; com "hand" e "arm" ela voltou. A mascara do SAM
# e alargada so um pouco: com 21 px a colcha voltava a aparecer junto ao braco; com 7 sumiu.
SAM = "sam3.1_multiplex_fp16.safetensors"
SAM_TEXTOS = ("person", "hand", "arm")
SAM_ALARGA = 7


def grafo_sam(video, total, largura_mascara, prefixo):
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SAM}},
         "3": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": video, "force_rate": 24, "custom_width": largura_mascara, "custom_height": ALTURA_MASCARA,
                                                               "frame_load_cap": total, "start_time": 0, "format": "None"}}}
    for i, texto in enumerate(SAM_TEXTOS):
        g[f"2{i}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": texto}}
        g[f"4{i}"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["1", 0], "image": ["3", 0], "conditioning": [f"2{i}", 0], "threshold": 0.3,
                                                              "refine_iterations": 2, "individual_masks": False}}
        g[f"5{i}"] = {"class_type": "MaskToImage", "inputs": {"mask": [f"4{i}", 0]}}
        g[f"6{i}"] = {"class_type": "SaveImage", "inputs": {"images": [f"5{i}", 0], "filename_prefix": f"{prefixo}_{texto}"}}
    return g


def so_pessoas(alfas, video, total, largura, altura, largura_mascara, rodar):
    """Os alfas do BiRefNet vezes a mascara de pessoa do SAM 3.1. Sem o modelo do SAM, ou se ele falhar ou nao der uma mascara
    por quadro, ficam os alfas como vieram (o fundo novo sai como antes, so com o BiRefNet)."""
    import cv2
    import numpy as np
    from PIL import Image
    if not (config.MODELOS / "checkpoints" / SAM).is_file():
        return alfas
    r = rodar(grafo_sam(video, total, largura_mascara, f"troca/fundo_sam_{uuid.uuid4().hex[:8]}"), 1800)
    listas = [[config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get(f"6{k}") or {}).get("images", [])] for k in range(len(SAM_TEXTOS))]
    try:
        if r["status"] != "success" or len(listas[0]) < len(alfas):
            print("AVISO: o SAM não separou a pessoa em todos os quadros; o fundo novo vai só com o recorte do BiRefNet.", flush=True)
            return alfas
        nucleo = np.ones((SAM_ALARGA, SAM_ALARGA), np.uint8)
        saida = []
        for k, alfa in enumerate(alfas):
            pessoa = np.zeros((altura, largura), np.float32)
            for arqs in listas:
                if k < len(arqs):
                    pessoa = np.maximum(pessoa, np.asarray(Image.open(arqs[k]).convert("L").resize((largura, altura), Image.BILINEAR), np.float32) / 255)
            saida.append(alfa * np.clip(cv2.GaussianBlur(cv2.dilate(pessoa, nucleo), (0, 0), 3), 0, 1))
        return saida
    finally:
        for arqs in listas:
            for a in arqs:
                a.unlink(missing_ok=True)
        try:
            # O SAM ficava na placa e a geracao seguinte saia mais lenta (trocar_personagem.cabeca_da_foto)
            from comfy_api import posta
            posta("/free", {"unload_models": True, "free_memory": True})
        except Exception:
            pass


def movimentos(cinzas, alfas, cortes=()):
    """A transformacao (3x3) que leva o quadro 0 do plano ate cada quadro: o movimento acumulado da camera, medido nos
    pontos do cenario (onde o alfa das pessoas e baixo). Num corte, recomeca da identidade."""
    import cv2
    import numpy as np
    total = len(cinzas)
    acumulada = np.eye(3)
    saida = [acumulada.copy()]
    cortes = set(cortes)
    for k in range(1, total):
        if k in cortes:
            acumulada = np.eye(3)
            saida.append(acumulada.copy())
            continue
        anterior, atual = cinzas[k - 1], cinzas[k]
        fundo = ((alfas[k - 1] < 0.1) * 255).astype(np.uint8)
        fundo = cv2.erode(fundo, np.ones((9, 9), np.uint8))
        pontos = cv2.goodFeaturesToTrack(anterior, maxCorners=400, qualityLevel=0.01, minDistance=8, mask=fundo)
        passo = np.eye(3)
        if pontos is not None and len(pontos) >= 12:
            novos, ok, _ = cv2.calcOpticalFlowPyrLK(anterior, atual, pontos, None, winSize=(21, 21), maxLevel=3)
            bons = ok.reshape(-1) == 1
            if bons.sum() >= 10:
                a, _ = cv2.estimateAffinePartial2D(pontos[bons], novos[bons], method=cv2.RANSAC, ransacReprojThreshold=2.0)
                if a is not None:
                    passo = np.vstack([a, [0, 0, 1]])
        acumulada = passo @ acumulada
        saida.append(acumulada.copy())
    return saida


def montar(quadros, alfas, foto, cortes=()):
    """Os quadros com a foto no lugar do cenario, andando com a camera. `quadros`: imagens RGB (numpy, uint8)."""
    import cv2
    import numpy as np
    from PIL import Image
    altura, largura = quadros[0].shape[:2]
    cinzas = [cv2.cvtColor(q, cv2.COLOR_RGB2GRAY) for q in quadros]
    mov = movimentos(cinzas, alfas, cortes)
    im = Image.open(foto).convert("RGB")
    esc = max(largura * MARGEM / im.width, altura * MARGEM / im.height)
    placa = np.asarray(im.resize((round(im.width * esc), round(im.height * esc)), Image.LANCZOS))
    ph, pw = placa.shape[:2]
    # A foto centrada no quadro 0: deslocamento do centro da foto para o centro do quadro
    centro = np.array([[1, 0, largura / 2 - pw / 2], [0, 1, altura / 2 - ph / 2], [0, 0, 1]], float)
    saida = []
    total = len(quadros)
    for k, (q, a, m) in enumerate(zip(quadros, alfas, mov)):
        s = 1 + APROXIMA * k / max(1, total - 1)
        zoom = np.array([[s, 0, largura / 2 * (1 - s)], [0, s, altura / 2 * (1 - s)], [0, 0, 1]], float)
        t = (m @ zoom @ centro)[:2]
        fundo = cv2.warpAffine(placa, t, (largura, altura), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        alfa = a[..., None]
        saida.append((q.astype(np.float32) * alfa + fundo.astype(np.float32) * (1 - alfa)).round().astype(np.uint8))
    return saida


def trocar_fundo(video, foto, total, cortes, rodar, ffmpeg, pasta_projeto, fps=24):
    """Troca o cenario do video da entrada (entrada.caminho(video)) pela foto, no lugar (o arquivo passa a ser o guia da troca). Guarda uma copia
    em pasta_projeto/fundo_novo.mp4."""
    import numpy as np
    from PIL import Image
    origem = entrada.caminho(video)
    trab = pasta_projeto / "fundo_quadros"
    shutil.rmtree(trab, ignore_errors=True)
    (trab / "fonte").mkdir(parents=True)
    try:
        # A 24 quadros por segundo (o ritmo da troca), ate 1280 de largura
        ffmpeg("-i", str(origem), "-vf", f"fps={fps},scale='min(1280,iw)':-2", "-frames:v", str(total), str(trab / "fonte" / "%05d.png"))
        quadros = [np.asarray(Image.open(a).convert("RGB")) for a in sorted((trab / "fonte").glob("*.png"))]
        altura, largura = quadros[0].shape[:2]
        alfas = _mascaras(video, len(quadros), largura, altura, rodar)
        prontos = montar(quadros, alfas, foto, cortes)
        for k, q in enumerate(prontos):
            Image.fromarray(q).save(trab / f"{k + 1:05d}.png")
        novo = pasta_projeto / "fundo_novo.mp4"
        ffmpeg("-framerate", str(fps), "-i", str(trab / "%05d.png"), "-i", str(origem), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "12",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(novo))
        shutil.copyfile(novo, origem)
    finally:
        shutil.rmtree(trab, ignore_errors=True)
