"""Baixa uma midia de um endereco publico (http/https) para a pasta de entrada, para a ferramenta importar_url do MCP.
O estudio fica numa rede privada: o servidor nunca conecta a endereco interno, nem por redirecionamento. Cada nome e resolvido,
TODOS os enderecos devolvidos precisam ser publicos, e a conexao vai para o IP conferido (nao para o nome de novo), entao uma
resposta de DNS que muda depois da conferencia nao leva para dentro. No https o certificado continua conferido contra o nome original.
O corpo e lido em blocos, com limite de tamanho e de tempo, para um arquivo temporario fora da pasta de entrada; so depois vai
para envio.receber_arquivo, que confere o conteudo. Uso: baixar(url, tipo) -> o dict do receber_arquivo."""
import http.client, ipaddress, platform, secrets, socket, ssl, tempfile, threading, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from envio import nome_limpo, receber_arquivo
from erros import Erro

MAX_REDIRECIONAMENTOS = 3
LIMITE = {"foto": 50_000_000, "audio": 50_000_000, "video": 200_000_000}  # bytes
TEMPO = {"foto": 60, "audio": 60, "video": 300}  # s, prazo TOTAL de baixar() (redirecionamentos incluidos), imposto por um vigia que fecha o socket
SUFIXOS = {"foto": (".png", ".jpg", ".jpeg", ".webp"), "audio": (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"), "video": (".mp4",)}
EXTENSAO_DO_TIPO = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
                    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
                    "audio/ogg": ".ogg", "audio/flac": ".flac", "audio/x-flac": ".flac", "audio/aac": ".aac", "video/mp4": ".mp4"}
REDIRECIONAMENTOS = (301, 302, 303, 307, 308)
BLOCO = 64 * 1024
# Nome, versao e para que serve, no formato que a Wikimedia pede (sem contato pessoal); nome generico demais leva 403/429 em alguns sites
AGENTE = f"estudio-de-video/1.0 (importar_url; ferramenta local de video) Python/{platform.python_version()}"
NAT64 = ipaddress.ip_network("64:ff9b::/96")
IPV4_COMPATIVEL = ipaddress.ip_network("::/96")


def _ip_permitido(ip):
    """So enderecos publicos: recusa loopback, privados, link-local, a faixa 100.64/10 das operadoras, multicast e reservados."""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if a.version == 6:
        if a.ipv4_mapped:
            a = a.ipv4_mapped
        elif a in NAT64:  # DNS64: o IPv4 vem embutido nos 32 bits de baixo; vale a mesma regra dele (a faixa inteira nao se recusa)
            a = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
        elif a.is_site_local or a in IPV4_COMPATIVEL:  # fec0::/10 (antigo privado) e ::7f00:1 (formato antigo com IPv4)
            return False
    return a.is_global and not a.is_multicast  # 224.0.0.1 conta como global no ipaddress


def _enderecos(host, porta):
    """Resolve `host` e exige que todos os enderecos sejam publicos. Devolve a lista de IPs conferidos."""
    try:
        infos = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except OSError:
        infos = []
    ips = list(dict.fromkeys(i[4][0] for i in infos))
    if not ips:
        raise Erro(f"Não encontrei o endereço {host}. Confira o link ou envie o arquivo com pedir_envio.")
    if not all(_ip_permitido(ip) for ip in ips):
        raise Erro("Esse endereço aponta para a rede interna, e o estúdio só baixa de endereços públicos da internet. "
                   "Use um link público ou envie o arquivo com pedir_envio.")
    return ips


class _Vigia:
    """Fecha o socket quando o prazo acaba. O timeout do socket reinicia a cada recv, entao um servidor que pinga 1 byte de
    tempos em tempos seguraria a leitura (ou os cabecalhos) para sempre; o shutdown acorda quem estiver bloqueado."""
    def __init__(self, sock, prazo):
        self.estourou = False
        self._sock = sock
        self._timer = threading.Timer(max(0.0, prazo - time.monotonic()), self._estourar)
        self._timer.daemon = True
        self._timer.start()

    def _estourar(self):
        self.estourou = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def parar(self):
        self._timer.cancel()


def _contexto_ssl():
    """O contexto do sistema mais as raizes do certifi (vem com o Python do ComfyUI). O Python le so as raizes que o Windows ja
    guardou, e o Windows so baixa uma raiz nova quando um programa dele pede: nesta maquina faltavam as do Let's Encrypt de 2025
    (Root YE), e Wikimedia e Civitai davam "certificate has expired" (24/11/2026). Sem o certifi, fica o do sistema."""
    contexto = ssl.create_default_context()
    try:
        import certifi
        contexto.load_verify_locations(certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    return contexto


def _estouro(tipo):
    return Erro(f"O download passou de {TEMPO[tipo]} s e foi cancelado. Use um arquivo menor ou envie com pedir_envio.", 408)


def _conectar(url, prazo):
    """Abre a conexao com o IP conferido (https com certificado conferido contra o nome). Devolve (conexao, caminho, socket, vigia):
    o socket vai a parte porque o http.client larga o dele ao ler a resposta; quem chama fecha o socket e para o vigia."""
    try:
        partes = urlsplit(url)
    except ValueError:
        raise Erro("Endereço inválido. Confira o link (http:// ou https://) ou envie o arquivo com pedir_envio.")
    if partes.scheme not in ("http", "https"):
        raise Erro("Só aceito endereços http:// ou https://. Use um link público ou envie o arquivo com pedir_envio.")
    if partes.username or partes.password:
        raise Erro("O endereço não pode ter usuário e senha. Use um link público ou envie o arquivo com pedir_envio.")
    host = partes.hostname
    if not host:
        raise Erro("O endereço está incompleto. Confira o link.")
    try:
        porta = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError:
        raise Erro("A porta do endereço não é válida. Confira o link.")
    ultimo = None
    for ip in _enderecos(host, porta):
        sock = vigia = None
        try:
            restante = prazo - time.monotonic()
            if restante <= 0:
                raise TimeoutError
            sock = socket.create_connection((ip, porta), timeout=min(30, restante))
            if partes.scheme == "https":
                # O wrap_socket assume o descritor e deixa o socket antigo inutil: o vigia tem que olhar o socket novo.
                # O aperto de mao fica para depois do vigia, para o prazo valer tambem nele.
                sock = _contexto_ssl().wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
                vigia = _Vigia(sock, prazo)
                sock.do_handshake()
            else:
                vigia = _Vigia(sock, prazo)
            conexao = http.client.HTTPConnection(host, porta)  # o Host do pedido e o nome; o socket e o do IP conferido
            if partes.scheme == "https":
                conexao.default_port = 443  # sem isto o Host sai "nome:443" e quebra link assinado
            conexao.sock = sock
            return conexao, (partes.path or "/") + (f"?{partes.query}" if partes.query else ""), sock, vigia
        except OSError as e:  # inclui ssl.SSLError e TimeoutError
            ultimo = e
            if vigia:
                vigia.parar()
            if sock:
                sock.close()
            if isinstance(e, TimeoutError) or (vigia and vigia.estourou):
                raise Erro("O download passou do prazo antes de conectar e foi cancelado. Tente de novo ou envie o arquivo com pedir_envio.", 408)
    raise Erro(f"Não consegui conectar a {host} ({getattr(ultimo, 'strerror', None) or ultimo}). Confira o link ou tente de novo.")


def _nome(url, tipo, tipo_conteudo):
    """O nome do fim do caminho, limpo; sem extensao aceita para o tipo, `importado_<4 hex>` com a extensao do Content-Type."""
    fim = Path(urlsplit(url).path).name
    nome = nome_limpo(fim) if fim else ""
    if Path(nome).suffix.lower() in SUFIXOS[tipo]:
        return nome
    extensao = EXTENSAO_DO_TIPO.get((tipo_conteudo or "").split(";")[0].strip().lower(), "")
    return f"importado_{secrets.token_hex(2)}{extensao}"


def baixar(url, tipo):
    if tipo not in LIMITE:
        raise Erro("O tipo precisa ser foto, audio ou video.")
    if not isinstance(url, str) or not url.strip():
        raise Erro("Diga o endereço (http:// ou https://) do arquivo.")
    url = url.strip()
    limite = LIMITE[tipo]
    prazo = time.monotonic() + TEMPO[tipo]
    for _ in range(MAX_REDIRECIONAMENTOS + 1):
        conexao, caminho, sock, vigia = _conectar(url, prazo)
        try:
            try:
                conexao.request("GET", caminho, headers={"User-Agent": AGENTE, "Accept": "*/*", "Connection": "close"})
                r = conexao.getresponse()
            except (OSError, http.client.HTTPException) as e:
                if vigia.estourou:
                    raise _estouro(tipo)
                raise Erro(f"Não consegui baixar do endereço ({getattr(e, 'strerror', None) or e.__class__.__name__}). Confira o link ou tente de novo.")
            if r.status in REDIRECIONAMENTOS:
                destino = r.getheader("Location")
                if not destino:
                    raise Erro("O endereço mandou para outro lugar sem dizer onde. Confira o link.")
                try:
                    url = urljoin(url, destino)
                except ValueError:
                    raise Erro("O endereço mandou para um lugar inválido. Confira o link ou envie o arquivo com pedir_envio.")
                # volta ao laco: o novo destino passa por todas as conferencias
                continue
            if r.status != 200:
                raise Erro(f"O endereço respondeu {r.status} {r.reason}. Confira o link ou envie o arquivo com pedir_envio.", 502)
            try:
                declarado = int(r.getheader("Content-Length") or -1)
            except ValueError:
                declarado = -1
            if declarado > limite:
                raise Erro(f"O arquivo tem {declarado // 1_000_000} MB e o limite é {limite // 1_000_000} MB. Use um arquivo menor.")
            nome = _nome(url, tipo, r.getheader("Content-Type"))
            # Arquivo temporario fora da pasta de entrada: se parar no limite, nada fica la. receber_arquivo precisa do tamanho antes
            with tempfile.TemporaryFile() as temp:
                total = 0
                try:
                    while True:
                        if vigia.estourou or time.monotonic() > prazo:
                            raise _estouro(tipo)
                        bloco = r.read(BLOCO)
                        if not bloco:
                            break
                        total += len(bloco)
                        if total > limite:
                            raise Erro(f"O arquivo passa do limite de {limite // 1_000_000} MB e o download foi cancelado. Use um arquivo menor.")
                        temp.write(bloco)
                except (OSError, http.client.HTTPException):
                    if vigia.estourou:
                        raise _estouro(tipo)
                    raise Erro("O download foi interrompido. Tente de novo ou envie o arquivo com pedir_envio.")
                if vigia.estourou:  # o shutdown vira fim de arquivo: sem isto um arquivo cortado passaria por completo
                    raise _estouro(tipo)
                if declarado >= 0 and total != declarado:
                    raise Erro("O download foi interrompido. Tente de novo ou envie o arquivo com pedir_envio.")
                temp.seek(0)
                return receber_arquivo(temp, total, tipo, nome, origem="url")
        finally:
            vigia.parar()
            sock.close()
            conexao.close()
    raise Erro(f"O endereço redireciona mais de {MAX_REDIRECIONAMENTOS} vezes. Use o endereço final do arquivo.")
