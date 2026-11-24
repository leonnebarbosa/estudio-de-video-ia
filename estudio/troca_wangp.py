"""Troca de personagem pelo Viggle (motor "viggle" da aba Trocar), chamada pelo trocar_personagem.py. Aqui ficam as
contas, os pedidos e a montagem; os grafos do ComfyUI estao no troca_viggle.py. O arquivo se chama troca_wangp porque a
receita veio do Showrunner do WanGP (deepbeepmeep/WanGP), que rodou estas duas etapas ate 22/11/2026; hoje nada aqui
chama o WanGP.

0. Fundo novo, se pedido (fundo.py): o cenario do trecho vira a foto escolhida antes de tudo.
1. Pinta alguns quadros do trecho com a pessoa da foto. Com a roupa do video: a troca em foto do estudio (FLUX.2 Klein + BFS,
   ~30 s cada) com a cabeca recortada (cabeca_da_foto); cada quadro leva, das fotos de expressao da personagem, a de expressao
   mais perto do quadro original, e o tom da pele do rosto e igualado ao do video. Com a roupa da foto: Qwen Image 2.1
   Viggle Image Swap, 6 passos (~55 s cada).
2. Viggle Remake Swap (LoRA sobre o H3 FL2VA Pruned): espalha a troca pelo video, com o som original. 6 passos Euler. Acima de
   JANELA_UNICA quadros vai em janelas de JANELA quadros emendadas, cada uma com os seus quadros pintados.
3. Acabamento do rosto (acabamento_rosto.py): pele fosca e granulacao (a cor dos olhos fica desligada, ver `trocar`).
A receita das etapas 0, 1 (Klein) e 3 e as janelas vem dos testes de 22/11/2026 (testes_troca/reel_identico_2026-11-22), medidos
com fidelidade.py: numa janela unica de 243 quadros a expressao deixou de seguir o original (correlacao de 0,35 a 0,60); em
janelas de 124 ficou entre 0,82 e 0,93, o nivel de duas versoes do mesmo reel feitas pelo criador.
Nos testes de 17/11/2026, ainda no WanGP (Bruno no guia_giro, Cida no guia_cozinha_v, 5 s a 0,5 MP), saiu mais fiel a
foto que a Head Swap. No ComfyUI (21 e 22/11): 3 s em 481 s e 9 s em 1190 s, pico de 9,9 GB.

Saidas no projeto: final.mp4, comparativo.mp4 (trecho original | troca), prompt.txt e a pasta viggle/ com os quadros.
"""
import math, os, re, shutil, subprocess, sys, time
from pathlib import Path

import config, entrada, entrada_temp

FPS = 24
# Viggle Remake (WanGP models/minimax_h3/viggle.py): cada janela tem de 90 a 345 quadros, no formato 17n+5
MIN_QUADROS, MAX_QUADROS = 90, 345
PASSOS_VIGGLE = 6
# Onde pintar: fracao do trecho. O fim fica um pouco antes do ultimo quadro (nos testes, o quadro 108 de 124)
FIM_PINTADO = 0.88

PINTOR = {
    "video": ("Replace the person in image 1 with the person from image 2: their face, head shape, hair and skin. The person keeps the "
              "same clothes as in image 1. Keep everything else exactly as in image 1: the pose, the direction of the head, the "
              "expression, the framing, the background and the lighting."),
    "foto": ("Replace the person in image 1 with the character from image 2, including their clothes. Keep everything else exactly "
             "as in image 1: the pose, the direction of the head, the expression, the framing, the background and the lighting."),
}


def tamanho(proporcao, megapixels):
    """A mesma conta do imagem_para_video.tamanho (o ResolutionSelector): 16:9 a 0,5 MP da 960x544."""
    m = re.match(r"(\d+):(\d+)", proporcao)
    w, h = int(m.group(1)), int(m.group(2))
    escala = math.sqrt(megapixels * 1024 * 1024 / (w * h))
    return round(w * escala / 32) * 32, round(h * escala / 32) * 32


def quadros_render(pedidos, disponiveis):
    """Quantos quadros o Viggle gera: o pedido arredondado para cima no formato 17n+5, no minimo 90 (o trecho e cortado
    depois). Se o video nao tiver tantos, o maior 17n+5 que cabe. None se nem 90 cabem."""
    n = max(MIN_QUADROS, pedidos)
    n += (5 - n % 17) % 17
    while n > min(MAX_QUADROS, disponiveis):
        n -= 17
    return n if n >= MIN_QUADROS else None


# Janelas (22/11/2026): cada uma tem JANELA quadros e repete SOBRA da anterior, onde as duas se misturam. Ate JANELA_UNICA o
# trecho vai numa janela so (o formato 17n+5 logo acima de JANELA): dividir 5,9 s em duas dobraria o tempo por meio segundo.
JANELA, SOBRA, JANELA_UNICA = 124, 5, 141


def plano_janelas(pedidos, disponiveis):
    """[(inicio, quadros a gerar, quadros usados)] de cada janela do Viggle, ou None se o video nao tem quadros para a
    menor geracao. A ultima janela encosta no fim do trecho (pode repetir mais que SOBRA da anterior)."""
    pedidos = min(pedidos, disponiveis)
    if pedidos <= JANELA_UNICA:
        render = quadros_render(pedidos, disponiveis)
        return None if render is None else [(0, render, min(pedidos, render))]
    inicios = list(range(0, pedidos - JANELA, JANELA - SOBRA)) + [pedidos - JANELA]
    return [(i, JANELA, JANELA) for i in inicios]


def emendar(listas, inicios):
    """Junta os quadros das janelas (listas de imagens numpy) numa lista so: onde duas janelas se repetem, passa aos poucos
    da anterior para a seguinte."""
    saida = list(listas[0])
    for inicio, quadros in zip(inicios[1:], listas[1:]):
        comum = min(len(saida) - inicio, len(quadros))
        for k in range(comum):
            peso = (k + 1) / (comum + 1)
            saida[inicio + k] = (saida[inicio + k].astype("float32") * (1 - peso) + quadros[k].astype("float32") * peso).round().astype("uint8")
        saida += quadros[comum:]
    return saida


def posicoes(pedidos):
    """Os quadros a pintar (0 = primeiro): 2 ate 7 s, 3 ate 11 s, 4 acima, de 0 ate FIM_PINTADO do trecho."""
    n = 2 if pedidos <= 7 * FPS else 3 if pedidos <= 11 * FPS else 4
    fim = round(FIM_PINTADO * (pedidos - 1))
    return [round(k * fim / (n - 1)) for k in range(n)]


def tempo(q):
    return f"00:{q / FPS:06.3f}"


def prompt_viggle(quadros, roupa, fala=False, pele=False):
    """O prompt de seis secoes do Viggle Remake (formato testado pelo WanGP, defaults/viggle_remake.json), sem saber o que ha
    no video: a identidade vem dos quadros pintados. Nada de "dim" (escurece o video todo, segundo o WanGP).
    fala: a pessoa fala no trecho. O WanGP manda marcar a fala com o instante em que comeca, sem escrever as palavras (o som
    vem do video), e avisa que um sorriso escrito no mesmo momento disputa com a boca; por isso o rosto deixa de ser
    "identico em todo quadro".
    pele: descreve a pele seca e fosca da receita "Pele natural" (imagem_para_video.PELE_TEXTO e PELE_RETER); com a LoRA de
    pele (troca_viggle.PELE_LORA) o rosto saiu menos oleoso em 22/11/2026."""
    reter_pele = descrever_pele = ""
    if pele:
        from imagem_para_video import PELE_RETER, PELE_TEXTO
        reter_pele, descrever_pele = "\n" + PELE_RETER, PELE_TEXTO + " "
    fixo = "the hair and clothing stay identical in every frame, and the face is the same person while the mouth moves with the speech" if fala \
        else "the face, hair and clothing stay identical in every frame"
    falando = f" From {tempo(0)}, <Subject 1> (S1) is speaking with natural lip movements synchronized, <d>[unclear]</d>." if fala else ""
    som = "The soundtrack of <Video 1>, unchanged, with the voice of <Subject 1> (S1)." if fala else "The soundtrack of <Video 1>, unchanged."
    fotos = [f"<Picture {k}>" for k in range(1, len(quadros) + 1)]
    lista = ", ".join(fotos[:-1]) + f" and {fotos[-1]}"
    de_onde = ", ".join(f"{f} from [Shot 1] at {tempo(q)}" for f, q in zip(fotos, quadros))
    visual = "face, hair and skin, wearing the same clothes as the person in <Video 1>" if roupa == "video" else "face, hair, skin and the whole outfit"
    secoes = [
        "subject_definitions:\n"
        f"<Video 1> is the source video for the editing task.\n"
        f"{lista} are frames of the target video, {de_onde}.\n"
        f"<Subject 1> is the person in {lista}, with the {visual} shown there. <Subject 1> replaces the main person in <Video 1>.",
        "summary:\n"
        "[video editing + character replacement] The target video is an edited version of <Video 1> in which the main person becomes "
        "<Subject 1>, looking exactly as in <Picture 1>. All other people, the place and the soundtrack are unchanged; the shots, cuts, "
        "camera, motion and timing of <Video 1> are kept.",
        "retention_analysis:\n"
        "<Video 1> (source video editing): fully_preserved - the shots, the camera framing and movement, the background, the unchanged "
        "people, and the motion and timing of every performance.\n"
        + "\n".join(f"{f} (appears in [Shot 1]): reference - a frame of the target video. The people in it, their faces and clothing, "
                    f"and the background, framing and lighting are taken from {f}." for f in fotos) + "\n"
        f"<Subject 1> (appears in [Shot 1]): fully_preserved - {fixo}." + reter_pele,
        "detailed_description:\n" +
        ("Realistic phone footage with the natural light and colours of <Video 1>, mild sensor noise, no beauty filter.\n" if pele
         else "Realistic footage with the natural light and colours of <Video 1>.\n") + descrever_pele +
        "[Shot 1] <Subject 1> performs exactly the motion of the main person in <Video 1>, "
        + ", ".join(f"matching {f} at {tempo(q)}" for f, q in zip(fotos, quadros))
        + f".{falando} In every frame <Subject 1> is this same person exactly as in <Picture 1>.",
        f"overall_soundscape:\n{som}",
        "non_diegetic_music:\nN/A",
    ]
    return "\n\n".join(secoes)


def ffmpeg(*args):
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args], check=True, creationflags=config.SEM_JANELA)


def contar_quadros(video):
    import acabamento
    return acabamento.contar_quadros(video)


def garantir_24fps(origem, dono=None):
    """Passa o video da entrada para 24 fps, no proprio arquivo, se ele vier em outra taxa (celular: 30 ou 60). O Viggle
    le o video a 24 fps e conta os quadros presos nele: sem isto, o quadro 94 pintado de um video a 30 fps (3,1 s) era
    preso em 3,9 s (visto em 21/11/2026, projeto troca_REELS). Devolve True se converteu."""
    import acabamento
    if acabamento.fps_de(origem) == str(FPS):
        return False
    # A conversao vai para os temporarios do projeto (entrada_temp) e so depois substitui o original
    convertido = entrada_temp.arquivo(dono, origem.stem + "_24fps.mp4")[0] if dono else origem.with_name(origem.stem + "_24fps.mp4")
    ffmpeg("-i", str(origem), "-map", "0:v:0", "-map", "0:a?", "-vf", f"fps={FPS}", "-c:v", "libx264", "-crf", "12", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(convertido))
    os.replace(convertido, origem)
    return True


def mudar_etapa(progresso, etapa, valor=0, maximo=0):
    if progresso.etapa != etapa:
        progresso.tempos[progresso.etapa] = round(time.time() - progresso.inicio)
        progresso.etapa, progresso.inicio = etapa, time.time()
        progresso.monitor.rotulo = etapa
    progresso.valor, progresso.maximo = valor, maximo
    progresso.gravar()


def conferir_comfy(r, mon, etapa):
    """Sai com o codigo do trocar_personagem se uma etapa no ComfyUI nao deu certo: 5 placa quente, 3 servidor caiu, 4 o resto."""
    if mon.quente:
        print("PARADO por temperatura", flush=True)
        sys.exit(5)
    if r["status"] == "servidor caiu":
        print(f"SERVIDOR CAIU: {r['erro'][:300]}", flush=True)
        sys.exit(3)
    if r["status"] != "success":
        print(f"FALHA na geracao: {etapa} no ComfyUI não terminou ({r['status']}) {r['erro'][:700]}", flush=True)
        sys.exit(4)


def montar_final(gerado, origem, pasta, pedidos, altura):
    """final.mp4 (cortado nos quadros pedidos) e comparativo.mp4 (o trecho original | o resultado, com o som do resultado)."""
    segundos = pedidos / FPS
    final = pasta / "final.mp4"
    ffmpeg("-i", str(gerado), "-frames:v", str(pedidos), "-t", f"{segundos:.6f}", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final))
    try:
        ffmpeg("-i", str(origem), "-i", str(final), "-filter_complex",
               f"[0:v]trim=end_frame={pedidos},setpts=PTS-STARTPTS,scale=-2:{altura},setsar=1[a];[1:v]scale=-2:{altura},setsar=1[b];[a][b]hstack[v]",
               "-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-t", f"{segundos:.6f}", str(pasta / "comparativo.mp4"))
    except subprocess.CalledProcessError as e:
        print(f"AVISO: não consegui montar o comparativo ({e}).", flush=True)


def quadro_do_video(video, numero, destino):
    """Grava em `destino` (PNG) o quadro `numero` do video (0 = o primeiro)."""
    ffmpeg("-i", str(video), "-vf", f"select=eq(n\\,{numero})", "-frames:v", "1", str(destino))


def tem_som(video):
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace", creationflags=config.SEM_JANELA)
    return "Audio:" in r.stderr


def cortar_janela(origem, destino, inicio, quadros):
    """Os `quadros` quadros a partir de `inicio` (o video ja esta a 24 fps), com o som deles."""
    som = ["-af", f"atrim=start={inicio / FPS:.6f}:end={(inicio + quadros) / FPS:.6f},asetpts=PTS-STARTPTS", "-c:a", "aac", "-b:a", "192k"] if tem_som(origem) else ["-an"]
    ffmpeg("-i", str(origem), "-vf", f"trim=start_frame={inicio}:end_frame={inicio + quadros},setpts=PTS-STARTPTS", *som,
           "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(destino))


def ler_quadros(video, limite=None):
    """Os quadros do video como imagens BGR (numpy)."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    quadros = []
    try:
        while limite is None or len(quadros) < limite:
            ok, q = cap.read()
            if not ok:
                break
            quadros.append(q)
    finally:
        cap.release()
    return quadros


def gravar_video(quadros, som, destino):
    """Grava os quadros (BGR) a 24 fps, com o som de `som` (se tiver) completado com silencio ate o fim do video."""
    import imageio_ffmpeg
    h, w = quadros[0].shape[:2]
    segundos = len(quadros) / FPS
    audio = ["-i", str(som), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-af", f"apad=whole_dur={segundos:.6f}"] if som and tem_som(som) else []
    p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                          "-r", str(FPS), "-i", "-", *audio, "-t", f"{segundos:.6f}", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-r", str(FPS),
                          "-movflags", "+faststart", str(destino)], stdin=subprocess.PIPE, creationflags=config.SEM_JANELA)
    for q in quadros:
        p.stdin.write(q.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("o ffmpeg não gravou o vídeo emendado")


def escolher_cabecas(originais, cabecas):
    """Para cada quadro original (PNG), a foto da personagem (nome na entrada do ComfyUI) de expressao mais perto dele.
    Com uma foto so, ou sem como medir (fidelidade.py), todas levam a primeira."""
    import fidelidade
    if len(cabecas) < 2 or not fidelidade.disponivel():
        return [cabecas[0]] * len(originais)
    expressoes = {c: fidelidade.expressao(entrada.caminho(c)) for c in cabecas}
    return [fidelidade.mais_parecida(fidelidade.expressao(o), expressoes) for o in originais]


# Pixels de iris que a foto precisa ter para dar a cor dos olhos. Numa foto de corpo inteiro eram 190, a medida saiu saturada
# e os olhos do video ficaram laranja (23/11/2026); nas fotos de rosto da mov sao de 1.300 a 2.100
IRIS_MINIMA = 600


def iris_das_fotos(cabecas):
    """A cor da iris (L, a, b do OpenCV) nas fotos da personagem usadas na pintura (nomes na entrada do ComfyUI), ou None
    sem o MediaPipe ou sem iris visivel. Os quadros pintados vao para ela (acabamento_rosto.igualar_tom): o Klein pinta a
    iris mais clara que a da foto (em 23/11/2026, brilho 78 a 96 contra 62 a 67), e o castanho virava mel ou verde no video."""
    import acabamento_rosto
    try:
        return acabamento_rosto.referencia_da_iris([entrada.caminho(c) for c in dict.fromkeys(cabecas)], minimo=IRIS_MINIMA)
    except Exception as e:
        print(f"AVISO: não medi a cor dos olhos das fotos ({e}).", flush=True)
        return None


def trocar(pasta, p, video, foto, semente, mon, progresso, rodar, acompanhar=None, expressoes=()):
    """Faz a troca e grava pasta/final.mp4 e pasta/comparativo.mp4. Devolve (medidas, prompt). Sai com 4 se faltar algo ou
    a geracao falhar, com 3 se o ComfyUI cair e com 5 se a placa esquentar demais (os codigos do trocar_personagem).
    Tudo roda no ComfyUI (troca_viggle.py), com o `rodar` e o `acompanhar` do trocar_personagem. `foto` e `expressoes` estao
    na entrada do ComfyUI: com a roupa do video, sao as cabecas recortadas."""
    import troca_viggle
    origem = entrada.caminho(video)
    if garantir_24fps(origem, pasta.name):
        print(f"o vídeo não estava a {FPS} quadros por segundo: convertido antes da troca", flush=True)
    roupa = p.get("roupa", "video")
    klein = roupa == "video"
    falta = troca_viggle.preparar("swap_klein" if klein else "swap")
    if falta:
        print(f"FALHA na geracao: {falta}", flush=True)
        sys.exit(4)
    pedidos = round(p["duracao"] * FPS)
    disponiveis = contar_quadros(origem)
    plano = plano_janelas(pedidos, disponiveis)
    if plano is None:
        print(f"FALHA na geracao: o Viggle Remake precisa de pelo menos {MIN_QUADROS} quadros ({MIN_QUADROS / FPS:.2f} s) de vídeo a partir do início do trecho.", flush=True)
        sys.exit(4)
    pedidos = min(pedidos, disponiveis, plano[-1][0] + plano[-1][2])
    trab = pasta / "viggle"
    trab.mkdir(exist_ok=True)
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    inicio = time.time()
    # O trecho como veio, para o comparativo: o fundo novo troca o video da entrada
    original = trab / "original.mp4"
    shutil.copyfile(origem, original)
    pico_vram = temp_max = 0

    if p.get("fundo"):
        import fundo
        mudar_etapa(progresso, "fundo")
        print("trocando o fundo: o BiRefNet e o SAM separam a pessoa e a foto acompanha o movimento da câmera", flush=True)
        try:
            fundo.trocar_fundo(video, entrada.caminho(p["fundo"]), min(disponiveis, max(i + n for i, n, _ in plano)), (), rodar, ffmpeg, pasta)
        except Exception as e:
            print(f"FALHA na geracao: não consegui trocar o fundo ({e}).", flush=True)
            sys.exit(4)

    # Os quadros a pintar de cada janela, contados no trecho inteiro: o mesmo quadro em duas janelas e pintado uma vez
    janelas = []
    for ini, render, usados in plano:
        janelas.append([ini + q for q in posicoes(usados)])
    todos = sorted({q for j in janelas for q in j})
    originais = {q: trab / f"quadro_{q:03d}.png" for q in todos}
    pintados = {q: trab / f"pintado_{q:03d}.png" for q in todos}
    for q in todos:
        quadro_do_video(origem, q, originais[q])
    fala = p.get("fala") is True
    resumo = f"{len(plano)} janelas de {JANELA} quadros" if len(plano) > 1 else f"{plano[0][1]} quadros"
    print(f"pinta {len(todos)} quadros ({', '.join(str(q) for q in todos)}) e gera {resumo} a {largura}x{altura} (corta em {pedidos})", flush=True)

    mudar_etapa(progresso, "pintar", 0, len(todos))
    avanca = lambda feitos: mudar_etapa(progresso, "pintar", feitos, len(todos))
    if klein:
        # Com fotos de expressao, a pintura usa so elas: a foto principal costuma ser a de estudio (sorrindo, maquiada), e voltaria
        # a ser escolhida nos quadros com sorriso
        cabecas = escolher_cabecas([originais[q] for q in todos], list(expressoes) or [foto])
        if len(set(cabecas)) > 1 or expressoes:
            print("foto de expressão por quadro: " + ", ".join(f"{q} → {c}" for q, c in zip(todos, cabecas)), flush=True)
        r = troca_viggle.pintar_klein(pasta.name, [(q, originais[q], pintados[q], c) for q, c in zip(todos, cabecas)], semente % 2**32, rodar, avanca)
    else:
        r = troca_viggle.pintar(pasta.name, [(q, originais[q], pintados[q]) for q in todos], foto, PINTOR[roupa], semente % 2**32, rodar, avanca)
    conferir_comfy(r, mon, "a pintura dos quadros")
    pico_vram, temp_max = r["pico_vram"], r["temp_max"]
    usar = dict(pintados)
    if klein:
        # O tom da pele do video no rosto pintado, num arquivo a parte (a pintura fica guardada como saiu), e a iris na cor
        # da iris das fotos da personagem (iris_das_fotos)
        import acabamento_rosto
        iris = iris_das_fotos(cabecas)
        for q in todos:
            usar[q] = trab / f"pintado_{q:03d}_tom.png"
            if not usar[q].is_file():
                try:
                    acabamento_rosto.igualar_tom(pintados[q], originais[q], usar[q], iris=iris)
                except Exception as e:
                    print(f"AVISO: não igualei o tom da pele do quadro {q} ({e}).", flush=True)
                    shutil.copyfile(pintados[q], usar[q])

    prompts, partes = [], []
    extras = troca_viggle.loras_de_pele() if klein else []
    for i, ((ini, render, usados), pos) in enumerate(zip(plano, janelas), 1):
        relativos = [q - ini for q in pos]
        prompt = prompt_viggle(relativos, roupa, fala, pele=klein)
        prompts.append(prompt)
        parte = trab / f"janela_{i}.mp4"
        partes.append(parte)
        if len(plano) > 1:
            progresso.janela = [i, len(plano)]
        mudar_etapa(progresso, "viggle", 0, PASSOS_VIGGLE)
        if parte.is_file():
            continue
        arq_j, video_j = (None, video) if len(plano) == 1 else entrada_temp.arquivo(pasta.name, f"troca_{pasta.name}_vj{i}.mp4")
        if len(plano) > 1:
            cortar_janela(origem, arq_j, ini, render)
            print(f"janela {i} de {len(plano)}: quadros {ini} a {ini + render - 1}", flush=True)
        try:
            r, video_gerado = troca_viggle.gerar(f"{pasta.name}_j{i}", video_j, [(q - ini, usar[q]) for q in pos], prompt, largura, altura, render, semente, rodar, acompanhar,
                                                 lambda passo: mudar_etapa(progresso, "viggle", passo, PASSOS_VIGGLE), loras_extra=extras, dono=pasta.name)
        finally:
            if len(plano) > 1:
                arq_j.unlink(missing_ok=True)
        if r["status"] == "success" and (video_gerado is None or not video_gerado.is_file()):
            r = {**r, "status": "sem vídeo", "erro": "o ComfyUI não informou o vídeo gerado"}
        conferir_comfy(r, mon, "o Viggle Remake")
        shutil.copy2(video_gerado, parte)
        pico_vram, temp_max = max(pico_vram, r["pico_vram"]), max(temp_max, r["temp_max"])
    progresso.janela = None
    texto = prompts[0] if len(prompts) == 1 else "\n\n".join(f"[janela {i}]\n{t}" for i, t in enumerate(prompts, 1))
    pintor = "FLUX.2 Klein + BFS head swap (a troca em foto do estúdio)" if klein else f"Qwen Image 2.1 Viggle Image Swap:\n{PINTOR[roupa]}"
    (pasta / "prompt.txt").write_text(f"Pintor: {pintor}\n\nViggle Remake:\n{texto}\n", encoding="utf-8")

    mudar_etapa(progresso, "montar")
    gerado = trab / "viggle.mp4"
    quadros = emendar([ler_quadros(parte, usados) for parte, (_, _, usados) in zip(partes, plano)], [ini for ini, _, _ in plano])[:pedidos]
    if not quadros:
        print("FALHA na geracao: o Viggle Remake não devolveu quadros.", flush=True)
        sys.exit(4)
    pedidos = len(quadros)
    gravar_video(quadros, origem, gerado)
    del quadros
    if klein and p.get("acabamento", True):
        # Pele fosca e granulacao, na CPU (acabamento_rosto.py); se falhar, o video segue sem o acabamento. A cor dos olhos so
        # com "corrigir_olhos": a 0,5 MP o olho tem uns 20 pixels e a medida da iris pega palpebra e branco do olho. No teste pela
        # pagina (22/11/2026, teste_reel_viggle_api) a correcao deixou esverdeado um olho que estava castanho
        import acabamento_rosto
        mudar_etapa(progresso, "acabamento")
        try:
            acabado = trab / "acabado.mp4"
            olhos = p.get("corrigir_olhos") is True
            info = acabamento_rosto.acabar(gerado, acabado, acabamento_rosto.referencia_da_iris([usar[q] for q in todos]) if olhos else None, olhos=olhos)
            print(f"acabamento do rosto: {info['quadros']} quadros" + (f", íris corrigida em {info['iris']}" if olhos else ""), flush=True)
            gerado = acabado
        except Exception as e:
            print(f"AVISO: o acabamento do rosto falhou ({e}); o vídeo segue sem ele.", flush=True)
        mudar_etapa(progresso, "montar")
    montar_final(gerado, original, pasta, pedidos, altura)
    return {"segundos": round(time.time() - inicio), "pico_vram": pico_vram, "temp_max": temp_max}, prompts[0]
