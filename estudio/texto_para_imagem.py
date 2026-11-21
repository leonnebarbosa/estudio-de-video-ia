"""Texto para imagem: gera de 1 a 4 imagens com o Chroma1-HD-Flash a partir de um prompt.

Uso: python -I texto_para_imagem.py --projeto NOME
Le projetos/NOME/interface.json (prompt, negativo, proporcao, megapixels, quantidade, passos, semente) e grava
imagem_N.png na pasta do projeto, mais estado.json, progresso.json e gpu.csv. Se parar no meio, rodar de novo
segue da proxima imagem.
Configuracao do WEB_chroma_personagem_ficticia.json: 12 passos, CFG 1, euler com agendador beta.
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da geracao, 5 temperatura.
"""
import argparse, json, os, random, shutil, struct, sys, time
from pathlib import Path

# Com python -I a pasta do script nao entra no caminho de importacao
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, extras, loras, troca_foto
from continuar_video import Monitor, rodar
from detalhe_comfy import Detalhe
from imagem_para_video import tamanho
from trocar_personagem import acompanhar

MODELO = "Chroma1-HD-Flash-Q5_K_M.gguf"
ENCODER = "t5xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "ae.safetensors"
AMOSTRADOR = "7"
# Os modelos do seletor da aba. Um modelo novo entra aqui, depois de testado na 3080: arquivos, carregador, passos e amostrador.
# familia: diz quais LoRAs servem (ver familia_lora). negativo "texto" usa o campo O que evitar; "zero" zera o negativo, como nos fluxos oficiais.
MODELOS_TEXTO = {
    "chroma_flash": {"nome": "Chroma1-HD-Flash", "familia": "chroma",
                     "ajuda": "Rápido: 12 passos, cerca de 40 s por imagem em 0,9 MP. Não usa o texto do que evitar com força (CFG 1).",
                     "carregador": "UnetLoaderGGUF", "unet": MODELO, "encoder": ENCODER, "tipo_encoder": "chroma", "vae": VAE, "passos": 12,
                     "amostrador": "euler", "agendador": "beta", "latente": "EmptySD3LatentImage", "negativo": "texto", "shift": None},
    # Grafo do fluxo oficial image_z_image_turbo_int8: AuraFlow shift 3, 8 passos, res_multistep/simple.
    # Testado em 09/11/2026: 10 s por imagem de 1 MP (23 s a primeira, lendo do disco), pico de 9,4 GB.
    "z_image_turbo": {"nome": "Z-Image Turbo", "familia": "zimage",
                      "ajuda": "O mais rápido: uns 15 a 25 segundos por imagem. Bom em fotos realistas e em texto escrito na imagem. Entende português.",
                      "carregador": "UNETLoader", "unet": "z_image_turbo_int8_convrot.safetensors", "encoder": "qwen_3_4b_fp8_mixed.safetensors",
                      "tipo_encoder": "lumina2", "vae": VAE, "passos": 8, "amostrador": "res_multistep", "agendador": "simple",
                      "latente": "EmptySD3LatentImage", "negativo": "zero", "shift": 3},
    # FLUX.2 Klein 4B destilado (BFL, Apache 2.0), grafo do fluxo oficial de edicao do Klein. Teste de troca de roupa de 11/11/2026
    # (projetos/teste_editar_roupa): a 2 MP, 19 a 31 s por edicao, pico de 9,5 GB, rosto maior e com textura de pele; mais fiel que o Qwen
    # com Lightning. A 1 MP o rosto saiu pior. Exagera sardas se o pedido as citar. E o Editar padrao (primeiro da lista) desde 13/11/2026:
    # no teste teste_pele_* (mesma foto, semente 42) saiu nitido e fiel em 31 s, contra ~75 s e pele lisa no Qwen.
    "klein_edit": {"nome": "Editar imagem (FLUX.2 Klein, recomendado)", "familia": "flux2_klein", "edicao": True, "grafo_edicao": "klein",
                   "ajuda": "Muda só o que você pedir na imagem de partida: roupa, fundo, cor. Uns 30 s, com a pele natural e o rosto fiel. "
                            "Sai em 2 MP, na proporção da imagem. Não cite sardas no pedido: ele as exagera.",
                   "carregador": "UNETLoader", "unet": "flux-2-klein-4b-fp8.safetensors", "encoder": "qwen_3_4b_fp8_mixed.safetensors",
                   "tipo_encoder": "flux2", "vae": "flux2-vae.safetensors", "passos": 4, "amostrador": "euler", "agendador": None,
                   "latente": None, "negativo": "zero", "shift": None, "megapixels_edicao": 2.0},
    # Editar por instrucao: parte da imagem de partida e muda so o que a instrucao pede. Grafo do fluxo oficial image_qwen_image_edit_2511
    # com a LoRA Lightning de 4 passos (fixa). Testado em 09/11/2026: 112 a 117 s por edicao (modelo de 20 GB + codificador de 9 GB), pico de 9,4 GB.
    # Em pessoas a Lightning alisa a pele (efeito de plastico); a LoRA de pele da 2509 nao corrigiu (teste_pele_*, 13/11/2026).
    "qwen_edit": {"nome": "Editar imagem (Qwen, mais lento)", "familia": "qwen_edit", "edicao": True,
                  "ajuda": "Bom para trocar o texto de um letreiro ou um objeto. Em pessoas a pele sai lisa: prefira o Klein. Uns 75 s por edição, em 1 MP.",
                  "carregador": "UNETLoader", "unet": "qwen_image_edit_2511_int8_convrot.safetensors", "encoder": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                  "tipo_encoder": "qwen_image", "vae": "qwen_image_vae.safetensors", "passos": 4, "amostrador": "euler", "agendador": "simple",
                  "latente": None, "negativo": "edicao", "shift": 3.1, "lora_fixa": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"},
}
# Modelos da comunidade testados so nesta maquina entram pelo arquivo local, fora do git (ver extras.py)
MODELOS_TEXTO.update(extras.secao("texto"))
MAX_LORAS_TEXTO = 2
# Descrever imagem: a LLM de visao da troca (Qwen3.5 9B) escreve um prompt a partir de uma imagem. Sem raciocinio:
# com ele e poucos tokens a resposta vinha vazia (teste da troca, 09/11/2026).
LLM_VISAO = "qwen3.5_9b_w4a8_gptq.safetensors"
INSTRUCAO_DESCREVER = ("Describe this image as a single prompt for a text-to-image model, in English. Cover the main subject (apparent age, "
                       "appearance, clothing, pose, expression), the setting and background, the lighting, the camera framing and lens, and the "
                       "overall style (photo, illustration, 3D render...). Write one natural paragraph of 60 to 120 words describing only what is "
                       "visible, with no preamble, no lists and no quotation marks.")


def grafo_descrever(arquivo):
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": arquivo}},
        # A LLM nao precisa da imagem grande: 0,5 MP ja mostra tudo e gasta menos memoria
        "2": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "megapixels": 0.5, "resolution_steps": 1}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": LLM_VISAO, "type": "minimax", "device": "default"}},
        "4": {"class_type": "TextGenerate", "inputs": {"clip": ["3", 0], "image": ["2", 0], "prompt": INSTRUCAO_DESCREVER, "max_length": 400,
                                                       "sampling_mode": "on", "sampling_mode.temperature": 0.7, "sampling_mode.top_k": 64,
                                                       "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05,
                                                       "sampling_mode.seed": 0, "sampling_mode.presence_penalty": 0, "thinking": False,
                                                       "use_default_template": True, "mtp": "auto"}},
        "5": {"class_type": "PreviewAny", "inputs": {"source": ["4", 0]}},
    }


def descrever(arquivo, tempo=300):
    """O prompt que a LLM escreveu para a imagem (arquivo na entrada do ComfyUI). RuntimeError se o ComfyUI falhar."""
    from trocar_personagem import texto_de_saida
    r = rodar(grafo_descrever(arquivo), tempo)
    if r["status"] != "success":
        raise RuntimeError(f"{r['status']} {r.get('erro', '')[:300]}")
    return texto_de_saida(r["saidas"].get("5") or {}).strip().strip('"').strip()


def arquivos_que_faltam(modelo):
    m = MODELOS_TEXTO[modelo]
    lugares = {"unet": ("diffusion_models", "unet"), "encoder": ("text_encoders", "clip"), "vae": ("vae",)}
    return [m[k] for k, pastas in lugares.items() if not any((config.MODELOS / p / m[k]).is_file() for p in pastas)]


# Que modelo uma LoRA atende, pelo cabecalho do .safetensors: o metadado de treino, se houver, ou o formato dos nomes dos pesos.
# LoRAs de video (H3, Wan) e de outros modelos ficam de fora (None). Guardado por tamanho e data do arquivo.
_FAMILIAS = (("krea2", ("krea2",), (".attn.gate", ".attn.wk")), ("zimage", ("zimage", "z_image", "z-image"), (".adaln_modulation", ".feed_forward.w")),
             ("chroma", ("chroma",), ("double_blocks", "single_transformer_blocks", "single_blocks")),
             ("qwen_edit", ("qwen_image",), ("transformer_blocks.0.attn.add_k_proj",)))
_cache_familia = {}


def familia_lora(arq):
    arq = Path(arq)
    try:
        st = arq.stat()
    except OSError:
        return None
    chave = (str(arq), st.st_size, st.st_mtime)
    if chave in _cache_familia:
        return _cache_familia[chave]
    familia = None
    try:
        with arq.open("rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            cab = json.loads(f.read(n)) if n < 50_000_000 else {}
        meta = " ".join(str(v) for k, v in (cab.get("__metadata__") or {}).items() if k in ("ss_base_model_version", "modelspec.architecture")).lower()
        nomes = " ".join(k.lower() for k in cab if k != "__metadata__")
        for nome, marcas_meta, marcas_peso in _FAMILIAS:
            if any(x in meta for x in marcas_meta) or any(x in nomes for x in marcas_peso):
                familia = nome
                break
    except (OSError, ValueError, struct.error):
        # Arquivo quebrado ou que nao e safetensors: nao aparece em nenhum modelo
        familia = None
    _cache_familia[chave] = familia
    return familia


def loras_compativeis(modelo):
    """As LoRAs da pasta loras (e subpastas) que servem para o modelo, pelo nome do arquivo (o caminho entra no envio, ver loras.py)."""
    pasta, familia = config.MODELOS / "loras", MODELOS_TEXTO[modelo]["familia"]
    if not pasta.is_dir():
        return []
    fixa = MODELOS_TEXTO[modelo].get("lora_fixa")
    return sorted({p.name for p in pasta.rglob("*.safetensors") if familia_lora(p) == familia and p.name != fixa}, key=str.lower)


def grafo_edicao(p, m, semente, prefixo):
    """Qwen Image Edit: a instrucao (prompt) e a imagem de partida entram juntas no codificador; o tamanho segue a imagem (~1 MP)."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "21": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": m["shift"]}},
        "22": {"class_type": "CFGNorm", "inputs": {"model": ["21", 0], "strength": 1.0}},
        "23": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["22", 0], "lora_name": m["lora_fixa"], "strength_model": 1.0}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["encoder"], "type": m["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "30": {"class_type": "LoadImage", "inputs": {"image": p["partida"]}},
        "31": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["30", 0]}},
        "4": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "image1": ["31", 0], "prompt": p["prompt"]}},
        "5": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "image1": ["31", 0], "prompt": ""}},
        "24": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["4", 0], "reference_latents_method": "index_timestep_zero"}},
        "25": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["5", 0], "reference_latents_method": "index_timestep_zero"}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["31", 0], "vae": ["3", 0]}},
        AMOSTRADOR: {"class_type": "KSampler", "inputs": {"seed": semente, "steps": p["passos"], "cfg": 1, "sampler_name": m["amostrador"], "scheduler": m["agendador"],
                                                          "denoise": 1, "model": ["23", 0], "positive": ["24", 0], "negative": ["25", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    if p.get("referencia"):
        # Segunda imagem: so entra no codificador, que ajusta o tamanho sozinho; a saida segue o tamanho da primeira
        g["32"] = {"class_type": "LoadImage", "inputs": {"image": p["referencia"]}}
        g["4"]["inputs"]["image2"] = g["5"]["inputs"]["image2"] = ["32", 0]
    modelo = ["23", 0]
    for i, (nome, forca) in enumerate(p.get("loras") or []):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"20{i}", 0]
    g[AMOSTRADOR]["inputs"]["model"] = modelo
    return g


def grafo_edicao_klein(p, m, semente, prefixo, *, tamanho_saida=None):
    """FLUX.2 Klein: a imagem de partida, levada a megapixels_edicao, entra como latente de referencia no positivo e no negativo zerado;
    a saida tem o mesmo tamanho. A segunda imagem, se houver, e mais uma referencia em cadeia."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["encoder"], "type": m["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "30": {"class_type": "LoadImage", "inputs": {"image": p["partida"]}},
        "31": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["30", 0], "upscale_method": "lanczos", "megapixels": m["megapixels_edicao"],
                                                                 "resolution_steps": 16}},
        "33": {"class_type": "GetImageSize", "inputs": {"image": ["31", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": ["33", 0], "height": ["33", 1], "batch_size": 1}},
        "34": {"class_type": "VAEEncode", "inputs": {"pixels": ["31", 0], "vae": ["3", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": p["prompt"], "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "24": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["4", 0], "latent": ["34", 0]}},
        "25": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["5", 0], "latent": ["34", 0]}},
        "40": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["24", 0], "negative": ["25", 0], "cfg": 1}},
        "41": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m["amostrador"]}},
        "42": {"class_type": "Flux2Scheduler", "inputs": {"steps": p["passos"], "width": ["33", 0], "height": ["33", 1]}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        AMOSTRADOR: {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["41", 0], "sigmas": ["42", 0],
                                                                       "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    if tamanho_saida:
        for no in ("6", "42"):
            g[no]["inputs"].update(width=tamanho_saida[0], height=tamanho_saida[1])
    if p.get("referencia"):
        # Segunda imagem: 1 MP basta para servir de referencia (a saida segue a primeira)
        g["32"] = {"class_type": "LoadImage", "inputs": {"image": p["referencia"]}}
        g["35"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["32", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 16}}
        g["36"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["35", 0], "vae": ["3", 0]}}
        g["26"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["24", 0], "latent": ["36", 0]}}
        g["27"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["25", 0], "latent": ["36", 0]}}
        g["40"]["inputs"]["positive"], g["40"]["inputs"]["negative"] = ["26", 0], ["27", 0]
    return g


def grafo_troca_foto(p, chave, partida, referencia, semente, prefixo):
    """Uma passada da troca em foto (ver troca_foto): o grafo do Editar com o Klein, com o pedido fixo de cada troca e, no rosto,
    a LoRA de troca de cabeca entre o modelo e o guia."""
    m = MODELOS_TEXTO["klein_edit"]
    pedido = troca_foto.PEDIDO_ROSTO if chave == "rosto" else troca_foto.PEDIDO_ROUPA
    g = grafo_edicao_klein({"partida": partida, "referencia": referencia, "prompt": pedido, "passos": p["passos"]}, m, semente, prefixo)
    if chave == "rosto":
        g["50"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": troca_foto.LORA_ROSTO, "strength_model": 1.0}}
        g["40"]["inputs"]["model"] = ["50", 0]
    return g


def grafo(p, semente, prefixo):
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    # Projeto de antes do seletor, sem a chave: o Chroma Flash
    m = MODELOS_TEXTO[p.get("modelo") or "chroma_flash"]
    # LoRA com palavra-chave fixa (loras.GATILHOS e o arquivo local): entra no começo do prompt, se ainda não estiver nele
    p = {**p, "prompt": loras.com_gatilho(p.get("loras"), p["prompt"], ", ")}
    if m.get("grafo_edicao") == "klein":
        return grafo_edicao_klein(p, m, semente, prefixo)
    if m.get("edicao"):
        return grafo_edicao(p, m, semente, prefixo)
    g = {
        "1": {"class_type": m["carregador"], "inputs": {"unet_name": m["unet"]} | ({"weight_dtype": "default"} if m["carregador"] == "UNETLoader" else {})},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["encoder"], "type": m["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": p["prompt"], "clip": ["2", 0]}},
        "6": {"class_type": m["latente"], "inputs": {"width": largura, "height": altura, "batch_size": 1}},
        AMOSTRADOR: {"class_type": "KSampler", "inputs": {"seed": semente, "steps": p["passos"], "cfg": 1, "sampler_name": m["amostrador"], "scheduler": m["agendador"],
                                                          "denoise": 1, "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    g["5"] = ({"class_type": "CLIPTextEncode", "inputs": {"text": p["negativo"], "clip": ["2", 0]}} if m["negativo"] == "texto"
              else {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}})
    modelo = ["1", 0]
    # LoRAs em cadeia, so no modelo (como nos fluxos oficiais); a validacao ja conferiu que servem para ele
    for i, (nome, forca) in enumerate(p.get("loras") or []):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"20{i}", 0]
    if m["shift"]:
        g["21"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": modelo, "shift": m["shift"]}}
        modelo = ["21", 0]
    g[AMOSTRADOR]["inputs"]["model"] = modelo
    if p.get("partida"):
        # Img2img: a imagem de partida, cortada no centro para o tamanho escolhido, entra no lugar do latente vazio.
        # A forca (denoise) diz quanto o modelo refaz: 0,3 so melhora detalhes, 0,6 redesenha mantendo a ideia, 1 ignora a imagem.
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": p["partida"]}}
        g["31"] = {"class_type": "ImageScale", "inputs": {"image": ["30", 0], "upscale_method": "lanczos", "width": largura, "height": altura, "crop": "center"}}
        g["6"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["31", 0], "vae": ["3", 0]}}
        g[AMOSTRADOR]["inputs"]["denoise"] = p.get("forca_partida", 0.6)
    return g


class Progresso:
    """Guarda a imagem e o passo atuais em progresso.json, que a pagina le enquanto a geracao roda."""

    def __init__(self, arquivo, total, monitor):
        self.arquivo, self.total, self.monitor = arquivo, total, monitor
        self.inicio = time.time()
        self.n, self.valor, self.maximo, self.em = 0, 0, 0, 0
        self.detalhe = Detalhe(monitor, inicio=self.inicio)

    def gravar(self):
        dados = {"imagem": self.n, "total": self.total, "valor": self.valor, "maximo": self.maximo, "em": self.em, **self.detalhe.dados()}
        temporario = self.arquivo.with_name(self.arquivo.name + ".tmp")
        try:
            temporario.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(temporario, self.arquivo)
        except OSError:
            # A pagina pode estar lendo o arquivo neste instante; a proxima gravacao resolve
            pass

    def imagem(self, n, g):
        self.n, self.valor, self.maximo = n, 0, 0
        self.em = round(time.time() - self.inicio)
        self.monitor.rotulo = f"imagem {n}"
        self.detalhe.reiniciar(g)
        self.gravar()

    def evento(self, m):
        if m.get("type") != "progress_state":
            return
        nos = (m.get("data") or {}).get("nodes") or {}
        rodando = self.detalhe.evento(nos)
        n = nos.get(AMOSTRADOR)
        if n and n.get("state") == "running" and n.get("max", 0) > 1:
            self.valor, self.maximo = round(n.get("value", 0)), round(n["max"])
        if rodando:
            self.gravar()


def gravar_estado(arquivo, estado):
    import caminhos
    caminhos.gravar_json(arquivo, estado)   # resiste a uma queda do PC (fsync antes de trocar)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--projeto", required=True)
    a = a.parse_args()
    pasta = config.PROJETOS / a.projeto
    p = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
    arq_estado = pasta / "estado.json"
    estado = json.loads(arq_estado.read_text(encoding="utf-8"))
    feitas = estado.setdefault("imagens", [])
    total = p["quantidade"]
    if len(feitas) >= total:
        print("todas as imagens ja estao prontas", flush=True)
        return

    mon = Monitor(pasta / "gpu.csv")
    mon.start()
    progresso = Progresso(pasta / "progresso.json", total, mon)
    acompanhar(progresso)

    def sair(codigo, mensagem):
        mon.fim.set()
        print(mensagem, flush=True)
        sys.exit(codigo)

    def gerar(g):
        """Roda o grafo e devolve (arquivo de saida do ComfyUI, resultado); sai do script se a geracao falhar."""
        r = rodar(g, 900)
        if mon.quente:
            sair(5, "PARADO por temperatura")
        if r["status"] == "servidor caiu":
            sair(3, f"SERVIDOR CAIU: {r['erro'][:300]}")
        if r["status"] != "success":
            sair(4, f"FALHA na geracao: {r['status']} {r['erro'][:700]}")
        saidas = (r["saidas"].get("9") or {}).get("images") or []
        if not saidas:
            sair(4, f"FALHA na geracao: o ComfyUI nao informou a imagem. Saidas: {list(r['saidas'])}")
        return config.SAIDA / saidas[0].get("subfolder", "") / saidas[0]["filename"], r

    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    base = random.randrange(2**48) if p["semente"] is None else p["semente"]
    troca = p.get("troca_foto")
    if troca:
        # Troca em foto: os recortes saem uma vez, antes das imagens (ver troca_foto)
        try:
            refs, avisos = troca_foto.preparar(troca, a.projeto)
        except Exception as e:
            sair(4, f"FALHA ao recortar as fotos: {e}")
        for aviso in avisos:
            print(f"aviso: {aviso}", flush=True)
        estado["avisos"] = avisos
        gravar_estado(arq_estado, estado)
        print(f"{total} {'imagem' if total == 1 else 'imagens'} | troca em foto: {' e '.join(troca_foto.passadas(troca))} | semente inicial {base}", flush=True)
    else:
        print(f"{total} {'imagem' if total == 1 else 'imagens'} | {largura}x{altura} | {p['passos']} passos | semente inicial {base}", flush=True)
    for n in range(len(feitas) + 1, total + 1):
        # Cada imagem usa a semente seguinte: a mesma semente repete o mesmo conjunto
        semente = (base + n - 1) % 2**48
        print(f"imagem {n} de {total} | semente {semente}", flush=True)
        if troca:
            # Uma passada por troca, na ordem rosto e roupa: a saida de uma vira a imagem de partida da seguinte
            partida, segundos, pico, temp = p["partida"], 0.0, 0, 0
            for chave in troca_foto.passadas(troca):
                g = grafo_troca_foto(p, chave, partida, refs[chave], semente, f"texto/{a.projeto}/imagem{n}_{chave}")
                progresso.imagem(n, g)
                saida, r = gerar(g)
                segundos, pico, temp = segundos + r["segundos"], max(pico, r["pico_vram"] or 0), max(temp, r["temp_max"] or 0)
                print(f"imagem {n}: {chave} trocado em {round(r['segundos'])} s", flush=True)
                partida = f"trocafoto_{a.projeto}_{n}_{chave}.png"
                shutil.copy2(saida, config.ENTRADA / partida)
            r = {"segundos": segundos, "pico_vram": pico, "temp_max": temp}
        else:
            g = grafo(p, semente, f"texto/{a.projeto}/imagem{n}")
            progresso.imagem(n, g)
            saida, r = gerar(g)
        destino = pasta / f"imagem_{n}.png"
        shutil.copy2(saida, destino)
        feitas.append({"n": n, "arquivo": destino.name, "semente": semente, "segundos": round(r["segundos"]), "pico_vram": r["pico_vram"], "temp_max": r["temp_max"]})
        gravar_estado(arq_estado, estado)
        print(f"imagem {n} pronta: {round(r['segundos'])} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)
    mon.fim.set()
    print(f"pronto: {total} {'imagem' if total == 1 else 'imagens'} em {pasta}", flush=True)


if __name__ == "__main__":
    main()
