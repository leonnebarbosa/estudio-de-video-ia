"""Texto para imagem: gera de 1 a 4 imagens com o Chroma1-HD-Flash a partir de um prompt.

Uso: python -I texto_para_imagem.py --projeto NOME
Le projetos/NOME/interface.json (prompt, negativo, proporcao, megapixels, quantidade, passos, semente) e grava
imagem_N.png na pasta do projeto, mais estado.json, progresso.json e gpu.csv. Se parar no meio, rodar de novo
segue da proxima imagem.
Configuracao do WEB_chroma_personagem_ficticia.json: 12 passos, CFG 1, euler com agendador beta.
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da geracao, 5 temperatura.
"""
import argparse, json, os, random, re, shutil, struct, sys, time
from pathlib import Path

# Com python -I a pasta do script nao entra no caminho de importacao
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, entrada_temp, estilos, extras, loras, troca_foto
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
                   "latente": None, "negativo": "zero", "shift": None, "megapixels_edicao": 2.0,
                   # A LoRA de troca de cabeca e da Troca em foto (troca_foto), nao aparece na lista do Editar
                   "lora_fixa": "bfs_head_v1_flux-klein_4b.safetensors"},
    # O mesmo FLUX.2 Klein 4B do Editar, gerando do zero (aba Gerar, 24/11/2026): grafo do fluxo oficial de texto para imagem do Klein
    # destilado (latente vazio do Flux2, CFG 1 com o negativo zerado, 4 passos, euler com o Flux2Scheduler). Usa os arquivos do klein_edit.
    "klein_t2i": {"nome": "FLUX.2 Klein 4B", "familia": "flux2_klein", "grafo_texto": "klein",
                  "ajuda": "O mesmo modelo do Editar, gerando do zero: rápido (uns 20 s) e com pele natural. Entende melhor em inglês.",
                  "carregador": "UNETLoader", "unet": "flux-2-klein-4b-fp8.safetensors", "encoder": "qwen_3_4b_fp8_mixed.safetensors",
                  "tipo_encoder": "flux2", "vae": "flux2-vae.safetensors", "passos": 4, "amostrador": "euler", "agendador": None,
                  "latente": None, "negativo": "zero", "shift": None},
    # Varias referencias numa imagem so (pessoa + fundo + roupa). Grafo do fluxo oficial image_qwen_image_2_1_turbo_image_edit:
    # 8 passos com a programacao fixa (ManualSigmas), CFG 1, euler, referencias a 1024. Teste de 21/11/2026 (projetos/teste_multi_ref):
    # ~55 s por imagem, pico de 9,5 GB, com o codificador w4a8; rosto, roupa e fundo mais fieis que o Klein 4B e o Qwen 2511.
    # modo: a aba da area Imagem (validacao.modo_texto); sem a chave, edicao vai para Editar e o resto para Gerar
    "qwen21_edit": {"nome": "Várias referências (Qwen Image 2.1)", "familia": "qwen21", "edicao": True, "grafo_edicao": "qwen21", "modo": "referencias",
                    "ajuda": "Junta até 4 imagens numa só: a pessoa, o fundo, a roupa, um objeto. Cite cada uma pelo número (image 1, image 2...). "
                             "Uns 55 s, em 1 MP, no formato da imagem de partida. Testado em 21/11 com pessoa, café e vestido.",
                    "carregador": "UNETLoader", "unet": "qwen_image_2.1_turbo_int8_convrot.safetensors", "encoder": "qwen3vl_8b_w4a8.safetensors",
                    "tipo_encoder": "qwen_image", "vae": "qwen_image_2.1_vae_bf16.safetensors", "passos": 8, "passos_fixos": True,
                    "amostrador": "euler", "agendador": None, "latente": None, "negativo": "zero", "shift": None, "max_imagens": 4,
                    "sigmas": "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0", "resolucao_refs": 1024,
                    # Estilo realista sem o 9B: uma passada leve num modelo de foto depois do Qwen (estilos.py). None: so o Qwen.
                    # O arquivo local pode por {"modelo": id em MODELOS_TEXTO, "lora": nome, "forca_lora": 1.0, "forca": 0.3}
                    "refino_realista": None},
    # FLUX.2 Klein 9B destilado (BFL, licenca nao comercial, repositorio restrito): o motor da chave Qualidade alta do estilo (estilos.py).
    # Fora do seletor (oculto). Teste de 23/11/2026 (projetos/teste_estilo_foto): a 1,5 MP, ~47 s por imagem em INT8 e ~60 s em FP8,
    # pico de 9,3 GB na 3080 com --lowvram; estilos iguais ou mais fieis ao rosto que o 4B e o melhor realista. O arquivo local pode
    # trocar o unet e por a LoRA e o prefixo do realista (lora_realista [nome, forca], prefixo_realista).
    "klein9b_edit": {"nome": "Editar imagem (FLUX.2 Klein 9B)", "familia": "flux2_klein9b", "edicao": True, "grafo_edicao": "klein", "oculto": True,
                     "ajuda": "Qualidade alta do estilo: mais fiel ao rosto e às cores, uns 50 s por imagem.",
                     "carregador": "UNETLoader", "unet": "flux-2-klein-9b-fp8.safetensors", "encoder": "qwen_3_8b_fp8mixed.safetensors",
                     "tipo_encoder": "flux2", "vae": "flux2-vae.safetensors", "passos": 4, "amostrador": "euler", "agendador": None,
                     "latente": None, "negativo": "zero", "shift": None, "megapixels_edicao": 1.5, "max_imagens": 1,
                     "lora_realista": None, "prefixo_realista": ""},
}
# Imagens por edicao quando o modelo nao diz (o Klein encadeia referencias; 4 e o limite da interface)
MAX_IMAGENS_EDICAO = 4
# Modelos que sairam do seletor e o que entra no lugar deles nos projetos antigos (pedido, geracao que faltava, Usar de novo).
# qwen_edit (Qwen Image Edit 2511 + Lightning) saiu em 22/11/2026: no teste projetos/teste_qwen_edit o Qwen 2.1 e o Klein fizeram
# as tarefas dele (cores, letreiro, roupa e fundo) tao bem e em um terco do tempo; os ~31 GB dele foram apagados
MODELOS_SUBSTITUIDOS = {"qwen_edit": "klein_edit"}
# Modelos da comunidade testados so nesta maquina entram pelo arquivo local, fora do git (ver extras.py). Uma entrada com o id de um
# modelo oficial so troca os campos que trouxer (ex.: o unet do klein9b_edit ou o refino_realista do qwen21_edit)
for _id, _m in extras.secao("texto").items():
    if isinstance(_m, dict):
        MODELOS_TEXTO[_id] = {**MODELOS_TEXTO.get(_id, {}), **_m}
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
             ("chroma", ("chroma",), ("double_blocks", "single_transformer_blocks", "single_blocks")))
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
        familia = familia_klein(arq, meta, cab)
        for nome, marcas_meta, marcas_peso in ([] if familia else _FAMILIAS):
            if any(x in meta for x in marcas_meta) or any(x in nomes for x in marcas_peso):
                familia = nome
                break
    except (OSError, ValueError, struct.error):
        # Arquivo quebrado ou que nao e safetensors: nao aparece em nenhum modelo
        familia = None
    _cache_familia[chave] = familia
    return familia


def familia_klein(arq, meta, cab):
    """FLUX.2 Klein 4B ou 9B (24/11/2026). Os nomes dos pesos parecem os do Chroma (double_blocks...), entao o Klein vem antes:
    pelo metadado de treino (flux2_klein_4b, flux2_klein_9b, FLUX_KLEIN_9B), pela pasta (loras/klein e loras/klein9b) ou pela
    largura das camadas no formato do Flux2 (to_qkv_mlp_proj): 3072 no 4B, 4096 no 9B. None: nao e do Klein."""
    if "klein" in meta:
        return "flux2_klein9b" if "9b" in meta else "flux2_klein"
    pasta = arq.parent.name.lower()
    if pasta in ("klein9b", "flux2_klein9b"):
        return "flux2_klein9b"
    if pasta in ("klein", "flux2_klein"):
        return "flux2_klein"
    larguras = {v["shape"][-1] for k, v in cab.items() if k != "__metadata__" and isinstance(v, dict) and "to_qkv_mlp_proj" in k
                and k.endswith(("lora_A.weight", "lora_down.weight"))}
    if larguras:
        return "flux2_klein9b" if 4096 in larguras else "flux2_klein" if 3072 in larguras else None
    return None


def loras_compativeis(modelo):
    """As LoRAs da pasta loras (e subpastas) que servem para o modelo, pelo nome do arquivo (o caminho entra no envio, ver loras.py)."""
    pasta, familia = config.MODELOS / "loras", MODELOS_TEXTO[modelo]["familia"]
    if not pasta.is_dir():
        return []
    fixa = MODELOS_TEXTO[modelo].get("lora_fixa")
    return sorted({p.name for p in pasta.rglob("*.safetensors") if familia_lora(p) == familia and p.name != fixa}, key=str.lower)


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
    # Imagens seguintes: 1 MP basta para servir de referencia (a saida segue a primeira). `referencia` (uma) ou `referencias`
    # (lista, na ordem: a 2a, a 3a...), cada uma em cadeia no positivo e no negativo zerado
    pos, neg = ["24", 0], ["25", 0]
    for i, nome in enumerate(imagens_extras(p)):
        carga, escala, cod, rp, rn = (str(int(n) + 100 * i) for n in ("32", "35", "36", "26", "27"))
        g[carga] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g[escala] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [carga, 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 16}}
        g[cod] = {"class_type": "VAEEncode", "inputs": {"pixels": [escala, 0], "vae": ["3", 0]}}
        g[rp] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [cod, 0]}}
        g[rn] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [cod, 0]}}
        pos, neg = [rp, 0], [rn, 0]
    g["40"]["inputs"]["positive"], g["40"]["inputs"]["negative"] = pos, neg
    # LoRAs escolhidas (Editar com o Klein, 24/11/2026), em cadeia so no modelo, como no grafo de texto
    modelo = ["1", 0]
    for i, (nome, forca) in enumerate(p.get("loras") or []):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"20{i}", 0]
    g["40"]["inputs"]["model"] = modelo
    return g


def imagens_extras(p):
    """As imagens depois da de partida, na ordem do pedido (image 2, image 3...): `referencia` e a lista `referencias`."""
    return ([p["referencia"]] if p.get("referencia") else []) + [r for r in p.get("referencias") or [] if r]


def pedido_qwen21(texto):
    """O Qwen Image 2.1 cita as imagens como <image1>, <image2>...: "image 2", "Image 2", "imagem 2" e "picture 2" viram <image2>."""
    return re.sub(r"(?<![<\w])(?:image|imagem|picture)\s*(\d{1,2})\b(?!>)", r"<image\1>", texto, flags=re.IGNORECASE)


def grafo_edicao_qwen21(p, m, semente, prefixo):
    """Qwen Image 2.1 Turbo: todas as imagens entram no mesmo codificador, que devolve o positivo, o negativo e o latente vazio
    no tamanho da primeira (a saida segue a imagem de partida)."""
    imagens = [p["partida"], *imagens_extras(p)]
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        # Cache das referencias entre os passos (o fluxo oficial usa auto: sobra da placa, depois a RAM)
        "20": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["encoder"], "type": m["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": pedido_qwen21(p["prompt"]), "negative_prompt": "",
                                                                 "resolution": m["resolucao_refs"]}},
        "40": {"class_type": "CFGGuider", "inputs": {"model": ["20", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1}},
        "41": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m["amostrador"]}},
        "42": {"class_type": "ManualSigmas", "inputs": {"sigmas": m["sigmas"]}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        AMOSTRADOR: {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["41", 0], "sigmas": ["42", 0],
                                                                       "latent_image": ["4", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    for i, nome in enumerate(imagens, 1):
        g[str(29 + i)] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g["4"]["inputs"][f"images.image_{i}"] = [str(29 + i), 0]
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


def cores_da_foto(arquivo, tempo=300):
    """As cores da foto numa linha em ingles (cabelo, pele, olhos, roupa, fundo), pela LLM de visao, para travar no pedido do estilo."""
    from trocar_personagem import texto_de_saida
    g = grafo_descrever(arquivo)
    g["4"]["inputs"].update(prompt=estilos.INSTRUCAO_CORES, max_length=120)
    r = rodar(g, tempo)
    if r["status"] != "success":
        raise RuntimeError(f"{r['status']} {r.get('erro', '')[:300]}")
    return texto_de_saida(r["saidas"].get("5") or {}).strip().strip('"').strip()


def modelo_do_estilo(p):
    return estilos.motor(p["estilo"], bool(p.get("qualidade_alta")))


def grafo_estilo(p, semente, prefixo):
    """Estilo pronto (estilos.py) na imagem de partida: o pedido validado com as cores travadas, no motor da chave Qualidade alta.
    No realista com o 9B entram a LoRA e o prefixo de realismo, se o arquivo local os puser."""
    modelo = modelo_do_estilo(p)
    m = MODELOS_TEXTO[modelo]
    pedido = estilos.pedido(p["estilo"], p.get("cores"), p.get("prompt"))
    lora = m.get("lora_realista") if p["estilo"] == "realista" else None
    if lora:
        pedido = (m.get("prefixo_realista") or "") + pedido
    q = {"partida": p["partida"], "passos": m["passos"], "prompt": pedido, "loras": p.get("loras") or []}
    if m.get("grafo_edicao") == "qwen21":
        return grafo_edicao_qwen21(q, m, semente, prefixo)
    g = grafo_edicao_klein(q, m, semente, prefixo)
    if lora:
        g["60"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": g["40"]["inputs"]["model"], "lora_name": lora[0], "strength_model": lora[1]}}
        g["40"]["inputs"]["model"] = ["60", 0]
    return g


def refino_do_estilo(p):
    """A passada de realismo depois do Qwen (realista sem o 9B), se o arquivo local a configurou; senao None."""
    if p.get("estilo") != "realista" or modelo_do_estilo(p) != estilos.MOTOR_REALISTA_SEM_9B:
        return None
    cfg = MODELOS_TEXTO[estilos.MOTOR_REALISTA_SEM_9B].get("refino_realista")
    return cfg if isinstance(cfg, dict) and cfg.get("modelo") in MODELOS_TEXTO else None


REFINO_PEDIDO = ("A real candid smartphone photograph of a person, natural skin texture with pores and fine peach fuzz, real hair strands, "
                 "real fabric, soft natural light, subtle sensor noise, photorealistic.")


def grafo_refino(foto, cfg, semente, prefixo):
    """Img2img leve (forca ~0,3) no modelo de foto do refino, na imagem que o Qwen fez, a 1,5 MP no formato dela."""
    k = MODELOS_TEXTO[cfg["modelo"]]
    modelo = ["1", 0]
    g = {
        "1": {"class_type": k["carregador"], "inputs": {"unet_name": k["unet"]} | ({"weight_dtype": "default"} if k["carregador"] == "UNETLoader" else {})},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": k["encoder"], "type": k["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": k["vae"]}},
        "30": {"class_type": "LoadImage", "inputs": {"image": foto}},
        "31": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["30", 0], "upscale_method": "lanczos", "megapixels": 1.5, "resolution_steps": 16}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["31", 0], "vae": ["3", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": REFINO_PEDIDO, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    if cfg.get("lora"):
        g["10"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": cfg["lora"], "strength_model": float(cfg.get("forca_lora", 1.0))}}
        modelo = ["10", 0]
    if k.get("shift"):
        g["21"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": modelo, "shift": k["shift"]}}
        modelo = ["21", 0]
    g[AMOSTRADOR] = {"class_type": "KSampler", "inputs": {"seed": semente, "steps": k["passos"], "cfg": 1, "sampler_name": k["amostrador"],
                                                         "scheduler": k["agendador"], "denoise": float(cfg.get("forca", 0.3)), "model": modelo,
                                                         "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]}}
    return g


def grafo_texto_klein(p, m, semente, prefixo, largura, altura):
    """FLUX.2 Klein gerando do zero (fluxo oficial do Klein destilado): o mesmo amostrador do Editar, sem a imagem de referencia."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["encoder"], "type": m["tipo_encoder"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": p["prompt"], "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": largura, "height": altura, "batch_size": 1}},
        "40": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": 1}},
        "41": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m["amostrador"]}},
        "42": {"class_type": "Flux2Scheduler", "inputs": {"steps": p["passos"], "width": largura, "height": altura}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        AMOSTRADOR: {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["41", 0], "sigmas": ["42", 0],
                                                                       "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": [AMOSTRADOR, 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }
    modelo = ["1", 0]
    for i, (nome, forca) in enumerate(p.get("loras") or []):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"20{i}", 0]
    g["40"]["inputs"]["model"] = modelo
    return g


def grafo(p, semente, prefixo):
    if p.get("estilo"):
        return grafo_estilo(p, semente, prefixo)
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    # Projeto de antes do seletor, sem a chave: o Chroma Flash
    modelo = p.get("modelo") or "chroma_flash"
    m = MODELOS_TEXTO[MODELOS_SUBSTITUIDOS.get(modelo, modelo)]
    if p.get("qualidade_alta") and modelo in estilos.COM_9B:
        # Chave Qualidade alta, mesmo sem estilo: o Klein 9B. No Editar, a entrada inteira do 9B; no Gerar, o mesmo grafo de texto
        # com o modelo e o codificador do 9B (o arquivo local pode ter trocado o unet do klein9b_edit)
        alto = MODELOS_TEXTO[estilos.MOTOR_ALTO]
        m = alto if m.get("edicao") else {**m, "familia": alto["familia"], "unet": alto["unet"], "encoder": alto["encoder"]}
    # LoRA com palavra-chave fixa (loras.GATILHOS e o arquivo local): entra no começo do prompt, se ainda não estiver nele
    p = {**p, "prompt": loras.com_gatilho(p.get("loras"), p["prompt"], ", ")}
    if m.get("grafo_edicao") == "klein":
        return grafo_edicao_klein(p, m, semente, prefixo)
    if m.get("grafo_edicao") == "qwen21":
        return grafo_edicao_qwen21(p, m, semente, prefixo)
    if m.get("grafo_texto") == "klein":
        return grafo_texto_klein(p, m, semente, prefixo, largura, altura)
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
    elif p.get("estilo"):
        # Estilo pronto: as cores da foto saem uma vez, antes das imagens, e ficam no estado para a retomada (ver estilos.py)
        if estilos.usa_cores(p["estilo"]) and not estado.get("cores"):
            print("descrevendo as cores da foto", flush=True)
            try:
                estado["cores"] = cores_da_foto(p["partida"])
            except Exception as e:
                sair(4, f"FALHA ao descrever as cores da foto: {e}")
            gravar_estado(arq_estado, estado)
            print(f"cores: {estado['cores']}", flush=True)
        p = {**p, "cores": estado.get("cores")}
        print(f"{total} {'imagem' if total == 1 else 'imagens'} | estilo {p['estilo']} | {modelo_do_estilo(p)} | semente inicial {base}", flush=True)
    else:
        print(f"{total} {'imagem' if total == 1 else 'imagens'} | {largura}x{altura} | {p['passos']} passos | semente inicial {base}", flush=True)
    refino = refino_do_estilo(p) if p.get("estilo") else None
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
                arq_partida, partida = entrada_temp.arquivo(a.projeto, f"trocafoto_{a.projeto}_{n}_{chave}.png")
                shutil.copy2(saida, arq_partida)
            r = {"segundos": segundos, "pico_vram": pico, "temp_max": temp}
        else:
            g = grafo(p, semente, f"texto/{a.projeto}/imagem{n}")
            progresso.imagem(n, g)
            saida, r = gerar(g)
            if refino:
                # Realista sem o 9B: a passada de realismo por cima do que o Qwen fez
                arq_refino, base_refino = entrada_temp.arquivo(a.projeto, f"estilo_{a.projeto}_{n}.png")
                shutil.copy2(saida, arq_refino)
                g = grafo_refino(base_refino, refino, semente, f"texto/{a.projeto}/imagem{n}_refino")
                progresso.imagem(n, g)
                saida, r2 = gerar(g)
                print(f"imagem {n}: refino em {round(r2['segundos'])} s", flush=True)
                r = {"segundos": r["segundos"] + r2["segundos"], "pico_vram": max(r["pico_vram"] or 0, r2["pico_vram"] or 0),
                     "temp_max": max(r["temp_max"] or 0, r2["temp_max"] or 0)}
        destino = pasta / f"imagem_{n}.png"
        shutil.copy2(saida, destino)
        feitas.append({"n": n, "arquivo": destino.name, "semente": semente, "segundos": round(r["segundos"]), "pico_vram": r["pico_vram"], "temp_max": r["temp_max"]})
        gravar_estado(arq_estado, estado)
        print(f"imagem {n} pronta: {round(r['segundos'])} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)
    mon.fim.set()
    print(f"pronto: {total} {'imagem' if total == 1 else 'imagens'} em {pasta}", flush=True)


if __name__ == "__main__":
    main()
