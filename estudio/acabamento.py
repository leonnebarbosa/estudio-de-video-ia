"""Acabamento do video pronto: amplia para Full HD, com ou sem uma segunda passagem do H3 antes.

esrgan  RealESRGAN x2 quadro a quadro e corte no tamanho Full HD do formato. Testado em 08/11/2026 no video
        inteiro da barata (515 quadros de 544x928 em 160 s, 1 GB de memoria): contornos limpos, textura lisa.
refino  Antes do ESRGAN, o H3 refaz o video em pedacos de 73 quadros a cerca de 1 MP (latente ampliado pelo LMS,
        2 passos com sigma baixo). Testado so num pedaco de 3 s: ganha detalhe, mas clareia o fundo e pode mudar
        pequenas cores. Os pedacos se sobrepoem e sao misturados aos poucos para a emenda nao saltar.
A saida e final_hd.mp4, com o audio do final.mp4. O final.mp4 nao e alterado.
"""
import math, re, subprocess, sys, time
from pathlib import Path

import av
import imageio_ffmpeg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from comfy_api import posta, rodar
from trocar_personagem import arquivo_de_saida

MODELO_ESRGAN = "RealESRGAN_x2plus.pth"
LADO_MENOR = 1080
QUADROS_PEDACO, MISTURA = 73, 8  # 73 quadros a ~1 MP rodaram sem queda; 8 quadros (1/3 s) de mistura em cada emenda
MP_REFINO = 1.0
SIGMAS_REFINO = "0.6316, 0.3158, 0.0"
REALCE = "Enhance this video with sharp, crisp details while preserving the same cartoon 3D look, colors and motion."
FPS = 24


def tamanho_hd(proporcao):
    """Lado menor 1080, o outro pelo formato, sempre par."""
    m = re.match(r"(\d+):(\d+)", proporcao)
    w, h = int(m.group(1)), int(m.group(2))
    if h >= w:
        return LADO_MENOR, round(LADO_MENOR * h / w / 2) * 2
    return round(LADO_MENOR * w / h / 2) * 2, LADO_MENOR


def tamanho_refino(largura, altura):
    """Cerca de 1,41 vez em cada lado, no maximo 1 MP, multiplo de 32: 544x928 vira 768x1312, como no teste."""
    escala = min(math.sqrt(2), math.sqrt(MP_REFINO * 1024 * 1024 / (largura * altura)))
    return round(largura * escala / 32) * 32, round(altura * escala / 32) * 32


def pedacos(total):
    """Inicios dos pedacos, espalhados por igual: o primeiro no comeco, o ultimo terminando no fim e
    pelo menos MISTURA quadros em comum entre vizinhos."""
    if total <= QUADROS_PEDACO:
        return [0]
    n = math.ceil((total - MISTURA) / (QUADROS_PEDACO - MISTURA))
    return [round(i * (total - QUADROS_PEDACO) / (n - 1)) for i in range(n)]


def ler(arq):
    return list(quadros_de(arq))


def quadros_de(arq):
    c = av.open(str(arq))
    try:
        for f in c.decode(video=0):
            yield f.to_ndarray(format="rgb24")
    finally:
        c.close()


def contar_quadros(arq):
    c = av.open(str(arq))
    try:
        return sum(1 for _ in c.demux(video=0) if _.size)
    finally:
        c.close()


def fps_de(arq):
    """Os quadros por segundo de um video, como texto que o ffmpeg aceita (ex.: "24" ou "30000/1001"). Sem a informacao, 24."""
    c = av.open(str(arq))
    try:
        taxa = c.streams.video[0].average_rate
        return str(taxa) if taxa else str(FPS)
    finally:
        c.close()


def gravar_mp4(quadros, destino, crf=10):
    h, w = quadros[0].shape[:2]
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-crf", str(crf), "-preset", "fast", "-pix_fmt", "yuv420p", str(destino)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for q in quadros:
        proc.stdin.write(np.ascontiguousarray(q).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg falhou ao gravar {destino}")


def liberar_comfy():
    """Tira os modelos do H3 da placa antes do ESRGAN rodar fora do ComfyUI."""
    try:
        posta("/free", {"unload_models": True, "free_memory": True})
        time.sleep(3)
    except OSError:
        pass


def esrgan(quadros, total, entrada_audio, saida, proporcao, avisar=lambda feito, total: None, fps=FPS):
    """Amplia cada quadro (qualquer iteravel, com total itens) com o ESRGAN, cobre o tamanho Full HD e corta o excesso
    no centro. Audio copiado de entrada_audio, se houver (o Wan nao tem). fps: o do video (H3 24, Wan 16)."""
    import torch
    from spandrel import ModelLoader
    W, H = tamanho_hd(proporcao)
    modelo = ModelLoader().load_from_file(str(config.MODELOS / "upscale_models" / MODELO_ESRGAN)).model.eval().half().cuda()
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(entrada_audio), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "copy", str(saida)]
    # Sem -shortest: o audio e um pouco mais curto que o video e cortaria os ultimos quadros
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        with torch.inference_mode():
            for i, q in enumerate(quadros):
                x = torch.from_numpy(q).cuda().half().permute(2, 0, 1)[None] / 255
                y = modelo(x).clamp(0, 1)[0].permute(1, 2, 0).float().mul(255).round().byte().cpu().numpy()
                img = Image.fromarray(y)
                escala = max(W / img.width, H / img.height)
                nw, nh = max(W, round(img.width * escala)), max(H, round(img.height * escala))
                img = img.resize((nw, nh), Image.LANCZOS)
                e, t = (nw - W) // 2, (nh - H) // 2
                proc.stdin.write(np.asarray(img.crop((e, t, e + W, t + H))).tobytes())
                if i % 12 == 0:
                    avisar(i, total)
    finally:
        proc.stdin.close()
        codigo = proc.wait()
        del modelo
        torch.cuda.empty_cache()
    if codigo != 0:
        raise RuntimeError("ffmpeg falhou ao gravar o video ampliado")


def grafo_refino(video, quadros, largura, altura, prompt, referencias, prefixo, semente):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "3": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["2", 0], "attention": "comfy kitchen attention"}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["3", 0], "lora_name": "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", "strength_model": 1.0}},
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["4", 0], "lora_name": "minimax_h3_lms_v1.0_r64.safetensors", "strength_model": 0.7}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "30": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"clip": ["10", 0], "vae": ["11", 0], "audio_vae": ["12", 0], "prompt": prompt,
                                                                   "width": largura, "height": altura, "length": quadros, "ref_image_size": "max"}},
        "40": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": video, "force_rate": 0, "custom_width": 0, "custom_height": 0, "frame_load_cap": quadros, "start_time": 0}},
        "41": {"class_type": "VAEEncode", "inputs": {"pixels": ["40", 0], "vae": ["11", 0]}},
        "42": {"class_type": "MinimaxH3LatentUpscaler3D", "inputs": {"latent": ["41", 0], "model_name": "h3_upscaler_lms_v0.1.safetensors", "mode": "target dimensions",
                                                                   "mode.width": largura, "mode.height": altura, "align": 32, "enable_temporal_chunking": True, "force_unload": True,
                                                                   "device": "cuda", "precision": "fp16"}},
        "43": {"class_type": "EmptyMiniMaxH3LatentAV", "inputs": {"width": largura, "height": altura, "length": quadros}},
        "44": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["43", 0]}},
        "45": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["42", 0], "audio_latent": ["44", 1]}},
        "50": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        "51": {"class_type": "BasicGuider", "inputs": {"model": ["5", 0], "conditioning": ["30", 0]}},
        "52": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "53": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_REFINO}},
        "54": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["50", 0], "guider": ["51", 0], "sampler": ["52", 0], "sigmas": ["53", 0], "latent_image": ["45", 0]}},
        "55": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["54", 0]}},
        "56": {"class_type": "VAEDecode", "inputs": {"samples": ["55", 0], "vae": ["11", 0]}},
        "57": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["56", 0], "frame_rate": FPS, "loop_count": 0, "filename_prefix": prefixo, "format": "video/h264-mp4",
                                                          "pix_fmt": "yuv420p", "crf": 14, "save_metadata": False, "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }
    for i, nome in enumerate(referencias):
        g[f"2{i}"] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g["30"]["inputs"][f"ref_images.ref_image_{i}"] = [f"2{i}", 0]
    return g


def prompt_refino(quem, tomada, n_refs):
    vistas = ", ".join(f"<Picture {i}>" for i in range(1, n_refs + 1))
    acao = " ".join(str(tomada.get("acao") or "").split())
    fala = " ".join(str(tomada.get("fala") or "").replace("<", "").replace(">", "").split())
    partes = [f"<Subject 1> is {quem}, shown in {vistas}. The plain background of those pictures is not part of the scene.",
              acao, f"The character (S1) says: <d>[Brazilian Portuguese] {fala}</d>" if fala else "", REALCE]  # o mesmo IDIOMA de imagem_para_video
    return " ".join(x for x in partes if x)


def igualar_cor(refinado, original):
    """O refino clareia o fundo: ganho por canal medido no quadro inteiro, para voltar a cor do original."""
    a = np.median(original.reshape(-1, 3), axis=0).astype(np.float32)
    b = np.median(refinado.reshape(-1, 3), axis=0).astype(np.float32)
    return np.clip(a / np.maximum(b, 1), 0.85, 1.2)


def plano_refino(total):
    """Tamanho de cada pedaco e onde cada um comeca."""
    if total < 2 * MISTURA + 1:
        raise RuntimeError("Video curto demais para o refino.")
    # O modelo so aceita 17k+5 quadros; videos curtos usam o maior tamanho valido que cabe
    tam = (min(QUADROS_PEDACO, total) - 5) // 17 * 17 + 5
    inicios = pedacos(total)
    if len(inicios) == 1 and tam < total:
        inicios = [0, total - tam]
    return tam, inicios


def refinar(quadros, largura, altura, prompts, referencias, entrada_comfy, marca, prefixo, semente, avisar=lambda feito, total: None):
    """Refaz o video em pedacos no ComfyUI. prompts(inicio, fim) da o texto de cada pedaco.
    Devolve (tam, [(inicio, arquivo)], medidas) ou levanta RuntimeError com a falha."""
    lw, lh = tamanho_refino(largura, altura)
    tam, inicios = plano_refino(len(quadros))
    prontos, medidas = [], []
    for k, ini in enumerate(inicios):
        avisar(k, len(inicios))
        # marca ja vem com o projeto (imagem_<projeto>_<hora>): assim apagar o projeto acha estes arquivos
        nome = f"{marca}_acab{k:02d}.mp4"
        gravar_mp4(quadros[ini:ini + tam], entrada_comfy / nome)
        r = rodar(grafo_refino(nome, tam, lw, lh, prompts(ini, ini + tam), referencias, f"{prefixo}_p{k:02d}", semente + k), 1800)
        medidas.append({k2: r.get(k2) for k2 in ("status", "segundos", "pico_vram", "temp_max")})
        if r["status"] != "success":
            raise RuntimeError(f"refino do pedaco {k + 1} de {len(inicios)}: {r['status']} {r.get('erro', '')[:500]}")
        arq = arquivo_de_saida(r["saidas"].get("57", {}))
        if arq is None or not arq.is_file():
            raise RuntimeError(f"refino do pedaco {k + 1}: o ComfyUI nao informou o video")
        prontos.append((ini, arq))
    avisar(len(inicios), len(inicios))
    return tam, prontos, medidas


def misturar(quadros, tam, prontos):
    """Entrega os quadros refinados em ordem, com a cor do original e uma mistura gradual onde os pedacos se sobrepoem.
    Le um pedaco por vez, para nao guardar o video inteiro na memoria."""
    total = len(quadros)
    cache = {}

    def pedaco(k):
        if k not in cache:
            # Um quadro pode estar em dois pedacos: guarda no maximo os dois da vez
            for velho in [x for x in cache if x < k - 1]:
                del cache[velho]
            q = ler(prontos[k][1])[:tam]
            if len(q) < tam:
                raise RuntimeError(f"refino do pedaco {k + 1}: voltaram {len(q)} quadros de {tam}")
            cache[k] = q
        return cache[k]

    def peso(k, j):
        """Rampa nas bordas que encostam em outro pedaco; nas pontas do video, peso cheio."""
        ini, w = prontos[k][0], 1.0
        if k > 0:
            sobra = prontos[k - 1][0] + tam - ini
            if j < sobra:
                w = min(w, (j + 1) / (sobra + 1))
        if k < len(prontos) - 1:
            sobra = ini + tam - prontos[k + 1][0]
            if j >= tam - sobra:
                w = min(w, (tam - j) / (sobra + 1))
        return w

    for i in range(total):
        soma, pesos = None, 0.0
        for k, (ini, _) in enumerate(prontos):
            if ini <= i < ini + tam:
                q = pedaco(k)[i - ini]
                h, w = q.shape[:2]
                original = np.asarray(Image.fromarray(quadros[i]).resize((w, h), Image.LANCZOS))
                p = peso(k, i - ini)
                v = q.astype(np.float32) * igualar_cor(q, original) * p
                soma = v if soma is None else soma + v
                pesos += p
        yield np.clip(np.rint(soma / max(pesos, 1e-6)), 0, 255).astype(np.uint8)
