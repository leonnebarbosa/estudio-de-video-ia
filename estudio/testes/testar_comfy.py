"""Testes da conversa com o ComfyUI: leitura da placa, espera do pedido e cache das opcoes.
Tudo com nvidia-smi, ComfyUI e relogio falsos: nao toca na placa nem no ComfyUI.

Uso: python -I testar_comfy.py
"""
import json, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ambiente, comfy_api, continuar_video

MSG_PERDIDO = "o ComfyUI foi reiniciado e perdeu o pedido"


def smi_falso(temp="70.66", vram="8447"):
    """subprocess.run falso que responde como o nvidia-smi novo (temperatura com decimais)."""
    def run(cmd, *a, **k):
        if "--query-gpu=memory.used,temperature.gpu" in cmd:
            return SimpleNamespace(stdout=f"{vram}, {temp}\n", returncode=0)
        if "--query-gpu=clocks.gr,power.draw" in cmd:
            return SimpleNamespace(stdout="1905, 280.50\n", returncode=0)
        raise AssertionError(f"comando inesperado: {cmd}")
    return run


class RelogioFalso:
    def __init__(self):
        self.agora = 0.0

    def time(self):
        return self.agora

    def sleep(self, s):
        self.agora += s


class Placa(unittest.TestCase):
    def test_gpu_aceita_decimais(self):
        with mock.patch.object(comfy_api.subprocess, "run", smi_falso()):
            self.assertEqual(comfy_api.gpu(), (8447, 71))
        with mock.patch.object(comfy_api.subprocess, "run", smi_falso(temp="64", vram="512.4")):
            self.assertEqual(comfy_api.gpu(), (512, 64))

    def test_monitor_grava_linha_com_temperatura_decimal(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "gpu.csv"
            with mock.patch.object(subprocess, "run", smi_falso()), mock.patch.object(continuar_video, "posta") as posta:
                m = continuar_video.Monitor(arq, intervalo=0.01)
                m.start()
                time.sleep(0.3)
                m.fim.set()
                m.join(5)
            linhas = arq.read_text(encoding="utf-8").splitlines()
            self.assertEqual(linhas[0], "hora,etapa,vram_mib,temp,clock_mhz,watts")
            self.assertGreater(len(linhas), 1)
            self.assertTrue(linhas[1].endswith(",8447,71,1905,280.50"), linhas[1])
            self.assertFalse(m.quente)
            posta.assert_not_called()

    def test_monitor_corta_a_85_graus_com_decimais(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(subprocess, "run", smi_falso(temp="85.4")), mock.patch.object(continuar_video, "posta") as posta:
                m = continuar_video.Monitor(Path(d) / "gpu.csv", intervalo=0.01)
                m.start()
                time.sleep(0.3)
                m.fim.set()
                m.join(5)
            self.assertTrue(m.quente)
            posta.assert_called_once_with("/interrupt", {})


class Espera(unittest.TestCase):
    """rodar(): o pedido some quando o vigia religa o ComfyUI no meio da geracao."""

    def rodar(self, historico, fila, limite=3600):
        """historico(n) e fila(n) dizem o que o ComfyUI responde na consulta n (0, 1, 2...)."""
        self.consultas = {"hist": 0, "fila": 0}

        def pega(caminho):
            if caminho == "/history/p1":
                r = historico(self.consultas["hist"])
                self.consultas["hist"] += 1
                return r
            if caminho == "/queue":
                r = fila(self.consultas["fila"])
                self.consultas["fila"] += 1
                return r
            raise AssertionError(caminho)

        def posta(caminho, dados):
            return json.dumps({"prompt_id": "p1"}).encode() if caminho == "/prompt" else b"{}"
        rel = RelogioFalso()
        with mock.patch.object(comfy_api, "pega", pega), mock.patch.object(comfy_api, "posta", posta), \
             mock.patch.object(comfy_api, "gpu", lambda: (8000, 70)), mock.patch.object(comfy_api, "time", rel):
            return comfy_api.rodar({}, limite)

    PRONTO = {"p1": {"status": {"status_str": "success", "messages": []}, "outputs": {"9": {"x": 1}}}}
    VAZIA = {"queue_running": [], "queue_pending": []}
    NA_FILA = {"queue_running": [[0, "p1", {}, {}, []]], "queue_pending": []}

    def test_pedido_perdido_volta_logo(self):
        r = self.rodar(lambda n: {}, lambda n: self.VAZIA)
        self.assertEqual(r["status"], "servidor caiu")
        self.assertEqual(r["erro"], MSG_PERDIDO)
        self.assertEqual(self.consultas["fila"], 3)
        self.assertLess(r["segundos"], 60)

    def test_pedido_na_fila_espera_ate_acabar(self):
        r = self.rodar(lambda n: self.PRONTO if n >= 10 else {}, lambda n: self.NA_FILA)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["saidas"], {"9": {"x": 1}})
        self.assertEqual(r["temp_max"], 70)

    def test_pedido_na_espera_tambem_conta(self):
        pendente = {"queue_running": [[0, "outro", {}, {}, []]], "queue_pending": [[1, "p1", {}, {}, []]]}
        r = self.rodar(lambda n: self.PRONTO if n >= 6 else {}, lambda n: pendente)
        self.assertEqual(r["status"], "success")

    def test_sumico_curto_nao_derruba(self):
        # some 2 vezes, aparece, some 2 vezes, termina: nunca 3 seguidas
        fila = lambda n: self.NA_FILA if n == 2 else self.VAZIA
        r = self.rodar(lambda n: self.PRONTO if n >= 5 else {}, fila)
        self.assertEqual(r["status"], "success")

    def test_gpu_com_decimais_nao_derruba_a_espera(self):
        rel = RelogioFalso()
        posta = lambda c, d: json.dumps({"prompt_id": "p1"}).encode()
        with mock.patch.object(comfy_api.subprocess, "run", smi_falso()), mock.patch.object(comfy_api, "pega", lambda c: self.PRONTO), \
             mock.patch.object(comfy_api, "posta", posta), mock.patch.object(comfy_api, "time", rel):
            r = comfy_api.rodar({}, 3600)
        self.assertEqual((r["status"], r["pico_vram"], r["temp_max"]), ("success", 8447, 71))


class CacheOpcoes(unittest.TestCase):
    """ambiente.opcoes: resultado bom vale 30 s; falha (ComfyUI ainda ligando) vale no maximo 2 s."""

    def setUp(self):
        self.agora = 1000.0
        self.chamadas = 0
        self.resposta = None
        c = ambiente.opcoes
        guardado = (c.funcao, c.relogio, c.valor, c.quando, c.validade)
        self.addCleanup(lambda: (setattr(c, "funcao", guardado[0]), setattr(c, "relogio", guardado[1]), setattr(c, "valor", guardado[2]),
                                 setattr(c, "quando", guardado[3]), setattr(c, "validade", guardado[4])))

        def ler():
            self.chamadas += 1
            return self.resposta
        c.funcao, c.relogio, c.valor, c.quando, c.validade = ler, lambda: self.agora, None, 0, 0

    def test_falha_nao_fica_guardada(self):
        vazio = {"modelos": [], "loras": [], "samplers": [], "agendadores": [], "loras_troca": {}, "upscalers": []}
        bom = {"modelos": ["m"], "loras": [], "samplers": ["euler"], "agendadores": ["beta"], "loras_troca": {}, "upscalers": []}
        self.resposta = vazio
        self.assertEqual(ambiente.opcoes(), vazio)
        self.agora += 1
        ambiente.opcoes()
        self.assertEqual(self.chamadas, 1)  # dentro de 2 s ainda usa a falha
        self.agora += 1.5
        self.resposta = bom
        self.assertEqual(ambiente.opcoes(), bom)  # passou de 2 s: pergunta de novo
        self.assertEqual(self.chamadas, 2)
        self.resposta = vazio
        self.agora += 29
        self.assertEqual(ambiente.opcoes(), bom)  # o bom vale 30 s
        self.assertEqual(self.chamadas, 2)
        self.agora += 1.5
        self.assertEqual(ambiente.opcoes(), vazio)
        self.assertEqual(self.chamadas, 3)


if __name__ == "__main__":
    unittest.main()
