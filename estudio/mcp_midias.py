"""Ferramentas do MCP que cuidam das midias (fotos, audios e videos) e do personagem criado a partir de uma foto."""
import shutil, time

import config
import entrada
import acoes, importar, links, midias, personagens, planos
import envio
from envio import nome_limpo
from erros import Erro
import mcp_servidor
from mcp_servidor import texto
from mcp_consultas import _parou, _pasta_do_projeto, _projeto_de_imagem


def _tipo_de_midia(a):
    """O tipo pedido (foto, audio ou video), ou Erro dizendo as opcoes."""
    tipo = a.get("tipo")
    if tipo not in midias.LIMITES:
        raise Erro("Diga o tipo da mídia: foto, audio ou video.")
    return tipo


ROTULO_MIDIA = {"foto": "uma foto", "audio": "um áudio", "video": "um vídeo"}


def pedir_envio(a):
    tipo = _tipo_de_midia(a)
    link = f"{mcp_servidor.base_atual()}/m/{links.criar_enviar(tipo)}"
    limite = midias.LIMITES[tipo] // 1_000_000
    return [texto(f"Link para enviar {ROTULO_MIDIA[tipo]}: {link}\n"
                  f'Com terminal: curl -T <arquivo> "{link}/" (troque <arquivo> pelo caminho do arquivo).\n'
                  f"Sem terminal: o usuário abre o link no navegador e escolhe o arquivo.\n"
                  f"O link vale 1 hora e para um envio só; o arquivo pode ter até {limite} MB. "
                  "Depois do envio, chame listar_midias para ver o nome com que a mídia ficou.")]


def importar_url(a):
    tipo = _tipo_de_midia(a)
    r = importar.baixar(a.get("url"), tipo)
    return [texto(f"Importei {r['arquivo']} ({_medidas({'tipo': tipo, **r})}). "
                  "Use esse nome nas ferramentas; chame listar_midias para ver as mídias do estúdio.")]


def _ha(segundos):
    s = max(0, int(segundos))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} dia(s)"


def _medidas(m):
    """O trecho entre parenteses de listar_midias: o tipo e as medidas que o registro tem."""
    larg = f"{m['largura']}x{m['altura']}" if m.get("largura") and m.get("altura") else ""
    dur = f"{planos._br(round(m['duracao'], 1))} s" if m.get("duracao") else ""
    if m["tipo"] == "foto":
        return f"foto {larg}".strip()
    if m["tipo"] == "audio":
        return f"áudio {dur}".strip()
    return ", ".join(p for p in (f"vídeo {dur}".strip(), larg) if p)


def listar_midias(a):
    tipo = a.get("tipo")
    if tipo is not None and tipo not in midias.LIMITES:
        raise Erro("O tipo precisa ser foto, audio ou video (ou deixe em branco para ver todos).")
    lista = midias.listar(tipo)
    if not lista:
        quais = f"do tipo {tipo} " if tipo else ""
        return [texto(f"Nenhuma mídia {quais}enviada ainda. Chame pedir_envio.")]
    agora = time.time()
    return [texto("\n".join(f"{m['nome']} ({_medidas(m)}, enviada há {_ha(agora - m['quando'])})" for m in lista))]


def _achar_midia(nome, tipo, erro):
    """O nome limpo de uma midia que existe na pasta do seu tipo (`tipo` None: qualquer um); senao Erro(erro, 404).
    O unico lugar que decide "esta midia existe e e do tipo X": audio_fala, cenario, foto e as referencias do modo livre."""
    limpo = nome_limpo(str(nome))
    achado = midias.tipo_de(limpo) if limpo else None
    if achado is None or (tipo and achado != tipo):
        raise Erro(erro, 404)
    return limpo


ERRO_AUDIO = "Áudio não encontrado entre as mídias. Chame listar_midias, ou pedir_envio para enviar um."
ERRO_FOTO = "Foto não encontrada entre as mídias. Chame listar_midias, ou pedir_envio para enviar uma."
ERRO_CENARIO = "Foto do lugar (cenario) não encontrada entre as mídias. Chame listar_midias, ou pedir_envio para enviar uma."


def criar_personagem(a):
    """Cria um personagem da biblioteca a partir de uma foto enviada (a mesma acao da pagina, sem ficha nem angulos: sem GPU)."""
    nome = a.get("nome")
    if not isinstance(nome, str) or not " ".join(nome.split()):
        raise Erro("Dê um nome ao personagem (campo nome). Nada foi criado.")
    descricao = a.get("descricao", "")
    if descricao is None:
        descricao = ""
    if not isinstance(descricao, str):
        raise Erro("A descrição precisa ser um texto curto (campo descricao), ou fique sem ela. Nada foi criado.")
    if not a.get("foto"):
        raise Erro("Falta a foto: mande o nome de uma mídia de listar_midias. Nada foi criado.")
    foto = _achar_midia(a.get("foto"), "foto", f"A foto '{a.get('foto')}' não foi encontrada entre as mídias. Nada foi criado. "
                        "Chame listar_midias para ver o nome certo, ou pedir_envio para enviar uma foto.")
    # Um agente local chamou tres vezes seguidas e criou ana, ana_2 e ana_3 (o operador nao apaga): mesmo nome e mesma foto de origem e o mesmo personagem
    chave = " ".join(nome.split())[:60].casefold()
    existente = next((p for p in personagens.listar() if " ".join(str(p.get("nome") or "").split()).casefold() == chave and p.get("origem") == foto), None)
    if existente:
        return [texto(f"Esse personagem já existia (id {existente['id']}); nada novo foi criado. Use o id {existente['id']} no campo personagem.")]
    try:
        from PIL import Image
        with Image.open(entrada.caminho(foto)) as im:
            im.load()  # a acao converte a imagem inteira: se o Pillow nao le, uma pasta ficaria sem ficha e prenderia o id
    except Exception:
        raise Erro(f"A mídia '{foto}' não abre como imagem. Nada foi criado. Chame listar_midias e escolha outra foto, ou peça outra com pedir_envio.")
    try:
        # A autorizacao vai marcada pelo MCP (decisao do usuario de 21/11); ficha, angulos e fotos extras usam a placa e ficam na pagina
        r = acoes.acao_personagem_criar({"nome": " ".join(nome.split()), "descricao": descricao, "foto": foto, "autorizacao": True})
    except Erro as e:
        raise Erro(f"{e.mensagem} Nada foi criado. Corrija e chame criar_personagem de novo, uma vez só.", e.codigo)
    except ValueError as e:
        raise Erro(f"{e} Nada foi criado. Corrija e chame criar_personagem de novo, uma vez só.")
    pid = r["id"]
    return [texto(f"Personagem criado. Id: {pid}. Passe exatamente \"{pid}\" no campo personagem do planejar_video. "
                  "A ficha e os ângulos se fazem pela página do estúdio (menu Personagem) e são opcionais; não tente fazer por aqui.")]


def _numero_da_imagem(a):
    n = a.get("imagem", 1)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise Erro("O campo imagem é o número da imagem do projeto (1, 2, 3...).")
    return n


def usar_resultado(a):
    """Copia (nunca move) o resultado de um projeto para as midias do estudio: imagem_<n>.png vira foto, final.mp4 vira video."""
    nome, pasta = _pasta_do_projeto(a)
    de_imagem = _projeto_de_imagem(pasta)
    if de_imagem:
        n = _numero_da_imagem(a)
        item = next((i for i in de_imagem["imagens"] if i["n"] == n), None)
        if item is None:
            tem = ", ".join(str(i["n"]) for i in de_imagem["imagens"]) or "nenhuma"
            if not de_imagem["completo"]:
                if _parou(nome, de_imagem):
                    raise Erro(f"A imagem {n} do projeto '{nome}' não ficou pronta: a geração parou em {len(de_imagem['imagens'])} de {de_imagem['total']} (tem: {tem}). "
                               "Nada foi copiado. Use uma imagem pronta, ou continue pela página do estúdio.", 409)
                raise Erro(f"A imagem {n} do projeto '{nome}' ainda não ficou pronta ({len(de_imagem['imagens'])} de {de_imagem['total']}). "
                           "Nada foi copiado. Chame ver_andamento, avise o usuário e espere.", 409)
            raise Erro(f"O projeto '{nome}' não tem a imagem {n} (tem: {tem}). Nada foi copiado. Chame ver_resultado para ver as imagens.", 404)
        origem, tipo, pasta_destino, nome_destino = pasta / item["arquivo"], "foto", None, f"{nome}_{n}.png"  # None: input/estudio/envios
        try:
            from PIL import Image
            with Image.open(origem) as im:
                info = {"largura": im.width, "altura": im.height}
        except Exception:
            raise Erro(f"Não consegui abrir a imagem {n} do projeto '{nome}'. Nada foi copiado. Chame listar_projetos e escolha outro.")
        serve = "planejar_imagem e planejar_video"
    else:
        origem = pasta / "final.mp4"
        if not origem.is_file():
            raise Erro(f"O projeto '{nome}' ainda não tem resultado. Nada foi copiado. Chame ver_andamento: se ainda estiver gerando, avise o usuário e espere; "
                       "senão, chame listar_projetos e escolha um projeto pronto.", 409)
        tipo, pasta_destino, nome_destino = "video", config.ENVIOS, f"{nome}.mp4"
        info = envio.examinar_video(origem)
        serve = "planejar_video_livre (como referência de vídeo)"
    (pasta_destino or entrada.pasta_envios()).mkdir(parents=True, exist_ok=True)
    destino = envio.destino_livre(pasta_destino, nome_limpo(nome_destino), origem)
    if not destino.exists():
        shutil.copy2(origem, destino)  # copia: o original fica no projeto
    midias.registrar(destino.name, tipo, "mcp", info)
    return [texto(f"Pronto: a mídia '{destino.name}' ({'foto' if tipo == 'foto' else 'vídeo'}) já existe no estúdio e serve em {serve}. "
                  "O original continua no projeto.")]
