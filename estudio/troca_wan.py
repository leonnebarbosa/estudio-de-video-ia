"""Troca de personagem pelo Wan Animate 2 (motor "wan" da aba Trocar), chamada pelo trocar_personagem.py.

O Wan Animate 2 (Wan-AI/Wan2.2-Animate-2-14B, nos nativos do ComfyUI) anima uma imagem com o movimento de um video: rosto,
corpo e maos. Aqui a imagem e o primeiro quadro do proprio trecho ja pintado com a personagem (o mesmo pintor do motor
Viggle: Klein + BFS com a roupa do video, Qwen Viggle Swap com a roupa da foto), entao o enquadramento, a pose inicial e o
cenario batem com o video, que e o que o modelo mais pede ("framing mismatch is the #1 cause of bad results"). Com o fundo
novo, o cenario vem da foto escolhida, pelo quadro pintado.

Receita: o fluxo oficial (Comfy-Org/workflow_templates, video_wan_animate2.json, subgrafo "Motion Transfer") desenrolado sem os
nos de loop: wan_animate_2_int8_convrot + LoRA lightx2v, 6 passos lcm, cfg 1, shift 5, janelas de 81 quadros em que cada uma
continua da anterior (continue_motion + video_frame_offset) e perde o 1o quadro, que repete o ultimo da anterior. O cache do
video de movimento vai na CPU (a nota do fluxo: evita picos de VRAM). Lado menor 480, o tamanho em que o modelo foi treinado.

Teste de 22/11/2026 (testes_troca/reel_identico_2026-11-22/wan_animate2, 5 s de selfie a 480x848, 150 quadros): 12,7 min, pico
de 9,6 GB, 71 graus. Foi o resultado mais natural (pele, boca fechando nos p, b e m), com a correlacao do fidelidade.py entre
0,82 e 0,93; exagera a expressao onde a do original e ambigua (um meio sorriso virou gargalhada), e baixar pose_strength ou
descrever expressoes contidas quase nao mudou isso. Por isso e o segundo motor: mais natural, menos identico.

Saidas no projeto: final.mp4, comparativo.mp4 (trecho original | troca), prompt.txt e a pasta wan/ com os quadros.
"""
import math
import shutil
import sys
import time

import config
import entrada
import entrada_temp
import loras
from troca_wangp import FPS, PINTOR, conferir_comfy, contar_quadros, ffmpeg, garantir_24fps, montar_final, mudar_etapa, quadro_do_video

MODELO = "wan_animate_2_int8_convrot.safetensors"
LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
CODIFICADOR = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VISAO = "clip_vision_h.safetensors"
VAE = "wan_2.1_vae.safetensors"
JANELA = 81
PASSOS = 6
LADO_MENOR = 480
NO_VIDEO = "26"
# O que o texto pode dizer sem conhecer o video: a aparencia vem da imagem e o movimento do video
TEXTO_PERSONAGEM = ("Character Description: the person in the reference image, with exactly their face, hair, skin and outfit, natural unretouched skin.\n"
                    "Background description: the place shown in the reference image, stationary.")
TEXTO_MOVIMENTO = "The person performs exactly the motion, the gestures, the facial expressions and the mouth movements of the driving video, background stationary."
NEGATIVO = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
            "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")


def faltam():
    """Os arquivos do Wan Animate 2 que nao estao na pasta de modelos do ComfyUI, como "pasta/arquivo"."""
    arquivos = (("diffusion_models", MODELO), ("text_encoders", CODIFICADOR), ("clip_vision", VISAO), ("vae", VAE))
    ausentes = [f"{pasta}/{nome}" for pasta, nome in arquivos if not (config.MODELOS / pasta / nome).is_file()]
    return ausentes + ([] if LORA.lower() in loras.mapa() else [f"loras/wan/{LORA}"])


def tamanho(largura, altura):
    """O tamanho da geracao na proporcao do video, com o lado menor em LADO_MENOR e os dois multiplos de 16."""
    if largura <= altura:
        return LADO_MENOR, max(16, round(LADO_MENOR * altura / largura / 16) * 16)
    return max(16, round(LADO_MENOR * largura / altura / 16) * 16), LADO_MENOR


def comprimentos(total):
    """Quantos quadros cada janela gera: a primeira JANELA, as seguintes acrescentam JANELA - 1 cada, a ultima so o que falta
    (em 4n+1, o formato do Wan)."""
    feitos, tamanhos = 0, []
    while feitos < total:
        if not tamanhos:
            n = JANELA
            feitos = n
        else:
            n = min(JANELA, 4 * math.ceil((total - feitos) / 4) + 1)
            feitos += n - 1
        tamanhos.append(n)
    return tamanhos


def grafo(referencia, video, total, largura, altura, semente, prefixo):
    """`referencia` (imagem) e `video` (a 24 fps, com o som) na entrada do ComfyUI. Gera `total` quadros."""
    redimensionar = lambda origem: {"class_type": "ResizeImageMaskNode", "inputs": {"input": origem, "resize_type": "scale dimensions", "resize_type.width": largura,
                                                                                   "resize_type.height": altura, "resize_type.crop": "center", "scale_method": "area"}}
    g = {
        "578": {"class_type": "UNETLoader", "inputs": {"unet_name": MODELO, "weight_dtype": "default"}},
        "579": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["578", 0], "lora_name": LORA, "strength_model": 1.0}},
        "594": {"class_type": "WanAnimate2Cache", "inputs": {"model": ["579", 0], "device": "cpu", "dtype": "int8"}},
        "592": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["594", 0], "shift": 5.0}},
        "591": {"class_type": "BasicScheduler", "inputs": {"model": ["594", 0], "scheduler": "simple", "steps": PASSOS, "denoise": 1.0}},
        "593": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "lcm"}},
        "580": {"class_type": "CLIPLoader", "inputs": {"clip_name": CODIFICADOR, "type": "wan", "device": "default"}},
        "583": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": VISAO}},
        "584": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "1": {"class_type": "LoadImage", "inputs": {"image": referencia}},
        "2": {"class_type": "LoadVideo", "inputs": {"file": video}},
        "288": {"class_type": "GetVideoComponents", "inputs": {"video": ["2", 0]}},
        "3": {"class_type": "ImageFromBatch", "inputs": {"image": ["288", 0], "batch_index": 0, "length": total}},
        "600": redimensionar(["3", 0]),
        "590": redimensionar(["1", 0]),
        "599": {"class_type": "ImageFromBatch", "inputs": {"image": ["600", 0], "batch_index": 0, "length": 1}},
        "582": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["580", 0], "text": TEXTO_PERSONAGEM}},
        "585": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["580", 0], "text": TEXTO_MOVIMENTO}},
        "581": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["580", 0], "text": NEGATIVO}},
        "589": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["583", 0], "image": ["590", 0], "crop": "none"}},
        "598": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["583", 0], "image": ["599", 0], "crop": "none"}},
    }
    partes, anterior, pulo = [], None, 0
    for i, n in enumerate(comprimentos(total)):
        w, s, t, d = f"{i}87", f"{i}97", f"{i}02", f"{i}01"
        g[w] = {"class_type": "WanAnimate2ToVideo", "inputs": {
            "positive": ["582", 0], "negative": ["581", 0], "vae": ["584", 0], "reference_image": ["590", 0], "pose_video": ["600", 0],
            "clip_vision_output": ["589", 0], "positive_pose": ["585", 0], "clip_vision_output_pose": ["598", 0],
            "width": largura, "height": altura, "length": n, "batch_size": 1, "video_frame_offset": pulo,
            "pose_strength": 1.0, "pose_start_percent": 0.0, "pose_end_percent": 1.0, "reference_image_strength": 1.0}}
        if anterior:
            g[w]["inputs"]["continue_motion"] = anterior
        g[s] = {"class_type": "SamplerCustom", "inputs": {"model": ["592", 0], "add_noise": True, "noise_seed": semente + i, "cfg": 1.0, "positive": [w, 0],
                                                          "negative": [w, 1], "sampler": ["593", 0], "sigmas": ["591", 0], "latent_image": [w, 2]}}
        g[t] = {"class_type": "TrimVideoLatent", "inputs": {"samples": [s, 0], "trim_amount": [w, 3]}}
        g[d] = {"class_type": "VAEDecode", "inputs": {"samples": [t, 0], "vae": ["584", 0]}}
        if i == 0:
            partes.append([d, 0])
        else:
            g[f"{i}04"] = {"class_type": "ImageFromBatch", "inputs": {"image": [d, 0], "batch_index": 1, "length": 4096}}
            partes.append([f"{i}04", 0])
        anterior, pulo = [d, 0], [w, 5]
    junto = partes[0]
    for i, parte in enumerate(partes[1:]):
        g[f"9{i}0"] = {"class_type": "ImageBatch", "inputs": {"image1": junto, "image2": parte}}
        junto = [f"9{i}0", 0]
    g["95"] = {"class_type": "ImageFromBatch", "inputs": {"image": junto, "batch_index": 0, "length": total}}
    g["245"] = {"class_type": "CreateVideo", "inputs": {"images": ["95", 0], "audio": ["288", 1], "fps": FPS}}
    g[NO_VIDEO] = {"class_type": "SaveVideo", "inputs": {"video": ["245", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}}
    return g


def janela_do_evento(m, janelas):
    """(janela, passo) num aviso progress_state do ComfyUI, ou None se o aviso nao e da amostragem. As janelas sao os nos
    "097", "197"... do grafo."""
    if m.get("type") != "progress_state":
        return None
    nos = (m.get("data") or {}).get("nodes") or {}
    for i in range(janelas - 1, -1, -1):
        n = nos.get(f"{i}97") or {}
        if n.get("state") == "running" and n.get("max", 0) > 1:
            return i + 1, round(n.get("value", 0))
    return None


def trocar(pasta, p, video, foto, semente, mon, progresso, rodar, acompanhar=None, expressoes=()):
    """Faz a troca e grava pasta/final.mp4 e pasta/comparativo.mp4. Devolve (medidas, prompt), com os codigos de saida do
    trocar_personagem (4 falta algo ou falhou, 3 o ComfyUI caiu, 5 a placa esquentou). `foto` e `expressoes` como no
    troca_wangp.trocar."""
    import types
    import troca_viggle
    import troca_wangp
    from envio import examinar_video
    origem = entrada.caminho(video)
    if garantir_24fps(origem, pasta.name):
        print(f"o vídeo não estava a {FPS} quadros por segundo: convertido antes da troca", flush=True)
    roupa = p.get("roupa", "video")
    klein = roupa == "video"
    ausentes = faltam() + (troca_viggle.falta_do_klein() if klein else troca_viggle.falta_do_pintor())
    if ausentes:
        print("FALHA na geracao: faltam arquivos na pasta de modelos do ComfyUI: " + ", ".join(ausentes) + ".", flush=True)
        sys.exit(4)
    total = min(round(p["duracao"] * FPS), contar_quadros(origem))
    if total < 5:
        print("FALHA na geracao: o trecho do vídeo é curto demais.", flush=True)
        sys.exit(4)
    trab = pasta / "wan"
    trab.mkdir(exist_ok=True)
    inicio = time.time()
    original = trab / "original.mp4"
    shutil.copyfile(origem, original)
    info = examinar_video(origem)
    largura, altura = tamanho(info["largura"], info["altura"])

    if p.get("fundo"):
        import fundo
        mudar_etapa(progresso, "fundo")
        print("trocando o fundo: o BiRefNet e o SAM separam a pessoa e a foto acompanha o movimento da câmera", flush=True)
        try:
            fundo.trocar_fundo(video, entrada.caminho(p["fundo"]), total, (), rodar, ffmpeg, pasta)
        except Exception as e:
            print(f"FALHA na geracao: não consegui trocar o fundo ({e}).", flush=True)
            sys.exit(4)

    # A imagem que o Wan anima: o primeiro quadro do trecho com a personagem pintada
    mudar_etapa(progresso, "pintar", 0, 1)
    quadro, pintado = trab / "quadro_000.png", trab / "pintado_000.png"
    quadro_do_video(origem, 0, quadro)
    if klein:
        cabeca = troca_wangp.escolher_cabecas([quadro], list(expressoes) or [foto])[0]
        r = troca_viggle.pintar_klein(pasta.name, [(0, quadro, pintado, cabeca)], semente % 2**32, rodar)
    else:
        r = troca_viggle.pintar(pasta.name, [(0, quadro, pintado)], foto, PINTOR[roupa], semente % 2**32, rodar)
    conferir_comfy(r, mon, "a pintura do primeiro quadro")
    pico_vram, temp_max = r["pico_vram"], r["temp_max"]
    referencia = pintado
    if klein:
        import acabamento_rosto
        referencia = trab / "pintado_000_tom.png"
        if not referencia.is_file():
            try:
                acabamento_rosto.igualar_tom(pintado, quadro, referencia, iris=troca_wangp.iris_das_fotos([cabeca]))
            except Exception as e:
                print(f"AVISO: não igualei o tom da pele do quadro pintado ({e}).", flush=True)
                shutil.copyfile(pintado, referencia)
    mudar_etapa(progresso, "pintar", 1, 1)

    janelas = comprimentos(total)
    print(f"Wan Animate 2: {total} quadros a {largura}x{altura}, em {len(janelas)} janela{'s' if len(janelas) > 1 else ''}", flush=True)
    arq_ref, nome_ref = entrada_temp.arquivo(pasta.name, f"wan_{pasta.name}_ref.png")
    shutil.copyfile(referencia, arq_ref)
    g = grafo(nome_ref, video, total, largura, altura, semente % 2**32, f"troca/{pasta.name}_wan")
    (pasta / "prompt.txt").write_text(f"Wan Animate 2\n\nPersonagem:\n{TEXTO_PERSONAGEM}\n\nMovimento:\n{TEXTO_MOVIMENTO}\n", encoding="utf-8")
    mudar_etapa(progresso, "wan", 0, PASSOS)
    if acompanhar:
        def evento(m):
            onde = janela_do_evento(m, len(janelas))
            if onde:
                if len(janelas) > 1:
                    progresso.janela = [onde[0], len(janelas)]
                mudar_etapa(progresso, "wan", onde[1], PASSOS)
        acompanhar(types.SimpleNamespace(evento=evento))
    try:
        r = rodar(g, 7200)
    finally:
        arq_ref.unlink(missing_ok=True)
    progresso.janela = None
    gerado = None
    for item in (r["saidas"].get(NO_VIDEO) or {}).get("images") or []:
        if isinstance(item, dict) and str(item.get("filename", "")).endswith(".mp4"):
            gerado = config.SAIDA / item.get("subfolder", "") / item["filename"]
    if r["status"] == "success" and (gerado is None or not gerado.is_file()):
        r = {**r, "status": "sem vídeo", "erro": "o ComfyUI não informou o vídeo gerado"}
    conferir_comfy(r, mon, "o Wan Animate 2")
    shutil.copy2(gerado, trab / "wan.mp4")
    mudar_etapa(progresso, "montar")
    montar_final(trab / "wan.mp4", original, pasta, total, altura)
    return ({"segundos": round(time.time() - inicio), "pico_vram": max(pico_vram, r["pico_vram"]), "temp_max": max(temp_max, r["temp_max"])},
            f"Wan Animate 2: {TEXTO_MOVIMENTO}")
