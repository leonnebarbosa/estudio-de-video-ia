"""Troca de personagem pelo WanGP (motor "wangp" da aba Trocar), chamada pelo trocar_personagem.py.

A receita do Showrunner do WanGP (deepbeepmeep/WanGP, testada aqui em 17/11/2026):
1. Pinta alguns quadros do trecho com a pessoa da foto: Qwen Image 2.1 Viggle Image Swap, 6 passos (~45-60 s cada).
   Com roupa do video vai so a cabeca recortada (cabeca_da_foto): com a foto inteira o pintor vestiu a roupa da foto num
   quadro e nao no outro.
2. Viggle Remake Swap (LoRA sobre o H3 FL2VA Pruned): espalha a troca pelo video, com o som original. 6 passos Euler.
Nos testes (Bruno no guia_giro, Cida no guia_cozinha_v, 5 s a 0,5 MP) saiu mais fiel a foto que a Head Swap e mais rapido
(~490 e ~465 s contra 637 e 520 s), com metade da VRAM (~5 GB). Mas puxa mais da placa (285-305 W) e a 3080 caiu duas
vezes nesse ritmo.

O WanGP roda num processo filho, com o Python dele (config.WANGP_PYTHON), pelo wangp_executar.py.
Saidas no projeto: final.mp4, comparativo.mp4 (trecho original | troca), prompt.txt e a pasta wangp/ com os quadros.
"""
import json, math, os, re, subprocess, sys, threading, time

import config

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


def posicoes(pedidos):
    """Os quadros a pintar (0 = primeiro): 2 ate 7 s, 3 ate 11 s, 4 acima, de 0 ate FIM_PINTADO do trecho."""
    n = 2 if pedidos <= 7 * FPS else 3 if pedidos <= 11 * FPS else 4
    fim = round(FIM_PINTADO * (pedidos - 1))
    return [round(k * fim / (n - 1)) for k in range(n)]


def tempo(q):
    return f"00:{q / FPS:06.3f}"


def prompt_viggle(quadros, roupa):
    """O prompt de seis secoes do Viggle Remake (formato testado pelo WanGP, defaults/viggle_remake.json), sem saber o que ha
    no video: a identidade vem dos quadros pintados. Nada de "dim" (escurece o video todo, segundo o WanGP)."""
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
        "<Subject 1> (appears in [Shot 1]): fully_preserved - the face, hair and clothing stay identical in every frame.",
        "detailed_description:\n"
        "Realistic footage with the natural light and colours of <Video 1>.\n"
        "[Shot 1] <Subject 1> performs exactly the motion of the main person in <Video 1>, "
        + ", ".join(f"matching {f} at {tempo(q)}" for f, q in zip(fotos, quadros))
        + ". In every frame <Subject 1> is this same person exactly as in <Picture 1>.",
        "overall_soundscape:\nThe soundtrack of <Video 1>, unchanged.",
        "non_diegetic_music:\nN/A",
    ]
    return "\n\n".join(secoes)


def ffmpeg(*args):
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args], check=True, creationflags=config.SEM_JANELA)


def contar_quadros(video):
    import acabamento
    return acabamento.contar_quadros(video)


class Placa(threading.Thread):
    """Guarda os picos lidos pelo Monitor e mata o WanGP se a placa passar do limite de temperatura (o Monitor so sabe
    interromper o ComfyUI)."""

    def __init__(self, mon):
        super().__init__(daemon=True)
        self.mon, self.proc, self.fim = mon, None, threading.Event()
        self.pico_vram = self.temp_max = 0

    def run(self):
        while not self.fim.wait(1):
            u = self.mon.ultimo or {}
            self.pico_vram = max(self.pico_vram, int(u.get("vram_mib") or 0))
            self.temp_max = max(self.temp_max, int(u.get("temp") or 0))
            if self.mon.quente and self.proc and self.proc.poll() is None:
                self.proc.kill()


def mudar_etapa(progresso, etapa, valor=0, maximo=0):
    if progresso.etapa != etapa:
        progresso.tempos[progresso.etapa] = round(time.time() - progresso.inicio)
        progresso.etapa, progresso.inicio = etapa, time.time()
        progresso.monitor.rotulo = etapa
    progresso.valor, progresso.maximo = valor, maximo
    progresso.gravar()


def trocar(pasta, p, video, foto, semente, mon, progresso):
    """Faz a troca e grava pasta/final.mp4 e pasta/comparativo.mp4. Devolve (medidas, prompt). Sai com 4 se o WanGP falhar
    e 5 se a placa esquentar demais (os codigos do trocar_personagem)."""
    import acabamento
    if not config.WANGP_PYTHON.is_file():
        print(f"FALHA na geracao: o WanGP não está instalado em {config.WANGP}.", flush=True)
        sys.exit(4)
    origem = config.ENTRADA / video
    pedidos = round(p["duracao"] * FPS)
    disponiveis = contar_quadros(origem)
    render = quadros_render(pedidos, disponiveis)
    if render is None:
        print(f"FALHA na geracao: o WanGP precisa de pelo menos {MIN_QUADROS} quadros ({MIN_QUADROS / FPS:.2f} s) de vídeo a partir do início do trecho.", flush=True)
        sys.exit(4)
    pedidos = min(pedidos, render)
    trab = pasta / "wangp"
    trab.mkdir(exist_ok=True)
    roupa = p.get("roupa", "video")
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    quadros = posicoes(pedidos)
    print(f"WanGP: pinta {len(quadros)} quadros ({', '.join(str(q) for q in quadros)}) e gera {render} quadros a {largura}x{altura} (corta em {pedidos})", flush=True)

    tarefas = []
    for q in quadros:
        original = trab / f"quadro_{q:03d}.png"
        ffmpeg("-i", str(origem), "-vf", f"select=eq(n\\,{q})", "-frames:v", "1", str(original))
        tarefas.append({"etapa": "pintar", "destino": str(trab / f"pintado_{q:03d}.png"), "settings": {
            "model_type": "qwen_image_21_viggle_image_swap_7B", "image_mode": 1, "prompt": PINTOR[roupa], "negative_prompt": "",
            "image_refs": [str(original), str(config.ENTRADA / foto)], "video_prompt_type": "KI", "resolution": "1024x1024",
            "num_inference_steps": 6, "sample_solver": "viggle_v02", "guidance_scale": 1.0, "batch_size": 1, "seed": semente % 2**32,
            "remove_background_images_ref": 0, "custom_settings": {"qwen21_kv_cache": "Disabled"}}})
    prompt = prompt_viggle(quadros, roupa)
    gerado = trab / "viggle.mp4"
    tarefas.append({"etapa": "viggle", "destino": str(gerado), "settings": {
        "model_type": "viggle_remake", "image_mode": 0, "prompt": prompt, "video_guide": str(origem),
        "image_refs": [t["destino"] for t in tarefas], "video_prompt_type": "FIVU", "frames_positions": " ".join(str(q + 1) for q in quadros),
        "audio_prompt_type": "K", "video_length": render, "sliding_window_size": MAX_QUADROS, "sliding_window_overlap": 17,
        "resolution": f"{largura}x{altura}", "num_inference_steps": PASSOS_VIGGLE, "flow_shift": 12, "sample_solver": "euler",
        "guidance_phases": 1, "guidance_scale": 1, "multi_prompts_gen_type": "PW", "seed": semente % 2**32,
        # O codificador de texto NVFP4 (15,7 GB, o mesmo arquivo do ComfyUI): o INT8 padrao tem 26,7 GB e a RAM e de 32 GB
        "config": "nvfp4_awq"}})
    pedido = trab / "tarefas.json"
    pedido.write_text(json.dumps({"raiz": str(config.WANGP), "saida": str(trab / "saidas"), "tarefas": tarefas}, ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / "prompt.txt").write_text(f"Pintor (Qwen Image 2.1 Viggle Image Swap):\n{PINTOR[roupa]}\n\nViggle Remake:\n{prompt}\n", encoding="utf-8")

    # O WanGP precisa da placa inteira: o ComfyUI solta o que tiver carregado (o SAM do recorte, por exemplo)
    acabamento.liberar_comfy()
    inicio = time.time()
    placa = Placa(mon)
    placa.start()
    mudar_etapa(progresso, "pintar", 0, len(quadros))
    ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HOME": str(config.WANGP / ".cache" / "hf")}
    proc = subprocess.Popen([str(config.WANGP_PYTHON), "-I", "-X", "utf8", "-u", str(config.ESTUDIO / "wangp_executar.py"), str(pedido)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(config.WANGP), env=ambiente,
                            text=True, encoding="utf-8", errors="replace", creationflags=config.SEM_JANELA)
    placa.proc = proc
    for linha in proc.stdout:
        if not linha.startswith("@@ "):
            print(linha.rstrip(), flush=True)
            continue
        try:
            d = json.loads(linha[3:])
        except ValueError:
            continue
        if d.get("etapa") == "viggle":
            mudar_etapa(progresso, "viggle", 0, PASSOS_VIGGLE)
        elif "passo" in d and progresso.etapa == "viggle":
            mudar_etapa(progresso, "viggle", d["passo"], d["total"])
        elif "pronta" in d:
            print(f"WanGP: tarefa {d['pronta']} de {len(tarefas)} pronta em {d['segundos']} s", flush=True)
            if progresso.etapa == "pintar":
                mudar_etapa(progresso, "pintar", d["pronta"], len(quadros))
    codigo = proc.wait()
    placa.fim.set()
    if mon.quente:
        print("FALHA na geracao: a placa chegou ao limite de temperatura e o WanGP foi parado.", flush=True)
        sys.exit(5)
    if codigo != 0 or not gerado.is_file():
        print(f"FALHA na geracao: o WanGP parou (código {codigo}). O motivo está nas linhas acima.", flush=True)
        sys.exit(4)

    mudar_etapa(progresso, "montar")
    segundos = pedidos / FPS
    final = pasta / "final.mp4"
    ffmpeg("-i", str(gerado), "-frames:v", str(pedidos), "-t", f"{segundos:.6f}", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final))
    try:
        # Lado a lado, com o som da troca: o trecho original | a troca, na altura da troca
        ffmpeg("-i", str(origem), "-i", str(final), "-filter_complex",
               f"[0:v]trim=end_frame={pedidos},setpts=PTS-STARTPTS,scale=-2:{altura},setsar=1[a];[1:v]scale=-2:{altura},setsar=1[b];[a][b]hstack[v]",
               "-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-t", f"{segundos:.6f}", str(pasta / "comparativo.mp4"))
    except subprocess.CalledProcessError as e:
        print(f"AVISO: não consegui montar o comparativo ({e}).", flush=True)
    medidas = {"segundos": round(time.time() - inicio), "pico_vram": placa.pico_vram, "temp_max": placa.temp_max}
    return medidas, prompt
