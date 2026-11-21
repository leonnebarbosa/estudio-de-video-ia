"""A geracao em andamento: uma por vez, rodando num processo filho. Com uma rodando, os pedidos novos vao para a fila
(fila.py), que comeca o proximo 15 s depois que a atual termina bem."""
import json, os, subprocess, threading, time, urllib.request

import comfy_api, config, fila, lmstudio, retomada
from validacao import Erro, PADRAO, PARAMETROS


def comfy_pronto():
    import ambiente
    c = ambiente.ler_comfy()
    return c["ligado"] and not c["ocupado"]


SCRIPT = config.ESTUDIO / "continuar_video.py"
SCRIPT_TROCA = config.ESTUDIO / "trocar_personagem.py"
SCRIPT_IMAGEM = config.ESTUDIO / "imagem_para_video.py"
SCRIPT_TEXTO = config.ESTUDIO / "texto_para_imagem.py"
SCRIPT_WAN = config.ESTUDIO / "wan_para_video.py"
SCRIPT_PERSONAGEM = config.ESTUDIO / "personagens.py"
SCRIPT_EDITAR = config.ESTUDIO / "editar_video.py"


class Tarefa:
    """Uma geracao por vez."""

    def __init__(self):
        self.trava = threading.Lock()
        self.proc = None
        self.projeto = self.modo = self.tipo = None
        self.inicio = self.fim = 0
        self.codigo = None
        self.parada = False
        self.log = None
        self.offset = 0
        self.fila = fila.Fila(self._lancar, self.rodando, self.trava, comfy_pronto)

    def rodando(self):
        return self.proc is not None and self.codigo is None

    def _pedir(self, cmd, projeto, modo, tipo):
        """Chamado com a trava. Comeca agora ou poe na fila. Devolve {"fila": posicao}, 0 se comecou agora."""
        if (self.rodando() and self.projeto == projeto) or self.fila.tem(projeto):
            raise Erro(f"{projeto} já está gerando ou na fila.", 409)
        if self.rodando() or self.fila.ativa():
            return {"fila": self.fila.adicionar(cmd, projeto, modo, tipo)}
        self._lancar(cmd, projeto, modo, tipo)
        return {"fila": 0}

    def iniciar(self, projeto, modo, extras):
        with self.trava:
            pasta = config.PROJETOS / projeto
            p = {**PADRAO, **json.loads((pasta / PARAMETROS).read_text(encoding="utf-8"))}
            cmd = [str(config.PYTHON), "-I", "-u", str(SCRIPT), "--projeto", projeto, "--duracao", str(p["duracao"]), "--megapixels", str(p["megapixels"]), "--proporcao", p["proporcao"],
                   "--modelo", p["modelo"], "--sampler", p["sampler"], "--agendador", p["agendador"], "--passos", str(p["passos"]), "--tentativas", str(p["tentativas"])] + extras
            for nome, forca in p["loras"]:
                cmd += ["--lora", f"{nome}={forca}"]
            if not p["loras"]:
                cmd.append("--sem-lora")
            if p["semente"] is not None:
                cmd += ["--semente", str(p["semente"])]
            if modo == "plano":
                cmd.append("--so-plano")
            elif modo == "juntar":
                cmd.append("--so-juntar")
            return self._pedir(cmd, projeto, modo, "continuar")

    def iniciar_troca(self, projeto, extras=()):
        """extras: ["--refazer", "N"] refaz da janela N em diante (Refazer uma janela)."""
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_TROCA), "--projeto", projeto, *extras], projeto, "gerar", "troca")

    def iniciar_imagem(self, projeto, extras=()):
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_IMAGEM), "--projeto", projeto, *extras], projeto, "acabar" if extras else "gerar", "imagem")

    def iniciar_texto(self, projeto):
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_TEXTO), "--projeto", projeto], projeto, "gerar", "texto")

    def iniciar_wan(self, projeto):
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_WAN), "--projeto", projeto], projeto, "gerar", "wan")

    def iniciar_editar(self, projeto):
        """Editar video pelo WanGP (editar_video.py)."""
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_EDITAR), "--projeto", projeto], projeto, "gerar", "editar")

    def iniciar_personagem(self, pid):
        """Gera os ângulos que faltam de um personagem da biblioteca (personagens.py). O log fica na pasta do personagem."""
        with self.trava:
            return self._pedir([str(config.PYTHON), "-I", "-u", str(SCRIPT_PERSONAGEM), "--personagem", pid], pid, "gerar", "personagem")

    def iniciar_ficha(self, pid, etapa="frente"):
        with self.trava:
            cmd = [str(config.PYTHON), "-I", "-u", str(SCRIPT_PERSONAGEM), "--personagem", pid, "--ficha", etapa]
            return self._pedir(cmd, pid, f"ficha-{etapa}", "personagem")

    def relancar(self, dados):
        """Roda de novo a geracao que um reinicio do PC interrompeu (ver retomada.py)."""
        with self.trava:
            if self.rodando():
                raise Erro(f"Já existe uma geração em andamento: {self.projeto}.", 409)
            self._lancar(dados["cmd"], dados["projeto"], dados["modo"], dados["tipo"], dados.get("retomada", 0) + 1)

    def _lancar(self, cmd, projeto, modo, tipo, vez=0):
        # Os ângulos de um personagem não são um projeto: o log vai para personagens/<id>
        pasta = (config.WORKFLOWS / "personagens" if tipo == "personagem" else config.PROJETOS) / projeto
        self.log = pasta / "execucao.log"
        self.offset = self.log.stat().st_size if self.log.exists() else 0
        saida = self.log.open("ab")
        # O modelo de conversa do LM Studio (ou Bionic) sai da placa antes de gerar: com ele ocupando ~7 GB o ComfyUI fica lentíssimo
        liberado = lmstudio.descarregar()
        if liberado:
            saida.write(f"LM Studio: {liberado}\n".encode("utf-8"))
            saida.flush()
        ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(cmd, stdout=saida, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(config.ESTUDIO), env=ambiente, creationflags=config.SEM_JANELA)
        saida.close()
        self.projeto, self.modo, self.tipo, self.ultimo_progresso = projeto, modo, tipo, None
        self.inicio, self.fim, self.codigo, self.parada = time.time(), 0, None, False
        retomada.gravar(cmd, projeto, modo, tipo, self.inicio, vez)
        threading.Thread(target=self._esperar, args=(self.proc,), daemon=True).start()

    def _esperar(self, proc):
        codigo = proc.wait()
        retomada.terminou(codigo, self.parada)
        self.codigo, self.fim = codigo, time.time()
        # Terminou bem: o proximo da fila em 15 s. Falhou ou foi parada: a fila pausa
        self.fila.terminou(self.projeto, codigo, self.parada)

    def parar(self):
        if not self.rodando():
            return
        self.parada = True
        try:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=config.SEM_JANELA)
        except subprocess.TimeoutExpired:
            pass
        try:
            pedido = urllib.request.Request(config.URL_COMFY + "/interrupt", data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(pedido, timeout=5).read()
        except Exception:
            pass

    def registro(self):
        if not self.log or not self.log.exists():
            return ""
        with self.log.open("rb") as f:
            f.seek(self.offset)
            texto = f.read().decode("utf-8", "replace")
        return "\n".join(texto.splitlines()[-80:])

    def etapa(self):
        """O script grava a etapa atual no gpu.csv a cada 2 s. Devolve o nome e ha quantos segundos ela esta rodando."""
        if not self.rodando():
            return "", 0
        arq = config.PROJETOS / self.projeto / "gpu.csv"
        segundos = lambda h: sum(int(x) * m for x, m in zip(h.split(":"), (3600, 60, 1)))
        try:
            if arq.stat().st_mtime < self.inicio:
                return "", 0
            with arq.open("rb") as f:
                f.seek(max(0, arq.stat().st_size - 65536))
                linhas = f.read().decode("utf-8", "replace").strip().splitlines()
            fim, nome = linhas[-1].split(",")[:2]
            comeco = fim
            for linha in reversed(linhas):
                c = linha.split(",")
                if len(c) < 2 or c[1] != nome:
                    break
                comeco = c[0]
            # O limite cobre uma execucao anterior que parou nesta mesma etapa; o % cobre a virada da meia-noite
            return nome, min((segundos(fim) - segundos(comeco)) % 86400, round(time.time() - self.inicio))
        except Exception:
            return "", 0

    def placa(self):
        """A leitura mais recente da placa no gpu.csv (o script grava a cada 2 s), se for desta execucao e recente."""
        if not self.rodando():
            return None
        arq = config.PROJETOS / self.projeto / "gpu.csv"
        try:
            st = arq.stat()
            if st.st_mtime < self.inicio or time.time() - st.st_mtime > 15:
                return None
            with arq.open("rb") as f:
                f.seek(max(0, st.st_size - 2048))
                c = f.read().decode("utf-8", "replace").strip().splitlines()[-1].split(",")
            return {"vram_mib": int(c[2]), "temp": int(c[3]), "watts": round(float(c[5])) if len(c) > 5 and c[5].strip() else None}
        except (OSError, ValueError, IndexError):
            return None

    def progresso_troca(self):
        """Etapa e passo gravados pelo trocar_personagem.py. Ignora o arquivo de uma execucao anterior."""
        arq = config.PROJETOS / self.projeto / "progresso.json"
        try:
            if arq.stat().st_mtime >= self.inicio:
                self.ultimo_progresso = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # O script pode estar gravando o arquivo neste instante
            pass
        return self.ultimo_progresso

    def resumo(self):
        if self.proc is None:
            return None
        etapa, etapa_segundos = self.etapa()
        return {"projeto": self.projeto, "modo": self.modo, "tipo": self.tipo, "rodando": self.rodando(), "codigo": self.codigo, "parada": self.parada, "etapa": etapa, "etapa_segundos": etapa_segundos,
                "segundos": round((self.fim or time.time()) - self.inicio), "registro": self.registro(), "placa": self.placa(),
                "temp_limite": comfy_api.limite_temperatura() if self.codigo == 5 else None, "progresso": self.progresso_troca() if self.tipo in ("troca", "imagem", "texto", "wan", "editar") else None}


tarefa = Tarefa()
