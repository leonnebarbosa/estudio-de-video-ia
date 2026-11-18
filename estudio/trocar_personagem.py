"""Troca a personagem de um video (Character Swap v1.1, ou Head Swap com a roupa do video) e guarda o resultado no projeto.

Uso, normalmente pela interface:
  python -I trocar_personagem.py --projeto nome

Os ajustes vem de <projeto>/interface.json e o video e a foto de <projeto>/estado.json.
Saidas em projetos\\<projeto>: final.mp4, comparativo.mp4, prompt.txt, progresso.json, gpu.csv
Acima do que roda numa passada (validacao.DURACAO_MAX_TROCA_POR_MP), a troca vai em janelas com emenda (ver HISTORIA e
trocar_em_janelas); nesse caso nao ha comparativo.mp4.
Com "esrgan" (o padrao desde 11/11/2026), roda sem a segunda passagem e amplia o final.mp4 para Full HD com o ESRGAN do
acabamento, fora do ComfyUI; o video da primeira passagem fica como primeira_passagem.mp4.
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da geracao, 5 temperatura.
"""
import argparse, copy, json, os, random, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos, config, loras
from comfy_api import posta
from continuar_video import FPS, Monitor, quadros_por_duracao, rodar
from detalhe_comfy import Detalhe

GRAFO = config.GRAFOS / "troca_personagem_api.json"
# Roupa do video: a Character Swap copia a roupa da foto seja qual for o prompt. A Head Swap, do mesmo autor, troca so
# a cabeca e mantem do video o corpo, a roupa e cada peca posta ou tirada (testado em 09/11/2026, teste F).
# Montada como o fluxo do autor (docs/head-swap.md): foto inteira (a 1 MP desde 16/11/2026, ver cabeca_do_video), LLM
# descreve so o rosto, e o prompt e o modelo head_swap com essa descricao no lugar de {ROSTO}.
HEAD_SWAP = "minimax_h3_head_swap_v1.0_r32.safetensors"
PROMPT_HEAD_SWAP = config.GRAFOS / "troca_head_swap.txt"
INSTRUCAO_ROSTO = config.GRAFOS / "troca_head_swap_rosto.txt"
ORDEM = ["descrever", "primeira", "ampliar", "montar", "esrgan"]
# Tamanho da foto de referencia. O H3 a recebe com ref_image_size "max" (ate 2048 px no lado menor, nunca amplia):
# com "match" ela era reduzida ao tamanho da geracao. O Henge limita a 1 MP porque fotos maiores derrubavam o codificador.
REF_MEGAPIXELS = 1.0
# Janelas (16/11/2026, receita do Imagination Studio, spark/swap_plan.py): acima do que roda numa passada, a troca e feita
# em janelas desse tamanho. Cada janela comeca com os ultimos HISTORIA quadros da anterior, que entram prontos no latente
# com uma mascara de ruido que nao deixa o modelo mexer neles; o resto e redesenhado seguindo o trecho do video. O H3 pega
# 17n+5 quadros e o latente tem 1 quadro e depois grupos de 4: 18 quadros (17 antes da emenda e a emenda) enchem 6 latentes
# inteiros. Da segunda janela em diante vai o prompt da primeira e um quadro ja trocado dela como segunda referencia
# (<Picture 2>): sem ele, o lenco do video voltou na janela 2 (teste de 16/11, projetos/teste_janelas_troca).
HISTORIA = 18
FRASE_REF = {"video": " Keep the head, face and hair identical to <Picture 2>.",
             "foto": " Keep the character's face, hair and clothing identical to <Picture 2>."}


# Personagem da biblioteca (personagens.py): os outros ângulos dele entram como mais fotos de referência, depois da foto
# (e do quadro de referência, da segunda janela em diante). Menores que a foto: cada imagem vira contexto do modelo.
REF_ANGULO_MP = 0.5


def com_angulos(g, angulos, primeira, gatilho=""):
    """Acrescenta os `angulos` (arquivos na input do ComfyUI) como ref_image_<primeira>.. nas duas passagens e diz no prompt
    quais <Picture N> são eles; `gatilho` (palavra de uma LoRA de estilo, loras.gatilho) vai no começo do prompt.
    Antes da LLM (prompt ligado ao 835) entram StringConcatenate; da segunda janela em diante o prompt já é texto."""
    nomes = []
    for i, arq in enumerate(angulos or []):
        g[f"98{i}"] = {"class_type": "LoadImage", "inputs": {"image": arq}}
        g[f"99{i}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [f"98{i}", 0], "upscale_method": "lanczos", "megapixels": REF_ANGULO_MP,
                                                                         "resolution_steps": 16}}
        for no in ("400", "587"):
            g[no]["inputs"][f"ref_images.ref_image_{primeira + i}"] = [f"99{i}", 0]
        nomes.append(f"<Picture {primeira + i + 1}>")
    lista = nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " and " + nomes[-1] if nomes else ""
    frase = f" {lista} show{'s' if len(nomes) == 1 else ''} the same character from other angles." if nomes else ""
    antes = f"{gatilho} " if gatilho else ""
    if not frase and not antes:
        return
    # 400 e a primeira passagem; 550 junta a frase de nitidez para a segunda (587)
    for no, campo in (("400", "prompt"), ("550", "string_a")):
        if no not in g:
            continue
        v = g[no]["inputs"].get(campo)
        if isinstance(v, str):
            g[no]["inputs"][campo] = antes + v + frase
        elif v == ["835", 0]:
            fonte = ["835", 0]
            if antes:
                g["978"] = {"class_type": "StringConcatenate", "inputs": {"string_a": antes, "string_b": fonte, "delimiter": ""}}
                fonte = ["978", 0]
            if frase:
                g["979"] = {"class_type": "StringConcatenate", "inputs": {"string_a": fonte, "string_b": frase, "delimiter": ""}}
                fonte = ["979", 0]
            g[no]["inputs"][campo] = fonte


def ignorar(g, no):
    """Tira um no da cadeia de modelos: quem usava a saida dele passa a usar a entrada."""
    modelo = g[no]["inputs"]["model"]
    for n in g.values():
        for k, v in n["inputs"].items():
            if v == [no, 0]:
                n["inputs"][k] = modelo
    del g[no]


def cabeca_do_video(g, forca):
    """Troca a Character Swap pela Head Swap: so a cabeca vem da foto."""
    g["586"]["inputs"].update(lora_name=HEAD_SWAP, strength_model=forca)
    # A foto vai inteira, sem tirar o fundo, a 1 MP (receita do Henge, do autor da LoRA). Antes ia com borda no tamanho da
    # geracao (0,2 MP) e o rosto chegava com poucos pixels; com 1 MP e "max" (montar_grafo) o rosto ficou bem mais fiel
    # a foto (teste de 16/11/2026, projetos/teste_janelas_troca), sem custo de tempo ou VRAM visivel a 0,2 MP.
    g["902"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["349", 0], "upscale_method": "lanczos", "megapixels": REF_MEGAPIXELS, "resolution_steps": 16}}
    g["400"]["inputs"]["ref_images.ref_image_0"] = g["587"]["inputs"]["ref_images.ref_image_0"] = ["902", 0]
    # Com raciocinio e 512 tokens a LLM pensa ate acabar e devolve vazio (teste F); sem ele, 15 s e a descricao completa
    g["826"]["inputs"].update(image=["902", 0], prompt=INSTRUCAO_ROSTO.read_text(encoding="utf-8"), max_length=512, thinking=False)
    antes, depois = PROMPT_HEAD_SWAP.read_text(encoding="utf-8").split("{ROSTO}")
    g["900"] = {"class_type": "StringConcatenate", "inputs": {"string_a": antes, "string_b": ["826", 0], "delimiter": ""}}
    g["901"] = {"class_type": "StringConcatenate", "inputs": {"string_a": ["900", 0], "string_b": depois, "delimiter": ""}}
    g["835"]["inputs"]["source"] = ["901", 0]


def estilo(g, loras):
    """LoRAs de estilo logo depois da de troca. Quem usava a saida dela (a primeira passagem e a LoRA de nitidez do
    upscale) passa a usar a ultima, entao valem nas duas passagens: o upscale parte de sigma 0,90 e redesenha quase tudo."""
    if not loras:
        return
    usam = [(n["inputs"], campo) for n in g.values() for campo, v in n["inputs"].items() if v == ["586", 0]]
    modelo = ["586", 0]
    for i, (nome, forca) in enumerate(loras):
        g[f"91{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"91{i}", 0]
    for entradas, campo in usam:
        entradas[campo] = modelo


def segunda_passagem(p):
    """A segunda passagem do H3 (upscale) so roda se pedida e sem o ESRGAN, que a substitui."""
    return bool(p.get("upscale")) and not p.get("esrgan")


def montar_grafo(base, p, video, foto, prefixo, semente, semente_llm):
    g = copy.deepcopy(base)
    valor = lambda no, **campos: g[no]["inputs"].update(campos)
    valor("320", video=video)
    valor("349", image=foto)
    valor("5", value=p["duracao"])
    valor("4", aspect_ratio=p["proporcao"], megapixels=p["megapixels"])
    valor("607", aspect_ratio=p["proporcao"], megapixels=p["upscale_megapixels"])
    # Com o ESRGAN no lugar, a segunda passagem fica desligada: foi ela que derrubou a placa 3 vezes em 11/11/2026
    valor("595", value=segunda_passagem(p))
    valor("597", value=bool(p["upscale_mesma"]))
    valor("860", value=not p["audio_original"])
    valor("530", model_name=p["upscaler"])
    valor("2", unet_name=p["modelo"])
    valor("586", lora_name=p["troca"][0], strength_model=p["troca"][1])
    if p["turbo"]:
        valor("64", lora_name=p["turbo"][0], strength_model=p["turbo"][1])
    else:
        ignorar(g, "64")
    if p["nitidez"]:
        valor("484", lora_name=p["nitidez"][0], strength_model=p["nitidez"][1])
    else:
        ignorar(g, "484")
    if not p["pouca_vram"]:
        ignorar(g, "59")
    if not p["dividir_blocos"]:
        ignorar(g, "60")
    valor("181", steps=p["passos"], scheduler=p["agendador"])
    valor("15", sampler_name=p["sampler"])
    valor("13", noise_seed=semente)
    valor("826", **{"sampling_mode.seed": semente_llm})
    if p.get("roupa", "video") == "video":
        cabeca_do_video(g, p["troca"][1])
    # A foto de referencia no tamanho dela (ate o limite do no), nao reduzida ao tamanho da geracao
    for no in ("400", "587"):
        valor(no, ref_image_size="max")
    estilo(g, p.get("loras"))
    valor("539", filename_prefix=f"{prefixo}/final")
    valor("791", filename_prefix=f"{prefixo}/comparativo")
    # Os rotulos do comparativo vinham com ajustes fixos que nem sempre sao os usados
    valor("759", string_a="Original ")
    valor("792", string_a="Primeira passagem ")
    valor("806", string_a="Upscale ")
    # O prompt inteiro escrito no comparativo fica cortado; a pagina ja mostra o texto
    valor("791", images=["810", 0])
    del g["780"]
    # Repete o final em outro arquivo
    del g["751"], g["838"]
    return g


def arquivo_de_saida(saida, sufixos=(".mp4",)):
    """Acha o video em uma saida do ComfyUI; prefere a versao com audio."""
    achados = [i for v in saida.values() if isinstance(v, list) for i in v if isinstance(i, dict) and str(i.get("filename", "")).endswith(sufixos)]
    achados.sort(key=lambda i: not i["filename"].endswith("-audio.mp4"))
    if not achados:
        return None
    return config.SAIDA / achados[0].get("subfolder", "") / achados[0]["filename"]


def texto_de_saida(saida):
    for v in saida.values():
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0].split("</think>")[-1].strip()
    return ""


class Progresso:
    """Guarda a etapa e o passo atuais em progresso.json, que a pagina le enquanto a geracao roda."""

    def __init__(self, arquivo, upscale, monitor, grafo=None, etapa="descrever"):
        self.arquivo, self.monitor = arquivo, monitor
        self.etapa, self.valor, self.maximo = etapa, 0, 0
        self.inicio = self.t0 = time.time()
        self.tempos = {}
        self.janela = None
        self.detalhe = Detalhe(monitor, grafo)
        self.mapa = {"14": "primeira", "530": "ampliar", "537": "ampliar", "538": "montar"} if upscale else {"14": "primeira", "45": "montar"}
        monitor.rotulo = self.etapa
        self.gravar()

    def gravar(self):
        dados = {"etapa": self.etapa, "valor": self.valor, "maximo": self.maximo, "segundos_etapa": round(time.time() - self.inicio), "tempos": self.tempos, **self.detalhe.dados()}
        if self.janela:
            dados["janela"] = self.janela
        temporario = self.arquivo.with_name(self.arquivo.name + ".tmp")
        try:
            temporario.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(temporario, self.arquivo)
        except OSError:
            # A pagina pode estar lendo o arquivo neste instante; a proxima gravacao resolve
            pass

    def nova_janela(self, i, n, grafo):
        """Comeco da janela i de n. Da segunda em diante nao ha LLM: volta para a primeira passagem. Em "tempos" fica so o
        que as janelas anteriores levaram, para a pagina medir o tempo da etapa atual."""
        self.janela = [i, n]
        if i > 1:
            self.etapa, self.valor, self.maximo = "primeira", 0, 0
            self.inicio = time.time()
            self.tempos = {"janelas_anteriores": round(self.inicio - self.t0)}
        # Sem o comparativo, quem decodifica o video e o 538 (o 45 nao roda)
        self.mapa = {"14": "primeira", "538": "montar"}
        self.monitor.rotulo = self.etapa
        self.detalhe.reiniciar(grafo)
        self.gravar()

    def esrgan(self, valor, maximo):
        """Ampliacao com o ESRGAN, depois do ComfyUI: quadro valor de maximo."""
        if self.etapa != "esrgan":
            self.tempos[self.etapa] = round(time.time() - self.inicio)
            self.etapa, self.inicio = "esrgan", time.time()
            self.monitor.rotulo = "esrgan"
            self.detalhe.reiniciar()
        self.valor, self.maximo = valor, maximo
        self.gravar()

    def evento(self, m):
        """Usa o progress_state, onde o ComfyUI informa o estado de cada no; ele nao envia o aviso executing."""
        if m.get("type") != "progress_state":
            return
        nos = (m.get("data") or {}).get("nodes") or {}
        self.detalhe.evento(nos)
        rodando = {no: n for no, n in nos.items() if n.get("state") == "running"}
        for no in rodando:
            etapa = self.mapa.get(no)
            if etapa and ORDEM.index(etapa) > ORDEM.index(self.etapa):
                self.tempos[self.etapa] = round(time.time() - self.inicio)
                self.etapa, self.valor, self.maximo = etapa, 0, 0
                self.inicio = time.time()
                self.monitor.rotulo = etapa
        for no in ("14", "537"):
            if no in rodando and rodando[no].get("max", 0) > 1:
                self.valor, self.maximo = round(rodando[no].get("value", 0)), round(rodando[no]["max"])
        if rodando:
            self.gravar()


def acompanhar(progresso):
    """Ouve os avisos do ComfyUI. Se falhar, a geracao segue, so sem o passo a passo."""
    async def laco():
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"{config.URL_COMFY.replace('http', 'ws', 1)}/ws?clientId={uuid.uuid4().hex}", heartbeat=30) as ws:
                async for m in ws:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        progresso.evento(json.loads(m.data))

    def rodar_laco():
        import asyncio
        try:
            asyncio.run(laco())
        except Exception as e:
            print(f"sem acompanhamento do ComfyUI: {e}", flush=True)

    threading.Thread(target=rodar_laco, daemon=True).start()


def descricao_do_rosto(prompt):
    """O trecho que a LLM escreveu dentro do modelo head_swap; vazio quando ela nao devolveu nada."""
    antes, depois = PROMPT_HEAD_SWAP.read_text(encoding="utf-8").split("{ROSTO}")
    return prompt.strip().removeprefix(antes.strip()).removesuffix(depois.strip()).strip()


def ampliar_com_esrgan(pasta, p, progresso):
    """Amplia o final.mp4 com o ESRGAN (o mesmo do acabamento do Imagem para video, ~1 GB, fora do ComfyUI). O video da
    primeira passagem fica como primeira_passagem.mp4. Devolve os segundos gastos, ou None se falhou: nesse caso o
    final.mp4 continua sendo a primeira passagem, porque a troca em si deu certo."""
    import acabamento as ac
    final, primeira, parte = pasta / "final.mp4", pasta / "primeira_passagem.mp4", pasta / "final_parte.mp4"
    shutil.copy2(final, primeira)
    inicio, total = time.time(), ac.contar_quadros(primeira)
    print(f"ampliando com o ESRGAN: {total} quadros", flush=True)
    try:
        ac.liberar_comfy()
        progresso.esrgan(0, total)
        ac.esrgan(ac.quadros_de(primeira), total, primeira, parte, p["proporcao"], avisar=progresso.esrgan, fps=ac.fps_de(primeira))
        os.replace(parte, final)
    except Exception as e:
        print(f"AVISO: a ampliação com o ESRGAN falhou ({e}); o final.mp4 ficou no tamanho da primeira passagem.", flush=True)
        parte.unlink(missing_ok=True)
        return None
    return round(time.time() - inicio)


# ---------------------------------------------------------------- janelas

def quadros_janela(megapixels):
    """Quadros de uma janela: o que ja rodou numa passada so nesta resolucao."""
    from validacao import duracao_max_troca  # aqui dentro: validacao importa este modulo (via imagem_para_video)
    return quadros_por_duracao(duracao_max_troca(megapixels))


def quadros_usados(duracao, megapixels):
    """Quadros do video que a troca le: numa passada, arredondados para cima ate o que o modelo aceita; em janelas, os
    pedidos (a ultima janela completa o que falta repetindo o ultimo quadro)."""
    n = quadros_por_duracao(duracao)
    return n if n <= quadros_janela(megapixels) else round(duracao * FPS)


def _grade(n):
    """O menor numero de quadros que o H3 aceita (17n+5) com pelo menos n."""
    n = max(5, int(n))
    return n + (5 - n % 17) % 17


def janelas(total, janela, historia=HISTORIA, cortes=()):
    """As janelas de `total` quadros. Cada uma: i, start (quadro do video no comeco), length (17n+5), held (quadros que
    vem prontos da anterior), first e last (os quadros do video que ela entrega) e fim (onde acaba o plano dela: a
    janela completa o que falta repetindo o quadro fim-1, nunca com quadros do plano seguinte).
    `cortes`: quadros em que um plano novo comeca (cortes.py). Ali a janela recomeca limpa, sem quadros do plano anterior
    (como o Henge faz); um plano com menos de 5 quadros fica junto do anterior."""
    antes, mais = historia - 1, janela - (historia - 1)
    marcas = [0]
    for c in sorted(set(int(c) for c in cortes)):
        if c - marcas[-1] >= 5 and total - c >= 5:
            marcas.append(c)
    marcas.append(total)
    plano = []
    for a, b in zip(marcas, marcas[1:]):
        n = b - a
        length = min(janela, _grade(n))
        plano.append({"i": len(plano) + 1, "start": a, "length": length, "held": 0, "first": a, "last": a + min(n, length) - 1, "fim": b})
        while plano[-1]["last"] < b - 1:
            emenda = plano[-1]["last"]
            falta = b - emenda
            alvo = mais if falta > mais else _grade(falta)
            plano.append({"i": len(plano) + 1, "start": emenda - antes, "length": antes + alvo, "held": historia,
                          "first": emenda + 1, "last": min(b - 1, emenda + alvo - 1), "fim": b})
    return plano


def quadros_dos_cortes(video, total):
    """Os cortes de camera do video (cortes.py) como quadros a 24 por segundo, dentro dos `total` primeiros."""
    import cortes
    try:
        achados = cortes.cortes(video)
    except Exception as e:  # sem os cortes a troca segue como antes, so sem recomecar nos cortes
        print(f"AVISO: não consegui procurar cortes de câmera ({e}).", flush=True)
        return []
    return [q for q in (round(c["segundos"] * FPS) for c in achados) if 0 < q < total]


def recortar_inicio(origem, destino, inicio):
    """O video a partir de `inicio` segundos (o trecho escolhido no editor da pagina), com o audio."""
    ffmpeg("-ss", f"{inicio:.3f}", "-i", str(origem), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-crf", "12", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(destino))


def latentes(length):
    return (length - 5) // 17 * 5 + 2


def spans_latentes(length):
    """Para cada quadro do latente, o primeiro e o ultimo quadro do video que ele guarda: a cada 5 latentes, 1 quadro e
    4 grupos de 4 (17 quadros), como em spark/swap_plan.py do Imagination Studio."""
    spans, at = [], 0
    for k in range(latentes(length)):
        n = 1 if k % 5 == 0 else 4
        spans.append((at, min(length - 1, at + n - 1)))
        at += n
    return spans


# Marcar quem trocar (Henge e Imagination Studio): o SAM 3.1 acha a pessoa clicada no primeiro quadro e a segue pelo
# trecho; so ela e redesenhada (mascara de ruido no latente), o resto de cada quadro fica como no video.
SAM = "sam3.1_multiplex_fp16.safetensors"
ALTURA_SAM = 360          # os quadros que o SAM le: a mascara nao precisa de mais
CRESCER = 0.045           # a mascara cresce isto da largura, para cabelo, maos e bordas da roupa ficarem dentro
VAZIA = 40                # pixels: menos que isto e um quadro em que o SAM perdeu a pessoa


FUNDO_CABECA = (190, 190, 190)   # cinza neutro atras da cabeca recortada
MARGEM_CABECA = 0.12             # folga em volta da cabeca, fracao do lado maior da mascara


def sem_buracos(mascara):
    """Preenche o que a mascara cerca por todos os lados. O "head" do SAM deixou a boca da Marina de fora (17/11/2026) e
    ela ia para a troca com um buraco cinza no lugar."""
    import cv2
    import numpy as np
    # Uma borda de fundo em volta: o preenchimento comeca nela e contorna a mascara por fora
    fora = np.pad(~mascara, 1, constant_values=True).astype(np.uint8)
    # O que e fundo ligado a borda vira 2; o que sobrar em 1 e buraco cercado pela mascara
    cv2.floodFill(fora, None, (0, 0), 2)
    return mascara | (fora[1:-1, 1:-1] == 1)


def cabeca_da_foto(foto):
    """So a cabeca da foto (cabelo e barba juntos) num fundo cinza, para a Head Swap. Com a foto de corpo inteiro a 0,5 MP
    a roupa da foto vazava para o video (Bruno de capa mostarda no lugar do moletom, teste de 17/11/2026); com a cabeca
    recortada a roupa do video voltou e o rosto ficou igual. O SAM 3.1 junta duas mascaras: "head" pega o rosto com a barba
    inteira e "hair" os cabelos compridos que passam do queixo. Devolve o nome do recorte na entrada, ou None se o SAM nao
    achar a cabeca (a troca segue com a foto inteira)."""
    import numpy as np
    from PIL import Image
    marca = uuid.uuid4().hex[:8]
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SAM}},
         "3": {"class_type": "LoadImage", "inputs": {"image": foto}}}
    for i, texto in enumerate(("head", "hair")):
        g[f"2{i}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": texto}}
        g[f"4{i}"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["1", 0], "image": ["3", 0], "conditioning": [f"2{i}", 0], "threshold": 0.35,
                                                              "refine_iterations": 2, "individual_masks": False}}
        g[f"5{i}"] = {"class_type": "MaskToImage", "inputs": {"mask": [f"4{i}", 0]}}
        g[f"6{i}"] = {"class_type": "SaveImage", "inputs": {"images": [f"5{i}", 0], "filename_prefix": f"troca/cabeca_{texto}_{marca}"}}
    r = rodar(g, 900)
    # O SAM ficava na placa e a troca saiu 20% mais lenta (61 s por passo contra 49, teste de 17/11/2026): descarrega
    try:
        posta("/free", {"unload_models": True, "free_memory": True})
        time.sleep(3)
    except OSError:
        pass
    arqs = [config.SAIDA / i.get("subfolder", "") / i["filename"] for no in ("60", "61") for i in (r["saidas"].get(no) or {}).get("images", [])] if r["status"] == "success" else []
    with Image.open(config.ENTRADA / foto) as im:
        img = im.convert("RGB")
    mascara = np.zeros((img.height, img.width), bool)
    for a in arqs:
        mascara |= np.asarray(Image.open(a).convert("L").resize(img.size)) >= 128
        a.unlink(missing_ok=True)
    if mascara.sum() < VAZIA * VAZIA:
        return None
    mascara = sem_buracos(mascara)
    ys, xs = np.nonzero(mascara)
    folga = round(MARGEM_CABECA * max(xs.max() - xs.min(), ys.max() - ys.min()))
    caixa = (max(xs.min() - folga, 0), max(ys.min() - folga, 0), min(xs.max() + folga + 1, img.width), min(ys.max() + folga + 1, img.height))
    so_cabeca = Image.composite(img, Image.new("RGB", img.size, FUNDO_CABECA), Image.fromarray((mascara * 255).astype(np.uint8)))
    nome = f"cab_{marca}.png"
    so_cabeca.crop(caixa).save(config.ENTRADA / nome)
    return nome


# Rosto borrado no video-guia (source_blur do ComfyUI-BFSNodes, do autor da Head Swap): o guia mostrava o rosto original
# nitido e o formato dele vazava (Marina e Cida sairam com o rosto mais fino, 17/11/2026). Com o rosto borrado o modelo
# ainda le pose, movimento e a boca, mas nao tem rosto para copiar; a identidade vem da foto. Mesmos numeros do autor.
LADO_SAM_BORRAO = 640     # o SAM le os quadros com o lado maior assim (bfs_source_blur._small)
CRESCER_ROSTO = 0.015     # o rosto cresce isto do lado menor, para a borda do rosto ficar dentro
CRESCER_BOCA = 0.012      # a boca que fica nitida cresce isto


def mascaras_sam_texto(video, texto, total, largura, altura, limiar):
    """[total, altura, largura] bool: o que o SAM 3.1 segue com este texto em cada quadro (todas as pessoas, ate 8)."""
    import numpy as np
    from PIL import Image
    marca = uuid.uuid4().hex[:8]
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SAM}},
         "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": texto}},
         "3": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": video, "force_rate": FPS, "custom_width": largura, "custom_height": altura,
                                                              "frame_load_cap": total, "start_time": 0, "format": "None"}},
         "6": {"class_type": "SAM3_VideoTrack", "inputs": {"images": ["3", 0], "model": ["1", 0], "conditioning": ["2", 0],
                                                           "detection_threshold": limiar, "max_objects": 8, "detect_interval": 1}},
         "7": {"class_type": "SAM3_TrackToMask", "inputs": {"track_data": ["6", 0], "object_indices": ""}},
         "8": {"class_type": "MaskToImage", "inputs": {"mask": ["7", 0]}},
         "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": f"troca/borrao_{marca}"}}}
    r = rodar(g, 1800)
    arqs = [config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get("9") or {}).get("images", [])] if r["status"] == "success" else []
    mascaras = np.zeros((total, altura, largura), bool)
    for k, a in enumerate(arqs):
        if k < total:
            mascaras[k] = np.asarray(Image.open(a).convert("L").resize((largura, altura))) >= 128
        a.unlink(missing_ok=True)
    if r["status"] != "success":
        print(f"o SAM não conseguiu seguir '{texto}' ({r['status']} {r['erro'][:200]})", flush=True)
    return mascaras


def crescer(m, px):
    """Dilata a mascara bool em px pixels."""
    import cv2
    import numpy as np
    if px <= 0:
        return m
    return cv2.dilate(m.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)) > 0


def borrar(quadro, peso, forca=1.0):
    """O quadro (uint8 [H,W,3]) com o borrao pesado do autor onde peso (float [H,W], 0 a 1) vale: reduz para 1/12-1/40 do
    tamanho e volta, mais uma passada suave; nenhum detalhe do rosto sobrevive."""
    import cv2
    import numpy as np
    H, W = quadro.shape[:2]
    f = max(4, int(min(H, W) * (0.025 + 0.06 * forca)))
    baixo = cv2.resize(quadro, (max(2, W // f), max(2, H // f)), interpolation=cv2.INTER_AREA)
    borrado = cv2.blur(cv2.resize(baixo, (W, H), interpolation=cv2.INTER_LINEAR), (5, 5)).astype(np.float32)
    p = peso[..., None]
    return (quadro.astype(np.float32) * (1 - p) + borrado * p).round().astype(np.uint8)


def peso_suave(m, W, H):
    """A mascara bool do SAM no tamanho do quadro, com a borda suave (float 0 a 1)."""
    import cv2
    import numpy as np
    mm = cv2.resize(m.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
    return np.clip(cv2.blur(mm, (9, 9)), 0, 1)


def borrar_rosto_do_guia(video, total, pasta):
    """Troca config.ENTRADA/video pelos `total` primeiros quadros com o rosto de todas as pessoas borrado e a boca nitida,
    com o som original. Guarda uma copia em guia_borrado.mp4. Devolve False se o SAM nao achou rosto (o guia fica igual)."""
    import av
    import numpy as np
    from PIL import Image
    with av.open(str(config.ENTRADA / video)) as c:
        tem_som = bool(c.streams.audio)
    # Os quadros a 24 por segundo, como o SAM (force_rate) e a troca leem o video
    trab = pasta / "borrao_trab"  # nao "guia_borrado_quadros": o gravar_clipe usa e apaga essa
    shutil.rmtree(trab, ignore_errors=True)
    trab.mkdir(parents=True)
    ffmpeg("-i", str(config.ENTRADA / video), "-vf", f"fps={FPS}", "-frames:v", str(total), str(trab / "orig_%05d.png"))
    quadros = [np.asarray(Image.open(a).convert("RGB")) for a in sorted(trab.glob("orig_*.png"))]
    if not quadros:
        shutil.rmtree(trab, ignore_errors=True)
        return False
    H, W = quadros[0].shape[:2]
    escala = LADO_SAM_BORRAO / max(H, W)
    w, h = (max(32, round(W * escala / 2) * 2), max(32, round(H * escala / 2) * 2)) if escala < 1 else (W, H)
    rosto = mascaras_sam_texto(video, "face", len(quadros), w, h, 0.4)
    if rosto.sum() == 0:
        shutil.rmtree(trab, ignore_errors=True)
        return False
    boca = mascaras_sam_texto(video, "mouth", len(quadros), w, h, 0.3)
    try:
        posta("/free", {"unload_models": True, "free_memory": True})
        time.sleep(3)
    except OSError:
        pass
    lado = min(h, w)
    arqs = []
    for k, q in enumerate(quadros):
        m = crescer(rosto[k], max(1, int(lado * CRESCER_ROSTO))) & ~crescer(boca[k], max(1, int(lado * CRESCER_BOCA)))
        arq = trab / f"{k + 1:05d}.png"
        Image.fromarray(borrar(q, peso_suave(m, W, H)) if m.any() else q).save(arq)
        arqs.append(arq)
    destino = pasta / "guia_borrado.mp4"
    gravar_clipe(arqs, destino, audio=config.ENTRADA / video if tem_som else None, segundos=len(arqs) / FPS)
    shutil.rmtree(trab, ignore_errors=True)
    shutil.copyfile(destino, config.ENTRADA / video)
    print(f"rosto borrado no vídeo-guia: {int(rosto.any(axis=(1, 2)).sum())} de {len(quadros)} quadros com rosto, "
          f"boca nítida em {int(boca.any(axis=(1, 2)).sum())}", flush=True)
    return True


def mascaras_da_pessoa(video, marca, total, trab):
    """As mascaras (PIL, modo L, 0 ou 255) da pessoa marcada em cada um dos `total` quadros do trecho. `marca`: o ponto
    clicado no primeiro quadro, {"x", "y"} de 0 a 1."""
    import numpy as np
    from PIL import Image, ImageFilter
    import av
    with av.open(str(config.ENTRADA / video)) as c:
        vs = c.streams.video[0]
        largura = round(ALTURA_SAM * vs.width / vs.height / 2) * 2
    px, py = round(marca["x"] * largura), round(marca["y"] * ALTURA_SAM)
    carregar = lambda n: {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": video, "force_rate": FPS, "custom_width": largura, "custom_height": ALTURA_SAM,
                                                                          "frame_load_cap": n, "start_time": 0, "format": "None"}}
    base = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SAM}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "person"}}}
    print("marcando a pessoa: o SAM 3.1 acha as pessoas do primeiro quadro e fica com a que foi clicada", flush=True)
    # 1. Todas as pessoas do primeiro quadro, cada uma na sua mascara: o ponto clicado escolhe uma. So o ponto (sem o
    #    texto) pegava uma parte dela, a cabeca e o lenco (teste de 16/11/2026)
    g = {**base, "3": carregar(1),
         "4": {"class_type": "SAM3_Detect", "inputs": {"model": ["1", 0], "image": ["3", 0], "conditioning": ["2", 0], "threshold": 0.35, "refine_iterations": 2, "individual_masks": True}},
         "5": {"class_type": "MaskToImage", "inputs": {"mask": ["4", 0]}},
         "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": f"troca/pessoas_{uuid.uuid4().hex[:8]}"}}}
    r = rodar(g, 900)
    achadas = [config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get("6") or {}).get("images", [])] if r["status"] == "success" else []
    candidatas = []
    for a in achadas:
        m = np.asarray(Image.open(a).convert("L").resize((largura, ALTURA_SAM))) >= 128
        if m.sum() >= VAZIA:
            ys, xs = np.nonzero(m)
            dist = 0 if m[min(py, ALTURA_SAM - 1), min(px, largura - 1)] else float(np.min((xs - px) ** 2 + (ys - py) ** 2))
            candidatas.append((dist, int(m.sum()), m))
        a.unlink(missing_ok=True)
    if not candidatas:
        print("FALHA na geracao: o SAM não achou nenhuma pessoa no primeiro quadro do trecho. Comece o trecho onde a pessoa aparece.", flush=True)
        sys.exit(4)
    # A que contem o ponto (das que contem, a menor: a pessoa da frente quando duas se sobrepoem); senao a mais perto
    dist, _, escolhida = min(candidatas, key=lambda c: (c[0], c[1]))
    if dist:
        print(f"o ponto marcado ficou fora das pessoas achadas: vai a mais perto dele ({len(candidatas)} no quadro)", flush=True)
    else:
        print(f"{len(candidatas)} {'pessoa' if len(candidatas) == 1 else 'pessoas'} no primeiro quadro; vai a que foi clicada", flush=True)
    inicial = f"troca_marcada_{uuid.uuid4().hex[:8]}.png"
    Image.fromarray((escolhida * 255).astype(np.uint8)).save(config.ENTRADA / inicial)
    # 2. Segue essa pessoa pelo trecho
    g = {**base, "3": carregar(total),
         "4": {"class_type": "LoadImage", "inputs": {"image": inicial}},
         "5": {"class_type": "ImageToMask", "inputs": {"image": ["4", 0], "channel": "red"}},
         "6": {"class_type": "SAM3_VideoTrack", "inputs": {"images": ["3", 0], "model": ["1", 0], "initial_mask": ["5", 0], "conditioning": ["2", 0],
                                                           "detection_threshold": 0.5, "max_objects": 1, "detect_interval": 1}},
         "7": {"class_type": "SAM3_TrackToMask", "inputs": {"track_data": ["6", 0], "object_indices": ""}},
         "8": {"class_type": "MaskToImage", "inputs": {"mask": ["7", 0]}},
         "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": f"troca/marcada_{uuid.uuid4().hex[:8]}"}}}
    r = rodar(g, 1800)
    (config.ENTRADA / inicial).unlink(missing_ok=True)
    if r["status"] != "success":
        print(f"FALHA na geracao: o SAM não conseguiu marcar a pessoa ({r['status']} {r['erro'][:400]}).", flush=True)
        sys.exit(4)
    arqs = [config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get("9") or {}).get("images", [])]
    brutas = [np.asarray(Image.open(a).convert("L")) >= 128 for a in arqs][:total]
    if not brutas or brutas[0].sum() < VAZIA:
        print("FALHA na geracao: o SAM não achou ninguém no ponto marcado. Marque de novo, bem em cima da pessoa, no começo do trecho.", flush=True)
        sys.exit(4)
    while len(brutas) < total:
        brutas.append(brutas[-1])
    # Quadro em que o SAM perdeu a pessoa: fica com a mascara do quadro mais proximo que tem
    tem = [i for i, m in enumerate(brutas) if m.sum() >= VAZIA]
    perdidos = 0
    for i, m in enumerate(brutas):
        if m.sum() < VAZIA:
            brutas[i] = brutas[min(tem, key=lambda t: abs(t - i))]
            perdidos += 1
    if perdidos:
        print(f"o SAM perdeu a pessoa em {perdidos} de {total} quadros: eles usam a máscara do quadro mais próximo", flush=True)
    tam = max(3, int(CRESCER * largura) | 1)
    for a in arqs:
        a.unlink(missing_ok=True)
    return [Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(tam)) for m in brutas]


def proporcao_numero(texto):
    """'16:9 (Widescreen)' -> 16/9"""
    a, b = texto.split(" ")[0].split(":")
    return float(a) / float(b)


def mascara_no_quadro(m, aspecto):
    """A mascara cortada no centro como o grafo corta o video (ImageResizeKJv2, crop) para a proporcao da geracao."""
    w, h = m.size
    if w / h > aspecto:
        nw = round(h * aspecto)
        return m.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = round(w / aspecto)
    return m.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def previa_mascaras(fonte, mascaras, destino):
    """O trecho com a pessoa marcada pintada de verde (pessoa_marcada.mp4 no projeto), para conferir a marcacao."""
    import numpy as np
    from PIL import Image
    pasta = destino.with_name(destino.stem + "_quadros")
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir()
    for k, (q, m) in enumerate(zip(fonte, mascaras)):
        im = Image.open(q).convert("RGB")
        rgb = np.asarray(im, np.float32)
        sel = np.asarray(m.resize(im.size)) >= 128
        rgb[sel] = rgb[sel] * .45 + np.array([232, 255, 90], np.float32) * .55
        Image.fromarray(rgb.astype(np.uint8)).save(pasta / f"{k + 1:05d}.png")
    try:
        ffmpeg("-framerate", str(FPS), "-i", str(pasta / "%05d.png"), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(destino))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def latentes_presos(historia):
    return (historia - 1) // 17 * 5 + 1


def ffmpeg(*args):
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args], check=True, creationflags=config.SEM_JANELA)


def gravar_clipe(quadros, destino, audio=None, inicio=0.0, segundos=None, sem_perda=False):
    """Um video de 24 quadros por segundo com estes quadros (PNG). sem_perda: RGB sem compressao com perda, para os
    quadros que entram prontos no latente e para a mascara."""
    pasta = destino.with_name(destino.stem + "_quadros")
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    for k, q in enumerate(quadros):
        shutil.copyfile(q, pasta / f"{k + 1:05d}.png")
    cod = ["-c:v", "libx264rgb", "-qp", "0", "-pix_fmt", "rgb24"] if sem_perda else ["-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p"]
    som = ["-ss", f"{inicio:.6f}", "-t", f"{segundos:.6f}", "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k",
           "-af", f"apad=whole_dur={segundos:.6f}"] if audio else []
    try:
        ffmpeg("-framerate", str(FPS), "-i", str(pasta / "%05d.png"), *som, *cod, "-r", str(FPS), str(destino))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def grafo_janela(base, p, j, clipe, foto, prefixo, semente, semente_llm, prompt=None, ref=None, pix=None, mascara=None):
    """O grafo de uma janela. A primeira e a troca normal; as seguintes partem dos quadros `pix` (os HISTORIA primeiros sao
    a saida da anterior) com a `mascara` de ruido, usam o `prompt` da primeira sem a LLM e o quadro `ref` como
    <Picture 2>. Sem comparativo nem video no ComfyUI: os quadros saem em PNG e o estudio monta o final."""
    g = montar_grafo(base, {**p, "duracao": j["length"] / FPS}, clipe, foto, prefixo, semente, semente_llm)
    for no in ("539", "791"):
        g.pop(no, None)
    g["970"] = {"class_type": "SaveImage", "inputs": {"images": ["538", 0], "filename_prefix": f"{prefixo}/q"}}
    if j["i"] > 1:
        # Da segunda janela em diante (inclusive a que recomeca limpa num corte): o prompt da primeira e o quadro de referencia
        texto = prompt + FRASE_REF[p.get("roupa", "video")]
        for n in g.values():
            for k, v in list(n["inputs"].items()):
                if v == ["835", 0]:
                    n["inputs"][k] = texto
        for no in ("827", "835", "826", "900", "901", "85"):
            g.pop(no, None)
        g["960"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        for no in ("400", "587"):
            g[no]["inputs"]["ref_images.ref_image_1"] = ["960", 0]
    com_angulos(g, p.get("angulos"), 2 if j["i"] > 1 else 1, loras.gatilho(p.get("loras")))
    # Sem quadros de partida (nem emenda nem pessoa marcada), o latente parte do vazio, como a troca normal
    if not pix:
        return g
    carregar = lambda arq: {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": arq, "force_rate": 0, "custom_width": 0, "custom_height": 0,
                                                                             "frame_load_cap": 0, "start_time": 0, "format": "None"}}
    g["950"] = carregar(pix)
    g["951"] = {"class_type": "ImageResizeKJv2", "inputs": {"image": ["950", 0], "width": ["432", 0], "height": ["432", 1], "upscale_method": "lanczos",
                "keep_proportion": "crop", "pad_color": "0, 0, 0", "crop_position": "center", "divisible_by": 32, "device": "cpu"}}
    g["952"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["951", 0], "vae": ["3", 0]}}
    g["953"] = carregar(mascara)
    g["954"] = {"class_type": "ImageToMask", "inputs": {"image": ["953", 0], "channel": "red"}}
    g["955"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["952", 0], "mask": ["954", 0]}}
    g["956"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["289", 0]}}
    g["957"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["955", 0], "audio_latent": ["956", 1]}}
    g["14"]["inputs"]["latent_image"] = ["957", 0]
    g["81"]["inputs"]["latent"] = ["957", 0]
    return g


def conferir(r, mon):
    """Sai com o codigo certo se a geracao nao deu certo."""
    if mon.quente:
        print("PARADO por temperatura", flush=True)
        sys.exit(5)
    if r["status"] == "servidor caiu":
        print(f"SERVIDOR CAIU: {r['erro'][:300]}", flush=True)
        sys.exit(3)
    if r["status"] != "success":
        print(f"FALHA na geracao: {r['status']} {r['erro'][:700]}", flush=True)
        sys.exit(4)


def conferir_prompt(r, pasta, roupa_do_video):
    prompt = texto_de_saida(r["saidas"].get("835", {}))
    if not prompt:
        # Sem prompt a troca nao acontece de verdade: a LLM esgotou os tokens ou nao viu a foto
        print("FALHA na geracao: a LLM devolveu um prompt vazio.", flush=True)
        sys.exit(4)
    (pasta / "prompt.txt").write_text(prompt, encoding="utf-8")
    if roupa_do_video and not descricao_do_rosto(prompt):
        # A troca acontece mesmo assim (a foto vai pelo canal de referencia), so sem o reforco do texto
        print("AVISO: a LLM nao descreveu o rosto; a troca usou so a foto.", flush=True)
    return prompt


JANELAS_FEITAS = "janelas_feitas"  # na pasta do projeto: os quadros de cada janela (j1, j2...), a referencia e o plano


def janelas_a_refazer(plano, n):
    """Refazer a janela n leva junto as seguintes do mesmo plano (elas emendam nela); depois de um corte, nao. A janela
    1 da a referencia de todas, entao refaze-la refaz tudo."""
    alvo = next(j for j in plano if j["i"] == n)
    return {j["i"] for j in plano if n == 1 or (j["fim"] == alvo["fim"] and j["i"] >= n)}


def trocar_em_janelas(pasta, projeto, p, video, foto, semente, semente_llm, mon, progresso, cortes=(), refazer=None, marca=None):
    """A troca em janelas. Grava pasta/final.mp4 e devolve (medidas somadas, prompt).
    Os quadros de cada janela ficam em pasta/janelas_feitas, com o plano, o prompt e a referencia (janelas.json), para
    `refazer` (Refazer uma janela, ideia do Henge): refaz da janela `refazer` ate o fim do plano dela, com outra
    semente, e monta o final de novo com as outras como estavam. Da janela 1, refaz tudo (a referencia muda)."""
    from PIL import Image
    import numpy as np
    guardadas = pasta / JANELAS_FEITAS
    meta_arq = guardadas / "janelas.json"
    if refazer:
        meta = json.loads(meta_arq.read_text(encoding="utf-8"))
        plano, tam, cortes, marca = meta["plano"], meta["tam"], meta["cortes"], meta.get("marca")
        total = plano[-1]["fim"]
        refazer_estas = janelas_a_refazer(plano, refazer)
        prompt = None if refazer == 1 else meta["prompt"]
        print(f"refazendo as janelas {', '.join(str(i) for i in sorted(refazer_estas))} de {len(plano)}, com a semente {semente}", flush=True)
    else:
        total, tam = round(p["duracao"] * FPS), quadros_janela(p["megapixels"])
        plano = janelas(total, tam, cortes=cortes)
        refazer_estas, prompt = {j["i"] for j in plano}, None
        meta = {"plano": plano, "tam": tam, "cortes": list(cortes), "sementes": {}, "marca": marca}
        shutil.rmtree(guardadas, ignore_errors=True)
        print(f"em {len(plano)} janelas de até {tam} quadros, {HISTORIA} de emenda: " + ", ".join(f"{j['first']}-{j['last']}" for j in plano)
              + (f"; recomeça nos cortes de câmera em {', '.join(f'{c / FPS:.2f} s' for c in cortes)}" if cortes else ""), flush=True)
    guardadas.mkdir(exist_ok=True)
    trab = pasta / "janelas"
    shutil.rmtree(trab, ignore_errors=True)
    (trab / "fonte").mkdir(parents=True)
    # Os quadros do video a 24 por segundo, ate 720 de altura (o grafo corta e reduz ao tamanho da geracao)
    ffmpeg("-i", str(config.ENTRADA / video), "-vf", f"fps={FPS},scale=-2:'min(720,ih)'", "-frames:v", str(total), str(trab / "fonte" / "%05d.png"))
    fonte = sorted((trab / "fonte").glob("*.png"))
    if len(fonte) < total - 2:
        print(f"FALHA na geracao: o vídeo deu {len(fonte)} quadros, eram precisos {total}.", flush=True)
        sys.exit(4)
    audio = None
    if p["audio_original"]:
        audio = trab / "fonte.wav"
        try:
            ffmpeg("-i", str(config.ENTRADA / video), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(audio))
        except subprocess.CalledProcessError:
            audio = None
    quadro = lambda s: fonte[min(s, len(fonte) - 1)]
    # Pessoa marcada: so ela e redesenhada em cada janela; o resto de cada quadro fica como no video
    mascaras = mascaras_da_pessoa(video, marca, total, trab) if marca else None
    if mascaras and not refazer:
        previa_mascaras(fonte[:total], mascaras, pasta / "pessoa_marcada.mp4")
    aspecto = proporcao_numero(p["proporcao"])
    base = json.loads(GRAFO.read_text(encoding="utf-8"))
    feitos, mistura, entradas = {}, {}, []
    ref = None
    if refazer and refazer != 1:
        ref = f"troca_{projeto}_ref.png"
        shutil.copyfile(guardadas / "ref.png", config.ENTRADA / ref)
        entradas.append(ref)
    soma = {"segundos": 0, "pico_vram": 0, "temp_max": 0, "janelas": len(plano)}
    for j in plano:
        pasta_j = guardadas / f"j{j['i']}"
        if j["i"] not in refazer_estas:
            # Fica como estava: os quadros guardados da ultima vez
            q = sorted(pasta_j.glob("*.png"))
            if len(q) < j["length"]:
                print(f"FALHA na geracao: faltam os quadros guardados da janela {j['i']}. Gere a troca de novo.", flush=True)
                sys.exit(4)
        else:
            nome = f"troca_{projeto}_j{j['i']}.mp4"
            # Alem do fim do plano, repete o ultimo quadro dele (nunca quadros depois de um corte)
            gravar_clipe([quadro(min(j["start"] + k, j["fim"] - 1)) for k in range(j["length"])], config.ENTRADA / nome, audio, j["start"] / FPS, j["length"] / FPS)
            entradas.append(nome)
            pix = mascara = None
            if j["held"] or mascaras:
                # Os quadros de partida: os HISTORIA primeiros sao a saida da anterior; o resto e o video (redesenhado
                # inteiro, ou so na pessoa marcada). Sem emenda, os quadros do video vao como estao (o grafo corta e reduz).
                W, H = Image.open(feitos[j["start"]]).size if j["held"] else (None, None)
                (trab / f"j{j['i']}").mkdir()
                lista = []
                for k in range(j["length"]):
                    s = j["start"] + k
                    if k < j["held"]:
                        lista.append(feitos[s])
                        continue
                    if not j["held"]:
                        lista.append(quadro(min(s, j["fim"] - 1)))
                        continue
                    im = Image.open(quadro(min(s, j["fim"] - 1))).convert("RGB")
                    esc = max(W / im.width, H / im.height)
                    im = im.resize((round(im.width * esc), round(im.height * esc)), Image.LANCZOS)
                    x, y = (im.width - W) // 2, (im.height - H) // 2
                    alvo = trab / f"j{j['i']}" / f"p{k:05d}.png"
                    im.crop((x, y, x + W, y + H)).save(alvo)
                    lista.append(alvo)
                pix, mascara = f"troca_{projeto}_j{j['i']}_pix.mp4", f"troca_{projeto}_j{j['i']}_mascara.mp4"
                gravar_clipe(lista, config.ENTRADA / pix, sem_perda=True)
                # A mascara no grid do latente: preto mantem (os latentes da emenda e, com a pessoa marcada, tudo
                # menos ela), branco redesenha. Cada quadro do latente junta as mascaras dos quadros do video que guarda.
                presos, cel = latentes_presos(j["held"]), []
                mh = 64
                mw = max(2, round(mh * aspecto / 2) * 2)
                for k, (a, b) in enumerate(spans_latentes(j["length"])):
                    alvo = trab / f"j{j['i']}" / f"m{k:05d}.png"
                    if k < presos:
                        Image.new("RGB", (mw, mh), (0, 0, 0)).save(alvo)
                    elif mascaras:
                        junta = np.zeros((mh, mw), bool)
                        for f in range(a, b + 1):
                            m = mascaras[min(j["start"] + f, j["fim"] - 1, total - 1)]
                            junta |= np.asarray(mascara_no_quadro(m, aspecto).resize((mw, mh), Image.BILINEAR)) >= 64
                        Image.fromarray((junta * 255).astype(np.uint8)).convert("RGB").save(alvo)
                    else:
                        Image.new("RGB", (mw, mh), (255, 255, 255)).save(alvo)
                    cel.append(alvo)
                gravar_clipe(cel, config.ENTRADA / mascara, sem_perda=True)
                entradas += [pix, mascara]
            g = grafo_janela(base, p, j, nome, foto, f"troca/{projeto}/j{j['i']}", semente, semente_llm, prompt, ref, pix, mascara)
            progresso.nova_janela(j["i"], len(plano), g)
            print(f"janela {j['i']} de {len(plano)}: quadros {j['first']} a {j['last']}", flush=True)
            r = rodar(g, 3600)
            conferir(r, mon)
            soma["segundos"] += r["segundos"]
            soma["pico_vram"], soma["temp_max"] = max(soma["pico_vram"], r["pico_vram"]), max(soma["temp_max"], r["temp_max"])
            saidas = [config.SAIDA / i.get("subfolder", "") / i["filename"] for i in (r["saidas"].get("970") or {}).get("images", [])]
            if len(saidas) < j["length"] - 2:
                print(f"FALHA na geracao: a janela {j['i']} deu {len(saidas)} quadros de {j['length']}.", flush=True)
                sys.exit(4)
            saidas += [saidas[-1]] * (j["length"] - len(saidas))
            # Guarda os quadros desta janela no projeto (para Refazer uma janela)
            shutil.rmtree(pasta_j, ignore_errors=True)
            pasta_j.mkdir()
            q = []
            for k, arq in enumerate(saidas):
                shutil.copyfile(arq, pasta_j / f"{k:05d}.png")
                q.append(pasta_j / f"{k:05d}.png")
            meta["sementes"][str(j["i"])] = semente
            if j["i"] == 1:
                prompt = conferir_prompt(r, pasta, p.get("roupa", "video") == "video")
                ref = f"troca_{projeto}_ref.png"
                shutil.copyfile(q[len(q) // 2], guardadas / "ref.png")
                shutil.copyfile(guardadas / "ref.png", config.ENTRADA / ref)
                entradas.append(ref)
                meta["prompt"] = prompt
            print(f"janela {j['i']}: {r['segundos']} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)
        # Nos quadros da emenda, passa aos poucos da versao da janela anterior para a desta (sao os mesmos quadros,
        # codificados de novo: uns 5 tons de diferenca)
        for k in range(j["held"]):
            mistura[j["start"] + k] = (feitos[j["start"] + k], q[k], (k + 1) / (j["held"] + 1))
        for k in range(j["held"], j["length"]):
            if j["start"] + k <= j["last"]:
                feitos[j["start"] + k] = q[k]
    meta_arq.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    final = trab / "final"
    final.mkdir()
    for s in range(total):
        alvo = final / f"{s + 1:05d}.png"
        if s in mistura:
            a, b, peso = mistura[s]
            im = (1 - peso) * np.asarray(Image.open(a).convert("RGB"), float) + peso * np.asarray(Image.open(b).convert("RGB"), float)
            Image.fromarray(im.round().astype(np.uint8)).save(alvo)
        else:
            shutil.copyfile(feitos[s], alvo)
    if refazer and (pasta / "final.mp4").exists():
        # O final de antes fica guardado, para comparar
        shutil.copy2(pasta / ("primeira_passagem.mp4" if (pasta / "primeira_passagem.mp4").exists() else "final.mp4"), pasta / "antes_de_refazer.mp4")
    som = ["-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-af", f"apad=whole_dur={total / FPS:.6f}"] if audio else []
    ffmpeg("-framerate", str(FPS), "-i", str(final / "%05d.png"), *som, "-t", f"{total / FPS:.6f}", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-movflags", "+faststart", str(pasta / "final.mp4"))
    for nome in entradas:
        (config.ENTRADA / nome).unlink(missing_ok=True)
    shutil.rmtree(trab, ignore_errors=True)
    soma["plano"] = [{"i": j["i"], "de": round(j["first"] / FPS, 2), "ate": round((j["last"] + 1) / FPS, 2), "corte": not j["held"] and j["i"] > 1,
                      "semente": meta["sementes"].get(str(j["i"]))} for j in plano]
    return soma, prompt


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--projeto", required=True)
    a.add_argument("--refazer", type=int, default=None, help="refaz desta janela ate o fim do plano dela, com outra semente")
    a = a.parse_args()
    pasta = config.PROJETOS / a.projeto
    p = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
    arq_estado = pasta / "estado.json"
    estado = json.loads(arq_estado.read_text(encoding="utf-8"))

    video = f"troca_{a.projeto}.mp4"
    inicio = float(p.get("inicio") or 0)
    if inicio > 0:
        # O trecho escolhido no editor da pagina: daqui em diante tudo le o video como se comecasse ali
        recortar_inicio(caminhos.abrir_envio(estado["origem"]), config.ENTRADA / video, inicio)
    else:
        shutil.copy2(caminhos.abrir_envio(estado["origem"]), config.ENTRADA / video)
    # Refazer uma janela e sempre com outra semente: com a mesma sairia igual
    semente = random.randrange(2**48) if p["semente"] is None or a.refazer else p["semente"]
    semente_llm = random.randrange(2**31) if p["semente"] is None else p["semente"] % 2**31
    roupa_do_video = p.get("roupa", "video") == "video"
    amplia = "ESRGAN" if p.get("esrgan") else "segunda passagem" if p["upscale"] else "nenhuma"
    print(f"semente {semente} | {p['duracao']} s | {p['megapixels']} MP | ampliação: {amplia} | roupa {'do vídeo' if roupa_do_video else 'da foto'}", flush=True)

    wangp = p.get("motor") == "wangp"
    if wangp:
        print("motor: WanGP (pinta quadros com o Qwen Image 2.1 Viggle Swap e gera com o Viggle Remake)", flush=True)
    if roupa_do_video and not wangp and HEAD_SWAP.lower() not in loras.mapa():
        print(f"FALHA na geracao: falta a LoRA {HEAD_SWAP} em models/loras (Hugging Face, Alissonerdx/Minimax-H3-ComfyUI).", flush=True)
        sys.exit(4)

    foto = estado["personagem"]
    if roupa_do_video and p.get("recortar_cabeca", True):
        print("recortando a cabeça da foto: o SAM 3.1 separa a cabeça com o cabelo e a barba", flush=True)
        cabeca = cabeca_da_foto(foto)
        if cabeca:
            foto = cabeca
            shutil.copyfile(config.ENTRADA / cabeca, pasta / "cabeca_recortada.png")
        else:
            print("o SAM não achou a cabeça na foto: vai a foto inteira (a roupa da foto pode aparecer no vídeo)", flush=True)

    mon = Monitor(pasta / "gpu.csv")
    mon.start()
    if wangp:
        r, prompt, progresso = trocar_pelo_wangp(pasta, p, video, foto, semente, mon)
    else:
        r, prompt, progresso = trocar_no_comfy(a, pasta, p, video, foto, semente, semente_llm, roupa_do_video, mon, estado)
    terminar(pasta, p, r, prompt, progresso, semente, estado, arq_estado)


def trocar_pelo_wangp(pasta, p, video, foto, semente, mon):
    """Motor WanGP (troca_wangp.py): Viggle Remake, numa janela so, sem os nos do ComfyUI."""
    import troca_wangp
    progresso = Progresso(pasta / "progresso.json", False, mon, etapa="pintar")
    r, prompt = troca_wangp.trocar(pasta, p, video, foto, semente, mon, progresso)
    mon.fim.set()
    return r, prompt, progresso


def trocar_no_comfy(a, pasta, p, video, foto, semente, semente_llm, roupa_do_video, mon, estado):
    """O motor do estudio: Head Swap (roupa do video) ou Character Swap (roupa da foto) no ComfyUI."""
    if p.get("borrar_rosto") and a.refazer and (pasta / "guia_borrado.mp4").exists():
        # Refazer uma janela: o mesmo guia borrado da primeira vez
        shutil.copyfile(pasta / "guia_borrado.mp4", config.ENTRADA / video)
    elif p.get("borrar_rosto"):
        print("borrando o rosto no vídeo-guia: o SAM 3.1 segue os rostos e a boca fica nítida", flush=True)
        if not borrar_rosto_do_guia(video, quadros_usados(p["duracao"], p["megapixels"]), pasta):
            print("o SAM não achou rosto no vídeo: o guia vai sem borrão", flush=True)
    g = montar_grafo(json.loads(GRAFO.read_text(encoding="utf-8")), p, video, foto, f"troca/{a.projeto}", semente, semente_llm)
    com_angulos(g, p.get("angulos"), 1, loras.gatilho(p.get("loras")))
    if p.get("angulos"):
        print(f"personagem {p.get('personagem_id')}: {len(p['angulos'])} ângulos como referências extras", flush=True)
    progresso = Progresso(pasta / "progresso.json", segunda_passagem(p), mon, g)
    acompanhar(progresso)
    # Um corte de camera dentro do trecho tambem leva para as janelas: cada plano e trocado a parte
    cortes_q = [] if segunda_passagem(p) or a.refazer else quadros_dos_cortes(config.ENTRADA / video, round(p["duracao"] * FPS))
    if p.get("fundo") and a.refazer and (pasta / "fundo_novo.mp4").exists():
        # Refazer uma janela com fundo novo: o guia e o video com o fundo ja trocado da primeira vez
        shutil.copyfile(pasta / "fundo_novo.mp4", config.ENTRADA / video)
    if p.get("fundo") and not a.refazer:
        # Fundo novo (Henge): o cenario vira a foto escolhida, andando com a camera; esse video passa a ser o guia
        import fundo
        print("trocando o fundo: o BiRefNet separa as pessoas e a foto acompanha o movimento da câmera", flush=True)
        try:
            fundo.trocar_fundo(video, config.ENTRADA / p["fundo"], quadros_por_duracao(p["duracao"]), cortes_q, rodar, ffmpeg, pasta)
        except Exception as e:
            print(f"FALHA na geracao: não consegui trocar o fundo ({e}).", flush=True)
            sys.exit(4)
    if a.refazer:
        r, prompt = trocar_em_janelas(pasta, a.projeto, p, video, foto, semente, semente_llm, mon, progresso, refazer=a.refazer)
        mon.fim.set()
        prompt = prompt or estado.get("prompt", "")
    elif not segunda_passagem(p) and (quadros_por_duracao(p["duracao"]) > quadros_janela(p["megapixels"]) or cortes_q or p.get("marca")):
        # A pessoa marcada tambem vai pelas janelas: e la que entra a mascara de ruido
        r, prompt = trocar_em_janelas(pasta, a.projeto, p, video, foto, semente, semente_llm, mon, progresso, cortes_q, marca=p.get("marca"))
        mon.fim.set()
    else:
        r = rodar(g, 3600)
        mon.fim.set()
        conferir(r, mon)
        prompt = conferir_prompt(r, pasta, roupa_do_video)
        final = arquivo_de_saida(r["saidas"].get("539", {}))
        if final is None or not final.is_file():
            print(f"FALHA na geracao: o ComfyUI nao informou o video final. Saidas: {list(r['saidas'])}", flush=True)
            sys.exit(4)
        shutil.copy2(final, pasta / "final.mp4")
        comparativo = arquivo_de_saida(r["saidas"].get("791", {}))
        if comparativo is not None and comparativo.is_file():
            shutil.copy2(comparativo, pasta / "comparativo.mp4")
    return r, prompt, progresso


def terminar(pasta, p, r, prompt, progresso, semente, estado, arq_estado):
    """O fim comum aos dois motores: ESRGAN (se pedido) e o resultado no estado.json."""
    resultado = {"segundos": r["segundos"], "pico_vram": r["pico_vram"], "temp_max": r["temp_max"], "semente": semente}
    if r.get("janelas"):
        resultado["janelas"] = r["janelas"]
        # Cada janela com o trecho e a semente: a pagina mostra Refazer daqui em cada uma
        estado["janelas"] = r.get("plano", [])
    else:
        estado.pop("janelas", None)
    if p.get("esrgan"):
        segundos = ampliar_com_esrgan(pasta, p, progresso)
        resultado["esrgan"] = {"segundos": segundos} if segundos is not None else {"falhou": True}
        if segundos is not None:
            resultado["segundos"] = r["segundos"] + segundos
    estado.update(resultado=resultado, prompt=prompt)
    caminhos.gravar_json(arq_estado, estado)
    print(f"final: {pasta / 'final.mp4'} | {resultado['segundos']} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)


if __name__ == "__main__":
    main()
