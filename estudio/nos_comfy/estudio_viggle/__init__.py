"""No do estudio para o Viggle Remake (LoRA de troca/edicao sobre o MiniMax H3 FL2VA) dentro do ComfyUI.
Esta e a copia de origem: o troca_viggle.preparar a poe em ComfyUI/custom_nodes/estudio_viggle.

Monta a entrada como o WanGP faz (models/minimax_h3/pipeline.py, remake_mode):
- o video original e a PRIMEIRA referencia, sem trilha, no tamanho da saida;
- cada quadro pintado entra depois, como referencia de imagem;
- o codificador de texto recebe so os rotulos ("<Video 1>: <0.2 seconds>...<Picture 1>: "), sem imagens.
Os quadros pintados presos a um instante continuam por conta do no "Add Guide for MiniMax H3" do ComfyUI.
"""
import math

import node_helpers
from comfy_extras.nodes_minimax_h3 import CANVAS_MULTIPLE, FPS, _empty_av_latent, _resize

VERSAO = 2


def rotulos(quadros_video, n_fotos):
    """O prefixo de rotulos do WanGP: um carimbo a cada par de amostras tiradas a 2 por segundo."""
    indices, cursor = [], 0.0
    while round(cursor) < quadros_video:
        if not indices or round(cursor) > indices[-1]:
            indices.append(round(cursor))
        cursor += FPS / 2
    tempos = [i / FPS for i in indices]
    if len(tempos) % 2:
        tempos.append(tempos[-1])
    texto = "<Video 1>: " + "".join("<%.1f seconds>" % ((tempos[i] + tempos[i + 1]) / 2.0) for i in range(0, len(tempos), 2))
    return texto + "".join("<Picture %d>: " % k for k in range(1, n_fotos + 1))


class EstudioViggleRemake:
    DESCRIPTION = "Condicionamento do Viggle Remake no MiniMax H3: video original como primeira referencia e quadros pintados depois."
    CATEGORY = "estudio"
    FUNCTION = "montar"
    RETURN_TYPES = ("CONDITIONING", "LATENT", "STRING")
    RETURN_NAMES = ("positive", "latent", "prefixo")

    @classmethod
    def INPUT_TYPES(cls):
        foto = ("IMAGE", {"tooltip": "Quadro do video ja pintado (referencia)"})
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "prompt": ("STRING", {"multiline": True}),
                "width": ("INT", {"default": 928, "min": 32, "max": 4096, "step": 32}),
                "height": ("INT", {"default": 544, "min": 32, "max": 4096, "step": 32}),
                "length": ("INT", {"default": 124, "min": 5, "max": 3600, "step": 17}),
                "video": ("IMAGE", {"tooltip": "Quadros do video original a 24 fps"}),
            },
            "optional": {"foto_1": foto, "foto_2": foto, "foto_3": foto, "foto_4": foto},
        }

    def montar(self, clip, vae, prompt, width, height, length, video, foto_1=None, foto_2=None, foto_3=None, foto_4=None):
        latent, frame_count = _empty_av_latent(width, height, length)

        # Corte no centro, como o Add Guide faz com os quadros presos: o video e os quadros ficam no mesmo enquadramento
        quadros = _resize(video[:frame_count], width, height, "center")
        n = quadros.shape[0]
        if n < 5:
            raise ValueError("o video de referencia precisa de pelo menos 5 quadros")
        while n % 17 != 5:
            n -= 1
        quadros = quadros[:n]
        z = vae.encode(quadros)
        refs = [{"kind": "video", "latent_t": z.shape[2], "latent_h": height // 16, "latent_w": width // 16,
                 "ref_audio_t": 0, "latent": z, "audio_latent": None}]

        fotos = [f for f in (foto_1, foto_2, foto_3, foto_4) if f is not None]
        for foto in fotos:
            h, w = foto.shape[1], foto.shape[2]
            escala = math.sqrt((width * height) / (w * h))  # mesma area da saida, proporcao da foto
            tw = max(CANVAS_MULTIPLE, round(w * escala / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            th = max(CANVAS_MULTIPLE, round(h * escala / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            zi = vae.encode(_resize(foto[:1], tw, th, "disabled"))
            refs.append({"kind": "image", "latent_h": th // 16, "latent_w": tw // 16, "latent": zi})

        prefixo = rotulos(n, len(fotos))
        cond = clip.encode_from_tokens_scheduled(clip.tokenize(prefixo + prompt))
        cond = node_helpers.conditioning_set_values(cond, {"minimax_refs": refs})
        return (cond, latent, prefixo)


NODE_CLASS_MAPPINGS = {"EstudioViggleRemake": EstudioViggleRemake}
NODE_DISPLAY_NAME_MAPPINGS = {"EstudioViggleRemake": "Viggle Remake (estudio)"}
