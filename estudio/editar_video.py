"""Editar video (aba Editar video): muda objetos, cenario, clima ou luz de um trecho e mantem as pessoas, o movimento, a
camera e o som. Usa o Viggle Remake Edit (LoRA viggle_remake_edit sobre o H3 FL2VA Pruned), no ComfyUI do estudio
(troca_viggle.py, modo "edit"); a receita veio do WanGP, que nao e mais chamado (22/11/2026).

O Viggle recebe o trecho, UM quadro dele ja pintado com a mudanca (pinado: o video passa exatamente por esse quadro) e um
roteiro de 6 partes em ingles. Testado em 18/11/2026 (projetos/teste_viggle_edit): 5,2 s de praia ensolarada viraram
tempestade em 413 s (358 s de amostragem), pico de 8,3 GB, 305 W, 72 graus, sem queda. O Viggle copia fielmente a
pintura, defeitos incluidos: por isso a pagina mostra 2 pinturas do Klein e o usuario escolhe antes de gerar.

Quem escreve em ingles e a IA de visao do estudio (continuar_video.chamar_llm, Qwen 3.5 9B no ComfyUI): o pedido para o
Klein, a partir do pedido em portugues, e o roteiro, olhando o quadro original e o pintado. Se ela falhar, valem o pedido
com a clausula fixa e o roteiro fixo daqui.
"""
import json, re, shutil, sys, time, types
from pathlib import Path

from PIL import Image

# A tarefa roda "python -I editar_video.py": o -I nao poe a pasta do script no caminho de importacao
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, entrada, entrada_temp
from comfy_api import rodar
from continuar_video import chamar_llm
from envio import examinar_video
import troca_viggle
from troca_wangp import FPS, MAX_QUADROS, PASSOS_VIGGLE, conferir_comfy, contar_quadros, ffmpeg, montar_final, mudar_etapa, quadros_render, tamanho, tempo

QUALIDADES = {"rapido": 0.4, "melhor": 0.5}
QUADRO_PADRAO = 24          # 1 s depois do inicio do trecho (o teste de 18/11 pintou o 25o quadro)
OPCOES_PINTURA = 2
DIAS_TEMPORARIOS = 2
TOLERANCIA_PROPORCAO = 0.03
PREFIXOS_TEMPORARIOS = ("editar_pintura_", "editar_quadro_", "editar_trecho_", "editar_par_")
SECOES = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music")
CLAUSULA_KLEIN = ("Keep the people exactly the same: their faces, bodies, pose, clothes and expression. Keep the framing, the camera "
                  "angle and everything not mentioned exactly as in the image.")


def tamanho_editar(largura, altura, qualidade):
    """O tamanho da geracao na proporcao do proprio video (vertical fica vertical), com os megapixels da qualidade."""
    return tamanho(f"{largura}:{altura}", QUALIDADES[qualidade])


def _uma_linha(texto):
    return " ".join(str(texto).split())


def _sem_dim(texto):
    # O WanGP avisa: "dim" no prompt escurece o video todo
    texto = re.sub(r"\bdimly[ -]lit\b", "low-light", texto, flags=re.I)
    texto = re.sub(r"\bdimly\b", "darkly", texto, flags=re.I)
    return re.sub(r"\bdim\b", "dark", texto, flags=re.I)


def pedido_klein_reserva(pedido):
    """Sem a IA: o pedido do usuario como veio, com a clausula fixa que segura as pessoas e o enquadramento."""
    return f"{_uma_linha(pedido).rstrip('.')}. {CLAUSULA_KLEIN}"


def pergunta_pedido_klein(pedido):
    return f"""Look at <Picture 1>, a frame from a live-action video. The user wants to change something in this video and wrote, possibly in Portuguese:
"{_uma_linha(pedido)}"

Write ONE image-editing instruction in English for an image editor that will paint this exact frame with the change. Describe concretely what the frame must show after the change (what appears, disappears or changes, its look, colours and light), based on what you see in <Picture 1>. Do not describe the people except to keep them. End the instruction with exactly this sentence:
{CLAUSULA_KLEIN}

Reply with only the instruction, in one paragraph, with no quotes and nothing else."""


def pergunta_roteiro(pedido, pedido_klein, quadro, duracao):
    return f"""<Picture 1> holds two images side by side: on the LEFT, a frame of a live-action source video; on the RIGHT, the same frame already edited with the change the user wants. The user's request, possibly in Portuguese: "{_uma_linha(pedido)}". The edit applied to the frame: "{_uma_linha(pedido_klein)}".

Write the prompt for a video model that will edit the whole source video (<Video 1>) so that it shows this change, with objects, setting, weather, light or style changed while the people stay. In your prompt, <Picture 1> means ONLY the edited frame on the right: it is the frame of the target video at {tempo(quadro)}. The video lasts {duracao:.3f} seconds; write every time as MM:SS.mmm, from 00:00.000 to at most 00:{duracao:06.3f}.

Output exactly these six sections in this order, a blank line between them, nothing before the first and no Markdown. Each name is followed by a colon and a line break. No blank lines inside a section.

subject_definitions:
First, always, this exact line: <Video 1> is the source video for the target video edit.
Then this exact line: <Picture 1> is a frame of the target video, exactly as the target video shows it at that moment.
Then one line per subject, each starting with "<Subject N> is the": one per thing removed or replaced, as it is in <Video 1> (for example: <Subject 1> is the clear blue sky in <Video 1>: bright and cloudless above the sea.); one per new thing, as it appears in the target video; one for the setting and one for each person who stays, each with enough looks to tell it apart from similar things in the frame.

summary:
[video editing] The target video is an edited version of <Video 1>. Then what the target video shows as it plays, with what is gone, new or changed, "with exactly the same framing, motion and timing as <Video 1>".

retention_analysis:
<Video 1> (source video editing): fully_preserved - the framing and camera movement, the people, the place and every part the change does not touch are copied frame for frame.
<Picture 1> (target keyframe): fully_preserved - the target video passes through this exact frame.
Then one line per subject: <Subject 1> (appears in [Shot 1]): removed - <it is gone in every frame, and what is visible where it stood>, or replaced - <what it becomes> by <Subject 2>, new - <what appears and where>, or fully_preserved - <what stays>.

detailed_description:
First one line for the style the right image shows: realistic footage, the light and the colours. A dark place is in "low light".
Then a paragraph that starts with "[Shot 1] A " and the framing and the place as the right image shows them, for example: "[Shot 1] A medium shot of a young man standing in shallow water at a beach under dark storm clouds." Call the changed things by their <Subject N> label. Then one sentence that starts with "At {tempo(quadro)}, exactly as in <Picture 1>, " and says what the frame shows of the change, written once. Never invent movements, camera moves or events: they come from <Video 1>. For a removal, say what is visible where the thing stood and repeat that it is absent.

overall_soundscape:
The soundtrack of <Video 1>, unchanged.

non_diegetic_music:
N/A

Use English, plain ASCII punctuation and the present tense. Never use the words "dim" or "dimly". Return only the six sections."""


def limpar_roteiro(texto):
    """O roteiro que a IA (ou o usuario) escreveu, sem o raciocinio e as cercas de codigo, sem "dim". None se faltar uma
    das 6 secoes ou se estiverem fora de ordem."""
    texto = (texto or "").split("</think>")[-1]
    texto = "\n".join(linha for linha in texto.splitlines() if not linha.strip().startswith("```")).strip()
    if not texto:
        return None
    posicoes = []
    for s in SECOES:
        m = re.search(rf"(?m)^{s}:", texto)
        if not m:
            return None
        posicoes.append(m.start())
    if posicoes != sorted(posicoes) or posicoes[0] != 0:
        return None
    return _sem_dim(texto)


def roteiro_reserva(pedido_klein, quadro, duracao):
    """O roteiro fixo, quando a IA nao escreve um que preste: a mudanca vem da pintura e do pedido do Klein."""
    mudanca = _sem_dim(_uma_linha(pedido_klein))
    secoes = [
        "subject_definitions:\n"
        "<Video 1> is the source video for the target video edit.\n"
        "<Picture 1> is a frame of the target video, exactly as the target video shows it at that moment.\n"
        f"<Subject 1> is the change in the target video, exactly as <Picture 1> shows it: {mudanca}\n"
        "<Subject 2> is everything else from <Video 1>: the people, their faces, clothes and movements, and the place.",
        "summary:\n"
        f"[video editing] The target video is an edited version of <Video 1>, changed as <Picture 1> shows: {mudanca} "
        "Everything else stays, with exactly the same framing, motion and timing as <Video 1>.",
        "retention_analysis:\n"
        "<Video 1> (source video editing): fully_preserved - the framing and camera movement, the people, the place and every part the change does not touch are copied frame for frame.\n"
        "<Picture 1> (target keyframe): fully_preserved - the target video passes through this exact frame.\n"
        "<Subject 1> (appears in [Shot 1]): new - the change is visible in every frame, exactly as in <Picture 1>.\n"
        "<Subject 2> (appears in [Shot 1]): fully_preserved - the people, their faces, clothes and movements, and the place stay as in <Video 1>.",
        "detailed_description:\n"
        "Realistic footage with the light and colours of <Picture 1>.\n"
        f"[Shot 1] The scene of <Video 1> plays from 00:00.000 to 00:{duracao:06.3f}. At {tempo(quadro)}, exactly as in <Picture 1>, "
        "<Subject 1> is visible, and it stays the same in every frame while <Subject 2> moves exactly as in <Video 1>.",
        "overall_soundscape:\nThe soundtrack of <Video 1>, unchanged.",
        "non_diegetic_music:\nN/A",
    ]
    return "\n\n".join(secoes)


def _perguntar(pergunta, imagem, rotulo):
    """A IA de visao do estudio (no ComfyUI). Devolve o texto, sem o raciocinio; "" se ela falhar."""
    try:
        r, texto = chamar_llm(pergunta, imagem, rotulo, types.SimpleNamespace(rotulo=None), pensar=False)
    except Exception as e:
        print(f"AVISO: a IA de visão falhou ({e}).", flush=True)
        return ""
    if r.get("status") != "success":
        return ""
    return (texto or "").split("</think>")[-1].strip()


SEGUNDOS_TRECHO = 15  # uma janela do Viggle tem no maximo 345 quadros (14,4 s a 24 fps)


def cortar_trecho(origem, destino, inicio):
    """O trecho a partir de `inicio`, ja a 24 fps e com no maximo SEGUNDOS_TRECHO, com o audio. O WanGP le o guia a 24 fps
    e conta frames_positions nele: cortando aqui a 24 fps, o quadro pintado (tirado deste mesmo corte) e o quadro pinado
    sao o mesmo momento tambem num video de celular a 30 ou 60 fps. Usado pela pintura e pela geracao."""
    ffmpeg("-ss", f"{inicio:.3f}", "-i", str(origem), "-t", str(SEGUNDOS_TRECHO), "-map", "0:v:0", "-map", "0:a?", "-vf", f"fps={FPS}",
           "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(destino))


def extrair_quadro(video, inicio, quadro, codigo):
    """Corta o trecho do mesmo jeito que a geracao (cortar_trecho) e grava o quadro `quadro` dele na entrada do ComfyUI,
    para a numeracao bater com frames_positions. Devolve o nome do PNG."""
    trecho = entrada.novo(f"editar_trecho_{codigo}.mp4")
    cortar_trecho(video, trecho, inicio)
    nome = f"editar_quadro_{codigo}.png"
    for antigo in entrada.onde(nome):  # o quadro de antes (em envios ou na raiz) nao pode passar pelo novo se o ffmpeg falhar
        antigo.unlink(missing_ok=True)
    destino = entrada.novo(nome)
    ffmpeg("-i", str(trecho), "-vf", f"select=eq(n\\,{quadro})", "-frames:v", "1", str(destino))
    if not destino.is_file():
        raise RuntimeError(f"o vídeo não tem o quadro {quadro + 1} a partir do início do trecho")
    return nome


def escrever_pedido_klein(pedido, quadro_png):
    """O pedido do Klein em ingles, escrito pela IA olhando o quadro. (texto, True) ou, se ela falhar, (reserva, False)."""
    texto = _perguntar(pergunta_pedido_klein(pedido), quadro_png, "pedido do Klein").strip().strip('"').strip()
    if not texto or CLAUSULA_KLEIN not in texto:
        return pedido_klein_reserva(pedido), False
    return _uma_linha(texto), True


def pintar(quadro_png, pedido_klein, codigo, largura, altura, sementes):
    """O Klein (klein_edit, 2 MP) pinta o quadro uma vez por semente. Cada pintura vai reduzida para largura x altura na
    entrada do ComfyUI. Devolve os nomes. RuntimeError se o ComfyUI falhar."""
    import texto_para_imagem as t2i
    m = t2i.MODELOS_TEXTO["klein_edit"]
    nomes = []
    for semente in sementes:
        g = t2i.grafo_edicao_klein({"partida": quadro_png, "prompt": pedido_klein, "passos": m["passos"]}, m, semente, f"editar/{codigo}_{semente}")
        r = rodar(g, 1800)
        if r["status"] != "success":
            raise RuntimeError(f"{r['status']} {str(r.get('erro', ''))[:300]}".strip())
        imagens = [im for s in r["saidas"].values() for im in s.get("images", [])]
        if not imagens:
            raise RuntimeError("o ComfyUI não devolveu a imagem")
        origem = config.SAIDA / imagens[0].get("subfolder", "") / imagens[0]["filename"]
        nome = f"editar_pintura_{codigo}_{semente}.png"
        with Image.open(origem) as im:
            im.convert("RGB").resize((largura, altura), Image.LANCZOS).save(entrada.novo(nome))
        nomes.append(nome)
    return nomes


def escrever_roteiro(pedido, pedido_klein, quadro_png, pintura_png, quadro, duracao, codigo, dono=None):
    """O roteiro de 6 partes, escrito pela IA olhando o quadro original (esquerda) e o pintado (direita) numa imagem so.
    (roteiro, True) ou, se ela falhar ou escrever algo fora do formato, (roteiro fixo, False). Com `dono` (a geracao de um
    projeto), a imagem junta vai para os temporarios dele (entrada_temp); sem ele (a pagina), fica em input/estudio/envios."""
    arq_par, par = entrada_temp.arquivo(dono, f"editar_par_{codigo}.png") if dono else (entrada.novo(f"editar_par_{codigo}.png"), f"editar_par_{codigo}.png")
    with Image.open(entrada.caminho(quadro_png)) as a, Image.open(entrada.caminho(pintura_png)) as b:
        a, b = a.convert("RGB"), b.convert("RGB").resize(a.size, Image.LANCZOS)
        junto = Image.new("RGB", (a.width * 2, a.height))
        junto.paste(a, (0, 0))
        junto.paste(b, (a.width, 0))
        junto.save(arq_par)
    roteiro = limpar_roteiro(_perguntar(pergunta_roteiro(pedido, pedido_klein, quadro, duracao), par, "roteiro"))
    if roteiro is None:
        return roteiro_reserva(pedido_klein, quadro, duracao), False
    return roteiro, True


def _e_link(p):
    return p.is_symlink() or p.is_junction()


def apagar_temporarios(agora=None):
    """Apaga as pinturas, quadros e trechos da aba que ficaram sem projeto ha mais de DIAS_TEMPORARIOS dias (na entrada do
    ComfyUI e em output/editar). Chamado quando o servidor do estudio abre. Devolve o que apagou."""
    limite = (agora or time.time()) - DIAS_TEMPORARIOS * 86400
    apagadas = []
    # Na entrada: em input/estudio/envios (os novos) e na raiz (os de antes)
    lugares = [(entrada.pasta_envios(), PREFIXOS_TEMPORARIOS), (config.ENTRADA, PREFIXOS_TEMPORARIOS), (config.SAIDA / "editar", ("",))]
    for pasta, prefixos in lugares:
        if not pasta.is_dir() or _e_link(pasta):
            continue
        raiz = pasta.resolve()
        for f in pasta.iterdir():
            if (f.name.startswith(prefixos) and f.is_file() and not _e_link(f) and f.resolve().parent == raiz
                    and f.stat().st_mtime < limite):
                f.unlink()
                apagadas.append(f)
    return apagadas


def gerar(pasta, p, video, semente, mon, progresso, rodar=rodar, acompanhar=None):
    """Escreve o roteiro (se faltar), roda o Viggle Remake Edit no ComfyUI (troca_viggle.py, modo "edit") e grava final.mp4 e
    comparativo.mp4. Devolve (medidas, roteiro). Poe em p["proporcao"] a proporcao do video (o ESRGAN do terminar usa).
    Sai com 4 se faltar a LoRA, o no ou quadros, ou se a geracao falhar; com 3 se o ComfyUI cair e com 5 se a placa
    esquentar demais. `acompanhar` e o do trocar_personagem (o passo a passo do ComfyUI)."""
    falta = troca_viggle.preparar("edit")
    if falta:
        print(f"FALHA na geracao: {falta}", flush=True)
        sys.exit(4)
    origem = entrada.caminho(video)
    pedidos = round(p["duracao"] * FPS)
    render = quadros_render(pedidos, contar_quadros(origem))
    if render is None:
        print(f"FALHA na geracao: o Viggle Remake precisa de pelo menos 90 quadros ({90 / FPS:.2f} s) de vídeo a partir do início do trecho.", flush=True)
        sys.exit(4)
    pedidos = min(pedidos, render)
    info = examinar_video(origem)
    p["proporcao"] = f"{info['largura']}:{info['altura']}"
    largura, altura = tamanho_editar(info["largura"], info["altura"], p.get("qualidade", "rapido"))
    pintado = pasta / "pintado.png"
    quadro = int(p["quadro"])
    pedido_klein = p.get("pedido_klein") or pedido_klein_reserva(p["pedido"])
    print(f"ComfyUI: Viggle Remake Edit, {render} quadros a {largura}x{altura} (corta em {pedidos}), pintura no quadro {quadro + 1}", flush=True)

    roteiro = p.get("roteiro") or ""
    if roteiro:
        print("roteiro: o escrito na página", flush=True)
    else:
        codigo = pasta.name
        # O quadro, a pintura e o par vao para os temporarios do projeto (entrada_temp)
        arq_quadro, quadro_png = entrada_temp.arquivo(codigo, f"editar_quadro_{codigo}.png")
        arq_pintura, pintura_png = entrada_temp.arquivo(codigo, f"editar_pintura_{codigo}_usada.png")
        ffmpeg("-i", str(origem), "-vf", f"select=eq(n\\,{quadro})", "-frames:v", "1", str(arq_quadro))
        shutil.copyfile(pintado, arq_pintura)
        roteiro, ia = escrever_roteiro(p["pedido"], pedido_klein, quadro_png, pintura_png, quadro, pedidos / FPS, codigo, dono=codigo)
        print("roteiro escrito pela IA" if ia else "AVISO: a IA não escreveu o roteiro; vai o roteiro fixo", flush=True)

    trab = pasta / "viggle"
    trab.mkdir(exist_ok=True)
    gerado = trab / "viggle.mp4"
    (pasta / "prompt.txt").write_text(f"Pedido: {p['pedido']}\n\nPintura (Klein):\n{pedido_klein}\n\nViggle Remake Edit:\n{roteiro}\n", encoding="utf-8")

    inicio = time.time()
    mudar_etapa(progresso, "viggle", 0, PASSOS_VIGGLE)
    # Uma janela so: o video como referencia, a pintura como referencia e presa no quadro escolhido, o som original fixo
    r, video_gerado = troca_viggle.gerar(pasta.name, video, [(quadro, pintado)], roteiro, largura, altura, render, semente, rodar, acompanhar,
                                         lambda passo: mudar_etapa(progresso, "viggle", passo, PASSOS_VIGGLE), modo="edit")
    if r["status"] == "success" and (video_gerado is None or not video_gerado.is_file()):
        r = {**r, "status": "sem vídeo", "erro": "o ComfyUI não informou o vídeo gerado"}
    conferir_comfy(r, mon, "o Viggle Remake Edit")
    shutil.copy2(video_gerado, gerado)
    mudar_etapa(progresso, "montar")
    montar_final(gerado, origem, pasta, pedidos, altura)
    return {"segundos": round(time.time() - inicio), "pico_vram": r["pico_vram"], "temp_max": r["temp_max"]}, roteiro


def main():
    import argparse, random
    import caminhos
    from continuar_video import Monitor
    from trocar_personagem import Progresso, terminar
    a = argparse.ArgumentParser()
    a.add_argument("--projeto", required=True)
    a = a.parse_args()
    pasta = config.PROJETOS / a.projeto
    p = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
    arq_estado = pasta / "estado.json"
    estado = json.loads(arq_estado.read_text(encoding="utf-8"))
    arq_video, video = entrada_temp.arquivo(a.projeto, f"editar_{a.projeto}.mp4")
    inicio = float(p.get("inicio") or 0)
    # O trecho escolhido na pagina, a 24 fps: daqui em diante tudo le o video como se comecasse ali (o mesmo corte da pintura)
    cortar_trecho(caminhos.abrir_envio(estado["origem"]), arq_video, inicio)
    semente = random.randrange(2**48) if p.get("semente") is None else p["semente"]
    print(f"semente {semente} | {p['duracao']} s | qualidade {p.get('qualidade')} | ESRGAN {'sim' if p.get('esrgan') else 'não'} | pedido: {p['pedido']}", flush=True)
    mon = Monitor(pasta / "gpu.csv")
    mon.start()
    progresso = Progresso(pasta / "progresso.json", False, mon, etapa="roteiro")
    from trocar_personagem import acompanhar
    r, roteiro = gerar(pasta, p, video, semente, mon, progresso, acompanhar=acompanhar)
    mon.fim.set()
    terminar(pasta, p, r, roteiro, progresso, semente, estado, arq_estado)


if __name__ == "__main__":
    main()
