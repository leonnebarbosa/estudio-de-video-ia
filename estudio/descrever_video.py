"""Descreve um video de exemplo para o pedido do H3 (23/11/2026, testes_troca/reel_identico_2026-11-22/ref_sem_video.py).

O teste que deu origem a isto: sem mandar o video como referencia (que quase triplica o tempo), so com a imagem, o som preso e um
pedido que dizia cada expressao com o seu momento e a fala por escrito, o H3 fez o que estava descrito, na ordem. Aqui o estudio
escreve essa parte sozinho: mede o rosto quadro a quadro (fidelidade.curvas, MediaPipe na CPU) e vira as curvas em frases com tempo.

So o rosto: sobrancelha, sorriso, bico, olho arregalado, piscadas e a boca parada no fim. Gestos das maos e movimento da cabeca
nao sao medidos; quem usa escreve essa parte.

A fala e transcrita por um faster-whisper de fora: o Python do ComfyUI nao o tem, e instalar la mexe em pacotes que o ComfyUI usa.
O local.json aponta o Python de um programa que o tenha (por exemplo o do VoiceStudio): {"python_transcricao": "D:\\...\\python.exe"}.
Sem ele (e sem o faster-whisper no proprio Python), as expressoes saem do mesmo jeito e a fala fica para quem usa escrever.
"""
import json
import subprocess
import sys

import config

FPS = 24
TRANSCRITOR = config.ESTUDIO / "transcrever_fala.py"
TEMPO_TRANSCRICAO = 300
# Abaixo disto a expressao e so um instante da fala (a vogal "o" arredonda os labios como um bico) e nao vira frase
MINIMO = 8                      # quadros a 24 por segundo: um terco de segundo
JUNTAR = 2                      # dois trechos separados por ate isto viram um so
PISCADA_MAX = 8                 # mais que isto de olho fechado nao e piscada
SORRISO, BICO, PISCADA = 0.4, 0.38, 0.5
# O olho arregalado mede pouco: no reel de 23/11 a pessoa arregala de verdade e a medida fica em 0,11 a 0,19 (picos de 0,35), contra
# 0,01 parada e ate 0,10 so de levantar a sobrancelha. Com o limite em 0,30 o evento sumia e a frase "nunca arregala" saia errada
ARREGALADO, NUNCA_ARREGALA = 0.12, 0.08
SOBRANCELHA_MIN, SOBRANCELHA_ACIMA = 0.55, 0.15    # levantada: acima disto e acima do jeito normal da pessoa (a mediana do video)
BOCA_ABERTA, BOCA_PARADA, BOCA_FALOU = 0.15, 0.06, 0.1
PARADA_MINIMO = 12              # meio segundo de boca fechada no fim


def mediana_movel(valores, janela=5):
    """Tira os picos de um ou dois quadros sem arrastar as bordas (a media arrastaria o comeco e o fim de cada expressao)."""
    meio = janela // 2
    n = len(valores)
    return [sorted(valores[max(0, i - meio):min(n, i + meio + 1)])[len(valores[max(0, i - meio):min(n, i + meio + 1)]) // 2] for i in range(n)]


def intervalos(valores, limiar, minimo):
    """Os trechos (inicio, fim), em quadros e com o fim de fora, em que o valor fica em `limiar` ou acima por pelo menos `minimo`
    quadros. Trechos separados por ate JUNTAR quadros contam como um."""
    trechos, ini = [], None
    for i, v in enumerate(list(valores) + [float("-inf")]):
        if v >= limiar and ini is None:
            ini = i
        elif v < limiar and ini is not None:
            if trechos and ini - trechos[-1][1] <= JUNTAR:
                trechos[-1] = (trechos[-1][0], i)
            else:
                trechos.append((ini, i))
            ini = None
    return [t for t in trechos if t[1] - t[0] >= minimo]


def eventos(linhas, fps=FPS):
    """As expressoes do video em ordem: [{"inicio": s, "fim": s ou None, "texto": frase em ingles sem ponto}]. `linhas` sao as
    medidas de cada quadro (fidelidade.curvas) e `fps` a cadencia do video medido. Um evento sem fim e um instante (a piscada)."""
    n = len(linhas)
    if not n:
        return []
    curva = lambda k: mediana_movel([float(l.get(k) or 0.0) for l in linhas])
    boca, sobrancelha = curva("boca"), curva("sobrancelha")
    s = lambda q: round(q / fps, 3)
    # As duracoes minimas sao contadas a 24 quadros por segundo: num video a 30 valem mais quadros
    q = lambda quadros: max(1, round(quadros * fps / FPS))
    saida = []
    normal = sorted(sobrancelha)[n // 2]
    for a, b in intervalos(sobrancelha, max(SOBRANCELHA_MIN, normal + SOBRANCELHA_ACIMA), q(MINIMO)):
        saida.append({"inicio": s(a), "fim": s(b), "texto": "the character's eyebrows are raised high"})
    for a, b in intervalos(curva("sorriso"), SORRISO, q(MINIMO)):
        aberta = sum(boca[a:b]) / (b - a) >= BOCA_ABERTA
        saida.append({"inicio": s(a), "fim": s(b), "texto": "the character smiles with the mouth open" if aberta else "the character gives a closed-lip smile"})
    for a, b in intervalos(curva("bico"), BICO, q(MINIMO)):
        saida.append({"inicio": s(a), "fim": s(b), "texto": "the character pushes the lips forward into a pout"})
    for a, b in intervalos(curva("olho_arregalado"), ARREGALADO, q(MINIMO - 2)):
        saida.append({"inicio": s(a), "fim": s(b), "texto": "the character's eyes open wide"})
    # A piscada dura dois ou tres quadros: sem a mediana, que a apagaria
    for a, b in intervalos([float(l.get("piscada") or 0.0) for l in linhas], PISCADA, 1):
        if b - a <= q(PISCADA_MAX):
            saida.append({"inicio": s(a), "fim": None, "texto": "the character blinks once, fully"})
        else:
            saida.append({"inicio": s(a), "fim": s(b), "texto": "the character keeps the eyes closed"})
    # A boca parada no fim, depois de ter falado: o modelo tende a seguir mexendo a boca ate o ultimo quadro
    parada = n
    while parada > 0 and boca[parada - 1] < BOCA_PARADA:
        parada -= 1
    if n - parada >= q(PARADA_MINIMO) and max(boca[:parada], default=0.0) >= BOCA_FALOU:
        saida.append({"inicio": s(parada), "fim": s(n), "texto": "the character's mouth is closed and still"})
    return sorted(saida, key=lambda e: (e["inicio"], e["fim"] is None, e["texto"]))


def tempo(segundos):
    """O instante como o H3 le nos pedidos: mm:ss.mmm."""
    segundos = max(0.0, segundos)
    return f"{int(segundos // 60):02d}:{segundos % 60:06.3f}"


def texto_das_expressoes(linhas, fps=FPS):
    """As frases, em ingles e sem < nem >, para o campo da acao (que entra no pedido como esta). Vazio se o rosto nao muda."""
    lista = eventos(linhas, fps)
    if not lista:
        return ""
    fim_do_video = len(linhas) / fps
    frases = []
    for e in lista:
        if e["fim"] is None:
            frases.append(f"At {tempo(e['inicio'])}, {e['texto']}.")
        elif e["fim"] >= fim_do_video - 1.5 / fps:
            frases.append(f"From {tempo(e['inicio'])} to the end, {e['texto']}.")
        else:
            frases.append(f"From {tempo(e['inicio'])} to {tempo(e['fim'])}, {e['texto']}.")
    if max((float(l.get("olho_arregalado") or 0.0) for l in linhas), default=0.0) < NUNCA_ARREGALA:
        # Sem isto, levantar a sobrancelha vira olho arregalado (visto no teste do quadro inicial de 23/11/2026). So quando a medida
        # fica claramente parada: na duvida, a frase nao entra
        frases.append("The character never opens the eyes wide.")
    return " ".join(frases)


def caber(texto, maximo, frases=False):
    """O texto cortado para caber em `maximo` caracteres sem partir uma palavra; com `frases`, sem partir uma frase (o ponto de
    "00:01.500" nao e fim de frase: so o ponto seguido de espaco)."""
    if len(texto) <= maximo:
        return texto
    corte = texto[:maximo + 1].rfind(". " if frases else " ")
    return texto[:corte + (1 if frases else 0)].rstrip() if corte > 0 else texto[:maximo]


def som_do_video(video, destino):
    """Grava em `destino` (WAV) o som do video. False se nao deu (o video nao tem som)."""
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "2", "-ar", "44100",
                        "-c:a", "pcm_s16le", str(destino)], capture_output=True, creationflags=config.SEM_JANELA)
    return r.returncode == 0 and destino.is_file() and destino.stat().st_size > 1000


def python_do_transcritor():
    """O Python que tem o faster-whisper: o do local.json ou, se o pacote estiver instalado aqui, este mesmo. None sem nenhum."""
    if config.PYTHON_TRANSCRICAO:
        return config.PYTHON_TRANSCRICAO
    try:
        import importlib.util
        return sys.executable if importlib.util.find_spec("faster_whisper") else None
    except (ImportError, ValueError):
        return None


def transcrever(audio, rodar=subprocess.run):
    """As palavras da fala com o tempo de cada uma: ([[inicio, fim, palavra], ...], "") ou (None, o motivo, para mostrar a quem usa).
    Roda transcrever_fala.py no Python do transcritor, na CPU. O modelo so e lido do disco: nada e baixado."""
    py = python_do_transcritor()
    if not py:
        return None, "este computador não tem um transcritor configurado"
    try:
        r = rodar([str(py), "-I", str(TRANSCRITOR), str(audio), config.MODELO_TRANSCRICAO, "pt"], capture_output=True, timeout=TEMPO_TRANSCRICAO,
                  creationflags=config.SEM_JANELA)
    except subprocess.TimeoutExpired:
        return None, "a transcrição demorou demais"
    except OSError as e:
        return None, f"não consegui abrir o transcritor ({e})"
    try:
        dados = json.loads(r.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        dados = None
    if r.returncode != 0 or not isinstance(dados, dict):
        return None, "o transcritor falhou" + (f" ({dados['erro']})" if isinstance(dados, dict) and dados.get("erro") else "")
    if dados.get("erro"):
        return None, str(dados["erro"])
    try:
        return [[float(a), float(b), str(p)] for a, b, p in dados.get("palavras") or []], ""
    except (TypeError, ValueError):
        return None, "o transcritor devolveu um formato desconhecido"


def fala_do_trecho(palavras, inicio, fim):
    """O que se diz entre `inicio` e `fim` (s): as palavras cujo meio cai no trecho, na ordem."""
    return " ".join(p for a, b, p in palavras if p and inicio <= (a + b) / 2 < fim)


# A leitura do ultimo video: mudar a resolucao muda os cortes e a tela pede de novo; sem isto seria mais um minuto de espera
_lido = {}


def _chave(video):
    try:
        e = video.stat()
        return str(video), e.st_mtime_ns, e.st_size
    except (OSError, AttributeError):
        return None


def descrever(video, fps, cortes, audio, max_acao, max_fala):
    """Para cada corte [inicio, fim] (s) do som do video: {"acao": expressoes do rosto com o tempo contado do comeco do corte,
    "fala": o que se diz nele}. Devolve {"tomadas": [...], "avisos": [...]}: os avisos dizem o que nao foi possivel ler."""
    import fidelidade
    avisos, linhas = [], None
    chave = _chave(video)
    guardado = _lido.get(chave) if chave else None
    if guardado:
        linhas, sem_rosto = guardado["rosto"]
    elif fidelidade.disponivel():
        linhas, sem_rosto = fidelidade.curvas(video)
    else:
        avisos.append("O leitor de expressões (MediaPipe) não está instalado, então não descrevi as expressões.")
    if linhas is not None and (not linhas or sem_rosto > len(linhas) / 2):
        avisos.append("Não achei um rosto em boa parte do vídeo, então não descrevi as expressões.")
        linhas = None
    palavras, motivo = (guardado["fala"], "") if guardado and guardado["fala"] is not None else transcrever(audio)
    if chave and (guardado or fidelidade.disponivel()):
        # So o ultimo video fica guardado; uma transcricao que falhou nao fica, para a proxima tentar de novo
        _lido.clear()
        _lido[chave] = {"rosto": guardado["rosto"] if guardado else (linhas if linhas is not None else [], sem_rosto), "fala": palavras}
    if palavras is None:
        avisos.append(f"Não transcrevi a fala ({motivo}). Escreva a fala de cada tomada.")
    elif not palavras:
        avisos.append("Não ouvi fala no vídeo.")
    tomadas = []
    for inicio, fim in cortes:
        trecho = linhas[max(0, round(inicio * fps)):max(0, round(fim * fps))] if linhas else []
        tomadas.append({"acao": caber(texto_das_expressoes(trecho, fps), max_acao, frases=True),
                        "fala": caber(fala_do_trecho(palavras or [], inicio, fim), max_fala)})
    if linhas:
        avisos.append("As expressões estão em inglês, como o modelo lê. Gestos das mãos e da cabeça não são lidos: acrescente-os em \"O que acontece\".")
    return {"tomadas": tomadas, "avisos": avisos}
