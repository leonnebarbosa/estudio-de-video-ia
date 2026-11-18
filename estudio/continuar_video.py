"""Continua um video em rodadas: a LLM local escreve o prompt de cada trecho vendo o ultimo quadro,
o Seed Hunter gera o trecho, o script confere a emenda e no fim junta tudo.

Uso:
  python -I continuar_video.py --projeto nome --video arquivo.mp4 --ideia "ideia geral" --duracao 30
  Rodar de novo com o mesmo --projeto retoma da ultima rodada aprovada.
  --so-plano gera so o plano; --ate-rodada N para depois da rodada N; --so-juntar refaz o video final.

Saidas em projetos\\<projeto>: estado.json, plano.json, rodadas.jsonl, prompts.md, gpu.csv, final.mp4
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da LLM ou da geracao, 5 temperatura.
"""
import argparse, csv, json, math, random, re, shutil, subprocess, sys, threading, time
from pathlib import Path

import av
import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos, config
from comfy_api import gpu, posta, rodar

if sys.stdout is not None:  # no pythonw.exe nao ha console
    sys.stdout.reconfigure(encoding="utf-8")
GRAFO = config.GRAFOS / "seed_hunter_continuacao_api.json"
FPS = 24
TEMP_MAX = 85
PROIBIDO = re.compile(r"(?!)", re.I)


def quadros_por_duracao(s):
    n = max(5, round(s * FPS))
    return n + (5 - (n % 17)) % 17


class Monitor(threading.Thread):
    """Registra a placa a cada 2 s e interrompe a geracao se a temperatura passar do limite."""

    def __init__(self, arquivo, intervalo=2):
        super().__init__(daemon=True)
        self.arquivo, self.fim, self.quente, self.rotulo = arquivo, threading.Event(), False, ""
        self.ultimo = None  # a leitura mais recente, para o registro tecnico (detalhe_comfy)
        self.intervalo = intervalo

    def run(self):
        novo = not self.arquivo.exists()
        with self.arquivo.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if novo:
                w.writerow(["hora", "etapa", "vram_mib", "temp", "clock_mhz", "watts"])
            while not self.fim.wait(self.intervalo):
                try:
                    u, t = gpu()
                    extra = subprocess.run(["nvidia-smi", "--query-gpu=clocks.gr,power.draw", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip().split(",")
                except Exception:
                    continue
                w.writerow([time.strftime("%H:%M:%S"), self.rotulo, u, t] + [x.strip() for x in extra])
                try:
                    self.ultimo = {"vram_mib": u, "temp": t, "watts": float(extra[1])}
                except (IndexError, ValueError):
                    self.ultimo = {"vram_mib": u, "temp": t}
                f.flush()
                if t >= TEMP_MAX and not self.quente:
                    self.quente = True
                    try:
                        posta("/interrupt", {})
                    except Exception:
                        pass


def texto_llm(res):
    """Pega o texto do PreviewAny e descarta o bloco de raciocinio."""
    s = res["saidas"].get("5", {})
    t = ""
    for v in s.values():
        if isinstance(v, list) and v and isinstance(v[0], str):
            t = v[0]
            break
    return t.split("</think>")[-1].strip()


def chamar_llm(pergunta, imagem, modelo_rotulo, mon, pensar=True):
    # Com raciocinio ligado a LLM pode gastar todos os tokens pensando e devolver texto vazio
    g = {
        "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3.5_9b_w4a8_gptq.safetensors", "type": "minimax", "device": "default"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": imagem}},
        "3": {"class_type": "ResizeImageMaskNode", "inputs": {"resize_type": "scale total pixels", "resize_type.megapixels": 0.75, "scale_method": "lanczos", "input": ["2", 0]}},
        "4": {"class_type": "TextGenerate", "inputs": {"prompt": pergunta, "max_length": 8192 if pensar else 1024, "sampling_mode": "on", "sampling_mode.temperature": 0.7, "sampling_mode.top_k": 64,
                                                       "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05, "sampling_mode.seed": random.randrange(2**31),
                                                       "sampling_mode.presence_penalty": 0, "thinking": pensar, "use_default_template": True, "mtp": "auto", "clip": ["1", 0], "image": ["3", 0]}},
        "5": {"class_type": "PreviewAny", "inputs": {"source": ["4", 0]}},
    }
    mon.rotulo = modelo_rotulo
    r = rodar(g, 1500)
    return r, texto_llm(r) if r["status"] == "success" else ""


def pedir_plano(ideia, rodadas, imagem, mon):
    pergunta = f"""Look at <Picture 1>, a sequence from a live-action video: the three small frames on the right go from earlier (top) to later (bottom), and the large frame on the left is the current frame. Plan how this same continuous shot goes on from the large frame.

General idea from the director:
{ideia}

The video will be extended in exactly {rodadas} short segments of about 3.5 seconds each. It is one continuous shot with no cuts.
The camera is locked off. The person stays at the same distance from the camera with her whole head always in frame. She never walks towards the camera; any walking is a few small steps sideways.
Split any hard action into separate small visible steps, one per segment. Every action happens in front of her body, in full view; never behind her back.
Objects do not appear or vanish by themselves.

Reply with only one JSON object and nothing else, using these keys:
"appearance": one comma-separated line in English with what must stay the same: person, hair, every clothing item, background, lighting and camera framing, exactly as seen in the image. Do not include objects she holds.
"beats": a list of exactly {rodadas} strings. Each string is ONE simple physical action achievable in 3.5 seconds, each starting where the previous ended. Together they must fulfil the general idea, in order.
"sound": one short line with continuous ambient sounds."""
    motivo = ""
    for tent in range(3):
        r, t = chamar_llm(pergunta, imagem, "plano", mon)
        if r["status"] != "success":
            return r, None, f"{r['status']} {r['erro']}".strip()
        m = re.search(r"\{.*\}", t, re.S)
        try:
            p = json.loads(m.group(0))
            if isinstance(p["appearance"], str) and len(p["beats"]) == rodadas and all(isinstance(b, str) and b.strip() for b in p["beats"]) and isinstance(p["sound"], str):
                # Procura no texto, nao no JSON: json.dumps escreve quebra de linha como \n e o termo seguinte escaparia do \b
                achado = PROIBIDO.search(" ".join([p["appearance"], p["sound"], *p["beats"]]))
                if not achado:
                    return r, p, ""
                motivo = f"termo recusado: {achado.group(0)}"
            else:
                motivo = "formato errado"
            print(f"plano recusado (tentativa {tent + 1}): {motivo} | {t[:300]}", flush=True)
        except Exception as e:
            motivo = f"resposta ilegivel: {e}"
            print(f"plano ilegivel (tentativa {tent + 1}): {e} | {t[:300]}", flush=True)
    return r, None, motivo


def validar_rodada(t):
    campos = {}
    for c in ("OBSERVED", "DONE", "PLAN_STEP", "SUMMARY", "DETAIL", "SOUND"):
        m = re.search(rf"^\W*{c}\W*:\W*(.+?)(?=^\W*(?:OBSERVED|DONE|PLAN_STEP|SUMMARY|DETAIL|SOUND)\W*:|\Z)", t, re.S | re.M)
        if not m or not m.group(1).strip():
            return None, f"sem o campo {c}"
        campos[c] = re.sub(r"\s+", " ", m.group(1)).strip(" *")
    if len(campos["SUMMARY"].split()) > 70 or len(campos["DETAIL"].split()) > 120:
        return None, "texto longo demais"
    m = re.search(r"\d+", campos["PLAN_STEP"])
    campos["PASSO"] = int(m.group(0)) if m else 0
    junto = " ".join((campos["SUMMARY"], campos["DETAIL"], campos["SOUND"]))
    a = PROIBIDO.search(junto)
    if a:
        return None, f"termo recusado: {a.group(0)}"
    return campos, ""


def pedir_rodada(plano, ideia, n, total, historico, proximo, imagem, mon, aviso="", objetos=""):
    restantes = plano["beats"][proximo:]
    lista = "\n".join(f"{proximo + i + 1}. {b}" for i, b in enumerate(restantes)) or "none left"
    feito = "\n".join(f"- {h}" for h in historico[-4:]) or "- nothing yet"
    pergunta = f"""Look at <Picture 1>, a sequence from the end of the video so far: the three small frames on the right go from earlier (top) to later (bottom), and the large frame on the left is the LAST frame. Decide and write what happens in the next 3.5 seconds of the same continuous shot, starting from the large frame.

General idea: {ideia}
What must stay the same: {plano['appearance']}
This is segment {n} of {total}.
What was really seen in the video so far:
{feito}
Objects after the last segment: {objetos or 'not recorded yet'}
Plan steps still to do:
{lista}
{aviso}
First compare the image with the plan:
- Count what she is really holding and see where her hands and head are.
- Do the FIRST plan step still to do, unless the image clearly shows it already happened. Do not jump ahead and do not combine steps.
- If the image differs from what was planned, take the action that best moves from what you SEE towards that step.
- Objects stay consistent: count them in the image; nothing appears or vanishes, and she picks nothing new unless the step says so.
- If no plan steps are left, write a small natural continuation with what she has now.

Rules:
- Exactly one simple action, achievable in 3.5 seconds. No cuts, no change of place, no new people, no change of clothing.
- Locked-off camera. She stays at the same distance from the camera with her whole head in frame and never walks towards the camera.
- End with a clear body position, to make the next segment easy.

Reply in English with exactly these six labelled lines and nothing else:
OBSERVED: what she holds, where her hands and head are, and what changed across the frames.
DONE: which plan steps are already done or not needed, according to the image.
PLAN_STEP: the number of the plan step you are doing now, or 0 if none.
SUMMARY: one sentence with the place and the action of this segment, starting with "She".
DETAIL: two or three sentences describing the movement step by step and the final position.
SOUND: continuous ambient sounds, based on: {plano['sound']}"""
    motivo = ""
    for tent in range(3):
        r, t = chamar_llm(pergunta, imagem, f"prompt r{n}", mon, pensar=tent == 2)
        if r["status"] != "success":
            return r, None, f"{r['status']} {r['erro']}".strip()
        campos, motivo = validar_rodada(t)
        if campos:
            return r, campos, ""
        print(f"prompt recusado na rodada {n}: {motivo} | {t[:300]}", flush=True)
    return r, None, motivo


def analisar_trecho(passo, objetos, imagem, mon):
    """Descreve o que apareceu no trecho gerado; o plano so avanca com a acao confirmada."""
    pergunta = f"""Look at <Picture 1>, a sequence from a generated video segment: the three small frames on the right go from earlier (top) to later (bottom), and the large frame on the left is the final frame.
Requested action: "{passo}"
Objects before this segment: {objetos or 'not recorded'}

Describe only what you can really see, not what was requested. Be strict:
- Count the objects in the final frame.
- Say an object is under the clothing only if you saw it go there or see a clear round shape in the fabric. If it just left the picture or vanished, say it disappeared.

Reply in English with exactly these three labelled lines and nothing else:
HAPPENED: one sentence with what really happened across the frames.
OBJECTS: where each object is in the final frame.
STEP_DONE: YES if the requested action was really completed and visible, otherwise NO."""
    for _ in range(2):
        r, t = chamar_llm(pergunta, imagem, "analise", mon, pensar=False)
        if r["status"] != "success":
            break
        campos = {}
        for c in ("HAPPENED", "OBJECTS", "STEP_DONE"):
            m = re.search(rf"^\W*{c}\W*:\W*(.+?)(?=^\W*(?:HAPPENED|OBJECTS|STEP_DONE)\W*:|\Z)", t, re.S | re.M)
            if m and m.group(1).strip():
                campos[c] = re.sub(r"\s+", " ", m.group(1)).strip(" *")
        if len(campos) == 3:
            campos["FEITO"] = re.search(r"\byes\b", campos["STEP_DONE"], re.I) is not None
            return campos
    return {"HAPPENED": "", "OBJECTS": objetos, "STEP_DONE": "sem resposta", "FEITO": False}


def checar_quadro(imagem, mon):
    """Pergunta direta a LLM sobre o ultimo quadro; devolve True se a cabeca inteira aparece."""
    pergunta = """Look at <Picture 1>. Is the person's whole head, including the top of the head, chin and at least part of the face, visible inside the image?
Reply with only one word: YES or NO."""
    r, t = chamar_llm(pergunta, imagem, "checagem", mon, pensar=False)
    if r["status"] != "success":
        return None, t
    return (not re.search(r"\bno\b", t, re.I)), t.strip()[:40]


def montar_prompt(plano, c, tem_personagem=False, objetos=""):
    # Com personagem: Picture 1 fixa a pessoa e Picture 2 fixa cenario e luz. Sem ela, Picture 1 faz os dois papeis.
    cena = " The place, lighting and framing are the ones in <Picture 2>." if tem_personagem else ""
    return (f"subject_definitions:\n<Subject 1> is the woman in <Picture 1>.{cena}\n\n"
            f"summary:\nA single continuous shot from beginning to end. {c['SUMMARY']}\n\n"
            f"retention_analysis:\n[reference generation] Keep <Subject 1>'s face, hair and body identical to the reference. Keep the same {plano['appearance']} Locked-off camera, same distance, her whole head always in frame.{(' At the start of this shot: ' + objetos) if objetos else ''}\n\n"
            f"detailed_description:\n{c['DETAIL']}\n\n"
            f"overall_soundscape:\n{c['SOUND']}")


def grafo_geracao(a, video, inicio, prompt, prefixo, referencias, desvio=0):
    g = json.loads(GRAFO.read_text(encoding="utf-8"))
    # Sem estas opcoes o grafo fica como foi capturado da interface
    if a.modelo:
        g["171:4"]["inputs"]["unet_name"] = a.modelo
    if a.sampler:
        g["22:6"]["inputs"]["sampler_name"] = a.sampler
    if a.agendador:
        g["22:7"]["inputs"]["scheduler"] = a.agendador
    if a.lora or a.sem_lora:
        estado_lora = json.loads(g["554"]["inputs"]["LoraLoaderState"])
        estado_lora["loras"] = []
        for item in a.lora or []:
            nome, _, forca = item.rpartition("=")
            estado_lora["loras"].append({"name": nome, "on": True, "sm": float(forca), "sc": float(forca), "triggers": []})
        g["554"]["inputs"]["LoraLoaderState"] = json.dumps(estado_lora)
    item = {"kind": "video", "name": video, "file": video, "has_audio": True, "audio_mode": "paired", "enabled": True}
    if inicio > 0:
        item["trim"] = {"start": round(inicio, 3)}
    fotos = [{"kind": "picture", "name": r, "file": r, "enabled": True} for r in referencias]
    g["416"]["inputs"]["media_state"] = json.dumps(fotos + [item])
    g["365"]["inputs"]["prompt"] = prompt
    g["22:23"]["inputs"]["value"] = a.trecho
    g["22:8"]["inputs"]["value"] = a.passos
    g["22:9"]["inputs"].update(aspect_ratio=a.proporcao, megapixels=a.megapixels)
    g["297"]["inputs"]["value"] = a.sobreposicao
    g["16"]["inputs"]["seed"] = random.randrange(2**48) if a.semente is None else a.semente + desvio
    g["103"]["inputs"]["seed"] = random.randrange(2**48) if a.semente is None else a.semente + desvio + 1
    g["34"]["inputs"]["filename_prefix"] = prefixo
    return g


def ler_quadros(p):
    c = av.open(str(p))
    q = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]
    c.close()
    return q


def tem_audio(p):
    c = av.open(str(p))
    r = len(c.streams.audio) > 0
    c.close()
    return r


def salvar_quadro(q, destino):
    from PIL import Image
    Image.fromarray(q).save(destino)


def mosaico(q, destino):
    """Quadro final grande a esquerda e tres quadros anteriores a direita, de cima para baixo."""
    from PIL import Image
    h, w = q[0].shape[:2]
    H = 544
    W = int(H * w / h)
    pw = W // 3
    ph = H // 3
    F = Image.new("RGB", (W + pw, H))
    F.paste(Image.fromarray(q[-1]).resize((W, H)), (0, 0))
    for k, i in enumerate(np.linspace(0, len(q) - 1, 4).astype(int)[:3]):
        F.paste(Image.fromarray(q[i]).resize((pw, ph)), (W, k * ph))
    F.save(destino)


def medir_emenda(q, inicio_geracao, sobreposicao):
    """Salto de cor e de movimento em volta do fim da mistura."""
    claro = lambda a, b: float(np.mean([f.mean() for f in q[a:b]]))
    antes = claro(max(0, inicio_geracao - 8), max(1, inicio_geracao))
    fim_mistura = inicio_geracao + sobreposicao
    depois = claro(fim_mistura, min(len(q), fim_mistura + 8))
    d = [float(np.abs(q[i + 1].astype(np.int16) - q[i].astype(np.int16)).mean()) for i in range(len(q) - 1)]
    mediana = float(np.median(d)) or 1.0
    em_volta = d[max(0, fim_mistura - 4):min(len(d), fim_mistura + 6)]
    return {"salto_luz": round(abs(depois - antes), 2), "razao_mov": round(max(em_volta) / mediana, 2), "variacao_final": round(float(q[-1].std()), 1)}


def aprovada(m):
    return m["salto_luz"] <= 10 and m["razao_mov"] <= 4 and m["variacao_final"] >= 8


def cor_fundo(q):
    """Media por canal da faixa esquerda, onde costuma ficar o fundo parado."""
    largura = q[0].shape[1] // 3
    return np.mean([f[:, :largura].reshape(-1, 3).mean(axis=0) for f in q], axis=0)


def corrigir_cor(arquivo, q, inicio_geracao, alvo, destino, medir=cor_fundo):
    """Aplica uma rampa de ganho no trecho gerado para o fim voltar a cor de referencia.
    O ganho comeca em 1, entao a emenda com o trecho anterior nao ganha salto."""
    atual = medir(q[-8:])
    ganho = np.full(3, float(np.clip(alvo.mean() / max(float(atual.mean()), 1.0), 0.85, 1.2)))
    n = len(q) - inicio_geracao
    saida = []
    for i, f in enumerate(q):
        if i < inicio_geracao:
            saida.append(f)
            continue
        fator = 1 + (ganho - 1) * ((i - inicio_geracao + 1) / n)
        saida.append(np.clip(f.astype(np.float32) * fator, 0, 255).astype(np.uint8))
    h, w = q[0].shape[:2]
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
           "-i", str(arquivo), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", str(destino)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in saida:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falhou ao corrigir a cor")
    return saida, [round(float(x), 3) for x in ganho]


def juntar(pasta, estado, alvo):
    """Une os trechos sem repetir a sobreposicao e corta na duracao pedida."""
    rs = estado["rodadas"]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ent, filtros, rotulos, soma = [], [], [], 0
    for i, r in enumerate(rs):
        a, b = r["pular"], r["total"] - (0 if i == len(rs) - 1 else r["sobreposicao"])
        b = min(b, a + alvo - soma)
        if b <= a:
            break
        ent += ["-i", str(caminhos.abrir(pasta, r["arquivo"]))]
        k = len(rotulos)
        filtros.append(f"[{k}:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,format=yuv420p[v{k}];[{k}:a]atrim=start={a / FPS:.4f}:end={b / FPS:.4f},asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo[a{k}]")
        rotulos.append(f"[v{k}][a{k}]")
        soma += b - a
    filtro = ";".join(filtros) + ";" + "".join(rotulos) + f"concat=n={len(rotulos)}:v=1:a=1[v][a]"
    destino = pasta / "final.mp4"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"] + ent + ["-filter_complex", filtro, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", str(destino)]
    subprocess.run(cmd, check=True)
    print(f"final: {destino} | {soma} quadros | {soma / FPS:.2f} s", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--projeto", required=True)
    p.add_argument("--video")
    p.add_argument("--ideia")
    p.add_argument("--duracao", type=float, default=30)
    p.add_argument("--trecho", type=float, default=4, help="Video Length do fluxo; inclui a sobreposicao")
    p.add_argument("--sobreposicao", type=int, default=22, choices=(5, 22, 39, 56))
    p.add_argument("--passos", type=int, default=6)
    p.add_argument("--megapixels", type=float, default=0.5)
    p.add_argument("--proporcao", default="16:9 (Widescreen)")
    p.add_argument("--contexto", type=float, default=2.0, help="segundos finais usados como entrada de cada rodada")
    p.add_argument("--tentativas", type=int, default=3)
    p.add_argument("--personagem", help="imagem da personagem na pasta input do ComfyUI, usada como <Picture 1> em toda rodada")
    p.add_argument("--quadro-ref", type=float, default=0.66, help="posicao do quadro de referencia no video inicial, de 0 a 1")
    p.add_argument("--modelo", help="arquivo em diffusion_models; sem esta opcao, usa o do fluxo")
    p.add_argument("--lora", action="append", metavar="ARQUIVO=FORCA", help="substitui as LoRAs do fluxo; pode repetir")
    p.add_argument("--sem-lora", action="store_true", help="tira as LoRAs do fluxo")
    p.add_argument("--sampler", help="sem esta opcao, usa o do fluxo")
    p.add_argument("--agendador", help="scheduler; sem esta opcao, usa o do fluxo")
    p.add_argument("--semente", type=int, help="fixa a semente de cada rodada; sem esta opcao, e aleatoria")
    p.add_argument("--so-plano", action="store_true")
    p.add_argument("--so-juntar", action="store_true")
    p.add_argument("--ate-rodada", type=int, default=0)
    a = p.parse_args()

    pasta = config.PROJETOS / a.projeto
    pasta.mkdir(parents=True, exist_ok=True)
    arq_estado = pasta / "estado.json"
    gen = quadros_por_duracao(a.trecho)
    novos = gen - a.sobreposicao
    alvo = round(a.duracao * FPS)

    if arq_estado.exists():
        estado = json.loads(arq_estado.read_text(encoding="utf-8"))
        print(f"retomando: {len(estado['rodadas'])} rodadas prontas", flush=True)
    else:
        if not a.video or not a.ideia:
            sys.exit("Projeto novo: informe --video e --ideia")
        origem = Path(a.video)
        if not tem_audio(origem):
            sys.exit("O video precisa ter audio; o fluxo salvo espera a faixa original.")
        q = ler_quadros(origem)
        copia = config.ENTRADA / f"cont_{a.projeto}_r00.mp4"
        shutil.copy2(origem, copia)
        mosaico(q, config.ENTRADA / f"cont_{a.projeto}_r00.png")
        salvar_quadro(q[min(len(q) - 1, int(len(q) * a.quadro_ref))], config.ENTRADA / f"cont_{a.projeto}_ref.png")
        if a.personagem and not (config.ENTRADA / a.personagem).exists():
            sys.exit(f"Imagem da personagem nao encontrada em input: {a.personagem}")
        estado = {"ideia": a.ideia, "origem": caminhos.guardar_envio(origem), "quadros_origem": len(q), "personagem": a.personagem, "plano": None, "rodadas": [], "tentativas_reprovadas": 0}
        caminhos.gravar_json(arq_estado, estado)

    if a.so_juntar:
        juntar(pasta, estado, alvo)
        return

    f0 = estado["quadros_origem"]
    total_rodadas = max(1, math.ceil((alvo - (f0 - a.sobreposicao + gen)) / novos) + 1)
    print(f"{total_rodadas} rodadas | {gen} quadros por rodada, {novos} novos | alvo {alvo} quadros", flush=True)

    mon = Monitor(pasta / "gpu.csv")
    mon.start()

    def checar(r, etapa):
        if mon.quente:
            print(f"PARADO por temperatura em {etapa}", flush=True)
            sys.exit(5)
        if r["status"] in ("servidor caiu",):
            print(f"SERVIDOR CAIU em {etapa}: {r['erro'][:300]}", flush=True)
            sys.exit(3)

    if not estado["plano"]:
        ini = time.time()
        r, plano, motivo = pedir_plano(estado["ideia"], total_rodadas, f"cont_{a.projeto}_r00.png", mon)
        checar(r, "plano")
        if not plano:
            print(f"FALHA no plano: {motivo[:500]}", flush=True)
            sys.exit(4)
        estado["plano"] = plano
        caminhos.gravar_json(arq_estado, estado)
        (pasta / "plano.json").write_text(json.dumps(plano, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"plano em {time.time() - ini:.0f} s:\n{json.dumps(plano, ensure_ascii=False, indent=1)}", flush=True)
    if a.so_plano:
        return

    while len(estado["rodadas"]) < total_rodadas:
        n = len(estado["rodadas"]) + 1
        if a.ate_rodada and n > a.ate_rodada:
            print(f"parado na rodada {a.ate_rodada} como pedido", flush=True)
            return
        ant = estado["rodadas"][-1] if estado["rodadas"] else None
        video = f"cont_{a.projeto}_r{n - 1:02d}.mp4"
        imagem = f"cont_{a.projeto}_r{n - 1:02d}.png"
        personagem = estado.get("personagem")
        referencias = ([personagem] if personagem else []) + [f"cont_{a.projeto}_ref.png"]
        inicio = max(0.0, ant["total"] / FPS - a.contexto) if ant else 0.0
        historico = [r.get("aconteceu") or r["summary"] for r in estado["rodadas"]]
        objetos = ant.get("objetos", "") if ant else ""
        proximo = max([r.get("passo", 0) for r in estado["rodadas"]] + [0])
        melhor = None
        aviso = ""
        for tent in range(1, a.tentativas + 1):
            ini = time.time()
            r, campos, motivo = pedir_rodada(estado["plano"], estado["ideia"], n, total_rodadas, historico, proximo, imagem, mon, aviso, objetos)
            checar(r, f"prompt r{n}")
            if not campos:
                print(f"FALHA no prompt da rodada {n}: {motivo[:400]}", flush=True)
                sys.exit(4)
            s_llm = time.time() - ini
            prompt = montar_prompt(estado["plano"], campos, bool(personagem), objetos)
            mon.rotulo = f"video r{n}"
            r = rodar(grafo_geracao(a, video, inicio, prompt, f"continuacao/{a.projeto}/r{n:02d}_t{tent}", referencias, n * 100 + tent * 2), 1800)
            checar(r, f"video r{n}")
            if r["status"] != "success":
                print(f"FALHA na geracao r{n} t{tent}: {r['status']} {r['erro'][:700]}", flush=True)
                sys.exit(4)
            nome = [i for i in r["saidas"]["34"]["gifs"] if i["filename"].endswith("-audio.mp4")][0]
            arq = config.SAIDA / nome.get("subfolder", "") / nome["filename"]
            q = ler_quadros(arq)
            pular = len(q) - gen
            if "cor_alvo" not in estado:
                estado["cor_alvo"] = [float(x) for x in cor_fundo(q[max(0, pular - 16):pular])]
            m = medir_emenda(q, pular, a.sobreposicao)
            quadro_qc = f"cont_{a.projeto}_qc.png"
            salvar_quadro(q[-1], config.ENTRADA / quadro_qc)
            cabeca, resposta = checar_quadro(quadro_qc, mon)
            ok = aprovada(m) and cabeca is not False
            corrigido = pasta / f"r{n:02d}_t{tent}_cor.mp4"
            saida, ganho = corrigir_cor(arq, q, pular, np.array(estado["cor_alvo"]), corrigido)
            beats = estado["plano"]["beats"]
            candidato = proximo + 1
            pedido = beats[candidato - 1] if candidato <= len(beats) else campos["SUMMARY"]
            trecho = saida[pular + a.sobreposicao:]
            quadro_seq = f"cont_{a.projeto}_seq.png"
            mosaico(trecho, config.ENTRADA / quadro_seq)
            analise = analisar_trecho(pedido, objetos, quadro_seq, mon)
            if PROIBIDO.search(analise["OBJECTS"]) or PROIBIDO.search(analise["HAPPENED"]):
                print(f"analise com termo recusado, descartada: {analise['OBJECTS'][:120]}", flush=True)
                analise.update(HAPPENED="", OBJECTS=objetos)
            passo = candidato if analise["FEITO"] and candidato <= len(beats) else proximo
            confirmou = analise["STEP_DONE"][:12]
            dados = {"rodada": n, "tentativa": tent, "arquivo": caminhos.guardar(pasta, corrigido), "bruto": str(arq), "total": len(q), "pular": pular if ant else 0, "inicio_geracao": pular, "sobreposicao": a.sobreposicao,
                     "emenda": m, "cabeca": cabeca, "resposta_cabeca": resposta, "ganho_cor": ganho, "aprovada": ok, "passo": passo, "confirmou_passo": confirmou, "aconteceu": analise["HAPPENED"], "objetos": analise["OBJECTS"], "s_llm": round(s_llm), "s_video": r["segundos"], "pico_vram": r["pico_vram"], "temp_max": r["temp_max"],
                     "observed": campos["OBSERVED"], "done": campos["DONE"], "passo_llm": campos["PLAN_STEP"], "summary": campos["SUMMARY"], "prompt": prompt}
            with (pasta / "rodadas.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(dados, ensure_ascii=False) + "\n")
            print(f"rodada {n} t{tent}: {r['segundos']} s video + {s_llm:.0f} s LLM | {m} | cabeca {resposta} | ganho {ganho[0]} | passo {passo} ({confirmou}) | {'ok' if ok else 'REPROVADA'} | PEDIU: {campos['SUMMARY'][:110]} | VIU: {analise['HAPPENED'][:140]} | OBJETOS: {analise['OBJECTS'][:110]}", flush=True)
            chave = (ok, cabeca is not False, -m["salto_luz"] - m["razao_mov"])
            if melhor is None or chave > melhor[0]:
                melhor = (chave, dados, trecho)
            if ok:
                break
            aviso = "The previous attempt failed: the motion changed too abruptly or her head left the frame. Keep the motion gentle, stay at the same distance and keep her whole head in frame.\n"
        _, dados, trecho_final = melhor
        if not dados["aprovada"]:
            estado["tentativas_reprovadas"] += 1
            print(f"rodada {n}: nenhuma tentativa aprovada; seguindo com a melhor (t{dados['tentativa']})", flush=True)
        shutil.copy2(caminhos.abrir(pasta, dados["arquivo"]), config.ENTRADA / f"cont_{a.projeto}_r{n:02d}.mp4")
        mosaico(trecho_final, config.ENTRADA / f"cont_{a.projeto}_r{n:02d}.png")
        estado["rodadas"].append(dados)
        caminhos.gravar_json(arq_estado, estado)
        with (pasta / "prompts.md").open("a", encoding="utf-8") as f:
            f.write(f"## Rodada {n} (tentativa {dados['tentativa']})\n\nViu: {dados['observed']}\n\nJa feito: {dados['done']}\n\nPasso: {dados['passo_llm']}\n\nAconteceu: {dados['aconteceu']}\n\nObjetos: {dados['objetos']}\n\nConfirmou: {dados['confirmou_passo']}\n\n```text\n{dados['prompt']}\n```\n\n")

    juntar(pasta, estado, alvo)
    mon.fim.set()


if __name__ == "__main__":
    main()
