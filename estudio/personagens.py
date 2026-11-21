"""Biblioteca de personagens (ideia do Imagination Studio, "Consistent characters"): um personagem criado uma vez, com a
foto de frente e uma folha de ângulos, reaproveitado na troca e no Imagem para vídeo.

Cada personagem fica em personagens/<id>/ (na raiz do repositório, fora do git, como projetos/): ficha.json e uma imagem
por ângulo (frente.png, tres_quartos.png, perfil.png, costas.png).

Os ângulos são feitos com o Klein (o mesmo grafo do Editar imagem): ~45 s cada na 3080, rosto nítido e fiel. O
Turnaround do H3 (5 vistas numa geração) foi testado em 17/11/2026 e a 512 deforma o rosto (cada vista tem o corpo
inteiro em 512 px); ver PLANO_PERSONAGENS.md.

Uso: python -I personagens.py --personagem <id>   (gera os ângulos que faltam; é o que a fila do estúdio roda)
"""
import argparse, json, re, shutil, sys, time, unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, ficha_personagem

PASTA = config.WORKFLOWS / "personagens"
FICHA = "ficha.json"
FOLHA = ficha_personagem.FOLHA
ORDEM = ("frente", "tres_quartos", "perfil", "costas")
NOMES_ANGULO = {"frente": "Frente", "tres_quartos": "Três quartos", "perfil": "Perfil", "costas": "Costas"}
# O que se pede ao Klein em cada ângulo. "Same framing" em vez de "full body": a foto pode ser de meio corpo.
# No teste de 17/11 "forty-five degrees" sozinho saiu quase de perfil; "both eyes visible" segura os três quartos.
# A descrição da ficha vai no fim (pedido_angulo): sem ela o Klein inventou cabelo comprido nas costas de um homem de
# cabeça raspada e deu outro rosto (sem o sorriso) aos três quartos de uma senhora; com ela, os dois acertaram (teste
# de 17/11/2026, mesma semente). Pedir "o mesmo penteado" ou "a mesma expressão" sozinho não resolveu.
PEDIDOS = {
    "tres_quartos": "The same person turned slightly to their left, a three-quarter view with both eyes still visible, the same face with the same facial "
                    "expression, the same hairstyle, the same clothes and accessories, the same background and the same framing",
    "perfil": "The same person seen exactly from their left side, a side profile view, the same face with the same facial expression, the same hairstyle, "
              "the same clothes and accessories, the same background and the same framing",
    "costas": "The same person seen from behind, a back view showing the back of their head and of their clothes, the same hairstyle and the same hair "
              "length as in the picture, the same clothes with all their details, the same background and the same framing",
}


def pedido_angulo(angulo, descricao=""):
    descricao = " ".join(str(descricao or "").split()).rstrip(".")
    return PEDIDOS[angulo] + (f". The person: {descricao}." if descricao else "")


# Jeito 1 (docs/superpowers/specs/2026-11-17-rostos-do-video-design.md): uma foto real de três quartos ou de perfil (enviada
# ou tirada de um vídeo, rostos_video.py) não entra como está, que não combina com a roupa e o fundo da frente. Ela vira a
# segunda imagem do Klein, só para o rosto. No teste de 17/11 o perfil ficou mais fiel ao vídeo e a roupa da frente ficou.
ROSTO = ("tres_quartos", "perfil")
FACE = (" Use the second picture only for the face and the hair: the face, the hair and the head shape must match the person in the second "
        "picture exactly. Keep the clothes, the background and the light of the first picture.")


def pedido_com_rosto(angulo, descricao=""):
    return pedido_angulo(angulo, descricao).rstrip(".") + "." + FACE


# Preparar a frente (docs/superpowers/specs/2026-11-19-preparar-frente-design.md): antes de criar, o Klein troca a roupa e/ou
# põe um fundo cinza liso na foto de frente, em 2 opções; o usuário escolhe uma e ela vira a frente. É o pedido que funcionou
# nos testes de 17/11 e 19/11/2026 (o Klein tirou a loja e a legenda do quadro do vídeo). A BFS no rosto depois da troca foi
# testada em 19/11 e ficou de fora: ganho pequeno e, com a legenda no recorte da cabeça, ela colou o texto na imagem.
PREFIXO_FRENTE = "frentenova_"
FUNDO_CINZA = "standing in a bright photo studio with a plain light grey background"
_MESMA_PESSOA = "The same person with the same face, the same hair and the same expression"


def pedido_frente(roupa_en, fundo_cinza):
    roupa_en = " ".join(str(roupa_en or "").split())
    if not roupa_en and not fundo_cinza:
        raise ValueError("Escreva a roupa ou escolha o fundo cinza: do jeito que está, a foto não muda.")
    return _MESMA_PESSOA + (f", now wearing {roupa_en}" if roupa_en else "") + (f", {FUNDO_CINZA}" if fundo_cinza else "") + ", the same framing"


def pergunta_roupa(roupa):
    return f"""The user described, possibly in Portuguese, the clothes the person in <Picture 1> should wear instead of the current ones:
"{" ".join(str(roupa).split())}"

Translate this into one short English description of the clothes, as a noun phrase, for example: a dark blue denim jacket over a white t-shirt. Describe only the clothes the user asked for; do not describe the person or the background.

Reply with only the phrase, with no quotes and nothing else."""


def limpar_roupa(texto):
    """A resposta da IA reduzida à frase da roupa: sem o raciocínio, uma linha, sem aspas, ponto final nem "wearing" no começo."""
    linhas = [l.strip() for l in str(texto or "").split("</think>")[-1].splitlines() if l.strip()]
    if not linhas:
        return ""
    frase = linhas[0].strip(" \"'“”‘’`").rstrip(".").strip()
    frase = re.sub(r"^(now\s+)?wearing\s+", "", frase, flags=re.I)
    primeira = frase.split(" ")[0] if frase else ""
    if frase and not (len(primeira) > 1 and primeira.isupper()):
        frase = frase[0].lower() + frase[1:]
    return frase[:300]


def traduzir_roupa(roupa, imagem):
    """A roupa em inglês, pela IA de visão do estúdio (a mesma do Editar vídeo) olhando `imagem` (na input do ComfyUI).
    (frase, True) ou, se a IA falhar, (a roupa como veio, False)."""
    import types
    import continuar_video
    reserva = " ".join(str(roupa or "").split())
    try:
        r, texto = continuar_video.chamar_llm(pergunta_roupa(roupa), imagem, "roupa da frente", types.SimpleNamespace(rotulo=None), pensar=False)
    except Exception as e:
        print(f"AVISO: a IA de visão falhou ({e}).", flush=True)
        return reserva, False
    frase = limpar_roupa(texto) if r.get("status") == "success" else ""
    return (frase, True) if frase else (reserva, False)


EXTENSOES = (".png", ".jpg", ".jpeg", ".webp")


def gerar_id(nome):
    """Um nome de pasta seguro e único a partir do nome do personagem."""
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "personagem"
    pid, n = base, 2
    while (PASTA / pid).exists():
        pid, n = f"{base}_{n}", n + 1
    return pid


def pasta_de(pid):
    if not re.fullmatch(r"[a-z0-9_]{1,48}", pid or "") or not (PASTA / pid / FICHA).is_file():
        raise ValueError("Personagem desconhecido.")
    return PASTA / pid


def ler(pid):
    pasta = pasta_de(pid)
    f = json.loads((pasta / FICHA).read_text(encoding="utf-8"))
    f["id"] = pid
    f["angulos"] = {a: (f"{a}.png" if (pasta / f"{a}.png").is_file() else None) for a in ORDEM}
    f["marca"] = int(max([(pasta / f"{a}.png").stat().st_mtime for a in ORDEM if (pasta / f"{a}.png").is_file()] or [0]))
    folha = pasta / FOLHA
    f["folha"] = str(folha.stat().st_mtime_ns) if folha.is_file() else None
    f["ficha_vistas"], f["ficha_aprovada"] = ficha_personagem.estado(pasta)
    f["ficha_roupa"] = (pasta / ficha_personagem.ROUPA).is_file()
    return f


def listar():
    if not PASTA.is_dir():
        return []
    saida = []
    for p in sorted(PASTA.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if (p / FICHA).is_file() and (p / "frente.png").is_file():
            try:
                saida.append(ler(p.name))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return saida


def criar(nome, descricao, origem, fotos=None, lados=None):
    """Cria o personagem com a foto `origem` (qualquer imagem) como frente. Devolve o id.
    `fotos`: {ângulo: arquivo} com fotos reais de três quartos, perfil ou costas.
    - Três quartos e perfil viram referência de rosto (ref_<ângulo>.png, ficha "referencias"): o Klein gera o ângulo com a
      roupa e o fundo da frente. A referência é espelhada se a pessoa olha para a direita da imagem (o Klein vira para a
      esquerda). `lados`: {ângulo: True/False} quando o lado já é conhecido (rosto tirado de um vídeo: o giro medido
      no quadro inteiro); aí não detecta de novo, porque num recorte de perfil o YuNet muitas vezes não acha o rosto.
    - As costas entram no lugar do que o Klein geraria (ele inventa o que não vê: cabelo comprido numa cabeça raspada,
      17/11/2026) e ficam marcadas em "enviadas"."""
    from PIL import Image
    nome = " ".join(str(nome or "").split())[:60]
    if not nome:
        raise ValueError("Dê um nome ao personagem.")
    origem = Path(origem)
    if not origem.is_file() or origem.suffix.lower() not in EXTENSOES:
        raise ValueError("A foto do personagem não foi encontrada.")
    fotos = {a: Path(f) for a, f in (fotos or {}).items() if f}
    for a, f in fotos.items():
        if a not in ORDEM[1:]:
            raise ValueError("Ângulo desconhecido.")
        if not f.is_file() or f.suffix.lower() not in EXTENSOES:
            raise ValueError(f"A foto de {NOMES_ANGULO[a].lower()} não foi encontrada. Envie de novo.")
    PASTA.mkdir(exist_ok=True)
    pid = gerar_id(nome)
    pasta = PASTA / pid
    pasta.mkdir()
    with Image.open(origem) as im:
        im.convert("RGB").save(pasta / "frente.png")
    try:
        for a, f in fotos.items():
            if a in ROSTO:
                gravar_referencia(f, pasta / f"ref_{a}.png", (lados or {}).get(a))
            else:
                with Image.open(f) as im:
                    im.convert("RGB").save(pasta / f"{a}.png")
    except Exception as e:
        # Sem isto sobrava uma pasta com frente.png e sem ficha: some da lista, prende o id e a página via um 500
        shutil.rmtree(pasta, ignore_errors=True)
        raise ValueError(f"Não consegui ler a foto de {NOMES_ANGULO[a].lower()}. Envie de novo.") from e
    referencias, enviadas = [a for a in ROSTO if a in fotos], [a for a in ORDEM[1:] if a in fotos and a not in ROSTO]
    ficha = {"nome": nome, "descricao": " ".join(str(descricao or "").split())[:600], "criado": time.strftime("%Y-%m-%d %H:%M:%S"),
             "origem": origem.name, **({"referencias": referencias} if referencias else {}), **({"enviadas": enviadas} if enviadas else {})}
    (pasta / FICHA).write_text(json.dumps(ficha, ensure_ascii=False, indent=1), encoding="utf-8")
    return pid


def gravar_referencia(origem, destino, direita=None):
    """Grava a foto como referência de rosto em PNG, espelhada se a pessoa olha para a direita da imagem
    (`direita` já conhecido, ou detectado aqui)."""
    import cv2, numpy as np
    import rostos_video
    from PIL import Image
    with Image.open(origem) as im:
        img = cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    if direita is None:
        direita = rostos_video.olha_para_direita(img)
    if direita:
        img = cv2.flip(img, 1)
    Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).save(destino)


def apagar(pid):
    shutil.rmtree(pasta_de(pid))


def apagar_angulo(pid, angulo):
    """Apaga um ângulo para gerar de novo (a frente não: ela é o personagem)."""
    if angulo not in ORDEM[1:]:
        raise ValueError("Ângulo desconhecido.")
    pasta = pasta_de(pid)
    (pasta / f"{angulo}.png").unlink(missing_ok=True)
    # Refazer com a mesma semente e o mesmo pedido sairia igual: a ficha conta quantas vezes cada ângulo foi refeito
    f = json.loads((pasta / FICHA).read_text(encoding="utf-8"))
    f.setdefault("refeitos", {})[angulo] = f.get("refeitos", {}).get(angulo, 0) + 1
    # Uma foto enviada que foi apagada para refazer passa a ser gerada pelo Klein
    if angulo in f.get("enviadas", []):
        f["enviadas"] = [a for a in f["enviadas"] if a != angulo]
    (pasta / FICHA).write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")


def angulos_prontos(pid):
    """Os arquivos dos ângulos que existem, na ordem frente, três quartos, perfil, costas."""
    pasta = pasta_de(pid)
    return [pasta / f"{a}.png" for a in ORDEM if (pasta / f"{a}.png").is_file()]


def faltam(pid):
    pasta = pasta_de(pid)
    return [a for a in ORDEM[1:] if not (pasta / f"{a}.png").is_file()]


def para_entrada(pid, com_angulos=True, sem_costas=False):
    """Copia a frente e os outros ângulos para a pasta input do ComfyUI. Devolve (foto, [ângulos]), os nomes dos arquivos.
    O nome leva a marca (data do arquivo mais novo): refazer um ângulo não reaproveita a cópia antiga.
    `sem_costas`: na Head Swap só a cabeça vem da foto; as costas não ajudam."""
    pasta, marca = pasta_de(pid), ler(pid)["marca"]
    nomes = []
    for a in ORDEM:
        if (a != "frente" and not com_angulos) or (a == "costas" and sem_costas) or not (pasta / f"{a}.png").is_file():
            continue
        nome = f"pers_{pid}_{marca}_{a}.png"
        if not (config.ENTRADA / nome).is_file():
            shutil.copyfile(pasta / f"{a}.png", config.ENTRADA / nome)
        nomes.append(nome)
    return nomes[0], nomes[1:]


def grafo_angulo(partida, angulo, semente, prefixo, descricao="", referencia=None):
    import texto_para_imagem as t2i
    m = t2i.MODELOS_TEXTO["klein_edit"]
    p = {"partida": partida, "prompt": pedido_com_rosto(angulo, descricao) if referencia else pedido_angulo(angulo, descricao), "passos": m["passos"]}
    if referencia:
        p["referencia"] = referencia
    return t2i.grafo_edicao_klein(p, m, semente, prefixo)


def gerar_angulos(pid, avisar=print):
    """Gera com o Klein os ângulos que faltam. Devolve {ângulo: segundos}."""
    from comfy_api import rodar
    pasta = pasta_de(pid)
    entrada = f"personagem_{pid}_frente.png"
    shutil.copyfile(pasta / "frente.png", config.ENTRADA / entrada)
    ficha = ler(pid)
    tempos, lista, descricao, refeitos = {}, faltam(pid), ficha.get("descricao", ""), ficha.get("refeitos", {})
    copias = [config.ENTRADA / entrada]
    avisar(f"{len(lista)} ângulos a gerar", flush=True)
    try:
        for i, angulo in enumerate(lista):
            nome = NOMES_ANGULO[angulo].lower()
            avisar(f"ângulo {nome}", flush=True)
            referencia = None
            if (pasta / f"ref_{angulo}.png").is_file():
                referencia = f"personagem_{pid}_ref_{angulo}.png"
                shutil.copyfile(pasta / f"ref_{angulo}.png", config.ENTRADA / referencia)
                copias.append(config.ENTRADA / referencia)
            r = rodar(grafo_angulo(entrada, angulo, 1000 + ORDEM.index(angulo) - 1 + 100 * refeitos.get(angulo, 0), f"personagens/{pid}_{angulo}", descricao,
                                   referencia), 1800)
            if r["status"] != "success":
                raise RuntimeError(f"o Klein não gerou o ângulo {nome} ({r['status']} {r['erro'][:300]})")
            imgs = (r["saidas"].get("9") or {}).get("images", [])
            if not imgs:
                raise RuntimeError(f"o ComfyUI não devolveu a imagem do ângulo {nome}")
            shutil.copyfile(config.SAIDA / imgs[0].get("subfolder", "") / imgs[0]["filename"], pasta / f"{angulo}.png")
            tempos[angulo] = round(r["segundos"])
            avisar(f"ângulo {nome}: {round(r['segundos'])} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)
    finally:
        for c in copias:
            c.unlink(missing_ok=True)
    return tempos


def preparar_frente(partida, roupa, fundo_cinza, codigo, sementes):
    """O Klein refaz a foto `partida` com a roupa e/ou o fundo cinza, uma vez por semente. As opções ficam na input do
    ComfyUI (frentenova_<código>_<semente>.png), onde o Criar lê a foto de frente. Devolve {"opcoes", "roupa_en", "ia"}.
    RuntimeError se o ComfyUI falhar (as opções já feitas desse código saem)."""
    from PIL import Image
    from comfy_api import rodar
    import texto_para_imagem as t2i
    m = t2i.MODELOS_TEXTO["klein_edit"]
    entrada = f"{PREFIXO_FRENTE}{codigo}_partida.png"
    with Image.open(partida) as im:
        im.convert("RGB").save(config.ENTRADA / entrada)
    feitas = []
    try:
        roupa_en, ia = traduzir_roupa(roupa, entrada) if str(roupa or "").strip() else ("", True)
        pedido = pedido_frente(roupa_en, fundo_cinza)
        for semente in sementes:
            r = rodar(t2i.grafo_edicao_klein({"partida": entrada, "prompt": pedido, "passos": m["passos"]}, m, semente, f"personagens/frente_{codigo}_{semente}"), 1800)
            if r["status"] != "success":
                raise RuntimeError(f"{r['status']} {str(r.get('erro', ''))[:300]}".strip())
            imgs = (r["saidas"].get("9") or {}).get("images", [])
            if not imgs:
                raise RuntimeError("o ComfyUI não devolveu a imagem")
            nome = f"{PREFIXO_FRENTE}{codigo}_{semente}.png"
            shutil.copyfile(config.SAIDA / imgs[0].get("subfolder", "") / imgs[0]["filename"], config.ENTRADA / nome)
            feitas.append(nome)
    except Exception:
        for nome in feitas:
            (config.ENTRADA / nome).unlink(missing_ok=True)
        raise
    finally:
        (config.ENTRADA / entrada).unlink(missing_ok=True)
    return {"opcoes": feitas, "roupa_en": roupa_en, "ia": ia}


def limpar_frentes_antigas(dias=2):
    """Apaga da input do ComfyUI as opções de frente de mais de `dias` dias (as que não viraram personagem)."""
    limite = time.time() - dias * 86400
    if not config.ENTRADA.is_dir():
        return
    for f in config.ENTRADA.glob(f"{PREFIXO_FRENTE}*"):
        try:
            if f.is_file() and not f.is_symlink() and f.stat().st_mtime < limite:
                f.unlink()
        except OSError:
            continue


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--personagem", required=True)
    a.add_argument("--ficha", nargs="?", const="frente", choices=(*ficha_personagem.VISTAS, "aprovar", "completar"))
    a = a.parse_args()
    try:
        import lmstudio
        lmstudio.descarregar()
    except Exception:
        pass
    try:
        if a.ficha:
            print("Gerando ficha de personagem", flush=True)
            ficha_personagem.gerar(pasta_de(a.personagem), a.ficha, ler(a.personagem).get("descricao"))
            print("pronto: ficha de personagem", flush=True)
            return
        tempos = gerar_angulos(a.personagem)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"FALHA na geracao: {e}", flush=True)
        sys.exit(4)
    print(f"pronto: {len(tempos)} ângulos, {sum(tempos.values())} s", flush=True)


if __name__ == "__main__":
    main()
