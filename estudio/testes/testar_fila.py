"""Testes da fila de geracoes (fila.py e tarefa._pedir). Nao rodam geracao nenhuma: o lancamento e falso.

Uso: python -I testar_fila.py
"""
import json, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fila, tarefa, validacao


class Falsa:
    """Faz o papel da tarefa: lanca guardando o pedido e diz se ha uma geracao rodando."""

    def __init__(self):
        self.lancados, self.rodando_agora, self.trava = [], False, threading.Lock()

    def lancar(self, cmd, projeto, modo, tipo):
        self.lancados.append(projeto)
        self.rodando_agora = True

    def rodando(self):
        return self.rodando_agora


def esperar(cond, limite=3.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class Fila(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.arq = Path(d.name) / "fila.json"
        self.t = Falsa()
        self.comfy = True
        self.f = self.nova()

    def nova(self):
        return fila.Fila(self.t.lancar, self.t.rodando, self.t.trava, lambda: self.comfy, arquivo=self.arq, intervalo=0.05, espera_comfy=0.3, passo_comfy=0.02)

    def por(self, *projetos):
        with self.t.trava:
            return [self.f.adicionar(["python", p], p, "gerar", "troca") for p in projetos]

    def test_espera_a_atual_e_segue_a_ordem(self):
        self.t.rodando_agora = True
        self.assertEqual(self.por("a", "b"), [1, 2])
        self.assertTrue(self.f.ativa() and self.f.tem("a"))
        self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8"))["itens"][0]["projeto"], "a")
        time.sleep(0.1)
        self.assertEqual(self.t.lancados, [])          # a atual ainda roda
        self.t.rodando_agora = False
        self.f.terminou("atual", 0, False)
        self.assertTrue(esperar(lambda: self.t.lancados == ["a"]))
        self.t.rodando_agora = False
        self.f.terminou("a", 0, False)
        self.assertTrue(esperar(lambda: self.t.lancados == ["a", "b"]))
        self.assertEqual(self.f.itens(), [])

    def test_espera_o_intervalo(self):
        self.f.intervalo = 0.4
        self.t.rodando_agora = True
        self.por("a")
        self.t.rodando_agora = False
        self.f.terminou("atual", 0, False)
        self.assertIsNotNone(self.f.resumo()["proxima_em"])
        time.sleep(0.15)
        self.assertEqual(self.t.lancados, [])
        self.assertTrue(esperar(lambda: self.t.lancados == ["a"]))

    def test_falha_pausa_e_continuar_retoma(self):
        self.t.rodando_agora = True
        self.por("a")
        self.t.rodando_agora = False
        self.f.terminou("atual", 4, False)
        r = self.f.resumo()
        self.assertTrue(r["pausada"])
        self.assertIn("falhou", r["motivo"])
        self.assertFalse(self.f.ativa())
        time.sleep(0.1)
        self.assertEqual(self.t.lancados, [])
        self.f.continuar()
        self.assertTrue(esperar(lambda: self.t.lancados == ["a"]))
        self.assertFalse(self.f.resumo()["pausada"])

    def test_parada_pelo_usuario_pausa(self):
        self.t.rodando_agora = True
        self.por("a")
        self.f.terminou("atual", 1, True)
        self.assertIn("parou", self.f.resumo()["motivo"])

    def test_sem_pedidos_nao_pausa(self):
        self.f.terminou("atual", 4, False)
        self.assertFalse(self.f.resumo()["pausada"])

    def test_mover_e_tirar(self):
        self.t.rodando_agora = True
        self.por("a", "b", "c")
        ids = [i["id"] for i in self.f.itens()]
        self.f.mover(ids[2], -1)
        self.assertEqual([i["projeto"] for i in self.f.itens()], ["a", "c", "b"])
        self.f.mover(ids[0], -1)     # o primeiro nao sobe mais
        self.f.tirar(ids[1])
        self.assertEqual([i["projeto"] for i in self.f.itens()], ["a", "c"])
        with self.assertRaises(KeyError):
            self.f.tirar("nao_existe")

    def test_sobrevive_ao_reinicio(self):
        self.t.rodando_agora = True
        self.por("a")
        self.assertEqual([i["projeto"] for i in self.nova().itens()], ["a"])

    def test_ao_ligar_sem_retomada_pausa(self):
        self.t.rodando_agora = True
        self.por("a")
        g = self.nova()
        g.ao_ligar(None, "o PC nao reiniciou depois que ela comecou")
        self.assertTrue(g.resumo()["pausada"])
        self.assertIn("reiniciado", g.resumo()["motivo"])
        h = self.nova()
        h.dados["pausada"] = False
        h.ao_ligar(None, "ja tinha sido retomada uma vez e caiu de novo")
        self.assertIn("duas vezes", h.resumo()["motivo"])

    def test_queda_com_retomada_segue_depois_dela(self):
        self.t.rodando_agora = True
        self.por("b")
        # A geracao "a" caiu (a placa sumiu): o script morre com erro e a fila pausa por ela
        self.f.terminou("a", 4, False)
        self.assertTrue(self.f.resumo()["pausada"])
        # O PC reinicia e a retomada relanca "a": a fila volta a andar e "b" vem depois
        g = self.nova()
        fio = threading.Thread(target=lambda: None)
        fio.start()
        self.t.rodando_agora = True
        g.ao_ligar(fio, "o PC reiniciou no meio da geracao")
        self.assertFalse(g.resumo()["pausada"])
        self.t.rodando_agora = False
        g.terminou("a", 0, False)
        self.assertTrue(esperar(lambda: self.t.lancados == ["b"]))

    def test_comfy_que_nao_fica_pronto_pausa(self):
        self.comfy = False
        self.t.rodando_agora = True
        self.por("a")
        self.t.rodando_agora = False
        self.f.terminou("atual", 0, False)
        self.assertTrue(esperar(lambda: self.f.resumo()["pausada"], 3))
        self.assertIn("ComfyUI", self.f.resumo()["motivo"])
        self.assertEqual(self.t.lancados, [])


class PedirNaTarefa(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.t = tarefa.Tarefa()
        self.t.fila = fila.Fila(self.t._lancar, self.t.rodando, self.t.trava, lambda: True, arquivo=Path(d.name) / "fila.json", intervalo=60)
        self.lancados = []
        m = mock.patch.object(self.t, "_lancar", lambda cmd, projeto, modo, tipo: self.lancados.append(projeto))
        m.start()
        self.addCleanup(m.stop)

    def test_sem_geracao_comeca_agora(self):
        with self.t.trava:
            self.assertEqual(self.t._pedir(["x"], "a", "gerar", "troca"), {"fila": 0})
        self.assertEqual(self.lancados, ["a"])

    def test_com_geracao_vai_para_a_fila_e_recusa_repetido(self):
        self.t.proc, self.t.codigo, self.t.projeto = object(), None, "atual"
        with self.t.trava:
            self.assertEqual(self.t._pedir(["x"], "a", "gerar", "troca"), {"fila": 1})
            self.assertEqual(self.t._pedir(["x"], "b", "gerar", "texto"), {"fila": 2})
            for repetido in ("a", "atual"):
                with self.assertRaises(validacao.Erro):
                    self.t._pedir(["x"], repetido, "gerar", "troca")
        self.assertEqual(self.lancados, [])
        self.t.fila._cancelar()

    def test_fila_ativa_sem_geracao_vai_para_o_fim(self):
        with self.t.trava:
            self.t.fila.dados["itens"].append({"id": "1", "cmd": ["x"], "projeto": "a", "modo": "gerar", "tipo": "troca", "criado": 0})
            self.assertEqual(self.t._pedir(["x"], "b", "gerar", "troca"), {"fila": 2})
        self.assertEqual(self.lancados, [])
        self.t.fila._cancelar()


if __name__ == "__main__":
    unittest.main()
