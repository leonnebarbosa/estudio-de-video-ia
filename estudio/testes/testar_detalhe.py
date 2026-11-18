"""Testes do detalhe do ComfyUI (fase, ritmo dos passos, linhas do registro). Nao usam o ComfyUI nem a placa.

Uso: python -I testar_detalhe.py
"""
import sys, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import detalhe_comfy
from detalhe_comfy import Detalhe, fase_de

GRAFO = {"1": {"class_type": "UNETLoader"}, "2": {"class_type": "CLIPTextEncode"}, "3": {"class_type": "SamplerCustomAdvanced"},
         "4": {"class_type": "VAEDecodeTiled"}, "125:12": {"class_type": "KSampler"}, "9": {"class_type": "MiniMaxH3ImageToVideo"}}


def rodando(no, valor=0, maximo=1):
    return {no: {"state": "running", "value": valor, "max": maximo}}


class Fases(unittest.TestCase):
    def test_nomes_de_no(self):
        casos = {"UNETLoader": "carregar", "LoraLoaderModelOnly": "carregar", "LoadImage": "ler", "VHS_LoadVideo": "ler", "CLIPTextEncode": "texto",
                 "VAEEncode": "codificar", "SamplerCustomAdvanced": "amostrar", "VAEDecodeTiled": "decodificar", "SaveVideo": "salvar",
                 "VHS_VideoCombine": "salvar", "MiniMaxH3ImageToVideo": "outro", "": "outro"}
        for tipo, fase in casos.items():
            self.assertEqual(fase_de(tipo), fase, tipo)


class Acompanhamento(unittest.TestCase):
    def setUp(self):
        self.linhas = []
        self.relogio = 1000.0
        patcher = mock.patch.object(detalhe_comfy.time, "time", lambda: self.relogio)
        patcher.start()
        self.addCleanup(patcher.stop)
        mon = types.SimpleNamespace(ultimo={"vram_mib": 9830, "temp": 74, "watts": 285.4})
        self.d = Detalhe(mon, GRAFO, escrever=lambda texto, flush=False: self.linhas.append(texto))

    def test_fase_e_linha_no_registro_com_a_placa(self):
        self.assertEqual(self.d.dados(), {})
        self.relogio += 5
        self.assertTrue(self.d.evento(rodando("1")))
        self.assertEqual(self.d.dados()["fase_nome"], "Carregando modelos")
        self.assertEqual(self.linhas, ["[0:05] Carregando modelos (UNETLoader #1) | placa 74 °C, 9,6 GB, 285 W"])

    def test_mesma_fase_nao_repete_linha(self):
        self.d.tipos["1b"] = "VAELoader"
        self.d.evento(rodando("1"))
        self.d.evento({"1": {"state": "finished"}, **rodando("1b")})
        self.d.evento(rodando("1b"))
        self.assertEqual(len(self.linhas), 1)

    def test_ritmo_dos_passos_e_fim_da_amostragem(self):
        self.d.evento(rodando("3", 0, 8))
        self.relogio += 30  # aquecimento: nao entra no ritmo
        self.d.evento(rodando("3", 1, 8))
        self.relogio += 20
        self.d.evento(rodando("3", 3, 8))
        self.assertEqual(self.d.dados()["s_passo"], 10.0)
        self.relogio += 50
        self.d.evento(rodando("3", 8, 8))
        self.d.evento(rodando("4"))
        self.assertIn("amostragem pronta: 8 passos em 1:40 (10.0 s por passo)", self.linhas[-2])
        self.assertTrue(self.linhas[-1].endswith("Decodificando (VAEDecodeTiled #4) | placa 74 °C, 9,6 GB, 285 W"))

    def test_no_com_passos_vence_quando_ha_dois_rodando(self):
        self.d.evento({**rodando("2"), **rodando("125:12", 2, 6)})
        self.assertEqual((self.d.dados()["fase"], self.d.valor, self.d.maximo), ("amostrar", 2, 6))

    def test_sem_no_rodando_nao_muda_nada(self):
        self.assertFalse(self.d.evento({"1": {"state": "finished"}}))
        self.assertEqual(self.linhas, [])

    def test_grafo_novo_esquece_o_anterior(self):
        self.d.evento(rodando("3", 2, 8))
        self.d.reiniciar({"3": {"class_type": "SaveVideo"}})
        self.d.evento(rodando("3"))
        self.assertEqual(self.d.dados()["fase"], "salvar")

    def test_sem_leitura_da_placa(self):
        d = Detalhe(types.SimpleNamespace(rotulo=""), GRAFO, escrever=lambda texto, flush=False: self.linhas.append(texto))
        d.evento(rodando("9"))
        self.assertEqual(self.linhas, ["[0:00] Processando (MiniMaxH3ImageToVideo #9)"])


if __name__ == "__main__":
    unittest.main()
