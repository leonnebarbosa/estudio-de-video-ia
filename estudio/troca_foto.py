"""Troca de personagem em FOTO: o rosto, a roupa ou os dois, com o FLUX.2 Klein 4B do Editar imagem.

Teste de 14/11/2026 (projetos/teste_troca_foto, semente 42, base modelo1.jpg), nota de identidade SFace (acima de 0,363 = mesma pessoa):
- Rosto: LoRA BFS head swap v1 do Klein 4B (MIT), corpo na imagem 1 e rosto na 2, pedido oficial com o gatilho "head_swap:".
  Com a foto do rosto inteira a gola da blusa dela vazava para a base; recortada so na cabeca (cabelo ate o queixo), sumiu, e o
  rosto novo subiu de 0,57 para 0,68 (a base caiu para 0,30). Mantem a expressao da base; o cabelo vem da foto do rosto.
- Roupa: sem LoRA, roupa na imagem 2. Com a cabeca da modelo da foto da roupa, o cabelo dela vazava; recortada do queixo para
  baixo, o rosto da base ficou em 0,93.
- Os dois: duas passadas (rosto, depois roupa). Uma passada so com as 3 imagens nao trocou o rosto e misturou as roupas.
- Tirar o fundo da foto do rosto (BiRefNet, como no fluxo do autor) nao muda nada com a cabeca ja recortada (0,66 contra 0,68):
  ficou de fora, e assim o modo nao depende do modelo do BiRefNet, que nenhum pacote traz.
Este modulo faz os recortes (detector de rosto YuNet do OpenCV Zoo, MIT, em modelos_aux) e guarda os pedidos; os grafos ficam em
texto_para_imagem, que roda as passadas."""
import shutil
from pathlib import Path

import config

YUNET = config.ESTUDIO / "modelos_aux" / "face_detection_yunet_2023mar.onnx"
LORA_ROSTO = "bfs_head_v1_flux-klein_4b.safetensors"
# Pedido do autor da LoRA (docs/flux-2-klein.md do repositorio BFS), sem mudar uma palavra: o gatilho e o texto foram treinados juntos
PEDIDO_ROSTO = ("head_swap: start with Picture 1 as the base image, keeping its lighting, environment, and background. remove the head from "
                "Picture 1 completely and replace it with the head from Picture 2, strictly preserving the hair, eye color, and nose structure "
                "of Picture 2. copy the direction of the eye, head rotation, and micro-expressions from Picture 1. Keep the body, clothing, "
                "pose, framing, and background intact.")
# Dos tutoriais de troca de roupa do Klein, mais o trecho do sorriso que segurou o rosto no teste do Editar (11/11/2026)
PEDIDO_ROUPA = ("Change only the clothing of the person in image 1 to match the outfit in image 2. Do not add any accessories, jewellery, "
                "bags, hats or shoes unless they are clearly visible in image 2. Keep the face, expression, hair, pose and background of "
                "image 1 unchanged, same subtle closed-mouth smile.")
SEGUNDOS_PASSADA = 30  # medido: 27 a 37 s por passada a 2 MP na 3080


def _detector():
    import cv2
    return cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6)


def _ler(caminho: Path):
    import cv2
    import numpy as np
    # imdecode no lugar de imread: aceita caminho com acento no Windows
    return cv2.imdecode(np.fromfile(str(caminho), np.uint8), cv2.IMREAD_COLOR)


def _gravar(img, destino: Path):
    import cv2
    ok, dados = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("não consegui gravar o recorte")
    dados.tofile(str(destino))


def caixa_rosto(img, detector=None):
    """(x, y, largura, altura) do maior rosto da imagem, ou None se nao achar nenhum."""
    detector = detector or _detector()
    detector.setInputSize((img.shape[1], img.shape[0]))
    _, rostos = detector.detect(img)
    if rostos is None or len(rostos) == 0:
        return None
    x, y, w, h = max(rostos, key=lambda r: r[2] * r[3])[:4]
    return float(x), float(y), float(w), float(h)


def limites_cabeca(caixa, largura, altura):
    """Recorte so da cabeca: o cabelo acima do rosto e para logo abaixo do queixo (sem pescoco nem roupa)."""
    x, y, w, h = caixa
    cx = x + w / 2
    return (int(max(cx - w * 1.1, 0)), int(max(y - h * 0.9, 0)), int(min(cx + w * 1.1, largura)), int(min(y + h * 1.08, altura)))


def topo_sem_cabeca(caixa, altura):
    """Linha de onde comeca o recorte da roupa: logo abaixo do queixo."""
    x, y, w, h = caixa
    return int(min(y + h * 1.15, altura - 1))


def recortar(origem: Path, destino: Path, modo: str, detector=None) -> bool:
    """Grava em destino o recorte "cabeca" ou "roupa" de origem. Sem rosto na foto, copia a foto inteira e devolve False
    (a troca segue, so pode vazar o que estiver junto)."""
    img = _ler(origem)
    if img is None:
        raise RuntimeError(f"não consegui ler a imagem {origem.name}")
    caixa = caixa_rosto(img, detector)
    if caixa is None:
        shutil.copyfile(origem, destino)
        return False
    altura, largura = img.shape[:2]
    if modo == "cabeca":
        x0, y0, x1, y1 = limites_cabeca(caixa, largura, altura)
        recorte = img[y0:y1, x0:x1]
    else:
        recorte = img[topo_sem_cabeca(caixa, altura):, :]
    # Um recorte minusculo (rosto colado na borda) nao serve de referencia: vai a foto inteira
    if recorte.shape[0] < 64 or recorte.shape[1] < 64:
        shutil.copyfile(origem, destino)
        return False
    _gravar(recorte, destino)
    return True


def preparar(troca: dict, projeto: str, entrada: Path | None = None) -> tuple[dict, list[str]]:
    """Recorta as fotos de rosto e de roupa na entrada do ComfyUI. Devolve ({"rosto": arquivo|None, "roupa": arquivo|None}, avisos)."""
    entrada = entrada or config.ENTRADA
    detector, prontos, avisos = None, {}, []
    for chave, modo, oque in (("rosto", "cabeca", "do rosto"), ("roupa", "roupa", "da roupa")):
        arquivo = troca.get(chave)
        if not arquivo:
            prontos[chave] = None
            continue
        detector = detector or _detector()
        destino = entrada / f"trocafoto_{projeto}_{chave}.png"
        if not recortar(entrada / arquivo, destino, modo, detector):
            avisos.append(f"Não achei um rosto na foto {oque}: ela foi usada inteira.")
        prontos[chave] = destino.name
    return prontos, avisos


def passadas(troca: dict) -> list[str]:
    """A ordem das passadas: o rosto primeiro (a roupa depois nao mexe nele)."""
    return [k for k in ("rosto", "roupa") if troca.get(k)]
