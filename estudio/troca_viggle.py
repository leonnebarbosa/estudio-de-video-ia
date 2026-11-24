"""A troca pelo Viggle toda dentro do ComfyUI do estudio (motor "viggle" da aba Trocar), chamada pelo troca_wangp.trocar:
pinta alguns quadros com a pessoa da foto (Qwen Image 2.1 + LoRA Viggle Image Swap) e espalha a troca pelo video (Viggle
Remake). E a mesma receita que o WanGP roda (models/qwen21/pipeline.py, models/minimax_h3/viggle.py e pipeline.py),
refeita com nos; o WanGP nao e chamado. O Viggle Remake:

- H3 FL2VA Pruned + a LoRA viggle_remake_swap convertida para os nomes do ComfyUI (converter_lora_viggle.py);
- o no EstudioViggleRemake (nos_comfy/estudio_viggle): o video original como primeira referencia, os quadros pintados
  depois e so os rotulos para o codificador de texto;
- cada quadro pintado tambem preso no seu instante (MiniMaxH3AddGuide), mas so nos 4 primeiros passos (sigma >= 0,9):
  por isso a amostragem vai em duas passagens, a segunda sem os quadros presos e sem ruido novo;
- o som original preso no latente (PixaromaH3AudioSync) e posto de volta no video;
- 6 passos Euler, cfg 1, sigmas fixos, desvio 12/3.

Testado em 21/11/2026 com 124 quadros a 544x960 (projetos/troca_REELS, mesmos quadros pintados, semente e pedido do
WanGP): 392 s, pico de 9,6 GB, 257 W, 72 graus. Rosto e roupa como os do WanGP; a boca acompanhou a fala do original.
"""
import shutil
import time

import config, entrada_temp, loras
from comfy_api import pega

LORA = "viggle_remake_swap_comfyui_bf16.safetensors"
MODELO = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
NO = "EstudioViggleRemake"
PASTA_NO = "estudio_viggle"
SIGMAS = (1.0, 0.990476, 0.965243, 0.923077, 0.8, 0.631579, 0.0)  # WanGP viggle.py, modo swap
PASSOS = len(SIGMAS) - 1
PASSOS_PRESOS = 4          # os de sigma >= 0,9
NO_PRESOS, NO_SOLTOS, NO_VIDEO = "57", "58", "26"
# O Viggle Remake tem duas LoRAs com a mesma receita e sigmas proprios (WanGP viggle.py): "swap" troca a pessoa (aba
# Trocar) e "edit" muda cenario, objetos, clima ou luz (aba Editar video). Em cada uma: a LoRA no ComfyUI, o arquivo de
# origem (como veio no WanGP, para converter) e os sigmas. Nas duas, os 4 primeiros passos tem sigma >= 0,9.
MODOS = {"swap": {"lora": LORA, "origem": "viggle_remake_swap_bf16.safetensors", "sigmas": SIGMAS},
         "edit": {"lora": "viggle_remake_edit_comfyui_bf16.safetensors", "origem": "viggle_remake_edit_bf16.safetensors",
                  "sigmas": (1.0, 0.983607, 0.96, 0.923077, 0.857143, 0.705882, 0.0)}}
ESPERA_COMFY = 300

# O pintor dos quadros: Qwen Image 2.1 (7B) + LoRA Viggle Image Swap, a mesma receita do WanGP (models/qwen21/pipeline.py).
# Testado em 22/11/2026 no quadro 0 do troca_REELS: 55 s, pico de 9,4 GB, mesma personagem, pose e roupa do video. Com o
# modelo Turbo (o do pacote "Varias referencias") a LoRA saiu pior: manteve o cabelo do video e o rosto ficou menos fiel.
PINTOR_MODELO = "qwen_image_21_7B_int8_convrot.safetensors"
PINTOR_LORA = "Qwen-Image-2.1-viggle-image-swap-v0.1-lora-r256.safetensors"
PINTOR_CODIFICADOR = "qwen3vl_8b_w4a8.safetensors"
PINTOR_VAE = "qwen_image_2.1_vae_bf16.safetensors"
# 6 passos Euler, cfg 1: os sigmas do WanGP ja com o deslocamento que ele aplica a ~1 MP (registro de 21/11/2026)
PINTOR_SIGMAS = "1.0, 0.967805, 0.933458, 0.857389, 0.667114, 0.400484, 0.0"
NO_PINTADO = "9"


def lora_de_origem(modo="swap"):
    """A LoRA ainda com os nomes do diffusers (como o autor a publica), para converter: em models/loras/h3 do ComfyUI."""
    return loras.pasta() / "h3" / MODOS[modo]["origem"]


def no_carregado():
    try:
        return NO in pega(f"/object_info/{NO}")
    except Exception:
        return False


def instalar_no():
    """Poe (ou atualiza) o no em custom_nodes. Devolve True se mexeu no arquivo: o ComfyUI precisa reiniciar para ler."""
    origem = config.ESTUDIO / "nos_comfy" / PASTA_NO / "__init__.py"
    destino = config.RAIZ_COMFY / "ComfyUI" / "custom_nodes" / PASTA_NO / "__init__.py"
    if destino.is_file() and destino.read_bytes() == origem.read_bytes():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, destino)
    return True


def reiniciar_comfy():
    """Encerra o ComfyUI que escuta na porta do estudio; o vigia do servidor o religa. Espera o no aparecer.
    So e chamado no comeco da troca, com a fila vazia (a tarefa e a unica geracao em curso)."""
    import psutil
    for c in psutil.net_connections(kind="inet"):
        if c.laddr and c.laddr.port == config.PORTA_COMFY and c.status == psutil.CONN_LISTEN and c.pid:
            try:
                psutil.Process(c.pid).kill()
            except psutil.Error:
                pass
    fim = time.time() + ESPERA_COMFY
    while time.time() < fim:
        time.sleep(5)
        if no_carregado():
            return True
    return False


def falta_do_pintor():
    """Os arquivos do pintor que nao estao na pasta de modelos do ComfyUI, como "pasta/arquivo"."""
    faltam = [f"{pasta}/{nome}" for pasta, nome in (("diffusion_models", PINTOR_MODELO), ("text_encoders", PINTOR_CODIFICADOR), ("vae", PINTOR_VAE))
              if not (config.MODELOS / pasta / nome).is_file()]
    if PINTOR_LORA.lower() not in loras.mapa():
        faltam.append(f"loras/qwen/{PINTOR_LORA}")
    return faltam


def pedido_do_pintor(pedido):
    """O pedido escrito para o WanGP ("image 1" e o quadro, "image 2" a pessoa) no formato do ComfyUI: a pessoa entra
    primeiro e o quadro a editar por ultimo (a ordem em que a LoRA foi treinada; o WanGP reordena por dentro), e o
    Qwen Image 2.1 cita as imagens como <image1>, <image2>."""
    return pedido.replace("image 1", "<quadro>").replace("image 2", "<image1>").replace("<quadro>", "<image2>")


def grafo_pintor(quadro, pessoa, pedido, semente, prefixo):
    """Pinta `quadro` (PNG na entrada do ComfyUI) com a pessoa de `pessoa`. A saida tem o tamanho do quadro, a ~1 MP."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": PINTOR_MODELO, "weight_dtype": "default"}},
        "11": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": PINTOR_LORA, "strength_model": 1.0}},
        "20": {"class_type": "QwenImage21Cache", "inputs": {"model": ["11", 0], "device": "auto", "dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": PINTOR_CODIFICADOR, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": PINTOR_VAE}},
        "30": {"class_type": "LoadImage", "inputs": {"image": pessoa}},
        "31": {"class_type": "LoadImage", "inputs": {"image": quadro}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": pedido_do_pintor(pedido), "negative_prompt": "",
                                                                 "resolution": 1024, "images.image_1": ["30", 0], "images.image_2": ["31", 0]}},
        # So para o latente vazio no tamanho do quadro: o no 4 devolve o da primeira imagem, que aqui e a pessoa
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": "", "negative_prompt": "", "resolution": 1024, "images.image_1": ["31", 0]}},
        "40": {"class_type": "CFGGuider", "inputs": {"model": ["20", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1}},
        "41": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "42": {"class_type": "ManualSigmas", "inputs": {"sigmas": PINTOR_SIGMAS}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        "6": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["41", 0], "sigmas": ["42", 0], "latent_image": ["5", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        NO_PINTADO: {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefixo}},
    }


def pintar(projeto, quadros, pessoa, pedido, semente, rodar, ao_pintar=lambda feitos: None):
    """Pinta cada quadro no ComfyUI. `quadros`: [(numero, PNG original, PNG de destino)]; `pessoa`: a foto (ou a cabeca
    recortada) na entrada do ComfyUI. Devolve o resultado do ultimo `rodar`; se um quadro falhar, para ali e o status
    desse resultado nao e "success". Um destino que ja existe e pulado (retomada)."""
    r = {"status": "success", "erro": "", "pico_vram": 0, "temp_max": 0, "saidas": {}}
    pico = temp = 0
    for feitos, (numero, original, destino) in enumerate(quadros, 1):
        if not destino.is_file():
            arq, nome = entrada_temp.arquivo(projeto, f"viggle_{projeto}_quadro_{numero:03d}.png")
            shutil.copyfile(original, arq)
            try:
                r = rodar(grafo_pintor(nome, pessoa, pedido, semente, f"troca/{projeto}_pintado_{numero:03d}"), 900)
            finally:
                arq.unlink(missing_ok=True)
            pico, temp = max(pico, r["pico_vram"]), max(temp, r["temp_max"])
            imagens = (r["saidas"].get(NO_PINTADO) or {}).get("images") or []
            if r["status"] != "success" or not imagens:
                if r["status"] == "success":
                    r = {**r, "status": "sem imagem", "erro": "o ComfyUI não devolveu o quadro pintado"}
                break
            gerado = config.SAIDA / imagens[0].get("subfolder", "") / imagens[0]["filename"]
            shutil.copyfile(gerado, destino)
            gerado.unlink(missing_ok=True)
        ao_pintar(feitos)
    return {**r, "pico_vram": pico, "temp_max": temp}


# A pele (22/11/2026, testes_troca/reel_identico_2026-11-22): com a LoRA Realism People (a da receita "Pele natural" do Imagem
# para video) por cima da do Viggle e a pele descrita no pedido, o rosto saiu menos oleoso, com a expressao igual.
PELE_LORA = ("h3-realism-people-t2v-i2v-r2v.safetensors", 0.8)


def loras_de_pele():
    """[(nome, forca)] da LoRA de pele, se ela esta instalada; senao, nada (a troca sai sem ela)."""
    return [PELE_LORA] if PELE_LORA[0].lower() in loras.mapa() else []


def falta_do_klein():
    """O que falta para pintar com o Klein + BFS (a troca em foto do estudio), como "pasta/arquivo"."""
    import texto_para_imagem as t2i
    import troca_foto
    m = t2i.MODELOS_TEXTO["klein_edit"]
    faltam = [f"{pasta}/{m[chave]}" for pasta, chave in (("diffusion_models", "unet"), ("text_encoders", "encoder"), ("vae", "vae"))
              if not (config.MODELOS / pasta / m[chave]).is_file()]
    if troca_foto.LORA_ROSTO.lower() not in loras.mapa():
        faltam.append(f"loras/klein/{troca_foto.LORA_ROSTO}")
    return faltam


def pintar_klein(projeto, quadros, semente, rodar, ao_pintar=lambda feitos: None):
    """Pinta cada quadro com a cabeca da personagem pela troca em foto do estudio (FLUX.2 Klein + LoRA BFS head swap), que
    mantem a pose, as maos, a roupa e o fundo do quadro. Em 22/11/2026 o pintor do Viggle (Qwen 2.1 + Image Swap) devolveu o
    rosto do video sem trocar, com a foto de busto e com a cabeca recortada; o Klein + BFS trocou em todos os quadros.
    `quadros`: [(numero, PNG original, PNG de destino, cabeca)], `cabeca` na entrada do ComfyUI (cada quadro pode levar uma
    foto de expressao diferente). Devolve o resultado do ultimo `rodar`, como `pintar`. Um destino que ja existe e pulado."""
    import texto_para_imagem as t2i
    passos = t2i.MODELOS_TEXTO["klein_edit"]["passos"]
    r = {"status": "success", "erro": "", "pico_vram": 0, "temp_max": 0, "saidas": {}}
    pico = temp = 0
    for feitos, (numero, original, destino, cabeca) in enumerate(quadros, 1):
        if not destino.is_file():
            arq, nome = entrada_temp.arquivo(projeto, f"viggle_{projeto}_quadro_{numero:03d}.png")
            shutil.copyfile(original, arq)
            try:
                r = rodar(t2i.grafo_troca_foto({"passos": passos}, "rosto", nome, cabeca, semente, f"troca/{projeto}_pintado_{numero:03d}"), 900)
            finally:
                arq.unlink(missing_ok=True)
            pico, temp = max(pico, r["pico_vram"]), max(temp, r["temp_max"])
            imagens = [im for s in r["saidas"].values() for im in s.get("images", [])]
            if r["status"] != "success" or not imagens:
                if r["status"] == "success":
                    r = {**r, "status": "sem imagem", "erro": "o ComfyUI não devolveu o quadro pintado"}
                break
            gerado = config.SAIDA / imagens[0].get("subfolder", "") / imagens[0]["filename"]
            shutil.copyfile(gerado, destino)
            gerado.unlink(missing_ok=True)
        ao_pintar(feitos)
    return {**r, "pico_vram": pico, "temp_max": temp}


def preparar(modo="swap"):
    """Deixa a LoRA convertida e o no no lugar. Devolve None se esta pronto, ou a frase do que falta. `modo`: "swap" (a
    troca com a roupa da foto, que tambem precisa do pintor Qwen), "swap_klein" (a troca com a roupa do video, pintada pelo
    Klein + BFS) ou "edit" (a edicao de video, pintada pelo Klein)."""
    faltam = falta_do_pintor() if modo == "swap" else falta_do_klein() if modo == "swap_klein" else []
    if faltam:
        return f"faltam os arquivos do pintor ({'Qwen Image 2.1' if modo == 'swap' else 'FLUX.2 Klein e LoRA BFS'}) na pasta de modelos do ComfyUI: " + ", ".join(faltam) + "."
    if modo == "swap_klein":
        modo = "swap"
    LORA = MODOS[modo]["lora"]
    if LORA.lower() not in loras.mapa():
        origem, base = lora_de_origem(modo), config.MODELOS / "diffusion_models" / MODELO
        if not origem.is_file():
            return f"falta a LoRA do Viggle Remake ({origem.name}) em models/loras/h3, para converter para o ComfyUI."
        if not base.is_file():
            return f"falta o modelo {MODELO} em models/diffusion_models."
        import converter_lora_viggle
        print("convertendo a LoRA do Viggle Remake para o ComfyUI (uma vez só, cerca de 1 minuto, sem usar a placa)", flush=True)
        destino = loras.pasta() / "h3" / LORA
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            n = converter_lora_viggle.converter(origem, base, destino)
        except converter_lora_viggle.NaoConverte as e:
            return f"não consegui converter a LoRA do Viggle Remake: {e}"
        print(f"LoRA convertida: {n} módulos conferidos com o modelo base", flush=True)
    if instalar_no() or not no_carregado():
        print("o nó do Viggle é novo para o ComfyUI: reiniciando o motor de geração para ele carregar", flush=True)
        if not reiniciar_comfy():
            return "o ComfyUI não voltou com o nó do Viggle carregado. Reinicie o estúdio e tente de novo."
    return None


def grafo(video, pintados, prompt, largura, altura, quadros, semente, prefixo, modo="swap", loras_extra=()):
    """`pintados`: [(quadro, nome do PNG na entrada do ComfyUI)], em ordem. O video ja esta a 24 fps na entrada.
    `loras_extra`: [(nome, forca)] a mais, entre a LoRA do Viggle e o desvio de sigma (a de pele, ver PELE_LORA)."""
    LORA, SIGMAS = MODOS[modo]["lora"], MODOS[modo]["sigmas"]
    g = {
        "1": {"class_type": "LoadVideo", "inputs": {"file": video}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": MODELO, "weight_dtype": "default"}},
        "11": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["10", 0], "lora_name": LORA, "strength_model": 1.0}},
        "13": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["11", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "12": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["13", 0], "attention": "comfy kitchen attention"}},
        "14": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "20": {"class_type": NO, "inputs": {"clip": ["14", 0], "vae": ["15", 0], "prompt": prompt, "width": largura, "height": altura,
                                           "length": quadros, "video": ["2", 0]}},
        "28": {"class_type": "PixaromaH3AudioSync", "inputs": {"model": ["12", 0], "latent": ["20", 1], "audio_vae": ["16", 0], "track": ["2", 1], "H3SyncState": "{}"}},
        "50": {"class_type": "ManualSigmas", "inputs": {"sigmas": ", ".join(str(s) for s in SIGMAS)}},
        "51": {"class_type": "SplitSigmas", "inputs": {"sigmas": ["50", 0], "step": PASSOS_PRESOS}},
        "52": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "53": {"class_type": "RandomNoise", "inputs": {"noise_seed": semente}},
        "54": {"class_type": "DisableNoise", "inputs": {}},
        "56": {"class_type": "BasicGuider", "inputs": {"model": ["28", 0], "conditioning": ["20", 0]}},
        "22": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": [NO_SOLTOS, 0]}},
        "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["15", 0]}},
        "25": {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "audio": ["28", 2], "fps": 24}},
        NO_VIDEO: {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }
    presos = ["20", 0]
    for i, (quadro, nome) in enumerate(pintados):
        g[f"4{i}"] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g["20"]["inputs"][f"foto_{i + 1}"] = [f"4{i}", 0]
        g[f"6{i}"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": presos, "vae": ["15", 0], "latent": ["20", 1], "image": [f"4{i}", 0], "frame_idx": quadro}}
        presos = [f"6{i}", 0]
    g["55"] = {"class_type": "BasicGuider", "inputs": {"model": ["28", 0], "conditioning": presos}}
    g[NO_PRESOS] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["53", 0], "guider": ["55", 0], "sampler": ["52", 0], "sigmas": ["51", 0], "latent_image": ["28", 1]}}
    g[NO_SOLTOS] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["54", 0], "guider": ["56", 0], "sampler": ["52", 0], "sigmas": ["51", 1], "latent_image": [NO_PRESOS, 0]}}
    anterior = ["11", 0]
    for i, (nome, forca) in enumerate(loras_extra):
        g[f"7{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": anterior, "lora_name": nome, "strength_model": float(forca)}}
        anterior = [f"7{i}", 0]
    g["13"]["inputs"]["model"] = anterior
    return g


def gerar(projeto, video, pintados, prompt, largura, altura, quadros, semente, rodar, acompanhar=None, ao_passo=lambda passo: None, modo="swap", loras_extra=(), dono=None):
    """Roda o grafo no ComfyUI. `pintados`: [(quadro, caminho do PNG)]. Devolve (resultado do rodar, video gerado ou None).
    `acompanhar` e o do trocar_personagem (ouve os avisos do ComfyUI); `ao_passo(passo)` recebe o passo de 0 a PASSOS.
    Os quadros pintados vao para os temporarios de `dono` (entrada_temp; sem ele, de `projeto`)."""
    import types
    nomes = []
    for quadro, arquivo in pintados:
        arq, nome = entrada_temp.arquivo(dono or projeto, f"viggle_{projeto}_{quadro:03d}.png")
        shutil.copyfile(arquivo, arq)
        nomes.append((quadro, nome, arq))
    g = grafo(video, [(q, n) for q, n, _ in nomes], prompt, largura, altura, quadros, semente, f"troca/{projeto}_viggle", modo, loras_extra)
    if acompanhar:
        def evento(m):
            passo = passo_do_evento(m)
            if passo is not None:
                ao_passo(passo)
        acompanhar(types.SimpleNamespace(evento=evento))
    try:
        r = rodar(g, 3600)
    finally:
        for _, _, arq in nomes:
            arq.unlink(missing_ok=True)
    return r, arquivo_gerado(r["saidas"]) if r["status"] == "success" else None


def passo_do_evento(m):
    """O passo (de 0 a PASSOS) num aviso progress_state do ComfyUI, ou None se o aviso nao e da amostragem."""
    if m.get("type") != "progress_state":
        return None
    nos = (m.get("data") or {}).get("nodes") or {}
    for no, base in ((NO_SOLTOS, PASSOS_PRESOS), (NO_PRESOS, 0)):
        n = nos.get(no) or {}
        if n.get("state") == "running" and n.get("max", 0) > 1:
            return base + round(n.get("value", 0))
    return None


def arquivo_gerado(saidas):
    """O video que o no SaveVideo gravou (o LoadVideo tambem aparece nas saidas, com o video de entrada)."""
    for item in (saidas.get(NO_VIDEO) or {}).get("images") or []:
        if isinstance(item, dict) and str(item.get("filename", "")).endswith(".mp4"):
            return config.SAIDA / item.get("subfolder", "") / item["filename"]
    return None
