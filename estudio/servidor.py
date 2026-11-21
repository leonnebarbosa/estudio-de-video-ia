"""Servidor local da pagina: so escuta neste computador (127.0.0.1) e nao apaga nada sem confirmacao.
A geracao e feita pelos scripts continuar_video.py, trocar_personagem.py e imagem_para_video.py;
esta camada recebe os pedidos da pagina e mostra o progresso."""
import json, os, re, sys, threading, time, traceback, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if sys.stdout is not None:  # no pythonw.exe nao ha console
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import acesso, acoes, ambiente, cortes, editar_video, extras, loras, modelos, pacotes, palavras_lora, personagens, projetos, recursos, rostos_video, tarefa, validacao, video_avancado
# As rotas POST /api/ do do_POST (abaixo) que a pagina usa, menos /api/desligar, /api/enviar e as que abrem janelas no PC
# (/api/abrir-pasta e /api/abrir-instalador): o MCP completo (chamar_api) so chama estas.
# Fica antes do import do mcp_ferramentas, que le esta lista. Quem acrescentar uma rota ao do_POST acrescenta aqui (um teste confere).
ROTAS_POST = frozenset({
    "/api/acabar-imagem",
    "/api/apagar",
    "/api/apagar-imagem",
    "/api/apagar-varios",
    "/api/audio-tomadas",
    "/api/continuar",
    "/api/descrever-imagem",
    "/api/editar-imagem-minha",
    "/api/editar-pintar",
    "/api/editar-roteiro",
    "/api/fila",
    "/api/iniciar",
    "/api/iniciar-avancado",
    "/api/iniciar-editar",
    "/api/iniciar-imagem",
    "/api/iniciar-texto",
    "/api/iniciar-troca",
    "/api/iniciar-troca-foto",
    "/api/ligar-comfy",
    "/api/loras/consultar",
    "/api/loras/restaurar",
    "/api/loras/salvar",
    "/api/modelos/anotar",
    "/api/modelos/apagar",
    "/api/parar",
    "/api/personagem-angulos",
    "/api/personagem-apagar",
    "/api/personagem-criar",
    "/api/personagem-ficha",
    "/api/personagem-frente",
    "/api/personagem-rosto-usar",
    "/api/personagem-rostos",
    "/api/personagem-usar",
    "/api/plano",
    "/api/refazer-imagem",
    "/api/refazer-janela",
    "/api/reusar",
    "/api/usar-imagem",
})
import mcp_ferramentas, mcp_servidor  # noqa: F401 (o import registra as ferramentas do MCP)
from envio import SUFIXOS_AUDIO, nome_limpo, receber_arquivo
from imagem_para_video import CAMERAS, DURACOES
from validacao import Erro, pasta_projeto

# woff2: as fontes da interface nova (pagina/fontes, licenca SIL OFL, vindas do freefield)
TIPOS_PAGINA = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".ico": "image/x-icon", ".woff2": "font/woff2"}


LIMITE_MCP = 1_000_000  # bytes de uma mensagem do /mcp (chave operador)
LIMITE_MCP_COMPLETO = 28_000_000  # chave completa: 20 MB do enviar_arquivo em base64 (x4/3) e o envelope JSON
LIMITE_ENTRADA = 4096  # bytes do formulario de /entrar


class Pedido(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def estado_vigia(self):
        v = self.server.vigia
        return v.estado() if v is not None else {"situacao": "desligado", "mensagem": "", "religadas": 0}

    def desligar(self, d):
        """Fecha o estudio: para a geracao (se confirmada), desliga o ComfyUI e encerra o servidor."""
        if self.server.remoto:
            raise Erro("Desligar o estúdio só pelo próprio computador.", 403)
        if tarefa.tarefa.rodando():
            if d.get("confirmar") is not True:
                raise Erro("Há uma geração em andamento.", 409)
            tarefa.tarefa.parar()
        if self.server.vigia is not None:
            self.server.vigia.desligar()
        self.responder({"ok": True})
        # shutdown espera o laco do servidor acabar; chamado daqui, dentro de um pedido, e preciso outra thread
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def so_no_computador(self):
        """Abrir pasta ou instalador abre uma janela no PC, que quem esta longe nao ve: no remoto, 403."""
        if self.server.remoto:
            raise Erro("Isso só funciona no próprio computador.", 403)

    def origem_valida(self):
        """Impede que um site aberto no navegador acione este servidor."""
        porta = self.server.server_address[1]
        validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
        if self.server.remoto:
            validos.add(f"{config.REMOTO['escutar']}:{porta}")
        if self.headers.get("Host") not in validos:
            return False
        origem = self.headers.get("Origin")
        return not origem or urllib.parse.urlparse(origem).netloc in validos

    def responder_mcp(self, nivel, tamanho):
        """POST /mcp: so com chave, ate no servidor local. Uma mensagem JSON-RPC por pedido."""
        if nivel not in ("operador", "completo"):
            time.sleep(acesso.PAUSA_ERRO)
            self.close_connection = True
            return self.responder({"erro": "Chave de acesso necessária."}, 401)
        if tamanho > (LIMITE_MCP_COMPLETO if nivel == "completo" else LIMITE_MCP):
            self.close_connection = True
            # Descarta uma parte do corpo antes de responder: fechar com o cliente ainda enviando da "conexao reiniciada" em vez do 413
            resta = min(tamanho, 8_000_000)
            while resta > 0:
                bloco = self.rfile.read(min(65536, resta))
                if not bloco:
                    break
                resta -= len(bloco)
            return self.responder({"erro": "Pedido grande demais."}, 413)
        codigo, dados = mcp_servidor.atender(self.rfile.read(tamanho), nivel)
        if dados is None:  # notificacao: so confirma o recebimento
            self.send_response(codigo)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.responder(dados, codigo)

    def nivel_do_pedido(self):
        """"operador" ou "completo" se o pedido traz uma chave valida; sem chave valida, "local" no servidor
        local (a pagina continua sem chave) e None no remoto."""
        chave = acesso.chave_do_pedido(self.headers)
        return acesso.nivel(chave) or (None if self.server.remoto else "local")

    def negar_acesso(self, nivel, caminho):
        """Barra quem nao pode ver `caminho` (True se ja respondeu). O operador so usa o /mcp; sem chave, o servidor remoto nao serve nada."""
        if nivel is None:
            time.sleep(acesso.PAUSA_ERRO)
            self.close_connection = True  # um corpo nao lido atrapalharia o proximo pedido
            self.responder({"erro": "Chave de acesso necessária."}, 401)
        elif nivel == "operador" and caminho != "/mcp":
            self.close_connection = True
            self.responder({"erro": "Esta chave só dá acesso ao /mcp."}, 403)
        else:
            return False
        return True

    def enviar_html(self, corpo, codigo=200, extra=()):
        corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def tela_de_entrada(self, erro="", codigo=200):
        html = (config.PAGINA / "entrar.html").read_text(encoding="utf-8")
        self.enviar_html(html.replace("<!--ERRO-->", erro), codigo)

    def entrar(self, tamanho):
        """POST /entrar (so no servidor remoto): troca a chave completa por um cookie. Chave operador ou errada: 401."""
        if tamanho > LIMITE_ENTRADA:
            self.close_connection = True
            return self.responder({"erro": "Pedido grande demais."}, 413)
        campos = urllib.parse.parse_qs(self.rfile.read(tamanho).decode("utf-8", "replace"))
        chave = (campos.get("chave") or [""])[0].strip()
        if acesso.nivel(chave) != "completo":
            time.sleep(acesso.PAUSA_ERRO)
            return self.tela_de_entrada("Chave inválida.", 401)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{acesso.COOKIE}={chave}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def enviar_arquivo(self, arq, tipo):
        tamanho = arq.stat().st_size
        inicio, fim, codigo = 0, tamanho - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                inicio = int(m.group(1))
                fim = min(int(m.group(2)), fim) if m.group(2) else fim
            else:
                inicio = max(0, tamanho - int(m.group(2)))
            if inicio > fim:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{tamanho}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            codigo = 206
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - inicio + 1))
        if codigo == 206:
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
        self.end_headers()
        with arq.open("rb") as f:
            f.seek(inicio)
            resta = fim - inicio + 1
            while resta > 0:
                bloco = f.read(min(1024 * 1024, resta))
                if not bloco:
                    break
                self.wfile.write(bloco)
                resta -= len(bloco)

    def do_GET(self):
        if not self.origem_valida():
            return self.responder({"erro": "Origem recusada."}, 403)
        u = urllib.parse.urlparse(self.path)
        nivel = self.nivel_do_pedido()
        if self.server.remoto and nivel is None and u.path in ("/", "/entrar"):
            # sem chave, o servidor remoto so mostra a tela de entrada
            if u.path == "/entrar":
                return self.tela_de_entrada()
            self.send_response(303)
            self.send_header("Location", "/entrar")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if self.negar_acesso(nivel, u.path):
            return
        partes = [urllib.parse.unquote(x) for x in u.path.split("/") if x]
        try:
            if u.path == "/mcp":
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif u.path == "/":
                corpo = (config.PAGINA / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corpo)
            elif u.path.startswith("/pagina/"):
                pasta = config.PAGINA.resolve()
                rel = urllib.parse.unquote(u.path[len("/pagina/"):])
                tipo = TIPOS_PAGINA.get(Path(rel).suffix.lower())
                arq = (pasta / rel).resolve() if rel and "\\" not in rel and "\0" not in rel else None
                if tipo is None or arq is None or not arq.is_relative_to(pasta) or not arq.is_file():
                    raise Erro("Arquivo não encontrado.", 404)
                corpo = arq.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corpo)
            elif u.path == "/api/estado":
                self.responder({"comfy": {**ambiente.comfy(), **self.estado_vigia()}, "recursos": recursos.lidos(), "tarefa": tarefa.tarefa.resumo(), "fila": tarefa.tarefa.fila.resumo(), "projetos": projetos.listar_projetos(), "opcoes": ambiente.opcoes(), "padrao": validacao.PADRAO,
                                "constantes": {"fps": validacao.FPS, "quadros": validacao.QUADROS_RODADA, "sobreposicao": validacao.SOBREPOSICAO, "novos": validacao.NOVOS}, "proporcoes": validacao.PROPORCOES, "qualidades": validacao.QUALIDADES,
                                "troca": {"padrao": validacao.PADRAO_TROCA, "qualidades": validacao.QUALIDADES_TROCA, "qualidades_upscale": validacao.QUALIDADES_UPSCALE, "duracao_max": validacao.DURACAO_MAX_TROCA,
                                          "duracao_max_por_mp": [list(x) for x in validacao.DURACAO_MAX_TROCA_POR_MP],
                                          "wangp": config.WANGP_PYTHON.is_file(), "duracao_max_wangp": validacao.DURACAO_MAX_TROCA_WANGP, "quadros_min_wangp": validacao.QUADROS_MIN_WANGP},
                                "imagem": {"padrao": validacao.PADRAO_IMAGEM, "qualidades": validacao.QUALIDADES_IMAGEM, "acabamentos": validacao.ACABAMENTOS, "max_mp_refino": validacao.MAX_MP_REFINO, "duracoes": DURACOES, "max_tomadas": validacao.MAX_TOMADAS, "max_acao": validacao.MAX_ACAO, "max_referencias": validacao.MAX_REFERENCIAS, "cameras": list(CAMERAS),
                                           "max_tomada_audio_por_mp": [list(x) for x in validacao.MAX_TOMADA_AUDIO_POR_MP], "acabamentos_audio": list(validacao.ACABAMENTOS_AUDIO),
                                           "modelos": validacao.modelos_imagem()},
                                "avancado": {"faltam": video_avancado.faltam(), "limites": video_avancado.LIMITES,
                                             "max_prompt": video_avancado.MAX_PROMPT},
                                "texto": {"padrao": validacao.PADRAO_TEXTO, "qualidades": validacao.QUALIDADES_TEXTO, "max_imagens": validacao.MAX_IMAGENS_TEXTO, "modelos": validacao.modelos_texto()},
                                "troca_foto": validacao.situacao_troca_foto(),
                                "editar": {"padrao": validacao.PADRAO_EDITAR, "qualidades": list(editar_video.QUALIDADES), "duracao_max": validacao.DURACAO_MAX_EDITAR,
                                           "quadros_min": validacao.QUADROS_MIN_WANGP, "quadro_padrao": editar_video.QUADRO_PADRAO, "wangp": config.WANGP_PYTHON.is_file()},
                                "abas": abas_prontas(), "extras": extras.secao("pagina"), "gatilhos": loras.para_a_pagina()})
            elif u.path == "/api/personagens":
                self.responder({"personagens": personagens.listar(), "angulos": [{"id": a, "nome": personagens.NOMES_ANGULO[a]} for a in personagens.ORDEM]})
            elif len(partes) == 3 and partes[0] == "personagem" and partes[2] in {personagens.FOLHA, *personagens.ficha_personagem.ARQUIVOS.values(), *(f"{a}.png" for a in personagens.ORDEM)}:
                try:
                    arq = personagens.pasta_de(partes[1]) / partes[2]
                except ValueError:
                    raise Erro("Personagem não encontrado.", 404)
                if not arq.is_file():
                    raise Erro("Imagem não encontrada.", 404)
                self.enviar_arquivo(arq, "image/png")
            elif len(partes) == 3 and partes[0] == "rostos":
                # Os rostos tirados de um vídeo (rostos_video.py), para escolher no personagem novo
                try:
                    arq = rostos_video.caminho_candidato(partes[1], partes[2])
                except ValueError:
                    raise Erro("Imagem não encontrada.", 404)
                self.enviar_arquivo(arq, "image/png")
            elif u.path == "/api/loras":
                # Palavras-chave de cada LoRA (palavras_lora.py): a tela "Palavras-chave das LoRAs" da aba Modelos
                self.responder({"loras": palavras_lora.listar(), "pendentes": len(palavras_lora.pendentes())})
            elif u.path == "/api/modelos":
                lista = modelos.listagem()
                self.responder({"modelos": lista, "total": sum(i["tamanho"] for i in lista)})
            elif len(partes) == 3 and partes[0] == "video" and partes[2] in ("final.mp4", "comparativo.mp4", "final_hd.mp4"):
                arq = pasta_projeto(partes[1]) / partes[2]
                if not arq.is_file():
                    raise Erro("Vídeo não encontrado.", 404)
                self.enviar_arquivo(arq, "video/mp4")
            elif len(partes) == 3 and partes[0] == "editar" and partes[2] == "pintado.png":
                # A pintura que o Editar video usou, no cartao do projeto
                arq = pasta_projeto(partes[1]) / "pintado.png"
                if not arq.is_file():
                    raise Erro("Imagem não encontrada.", 404)
                self.enviar_arquivo(arq, "image/png")
            elif len(partes) == 3 and partes[0] == "imagem" and re.fullmatch(r"imagem_\d{1,2}\.png", partes[2]):
                arq = pasta_projeto(partes[1]) / partes[2]
                if not arq.is_file():
                    raise Erro("Imagem não encontrada.", 404)
                self.enviar_arquivo(arq, "image/png")
            elif len(partes) == 2 and partes[0] == "quadro":
                pasta = pasta_projeto(partes[1])
                estado = projetos._ultimos.get(pasta.name) or {}
                arq = projetos.ultimo_quadro(pasta.name, len(estado.get("rodadas", [])))
                if arq is None:
                    raise Erro("Quadro não encontrado.", 404)
                self.enviar_arquivo(arq, "image/png")
            elif len(partes) == 3 and partes[0] == "cortes":
                # Os cortes de camera de um video enviado (cortes.py), para o editor do trecho da troca
                arq = config.ENVIOS / nome_limpo(partes[2]) if partes[1] == "video" else None
                if arq is None or not arq.is_file():
                    raise Erro("Vídeo não encontrado.", 404)
                self.responder({"cortes": cortes.cortes(arq)})
            elif len(partes) == 3 and partes[0] == "entrada" and partes[1] == "audio":
                # O audio da fala do modo audio do Imagem para video, para ouvir na pagina
                arq = config.ENTRADA / nome_limpo(partes[2])
                if not arq.is_file() or arq.suffix.lower() not in SUFIXOS_AUDIO:
                    raise Erro("Áudio não encontrado.", 404)
                self.enviar_arquivo(arq, {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac"}[arq.suffix.lower()])
            elif len(partes) == 3 and partes[0] == "entrada" and partes[1] in ("video", "foto"):
                arq = (config.ENVIOS if partes[1] == "video" else config.ENTRADA) / nome_limpo(partes[2])
                if not arq.is_file():
                    raise Erro("Arquivo não encontrado.", 404)
                self.enviar_arquivo(arq, "video/mp4" if partes[1] == "video" else "image/" + {".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}.get(arq.suffix.lower(), "png"))
            else:
                raise Erro("Endereço não encontrado.", 404)
        except Erro as e:
            self.responder({"erro": e.mensagem}, e.codigo)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            # Sem isto a conexao caia sem resposta e a pagina mostrava so "Failed to fetch"
            traceback.print_exc()
            try:
                self.responder({"erro": f"Falha inesperada no estúdio ({type(e).__name__}: {str(e)[:200]}). Os detalhes estão em logs\\estudio.log."}, 500)
            except (ConnectionError, BrokenPipeError):
                pass

    def do_POST(self):
        if not self.origem_valida():
            self.close_connection = True
            return self.responder({"erro": "Origem recusada."}, 403)
        # Antes de qualquer chave: com -1 o rfile.read lia sem limite, e um texto derrubava o pedido sem resposta
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = -1
        if tamanho < 0:
            self.close_connection = True
            return self.responder({"erro": "Tamanho do pedido inválido."}, 400)
        u = urllib.parse.urlparse(self.path)
        nivel = self.nivel_do_pedido()
        if u.path == "/entrar":
            if not self.server.remoto:
                self.close_connection = True
                return self.responder({"erro": "Endereço não encontrado."}, 404)
            return self.entrar(tamanho)
        if self.negar_acesso(nivel, u.path):
            return
        try:
            if u.path == "/mcp":
                return self.responder_mcp(nivel, tamanho)
            if u.path == "/api/enviar":
                q = urllib.parse.parse_qs(u.query)
                try:
                    r = receber_arquivo(self.rfile, tamanho, q.get("tipo", [""])[0], q.get("nome", [""])[0])
                except Erro:
                    self.close_connection = True
                    raise
                return self.responder(r)
            d = json.loads(self.rfile.read(tamanho) or b"{}")
            if u.path == "/api/reusar":
                return self.responder(acoes.acao_reusar(d))
            if u.path == "/api/apagar":
                return self.responder(acoes.acao_apagar(d))
            if u.path == "/api/apagar-varios":
                return self.responder(acoes.acao_apagar_varios(d))
            if u.path == "/api/apagar-imagem":
                return self.responder(acoes.acao_apagar_imagem(d))
            if u.path == "/api/usar-imagem":
                return self.responder(acoes.acao_usar_imagem(d))
            if u.path == "/api/descrever-imagem":
                return self.responder(acoes.acao_descrever_imagem(d))
            if u.path == "/api/audio-tomadas":
                return self.responder(acoes.acao_audio_tomadas(d))
            if u.path == "/api/editar-pintar":
                return self.responder(acoes.acao_editar_pintar(d))
            if u.path == "/api/editar-roteiro":
                return self.responder(acoes.acao_editar_roteiro(d))
            if u.path == "/api/editar-imagem-minha":
                return self.responder(acoes.acao_editar_imagem_minha(d))
            if u.path == "/api/personagem-criar":
                return self.responder(acoes.acao_personagem_criar(d))
            if u.path == "/api/personagem-usar":
                return self.responder(acoes.acao_personagem_usar(d))
            if u.path == "/api/personagem-rostos":
                return self.responder(acoes.acao_personagem_rostos(d))
            if u.path == "/api/personagem-rosto-usar":
                return self.responder(acoes.acao_personagem_rosto_usar(d))
            if u.path == "/api/personagem-frente":
                return self.responder(acoes.acao_personagem_frente(d))
            if u.path == "/api/personagem-ficha":
                return self.responder(acoes.acao_personagem_ficha(d))
            if u.path == "/api/fila":
                return self.responder(acoes.acao_fila(d))
            if u.path == "/api/personagem-angulos":
                acoes.acao_personagem_angulos(d)
                return self.responder({"ok": True})
            if u.path == "/api/personagem-apagar":
                acoes.acao_personagem_apagar(d)
                return self.responder({"ok": True})
            if u.path in ("/api/loras/salvar", "/api/loras/restaurar", "/api/loras/consultar"):
                try:
                    if u.path.endswith("salvar"):
                        palavras_lora.salvar(d.get("nome"), d.get("modo"), d.get("palavras"), d.get("nota"))
                    elif u.path.endswith("restaurar"):
                        palavras_lora.restaurar(d.get("nome"))
                    else:
                        palavras_lora.consultar(d.get("nome"))
                except palavras_lora.Erro as e:
                    raise Erro(str(e))
                return self.responder({"ok": True})
            if u.path == "/api/modelos/anotar":
                modelos.anotar(d.get("caminho"), d.get("nome"), d.get("nota"))
                return self.responder({"ok": True})
            if u.path == "/api/modelos/apagar":
                return self.responder(modelos.apagar(d.get("caminho"), d.get("confirmar") is True))
            if u.path == "/api/iniciar":
                acoes.acao_iniciar(d)
            elif u.path == "/api/iniciar-troca":
                acoes.acao_iniciar_troca(d)
            elif u.path == "/api/iniciar-editar":
                acoes.acao_iniciar_editar(d)
            elif u.path == "/api/refazer-janela":
                acoes.acao_refazer_janela(d)
            elif u.path == "/api/iniciar-texto":
                acoes.acao_iniciar_texto(d)
            elif u.path == "/api/iniciar-troca-foto":
                acoes.acao_iniciar_troca_foto(d)
            elif u.path == "/api/iniciar-imagem":
                acoes.acao_iniciar_imagem(d)
            elif u.path == "/api/iniciar-avancado":
                acoes.acao_iniciar_avancado(d)
            elif u.path == "/api/refazer-imagem":
                acoes.acao_refazer_imagem(d)
            elif u.path == "/api/acabar-imagem":
                acoes.acao_acabar_imagem(d)
            elif u.path == "/api/plano":
                acoes.acao_plano(d)
            elif u.path == "/api/abrir-pasta":
                self.so_no_computador()
                acoes.acao_abrir_pasta(d)
            elif u.path == "/api/continuar":
                acoes.acao_continuar(d)
            elif u.path == "/api/parar":
                tarefa.tarefa.parar()
            elif u.path == "/api/ligar-comfy":
                # So religa um ComfyUI parado e sem geracao: um clique atrasado nao pode matar o que esta funcionando
                if self.server.vigia is not None and (tarefa.tarefa.rodando() or not self.server.vigia.tentar_de_novo()):
                    raise Erro("O ComfyUI já está ligado.", 409)
            elif u.path == "/api/desligar":
                return self.desligar(d)
            elif u.path == "/api/abrir-instalador":
                self.so_no_computador()
                abrir_instalador()
            else:
                raise Erro("Endereço não encontrado.", 404)
            self.responder({"ok": True})
        except Erro as e:
            self.responder({"erro": e.mensagem}, e.codigo)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            # Sem isto a conexao caia sem resposta e a pagina mostrava so "Failed to fetch"
            traceback.print_exc()
            try:
                self.responder({"erro": f"Falha inesperada no estúdio ({type(e).__name__}: {str(e)[:200]}). Os detalhes estão em logs\\estudio.log."}, 500)
            except (ConnectionError, BrokenPipeError):
                pass


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, reutilizar o endereco deixaria duas copias ouvindo a mesma porta
    allow_reuse_address = False
    # Vigia do ComfyUI, posto pelo lancador (estudio.pyw). Sem ele (testes) a pagina funciona e o ComfyUI aparece como desligado.
    vigia = None
    # True quando escuta num endereco que nao e o 127.0.0.1 (a VPN): ai toda requisicao precisa de chave
    remoto = False

    def handle_error(self, request, client_address):
        # O navegador fecha conexoes ociosas o tempo todo; isso nao e erro
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def _ler_abas():
    try:
        return pacotes.abas()
    except Exception:
        return {}  # catalogo ausente ou quebrado: a pagina so nao avisa


abas_prontas = ambiente.Cache(15, _ler_abas)


def abrir_instalador(abrir=os.startfile):
    """A aba sem pacote tem o botao Baixar modelos: abre o mesmo instalador do atalho (a pagina de boas-vindas)."""
    bat = config.WORKFLOWS / "Instalar estudio.bat"
    if not bat.is_file():
        raise Erro("Não achei o Instalar estudio.bat na pasta do estúdio.", 404)
    abrir(str(bat))


def criar(porta: int = config.PORTA, vigia=None, endereco: str = "127.0.0.1"):
    """Abre a porta e devolve o servidor, sem atender ainda (quem chama usa serve_forever).
    `vigia` e o Vigia do ComfyUI; o lancador tambem pode atribuir `servidor.vigia` depois de criar.
    `endereco` diferente de 127.0.0.1 faz um servidor remoto (so atende com chave)."""
    s = Servidor((endereco, porta), Pedido)
    s.remoto = endereco != "127.0.0.1"
    s.vigia = vigia
    # As pastas de dados ficam fora do git: num PC novo nao existem ate a primeira geracao
    for pasta in (config.PROJETOS, config.ENVIOS, config.LOGS):
        pasta.mkdir(parents=True, exist_ok=True)
    # As pinturas do Editar video que nao viraram projeto (mais de 2 dias)
    try:
        editar_video.apagar_temporarios()
    except OSError as e:
        print(f"AVISO: não consegui apagar as pinturas antigas do Editar vídeo ({e}).", flush=True)
    return s


def criar_remoto(porta: int = config.PORTA, vigia=None):
    """O servidor da VPN, no IP de config.REMOTO["escutar"]. Sem esse IP e as duas chaves no local.json devolve None."""
    if not acesso.remoto_pronto():
        print("AVISO: acesso remoto desligado (faltam o IP e as duas chaves em remoto, no local.json).", flush=True)
        return None
    return criar(porta, vigia, config.REMOTO["escutar"])


def main(porta=None):
    porta = porta or config.PORTA
    endereco = f"http://127.0.0.1:{porta}/"
    try:
        s = criar(porta)
    except OSError:
        print(f"A página já está aberta: {endereco}")
        webbrowser.open(endereco)
        return
    print(f"Página: {endereco}")
    print("Deixe esta janela aberta. Fechá-la interrompe a geração em andamento; as rodadas prontas ficam guardadas.")
    threading.Timer(0.5, webbrowser.open, args=(endereco,)).start()
    s.serve_forever()


if __name__ == "__main__":
    main()
