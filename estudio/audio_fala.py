"""Video guiado por um audio enviado (Imagem para video com "Audio da fala"): divide o audio em tomadas nos silencios e
diz onde ha voz em cada tomada.

Vem dos testes de 20/11/2026 (testes_troca/audio_2026-11-20 e ugc_2026-11-20, aprovados pelo usuario): cada tomada e
gerada do zero a partir da imagem, com o trecho do audio preso no latente (PixaromaH3AudioSync), e as tomadas sao
emendadas a seco com o audio original por cima. O corte entre tomadas precisa cair num silencio de verdade: o fim de
palavra do Whisper errou por 0,4 s no "2027" do teste UGC (o "sete" ia ate 5,2 s e o Whisper disse 4,8 s), entao aqui
tudo e medido pelo volume do proprio audio, sem transcrever."""
import math
import subprocess
from itertools import combinations

import av
import imageio_ffmpeg

import config
import numpy as np

TAXA = 16000
JANELA = 0.02              # o volume e medido a cada 20 ms
ABAIXO_DO_PICO = 25.0      # dB abaixo do trecho mais alto (percentil 99): abaixo disso e silencio. Com 35 as pausas da voz da Amanda (-44 a -50 dB, pico -15) contavam como voz
PAUSA_MIN = 0.15           # um silencio menor que isto e respiro dentro da palavra, nao pausa
PAUSA_BOA = 0.25           # pausas a partir disto sao preferidas para cortar
DURACAO_MIN = 1.0          # nenhuma tomada menor que 1 s (o H3 tem minimo de 5 quadros, mas uma tomada curta demais nao vale)
MAX_SEGUNDOS = 30.0        # audio mais longo que isto passa de 6 tomadas de 5 s: o estudio nao aceita


def ler(arq):
    """O audio em mono a 16 kHz, de -1 a 1."""
    c = av.open(str(arq))
    try:
        if not c.streams.audio:
            raise ValueError("o arquivo nao tem audio")
        conv = av.AudioResampler(format="s16", layout="mono", rate=TAXA)
        partes = [g.to_ndarray().ravel() for f in c.decode(audio=0) for g in conv.resample(f)]
    finally:
        c.close()
    if not partes:
        raise ValueError("o audio esta vazio")
    return np.concatenate(partes).astype(np.float32) / 32768.0


def volumes(pcm):
    """dB de cada janela de 20 ms."""
    n = int(JANELA * TAXA)
    k = len(pcm) // n
    if k == 0:
        return np.zeros(0)
    blocos = pcm[:k * n].reshape(k, n)
    return 20 * np.log10(np.sqrt(np.mean(blocos ** 2, axis=1)) + 1e-9)


def voz(db):
    """Janelas com voz: acima de (pico - ABAIXO_DO_PICO)."""
    if len(db) == 0:
        return np.zeros(0, bool)
    return db > (np.percentile(db, 99) - ABAIXO_DO_PICO)


def silencios(tem_voz, minimo=PAUSA_MIN):
    """[(inicio, fim)] em segundos dos trechos sem voz com pelo menos `minimo` segundos (inclui o comeco e o fim do audio)."""
    saida, i, n = [], 0, len(tem_voz)
    while i < n:
        if tem_voz[i]:
            i += 1
            continue
        j = i
        while j < n and not tem_voz[j]:
            j += 1
        if (j - i) * JANELA >= minimo:
            saida.append((i * JANELA, j * JANELA))
        i = j
    return saida


def dividir(pcm, maximo):
    """Cortes [(inicio, fim)] em segundos cobrindo o audio todo, cada um com no maximo `maximo` s, cortados no meio de pausas.
    Usa o menor numero de tomadas que cabe nas pausas; entre as divisoes possiveis, prefere pausas longas e tomadas de tamanhos
    parecidos. Sem divisao possivel nas pausas, corta pelo jeito antigo (dividir_guloso). Em 20/11/2026 o guloso dividia a voz da
    Amanda em 3 tomadas com maximo de 8,5 s (6,4 + 7 + 1,4 s) quando 2 cabiam (6,4 + 8,4 s)."""
    total = len(pcm) / TAXA
    tem_voz = voz(volumes(pcm))
    pausas = silencios(tem_voz)
    ultima_voz = (np.flatnonzero(tem_voz)[-1] + 1) * JANELA if tem_voz.any() else total
    fim_total = min(total, ultima_voz + 0.3)
    if fim_total <= maximo + 1e-6:
        return [(0.0, round(fim_total, 3))]
    candidatas = [((a + b) / 2, b - a) for a, b in pausas if DURACAO_MIN <= (a + b) / 2 <= fim_total - DURACAO_MIN]
    n_min = math.ceil(fim_total / maximo - 1e-9)
    for n in range(n_min, n_min + 3):
        if n - 1 > len(candidatas):
            break
        melhor = None
        for combo in combinations(candidatas, n - 1):
            pontos = [0.0, *(c[0] for c in combo), fim_total]
            tamanhos = [b - a for a, b in zip(pontos, pontos[1:])]
            if not all(DURACAO_MIN - 1e-6 <= s <= maximo + 1e-6 for s in tamanhos):
                continue
            nota = (sum(c[1] >= PAUSA_BOA for c in combo), -(max(tamanhos) - min(tamanhos)), min(c[1] for c in combo))
            if melhor is None or nota > melhor[0]:
                melhor = (nota, pontos)
        if melhor:
            p = melhor[1]
            return [(round(a, 3), round(b, 3)) for a, b in zip(p, p[1:])]
    return dividir_guloso(pausas, fim_total, maximo)


def dividir_guloso(pausas, fim_total, maximo):
    """O jeito antigo: avanca cortando na pausa mais longa entre 60% e 100% do maximo; sem pausa, na ultima pausa curta;
    sem nenhuma, no maximo."""
    cortes, inicio = [], 0.0
    while fim_total - inicio > maximo + 1e-6:
        limite = inicio + maximo
        candidatas = [((a + b) / 2, b - a) for a, b in pausas if inicio + DURACAO_MIN <= (a + b) / 2 <= limite]
        boas = [c for c in candidatas if c[0] >= inicio + 0.6 * maximo and c[1] >= PAUSA_BOA]
        if boas:
            corte = max(boas, key=lambda c: (c[1], c[0]))[0]
        elif candidatas:
            corte = max(candidatas, key=lambda c: c[0])[0]
        else:
            corte = limite
        cortes.append((round(inicio, 3), round(corte, 3)))
        inicio = corte
    cortes.append((round(inicio, 3), round(fim_total, 3)))
    return cortes


def trechos_de_voz(pcm, inicio, fim):
    """Dentro do corte: (primeira voz, ultima voz, [meio das pausas de 0,25 s ou mais]) em segundos a partir do inicio do corte.
    None se o corte nao tem voz."""
    tudo = voz(volumes(pcm))
    a, b = int(round(inicio / JANELA)), int(round(fim / JANELA))
    tem_voz = tudo[a:b]
    if not tem_voz.any():
        return None
    ids = np.flatnonzero(tem_voz)
    primeira, ultima = ids[0] * JANELA, (ids[-1] + 1) * JANELA
    pausas = [round((x + y) / 2, 2) for x, y in silencios(tem_voz, PAUSA_BOA) if x > primeira and y < ultima]
    return round(primeira, 2), round(ultima, 2), pausas


def recortar(origem, destino, inicio, fim, segundos_video):
    """O trecho do audio, com silencio ate completar o tamanho do video gerado (o PixaromaH3AudioSync tambem completa,
    mas assim o arquivo enviado ao ComfyUI ja tem o tamanho certo). 0,03 s de entrada e saida suaves evitam estalo."""
    dur = max(0.05, fim - inicio)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{dur:.3f}", "-i", str(origem),
                    "-af", f"afade=t=in:d=0.03,afade=t=out:st={max(0.0, dur - 0.03):.3f}:d=0.03,apad", "-t", f"{segundos_video:.3f}",
                    "-ac", "2", "-ar", "44100", str(destino)], check=True, creationflags=config.SEM_JANELA)
