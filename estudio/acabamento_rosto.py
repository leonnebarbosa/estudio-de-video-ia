"""Acabamento do rosto na troca de personagem pelo Viggle (22/11/2026, testes_troca/reel_identico_2026-11-22). Tudo na CPU.

- `igualar_tom`: o Klein + BFS pinta o rosto rosado e lustroso, e o corpo do video segue com a pele da pessoa original. O tom e
  o brilho da pele do quadro original vao para o rosto pintado (Reinhard em LAB numa elipse do rosto; o brilho so encolhe).
  Os olhos ficam fora do ajuste e a iris vai para a cor da iris das fotos da personagem (23/11/2026): o Klein pintava a iris
  castanha mais clara (brilho 67 a 96 com fotos de 45 a 67) e o ajuste da pele ainda a desbotava para verde-oliva, com o
  branco do olho azulado. Era dai que vinha o "olho verde" do video, e nao do Viggle.
- `acabar`: passa o video gerado quadro a quadro e
  * leva a cor da iris para a de referencia (so se pedido). O Viggle clareava a iris (castanho virava verde) na segunda
    janela de um video de 10 s, mesmo com os quadros pintados de olho castanho e a cor escrita no pedido, e ali a correcao
    ajudou. Mas a 0,5 MP o olho tem uns 20 pixels, a medida pega palpebra e branco do olho, e no teste seguinte ela deixou
    esverdeado um olho que estava castanho: fica desligada por padrao (troca_wangp.trocar) ate a medida ser confiavel;
  * achata os reflexos da pele do rosto e do pescoco (a "pele oleosa") e poe um pouco de granulacao de sensor.
  A iris precisa do MediaPipe (fidelidade.py); sem ele, so a pele e tratada, com a caixa do rosto do YuNet.
"""
import subprocess

import config
import fidelidade
import troca_foto

FOSCO, GRAO = 0.7, 2.0


def _ler(caminho):
    import cv2
    import numpy as np
    return cv2.imdecode(np.fromfile(str(caminho), np.uint8), cv2.IMREAD_COLOR)


def _elipse_do_rosto(img, detector=None):
    import cv2
    import numpy as np
    caixa = troca_foto.caixa_rosto(img, detector)
    if caixa is None:
        return None
    x, y, w, h = caixa
    m = np.zeros(img.shape[:2], np.float32)
    cv2.ellipse(m, (int(x + w / 2), int(y + h * 0.45)), (int(w * 0.52), int(h * 0.62)), 0, 0, 360, 1, -1)
    return m


def _pele_do_rosto(img, lab, elipse):
    """(onde medir, onde aplicar) o tom num quadro: a pele dentro da elipse do rosto, pelo tom de pele em YCrCb (como em
    `mascara_da_pele`). `medir` e booleano; `aplicar` e float 0 a 1, ou None se quase nao ha pele (luz colorida, preto e
    branco): ai vale a elipse inteira, como antes.
    A elipse pega franja, sobrancelha e fundo. Com uma franja preta dentro dela, o desvio de brilho medido dobrava, o
    contraste da pele era achatado e a franja saia castanho-avermelhada (troca de 23/11/2026). Por isso so a pele entra na
    medida, e o ajuste nao toca no que e bem mais escuro que ela; os reflexos, pequenos e cercados de pele, continuam dentro."""
    import cv2
    import numpy as np
    dentro = elipse > 0.5
    pele = cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb), (0, 133, 77), (255, 180, 135)) > 0
    medir = dentro & pele
    if medir.sum() < 0.2 * dentro.sum():
        return dentro, None
    lado = max(3, int(img.shape[1] * 0.03) | 1)
    cheia = cv2.morphologyEx(pele.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado))) > 0
    escuro = lab[..., 0] < 0.6 * np.median(lab[..., 0][medir])
    return medir, cv2.GaussianBlur((cheia & ~escuro).astype(np.float32), (0, 0), max(1.5, img.shape[1] * 0.004))


def igualar_tom(pintado, original, destino, detector=None, iris=None):
    """Grava em `destino` o quadro `pintado` com o tom e o brilho da pele do rosto de `original` (caminhos). Sem rosto num dos
    dois, copia o pintado como esta e devolve False.
    Com o MediaPipe, a abertura dos olhos fica fora do ajuste (a pele levava junto a iris e o branco do olho) e, com `iris`
    (L, a, b, de `referencia_da_iris` nas fotos da personagem), a iris pintada vai para essa cor, guardando metade da textura."""
    import cv2
    import numpy as np
    a, b = _ler(pintado), _ler(original)
    b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    ma, mb = _elipse_do_rosto(a, detector), _elipse_do_rosto(b, detector)
    if ma is None or mb is None:
        if str(pintado) != str(destino):
            cv2.imencode(".png", a)[1].tofile(str(destino))
        return False
    la, lb = cv2.cvtColor(a, cv2.COLOR_BGR2LAB).astype(np.float32), cv2.cvtColor(b, cv2.COLOR_BGR2LAB).astype(np.float32)
    saida = la.copy()
    (medir_a, aplicar), (medir_b, _) = _pele_do_rosto(a, la, ma), _pele_do_rosto(b, lb, mb)
    for c in range(3):
        pa, pb = la[..., c][medir_a], lb[..., c][medir_b]
        # o brilho so encolhe (tira o lustro), nunca cresce
        ganho = min(pb.std() / max(pa.std(), 1e-3), 1.0) if c == 0 else 1.0
        saida[..., c] = (la[..., c] - pa.mean()) * ganho + pb.mean()
    suave = cv2.GaussianBlur(ma, (0, 0), a.shape[1] * 0.03)
    if aplicar is not None:
        suave = suave * aplicar
    pontos = fidelidade.detectar(a)[1] if fidelidade.disponivel() else None
    if pontos is not None:
        suave = suave * (1 - fidelidade.mascara_olhos(pontos, *a.shape[:2]))
    suave = suave[..., None]
    lab = la * (1 - suave) + saida * suave
    if pontos is not None and iris is not None:
        # O quadro pintado tem a iris com dezenas de pixels: aqui a medida e confiavel (no video a 0,5 MP nao e, ver `acabar`)
        m = cv2.GaussianBlur(fidelidade.mascara_iris(pontos, *a.shape[:2]), (0, 0), max(1.0, a.shape[1] * 0.0015))
        cor = cor_da_iris(lab, m)
        if cor is not None:
            pintar_iris(lab, m, cor, iris, textura=0.5)
    cv2.imencode(".png", cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR))[1].tofile(str(destino))
    return True


def cor_da_iris(lab, mascara):
    """(L, a, b) medianos da iris sem a pupila nem o reflexo: os pixels de brilho intermediario dentro da mascara. None se a
    iris quase nao aparece (olho fechado)."""
    import numpy as np
    px = lab[mascara > 0.6]
    if len(px) < 20:
        return None
    lo, hi = np.percentile(px[:, 0], [30, 85])
    meio = px[(px[:, 0] >= lo) & (px[:, 0] <= hi)]
    return np.median(meio if len(meio) else px, axis=0)


def pintar_iris(lab, mascara, cor, referencia, textura=0.0):
    """Leva o tom da iris de um quadro (LAB float, alterado no lugar) para a `referencia`; o reflexo, muito claro, fica como
    esta, e a iris que clareou escurece ate o brilho da referencia (nunca clareia). `textura` (0 a 1) e quanto da variacao
    de cor em volta de `cor` (a cor medida da iris) fica: 0 no video pequeno, 0,5 no quadro pintado, que tem os raios da iris."""
    import numpy as np
    L = lab[..., 0]
    peso = mascara * np.clip((225 - L) / 30, 0, 1)
    for c in (1, 2):
        alvo = referencia[c] + (lab[..., c] - cor[c]) * textura
        lab[..., c] += (alvo - lab[..., c]) * peso
    ganho = min(1.0, referencia[0] / max(cor[0], 1.0))
    lab[..., 0] = L * (1 - peso * (1 - ganho))


def mascara_da_pele(bgr, caixa):
    """A pele do rosto e do pescoco (float 0 a 1): uma elipse em volta da caixa do rosto vezes o tom de pele em YCrCb."""
    import cv2
    import numpy as np
    h, w = bgr.shape[:2]
    m = np.zeros((h, w), np.float32)
    if caixa is None:
        return m
    x, y, cw, ch = caixa
    cv2.ellipse(m, (int(x + cw / 2), int(y + ch * 0.55)), (int(cw * 0.75), int(ch * 1.05)), 0, 0, 360, 1, -1)
    pele = cv2.inRange(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb), (0, 133, 77), (255, 180, 135)).astype(np.float32) / 255
    return cv2.GaussianBlur(m * pele, (0, 0), max(3, w * 0.008))


def foscar(lab, mascara, forca):
    """Achata, na pele, o que sobe acima do tom local dela: o reflexo. `lab` float, alterado no lugar."""
    import cv2
    import numpy as np
    L = lab[..., 0]
    base = cv2.GaussianBlur(L, (0, 0), max(6, lab.shape[1] * 0.02))
    lab[..., 0] = L - np.clip(L - base - 4, 0, None) * forca * mascara


def _caixa_dos_pontos(pontos, altura, largura):
    xs, ys = [p.x * largura for p in pontos], [p.y * altura for p in pontos]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def referencia_da_iris(imagens, minimo=0):
    """A cor da iris (L, a, b) nas imagens dadas (os quadros pintados, que saem da foto da personagem): a mediana das que
    mostram a iris. None sem MediaPipe ou sem iris visivel. Com `minimo`, a imagem em que a iris tem menos pixels que isso
    nao conta: num rosto pequeno a medida pega a borda e sai saturada."""
    import cv2
    import numpy as np
    if not fidelidade.disponivel():
        return None
    cores = []
    for arq in imagens:
        img = _ler(arq)
        if img is None:
            continue
        _, pontos = fidelidade.detectar(img)
        if pontos is None:
            continue
        mascara = fidelidade.mascara_iris(pontos, *img.shape[:2])
        if (mascara > 0.6).sum() < minimo:
            continue
        cor = cor_da_iris(cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32), mascara)
        if cor is not None:
            cores.append(cor)
    return np.median(np.array(cores), axis=0) if cores else None


def acabar(entrada, saida, referencia=None, olhos=True, fosco=FOSCO, grao=GRAO, semente=7):
    """Grava em `saida` o video `entrada` com a iris na cor de `referencia` (de `referencia_da_iris`), a pele fosca e a
    granulacao, com o mesmo numero de quadros e o som de `entrada`. Devolve {"quadros", "iris"} (iris = quadros corrigidos)."""
    import cv2
    import imageio_ffmpeg
    import numpy as np
    medir = fidelidade.disponivel()
    olhos = bool(olhos and medir and referencia is not None)
    cap = cv2.VideoCapture(str(entrada))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.6f}",
                          "-i", "-", "-i", str(entrada), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "copy",
                          "-movflags", "+faststart", str(saida)], stdin=subprocess.PIPE, creationflags=config.SEM_JANELA)
    yunet = None if medir else troca_foto._detector()
    rng = np.random.default_rng(semente)
    quadros = iris = 0
    caixa = None
    try:
        while True:
            ok, q = cap.read()
            if not ok:
                break
            quadros += 1
            pontos = fidelidade.detectar(q)[1] if medir else None
            if pontos is not None:
                caixa = _caixa_dos_pontos(pontos, h, w)
            elif not medir:
                caixa = troca_foto.caixa_rosto(q, yunet) or caixa
            lab = cv2.cvtColor(q, cv2.COLOR_BGR2LAB).astype(np.float32)
            if olhos and pontos is not None:
                m = fidelidade.mascara_iris(pontos, h, w)
                cor = cor_da_iris(lab, m)
                if cor is not None:
                    pintar_iris(lab, m, cor, referencia)
                    iris += 1
            if fosco > 0:
                foscar(lab, mascara_da_pele(q, caixa), fosco)
            q = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
            if grao > 0:
                q = np.clip(q.astype(np.float32) + rng.normal(0, grao, (h, w)).astype(np.float32)[..., None], 0, 255).astype(np.uint8)
            p.stdin.write(q.tobytes())
    finally:
        cap.release()
        p.stdin.close()
        p.wait()
    if p.returncode != 0:
        raise RuntimeError("o ffmpeg não gravou o vídeo com o acabamento")
    return {"quadros": quadros, "iris": iris}
