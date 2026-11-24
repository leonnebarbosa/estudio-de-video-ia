"""Testes do vigia do ComfyUI, do lancador e da rota de fechar. Tudo com processo, relogio e porta falsos:
nao liga o ComfyUI de verdade nem abre navegador.

Uso: python -I testar_vigia.py
"""
import importlib.util, json, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from pathlib import Path
from unittest import mock

ESTUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ESTUDIO))
import config, servidor, tarefa, vigia
from vigia import Vigia

MSG_CAIU = "O ComfyUI não voltou depois de 2 tentativas. A placa pode ter caído: se continuar assim, reinicie o PC."


class Processo:
    def __init__(self, pid):
        self.pid, self.saiu = pid, None

    def poll(self):
        return self.saiu


class Mundo:
    """Processo, porta e relogio falsos, com um registro ordenado do que o vigia fez."""
    def __init__(self, tmp):
        self.tmp, self.eventos, self.procs, self.responde, self.porta = Path(tmp), [], [], False, None
        self.nome_porta, self.erro_abrir, self.erro_vincular = "python.exe", None, None
        self.prox_pid = 100

    def abrir(self, comando, **kw):
        if self.erro_abrir:
            raise self.erro_abrir
        p = Processo(self.prox_pid)
        self.prox_pid += 1
        self.procs.append(p)
        self.eventos.append(("abrir", p.pid))
        return p

    def matar(self, pid):
        self.eventos.append(("matar", pid))
        for p in self.procs:
            if p.pid == pid:
                p.saiu = 1

    def vincular(self, proc):
        self.eventos.append(("vincular", proc.pid))
        if self.erro_vincular:
            raise self.erro_vincular

    def vigia(self):
        return Vigia(["comfy"], self.tmp, self.tmp, consultar=lambda: self.responde, abrir=self.abrir, matar=self.matar, pid_na_porta=lambda porta: self.porta,
                     nome_do_pid=lambda pid: self.nome_porta, vincular=self.vincular)

    def abertos(self):
        return [e for e in self.eventos if e[0] == "abrir"]

    def log(self):
        arq = self.tmp / "estudio.log"
        return arq.read_text(encoding="utf-8") if arq.exists() else ""


class Vigiando(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.m = Mundo(self.d.name)
        self.v = self.m.vigia()

    def test_liga_e_fica_pronto(self):
        self.v.ligar()
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.m.responde = False
        self.v.passo(False, 0)
        self.v.passo(False, 5)
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.m.responde = True
        self.v.passo(False, 10)
        self.assertEqual(self.v.estado(), {"situacao": "pronto", "mensagem": "", "religadas": 0})
        self.assertEqual(len(self.m.abertos()), 1)

    def test_toma_conta_de_comfy_alheio(self):
        self.m.porta, self.m.nome_porta = 777, "Python.exe"
        self.v.ligar()
        self.assertEqual(self.m.eventos[0], ("matar", 777))
        self.assertEqual(self.m.eventos[1][0], "abrir")
        self.assertIn("777 (Python.exe)", self.m.log())

    def test_nao_mata_programa_que_nao_e_python(self):
        self.m.porta, self.m.nome_porta = 777, "chrome.exe"
        self.v.ligar()
        self.assertEqual(self.m.eventos, [])  # nao matou nem abriu nada
        self.assertEqual(self.v.estado(), {"situacao": "caiu", "religadas": 0,
                                           "mensagem": "A porta 8188 está ocupada por chrome.exe (pid 777). Feche esse programa e clique em Tentar de novo."})
        self.assertIn("777 (chrome.exe)", self.m.log())
        self.m.porta = None  # a pessoa fechou o programa
        self.assertTrue(self.v.tentar_de_novo())
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.assertEqual(len(self.m.abertos()), 1)

    def test_tentar_de_novo_so_quando_parado(self):
        self.v.ligar()
        self.assertFalse(self.v.tentar_de_novo())  # ligando
        self.m.responde = True
        self.v.passo(False, 0)
        self.assertFalse(self.v.tentar_de_novo())  # pronto
        self.assertEqual(len(self.m.abertos()), 1)

    def test_prende_cada_processo_ao_job(self):
        self.v.ligar()
        self.m.responde = True
        self.v.passo(False, 0)
        self.m.procs[0].saiu = 1
        self.v.passo(False, 5)
        self.assertEqual([e for e in self.m.eventos if e[0] == "vincular"], [("vincular", 100), ("vincular", 101)])
        self.assertEqual(self.m.eventos.index(("vincular", 100)), self.m.eventos.index(("abrir", 100)) + 1)

    def test_job_que_falha_nao_impede_a_ligada(self):
        self.m.erro_vincular = OSError("sem job")
        self.v.ligar()
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.assertEqual(len(self.m.abertos()), 1)
        self.assertIn("sem job", self.m.log())

    def test_vigia_padrao_usa_o_job_do_lancador(self):
        jobs, vinculados = [], []
        with mock.patch.object(vigia, "job_que_mata_ao_fechar", lambda: jobs.append(1) or 4242), \
             mock.patch.object(vigia, "vincular_ao_job", lambda job, proc: vinculados.append((job, proc.pid))):
            v = Vigia(["comfy"], self.m.tmp, self.m.tmp, consultar=lambda: False, abrir=self.m.abrir, matar=self.m.matar, pid_na_porta=lambda porta: None)
            v.ligar()
            v.passo(False, 0)
            self.m.procs[0].saiu = 1
            v.passo(False, 5)
        self.assertEqual(jobs, [1])  # um job so, guardado no vigia
        self.assertEqual(v.job, 4242)
        self.assertEqual(vinculados, [(4242, 100), (4242, 101)])

    def test_falhou_fica_caiu_e_registra(self):
        self.v.falhou("Não consegui ligar o ComfyUI: sem python. Veja logs\\estudio.log.", "Traceback: linha 1")
        self.assertEqual(self.v.estado(), {"situacao": "caiu", "religadas": 0, "mensagem": "Não consegui ligar o ComfyUI: sem python. Veja logs\\estudio.log."})
        self.assertIn("Traceback: linha 1", self.m.log())

    def test_taskkill_com_limite_de_tempo(self):
        chamadas = []

        def run(cmd, **kw):
            chamadas.append(kw)
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        with mock.patch.object(vigia.subprocess, "run", run):
            vigia.matar_arvore(123)  # o taskkill travado nao derruba o vigia
        self.assertEqual(chamadas[0]["timeout"], 15)

    def test_religa_quando_o_processo_some(self):
        self.v.ligar()
        self.m.responde = True
        self.v.passo(False, 0)
        self.m.procs[0].saiu = 1
        self.v.passo(True, 5)  # mesmo durante geracao
        self.assertEqual(len(self.m.abertos()), 2)
        e = self.v.estado()
        self.assertEqual((e["situacao"], e["religadas"]), ("religando", 1))
        self.v.passo(False, 10)
        self.assertEqual(self.v.estado()["situacao"], "pronto")

    def test_nao_religa_por_silencio_durante_geracao(self):
        self.v.ligar()
        self.m.responde = True
        self.v.passo(True, 0)
        self.m.responde = False
        for t in range(5, 305, 5):
            self.v.passo(True, t)
        self.assertEqual(len(self.m.abertos()), 1)
        self.assertEqual(self.v.estado()["situacao"], "pronto")

    def test_religa_por_silencio_fora_de_geracao(self):
        self.v.ligar()
        self.m.responde = True
        self.v.passo(False, 0)
        self.m.responde = False
        for t in range(5, 61, 5):
            self.v.passo(False, t)
        self.assertEqual(len(self.m.abertos()), 1)  # 60 s ainda nao passam de 60
        self.v.passo(False, 61)
        self.assertEqual(len(self.m.abertos()), 2)
        self.assertIn(("matar", 100), self.m.eventos)
        self.assertEqual(self.v.estado()["situacao"], "religando")

    def test_desiste_depois_de_2_falhas(self):
        self.v.ligar()
        self.m.responde = False
        for t in range(0, 605, 5):  # 420 s da primeira ligada + 180 s da religada
            self.v.passo(False, t)
        e = self.v.estado()
        self.assertEqual(e["situacao"], "caiu")
        self.assertEqual(e["mensagem"], MSG_CAIU)
        self.assertEqual(len(self.m.abertos()), 2)
        antes = len(self.m.eventos)
        for t in range(605, 1200, 5):
            self.v.passo(False, t)
        self.assertEqual(len(self.m.eventos), antes)  # parou de tentar
        self.v.ligar()  # "Tentar de novo"
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.assertEqual(len(self.m.abertos()), 3)

    def test_primeira_ligada_tem_420_s(self):
        self.v.ligar()
        for t in range(0, 405, 5):
            self.v.passo(False, t)
        self.assertEqual(self.v.estado()["situacao"], "ligando")  # 400 s sem resposta ainda nao e falha
        self.m.responde = True
        self.v.passo(False, 405)
        self.assertEqual(self.v.estado(), {"situacao": "pronto", "mensagem": "", "religadas": 0})
        self.assertEqual(len(self.m.abertos()), 1)

    def test_primeira_ligada_falha_aos_420_s(self):
        self.v.ligar()
        self.v.passo(False, 0)
        self.v.passo(False, 419)
        self.assertEqual(self.v.estado()["situacao"], "ligando")
        self.v.passo(False, 420)
        self.assertEqual((self.v.estado()["situacao"], self.v.estado()["religadas"]), ("religando", 1))

    def test_religada_tem_180_s(self):
        self.v.ligar()
        self.m.responde = True
        self.v.passo(False, 0)
        self.m.procs[0].saiu = 1
        self.m.responde = False
        self.v.passo(False, 5)  # religa; a contagem comeca aqui
        self.assertEqual(self.v.estado()["situacao"], "religando")
        self.v.passo(False, 184)
        self.assertEqual(len(self.m.abertos()), 2)
        self.v.passo(False, 186)  # 181 s sem ficar pronta: falha e religa de novo
        self.assertEqual(len(self.m.abertos()), 3)
        self.assertEqual(self.v.estado()["religadas"], 2)

    def test_tentar_de_novo_volta_a_ter_420_s(self):
        self.v.ligar()
        for t in range(0, 605, 5):
            self.v.passo(False, t)
        self.assertEqual(self.v.estado()["situacao"], "caiu")
        self.v.ligar()
        self.v.passo(False, 1000)
        self.v.passo(False, 1400)
        self.assertEqual(self.v.estado()["situacao"], "ligando")

    def test_religada_que_fica_pronta_zera_as_falhas(self):
        self.v.ligar()
        self.v.passo(False, 0)
        self.v.passo(False, 421)  # 1a falha, religa
        self.assertEqual(self.v.estado()["situacao"], "religando")
        self.m.responde = True
        self.v.passo(False, 430)
        self.assertEqual(self.v.estado()["situacao"], "pronto")
        self.m.responde = False
        self.v.passo(False, 431)
        self.v.passo(False, 500)  # silencio, religa; so 1 falha seguida
        self.assertEqual(self.v.estado()["situacao"], "religando")

    def test_desligar_fecha_o_comfy(self):
        self.v.ligar()
        self.v.desligar()
        self.assertIn(("matar", 100), self.m.eventos)
        self.assertEqual(self.v.estado()["situacao"], "desligado")
        n = len(self.m.eventos)
        self.v.passo(False, 500)
        self.v.desligar()
        self.assertEqual(len(self.m.eventos), n)


class Rotas(unittest.TestCase):
    PORTA = 8197

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.m = Mundo(self.d.name)
        self.v = self.m.vigia()
        self.s = servidor.criar(self.PORTA, vigia=self.v)
        self.fio = threading.Thread(target=self.s.serve_forever, daemon=True)
        self.fio.start()
        self.addCleanup(self.fio.join, 5)
        self.addCleanup(self.s.server_close)
        self.addCleanup(self.s.shutdown)
        self.rodando, self.paradas = False, []
        orig = (tarefa.tarefa.rodando, tarefa.tarefa.parar)
        tarefa.tarefa.rodando = lambda: self.rodando
        tarefa.tarefa.parar = lambda: self.paradas.append(1)
        self.addCleanup(lambda: (setattr(tarefa.tarefa, "rodando", orig[0]), setattr(tarefa.tarefa, "parar", orig[1])))

    def postar(self, caminho, dados):
        p = urllib.request.Request(f"http://127.0.0.1:{self.PORTA}{caminho}", data=json.dumps(dados).encode(), method="POST",
                                   headers={"Host": f"127.0.0.1:{self.PORTA}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(p, timeout=30) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_desligar_recusa_com_geracao(self):
        self.v.ligar()
        self.rodando = True
        codigo, corpo = self.postar("/api/desligar", {})
        self.assertEqual(codigo, 409)
        self.assertIn("Há uma geração em andamento", corpo["erro"])
        self.assertEqual(self.paradas, [])
        self.assertNotEqual(self.v.estado()["situacao"], "desligado")
        codigo, _ = self.postar("/api/desligar", {"confirmar": True})
        self.assertEqual(codigo, 200)
        self.assertEqual(self.paradas, [1])
        self.assertEqual(self.v.estado()["situacao"], "desligado")
        self.fio.join(5)
        self.assertFalse(self.fio.is_alive())

    def test_ligar_comfy_chama_o_vigia(self):
        self.v.ligar()
        self.m.procs[0].saiu = 1
        self.v.passo(False, 0)
        self.v.passo(False, 181)
        self.v.passo(False, 400)  # caiu
        self.assertEqual(self.v.estado()["situacao"], "caiu")
        self.assertEqual(self.postar("/api/ligar-comfy", {})[0], 200)
        self.assertEqual(self.v.estado()["situacao"], "ligando")

    def test_ligar_comfy_recusa_se_ja_ligado(self):
        self.v.ligar()
        self.assertEqual(self.postar("/api/ligar-comfy", {}), (409, {"erro": "O ComfyUI já está ligado."}))  # ligando
        self.m.responde = True
        self.v.passo(False, 0)
        self.assertEqual(self.postar("/api/ligar-comfy", {}), (409, {"erro": "O ComfyUI já está ligado."}))  # pronto
        self.assertEqual(len(self.m.abertos()), 1)

    def test_ligar_comfy_recusa_com_geracao(self):
        self.m.porta, self.m.nome_porta = 777, "chrome.exe"
        self.v.ligar()  # caiu: porta ocupada
        self.rodando = True
        self.assertEqual(self.postar("/api/ligar-comfy", {})[0], 409)
        self.assertEqual(self.m.abertos(), [])


class Lancador(unittest.TestCase):
    def test_segunda_instancia_so_abre_navegador(self):
        porta = 8196
        s = servidor.criar(porta)
        fio = threading.Thread(target=s.serve_forever, daemon=True)
        fio.start()
        self.addCleanup(fio.join, 5)
        self.addCleanup(s.server_close)
        self.addCleanup(s.shutdown)
        pyw = carregar_pyw()
        aberturas = []

        def proibido(*a, **k):
            raise AssertionError("nao devia criar o Vigia")
        pyw.principal(porta, aberturas.append, criar_vigia=proibido)
        self.assertEqual(aberturas, [f"http://127.0.0.1:{porta}/"])

    def test_primeira_instancia_liga_serve_e_fecha(self):
        porta = 8195
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        m = Mundo(d.name)
        v = m.vigia()
        pyw = carregar_pyw()
        urls = []

        def abrir_navegador(url):
            urls.append(url)
            req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/desligar", data=b"{}", method="POST", headers={"Host": f"127.0.0.1:{porta}", "Content-Type": "application/json"})
            threading.Thread(target=lambda: urllib.request.urlopen(req, timeout=30).read()).start()
        import mcp_completo
        self.addCleanup(setattr, mcp_completo, "PORTA_API", mcp_completo.PORTA_API)
        pyw.principal(porta, abrir_navegador, criar_vigia=lambda: v)
        self.assertEqual(urls, [f"http://127.0.0.1:{porta}/"])
        # O chamar_api do MCP fala com a porta escolhida
        self.assertEqual(mcp_completo.PORTA_API, porta)
        self.assertEqual(len(m.abertos()), 1)
        self.assertEqual(v.estado()["situacao"], "desligado")

    def test_ligar_que_quebra_ainda_abre_a_pagina(self):
        porta = 8194
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        m = Mundo(d.name)
        m.erro_abrir = FileNotFoundError(2, "python.exe sumiu")
        v = m.vigia()
        pyw = carregar_pyw()
        urls, estados = [], []

        def abrir_navegador(url):
            urls.append(url)

            def visitar():
                pedido = urllib.request.Request(f"http://127.0.0.1:{porta}/api/estado", headers={"Host": f"127.0.0.1:{porta}"})
                with urllib.request.urlopen(pedido, timeout=60) as r:
                    estados.append(json.load(r)["comfy"])
                req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/desligar", data=b"{}", method="POST", headers={"Host": f"127.0.0.1:{porta}", "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=30).read()
            threading.Thread(target=visitar).start()
        pyw.principal(porta, abrir_navegador, criar_vigia=lambda: v)
        self.assertEqual(urls, [f"http://127.0.0.1:{porta}/"])
        self.assertEqual(estados[0]["situacao"], "caiu")
        self.assertTrue(estados[0]["mensagem"].startswith("Não consegui ligar o ComfyUI: "), estados[0]["mensagem"])
        self.assertIn("python.exe sumiu", estados[0]["mensagem"])
        self.assertTrue(estados[0]["mensagem"].endswith(". Veja logs\\estudio.log."), estados[0]["mensagem"])
        self.assertIn("Traceback", m.log())

    def test_acesso_remoto_tenta_de_novo_ate_abrir(self):
        """O IP da VPN ainda nao existe (VPN ligando depois do estudio): tenta de novo e avisa so na 1a falha e ao abrir."""
        import contextlib, io
        pyw = carregar_pyw()

        class Falso:
            def __init__(self):
                self.servindo, self.fechado = threading.Event(), False

            def serve_forever(self):
                self.servindo.set()

            def shutdown(self):
                pass

            def server_close(self):
                self.fechado = True
        chamadas, falso = [], Falso()

        def criar_remoto(porta, vigia):
            chamadas.append((porta, vigia))
            if len(chamadas) <= 2:
                raise OSError(10049, "endereço não disponível")
            return falso
        saida = io.StringIO()
        r = pyw.AcessoRemoto(8199, "vigia", criar_remoto=criar_remoto, intervalo=0.01)
        with contextlib.redirect_stdout(saida):
            self.assertIs(r.tentar(), falso)
        self.assertEqual(chamadas, [(8199, "vigia")] * 3)
        self.assertTrue(falso.servindo.wait(5))
        linhas = saida.getvalue().splitlines()
        self.assertEqual(len(linhas), 2, linhas)
        self.assertTrue(linhas[0].startswith("AVISO: não consegui abrir o acesso remoto"), linhas)
        self.assertEqual(linhas[1], "Acesso remoto aberto.")
        r.fechar()
        self.assertTrue(falso.fechado)
        self.assertIsNone(r.servidor)

    def test_acesso_remoto_sem_configuracao_nao_tenta_de_novo(self):
        pyw = carregar_pyw()
        chamadas = []
        r = pyw.AcessoRemoto(8199, None, criar_remoto=lambda p, v: chamadas.append(p), intervalo=0.01)
        self.assertIsNone(r.tentar())
        self.assertEqual(len(chamadas), 1)

    def test_acesso_remoto_para_quando_o_estudio_fecha(self):
        import contextlib, io
        pyw = carregar_pyw()

        def criar_remoto(porta, vigia):
            raise OSError("sem VPN")
        r = pyw.AcessoRemoto(8199, None, criar_remoto=criar_remoto, intervalo=0.01)
        with contextlib.redirect_stdout(io.StringIO()):
            fio = r.em_fundo()
            time.sleep(0.05)
            r.fechar()
            fio.join(5)
        self.assertFalse(fio.is_alive())

    def test_importa_sem_stdout_nem_stderr(self):
        """No pythonw.exe sys.stdout e sys.stderr sao None: nenhum import da cadeia do lancador pode quebrar."""
        codigo = ("import sys, importlib.util\n"
                  "sys.stdout = None; sys.stderr = None\n"
                  f"sys.path.insert(0, {str(ESTUDIO)!r})\n"
                  "import config, servidor, vigia, comfy_api, continuar_video, acoes, ambiente, projetos, tarefa\n"
                  f"spec = importlib.util.spec_from_file_location('estudio_pyw', {str(ESTUDIO / 'estudio.pyw')!r})\n"
                  "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")
        r = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True, creationflags=config.SEM_JANELA, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)


class JobDoWindows(unittest.TestCase):
    """Teste de verdade do Job Object, so com um filho inofensivo (um python que dorme)."""

    def test_fechar_o_job_mata_o_filho(self):
        filho = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=config.SEM_JANELA)
        self.addCleanup(lambda: filho.poll() is None and (filho.kill(), filho.wait(5)))
        job = vigia.job_que_mata_ao_fechar()
        vigia.vincular_ao_job(job, filho)
        time.sleep(0.3)
        self.assertIsNone(filho.poll())  # vincular nao mata
        vigia.fechar_job(job)  # como se o lancador tivesse morrido
        fim = time.monotonic() + 5
        while filho.poll() is None and time.monotonic() < fim:
            time.sleep(0.1)
        self.assertIsNotNone(filho.poll(), "o filho continuou vivo depois de fechar o job")


def carregar_pyw():
    spec = importlib.util.spec_from_file_location("estudio_pyw", ESTUDIO / "estudio.pyw")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


if __name__ == "__main__":
    unittest.main()
