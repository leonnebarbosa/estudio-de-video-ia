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
import acoes, ambiente, cortes, extras, modelos, pacotes, personagens, projetos, recursos, rostos_video, tarefa, validacao
from envio import nome_limpo, receber_arquivo
from imagem_para_video import CAMERAS, DURACOES
from validacao import Erro, pasta_projeto

# woff2: as fontes da interface nova (pagina/fontes, licenca SIL OFL, vindas do freefield)
TIPOS_PAGINA = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".ico": "image/x-icon", ".woff2": "font/woff2"}


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
        if tarefa.tarefa.rodando():
            if d.get("confirmar") is not True:
                raise Erro("Há uma geração em andamento.", 409)
            tarefa.tarefa.parar()
        if self.server.vigia is not None:
            self.server.vigia.desligar()
        self.responder({"ok": True})
        # shutdown espera o laco do servidor acabar; chamado daqui, dentro de um pedido, e preciso outra thread
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def origem_valida(self):
        """Impede que um site aberto no navegador acione este servidor."""
        porta = self.server.server_address[1]
        validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
        if self.headers.get("Host") not in validos:
            return False
        origem = self.headers.get("Origin")
        return not origem or urllib.parse.urlparse(origem).netloc in validos

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
        partes = [urllib.parse.unquote(x) for x in u.path.split("/") if x]
        try:
            if u.path == "/":
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
                                           "modelos": validacao.modelos_imagem()},
                                "texto": {"padrao": validacao.PADRAO_TEXTO, "qualidades": validacao.QUALIDADES_TEXTO, "max_imagens": validacao.MAX_IMAGENS_TEXTO, "modelos": validacao.modelos_texto()},
                                "troca_foto": validacao.situacao_troca_foto(),
                                "abas": abas_prontas(), "extras": extras.secao("pagina")})
            elif u.path == "/api/personagens":
                self.responder({"personagens": personagens.listar(), "angulos": [{"id": a, "nome": personagens.NOMES_ANGULO[a]} for a in personagens.ORDEM]})
            elif len(partes) == 3 and partes[0] == "personagem" and partes[2] in {f"{a}.png" for a in personagens.ORDEM}:
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
            elif u.path == "/api/modelos":
                lista = modelos.listagem()
                self.responder({"modelos": lista, "total": sum(i["tamanho"] for i in lista)})
            elif len(partes) == 3 and partes[0] == "video" and partes[2] in ("final.mp4", "comparativo.mp4", "final_hd.mp4"):
                arq = pasta_projeto(partes[1]) / partes[2]
                if not arq.is_file():
                    raise Erro("Vídeo não encontrado.", 404)
                self.enviar_arquivo(arq, "video/mp4")
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
        u = urllib.parse.urlparse(self.path)
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
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
            if u.path == "/api/personagem-criar":
                return self.responder(acoes.acao_personagem_criar(d))
            if u.path == "/api/personagem-usar":
                return self.responder(acoes.acao_personagem_usar(d))
            if u.path == "/api/personagem-rostos":
                return self.responder(acoes.acao_personagem_rostos(d))
            if u.path == "/api/personagem-rosto-usar":
                return self.responder(acoes.acao_personagem_rosto_usar(d))
            if u.path == "/api/fila":
                return self.responder(acoes.acao_fila(d))
            if u.path == "/api/personagem-angulos":
                acoes.acao_personagem_angulos(d)
                return self.responder({"ok": True})
            if u.path == "/api/personagem-apagar":
                acoes.acao_personagem_apagar(d)
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
            elif u.path == "/api/refazer-janela":
                acoes.acao_refazer_janela(d)
            elif u.path == "/api/iniciar-texto":
                acoes.acao_iniciar_texto(d)
            elif u.path == "/api/iniciar-troca-foto":
                acoes.acao_iniciar_troca_foto(d)
            elif u.path == "/api/iniciar-imagem":
                acoes.acao_iniciar_imagem(d)
            elif u.path == "/api/refazer-imagem":
                acoes.acao_refazer_imagem(d)
            elif u.path == "/api/acabar-imagem":
                acoes.acao_acabar_imagem(d)
            elif u.path == "/api/plano":
                acoes.acao_plano(d)
            elif u.path == "/api/abrir-pasta":
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


def criar(porta: int = config.PORTA, vigia=None):
    """Abre a porta e devolve o servidor, sem atender ainda (quem chama usa serve_forever).
    `vigia` e o Vigia do ComfyUI; o lancador tambem pode atribuir `servidor.vigia` depois de criar."""
    s = Servidor(("127.0.0.1", porta), Pedido)
    s.vigia = vigia
    # As pastas de dados ficam fora do git: num PC novo nao existem ate a primeira geracao
    for pasta in (config.PROJETOS, config.ENVIOS, config.LOGS):
        pasta.mkdir(parents=True, exist_ok=True)
    return s


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
