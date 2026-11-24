"""Testes da troca de personagem em foto (troca_foto.py): recortes, validacao, grafos das passadas, projeto e apagar.
Nao usam o ComfyUI nem a placa. Uso: python -I testar_troca_foto.py"""
import json, shutil, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import cv2
import numpy as np

import acoes, config, loras, projetos, troca_foto, validacao
import texto_para_imagem as t2i


def imagem(caminho, largura=400, altura=600):
    cv2.imencode(".png", np.full((altura, largura, 3), 128, np.uint8))[1].tofile(str(caminho))


class Recortes(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_detector_vai_junto_do_estudio(self):
        self.assertTrue(troca_foto.YUNET.is_file())

    def test_limites_da_cabeca_e_da_roupa(self):
        # Rosto em (100, 200), 50 x 60: o cabelo acima, para logo abaixo do queixo; a roupa comeca abaixo do queixo
        self.assertEqual(troca_foto.limites_cabeca((100, 200, 50, 60), 1000, 1000), (70, 146, 180, 264))
        self.assertEqual(troca_foto.topo_sem_cabeca((100, 200, 50, 60), 1000), 269)
        # Rosto colado na borda: o recorte nao sai da imagem
        self.assertEqual(troca_foto.limites_cabeca((0, 0, 50, 60), 80, 70), (0, 0, 80, 64))

    def test_sem_rosto_usa_a_foto_inteira(self):
        imagem(self.d / "sem_rosto.png")
        self.assertFalse(troca_foto.recortar(self.d / "sem_rosto.png", self.d / "saida.png", "cabeca"))
        self.assertEqual((self.d / "saida.png").read_bytes(), (self.d / "sem_rosto.png").read_bytes())

    def test_recorta_cabeca_e_roupa_pelo_rosto(self):
        imagem(self.d / "foto.png")
        with mock.patch.object(troca_foto, "caixa_rosto", lambda img, det=None: (100, 100, 80, 100)):
            self.assertTrue(troca_foto.recortar(self.d / "foto.png", self.d / "cabeca.png", "cabeca", object()))
            self.assertTrue(troca_foto.recortar(self.d / "foto.png", self.d / "roupa.png", "roupa", object()))
        ler = lambda n: cv2.imdecode(np.fromfile(str(self.d / n), np.uint8), cv2.IMREAD_COLOR).shape[:2]
        self.assertEqual(ler("cabeca.png"), (198, 176))
        self.assertEqual(ler("roupa.png"), (385, 400))

    def test_recorte_minusculo_vai_inteiro(self):
        imagem(self.d / "foto.png")
        with mock.patch.object(troca_foto, "caixa_rosto", lambda img, det=None: (10, 560, 20, 30)):
            self.assertFalse(troca_foto.recortar(self.d / "foto.png", self.d / "roupa.png", "roupa", object()))

    def test_preparar_e_a_ordem_das_passadas(self):
        imagem(self.d / "rosto.png")
        imagem(self.d / "roupa.png")
        prontos, avisos = troca_foto.preparar({"rosto": "rosto.png", "roupa": "roupa.png"}, "proj", self.d)
        # Os recortes vao para os temporarios do projeto (entrada_temp): o grafo recebe o nome com a subpasta
        self.assertEqual(prontos, {"rosto": "estudio/temp/proj/trocafoto_proj_rosto.png", "roupa": "estudio/temp/proj/trocafoto_proj_roupa.png"})
        self.assertTrue((self.d / "estudio" / "temp" / "proj" / "trocafoto_proj_roupa.png").is_file())
        # Sem rosto nas fotos sinteticas: as duas vao inteiras, com aviso
        self.assertEqual(len(avisos), 2)
        prontos, avisos = troca_foto.preparar({"rosto": None, "roupa": "roupa.png"}, "p2", self.d)
        self.assertEqual((prontos["rosto"], len(avisos)), (None, 1))
        self.assertEqual(troca_foto.passadas({"rosto": "a", "roupa": "b"}), ["rosto", "roupa"])
        self.assertEqual(troca_foto.passadas({"rosto": None, "roupa": "b"}), ["roupa"])


class Validacao(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        for n in ("base.png", "rosto.png", "roupa.png"):
            (self.d / n).write_bytes(b"png")
        self.mapa = {troca_foto.LORA_ROSTO.lower(): f"klein\\{troca_foto.LORA_ROSTO}"}
        for alvo, nome, valor in ((config, "ENTRADA", self.d), (validacao, "faltam_texto", lambda k: []), (loras, "mapa", lambda: self.mapa)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def test_os_dois(self):
        r = validacao.validar_troca_foto({"partida": "base.png", "rosto": "rosto.png", "roupa": "roupa.png", "quantidade": "2", "semente": "7"})
        self.assertEqual((r["modelo"], r["partida"], r["referencia"], r["quantidade"], r["semente"], r["passos"]), ("klein_edit", "base.png", None, 2, 7, 4))
        self.assertEqual(r["troca_foto"], {"rosto": "rosto.png", "roupa": "roupa.png"})
        self.assertEqual(r["prompt"], "Troca em foto: rosto e roupa")
        # Os campos de um projeto de texto estao todos la: o texto_para_imagem le proporcao e megapixels
        self.assertTrue(set(validacao.PADRAO_TEXTO) <= set(r))

    def test_so_a_roupa_nao_precisa_da_lora(self):
        self.mapa = {}
        r = validacao.validar_troca_foto({"partida": "base.png", "roupa": "roupa.png"})
        self.assertEqual((r["troca_foto"], r["semente"], r["quantidade"]), ({"rosto": None, "roupa": "roupa.png"}, None, 1))

    def test_recusas(self):
        for errado in ({"rosto": "rosto.png"}, {"partida": "base.png"}, {"partida": "base.png", "rosto": "sumiu.png"},
                       {"partida": "base.png", "roupa": "roupa.png", "quantidade": 5}, {"partida": "base.png", "roupa": "roupa.png", "semente": "x"}):
            with self.assertRaises(validacao.Erro, msg=errado):
                validacao.validar_troca_foto(errado)

    def test_sem_a_lora_recusa_o_rosto(self):
        self.mapa = {}
        with self.assertRaisesRegex(validacao.Erro, "LoRA de troca de rosto"):
            validacao.validar_troca_foto({"partida": "base.png", "rosto": "rosto.png"})
        self.assertTrue(validacao.situacao_troca_foto()["falta_lora_rosto"])

    def test_sem_o_klein_recusa(self):
        with mock.patch.object(validacao, "faltam_texto", lambda k: ["flux-2-klein-4b-fp8.safetensors"]):
            with self.assertRaisesRegex(validacao.Erro, "Klein"):
                validacao.validar_troca_foto({"partida": "base.png", "roupa": "roupa.png"})


class Grafos(unittest.TestCase):
    P = {"passos": 4}

    def test_rosto_com_a_lora_e_o_pedido_do_autor(self):
        g = t2i.grafo_troca_foto(self.P, "rosto", "base.png", "trocafoto_x_rosto.png", 42, "texto/x/imagem1_rosto")
        self.assertEqual((g["50"]["inputs"]["lora_name"], g["50"]["inputs"]["strength_model"], g["50"]["inputs"]["model"]), (troca_foto.LORA_ROSTO, 1.0, ["1", 0]))
        self.assertEqual(g["40"]["inputs"]["model"], ["50", 0])
        self.assertEqual(g["4"]["inputs"]["text"], troca_foto.PEDIDO_ROSTO)
        self.assertTrue(troca_foto.PEDIDO_ROSTO.startswith("head_swap:"))
        # Corpo na imagem 1 e rosto na 2, a saida no tamanho da base, com a semente e o prefixo da passada
        self.assertEqual((g["30"]["inputs"]["image"], g["32"]["inputs"]["image"]), ("base.png", "trocafoto_x_rosto.png"))
        self.assertEqual((g["43"]["inputs"]["noise_seed"], g["9"]["inputs"]["filename_prefix"]), (42, "texto/x/imagem1_rosto"))

    def test_roupa_sem_lora(self):
        g = t2i.grafo_troca_foto(self.P, "roupa", "trocafoto_x_1_rosto.png", "trocafoto_x_roupa.png", 42, "p")
        self.assertNotIn("50", g)
        self.assertEqual(g["40"]["inputs"]["model"], ["1", 0])
        self.assertEqual((g["4"]["inputs"]["text"], g["30"]["inputs"]["image"]), (troca_foto.PEDIDO_ROUPA, "trocafoto_x_1_rosto.png"))


class Projeto(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.proj, self.entrada, self.saida = self.d / "projetos", self.d / "input", self.d / "output"
        for p in (self.proj, self.entrada, self.saida):
            p.mkdir()
        for alvo, nome, valor in ((config, "PROJETOS", self.proj), (config, "ENTRADA", self.entrada), (config, "SAIDA", self.saida)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def criar(self, nome="tf"):
        pasta = self.proj / nome
        pasta.mkdir()
        (pasta / "interface.json").write_text(json.dumps({"tipo": "texto", "prompt": "Troca em foto: rosto", "quantidade": 2,
                                                          "troca_foto": {"rosto": "r.png", "roupa": None}}), encoding="utf-8")
        (pasta / "estado.json").write_text(json.dumps({"tipo": "texto", "avisos": ["Não achei um rosto na foto do rosto: ela foi usada inteira."],
                                                       "imagens": [{"n": n, "arquivo": f"imagem_{n}.png", "semente": n} for n in (1, 2)]}), encoding="utf-8")
        for n in (1, 2):
            (pasta / f"imagem_{n}.png").write_bytes(b"p")
        return pasta

    def test_pagina_ve_a_troca_e_os_avisos(self):
        p = projetos.ler_projeto(self.criar())
        self.assertEqual((p["tipo"], p["troca_foto"], len(p["avisos"]), p["completo"]), ("texto", True, 1, True))

    def test_apagar_leva_os_recortes_e_as_passadas(self):
        self.criar()
        for nome in ("trocafoto_tf_rosto.png", "trocafoto_tf_roupa.png", "trocafoto_tf_1_rosto.png", "trocafoto_tf_2_roupa.png", "trocafoto_outro_rosto.png", "base.png"):
            (self.entrada / nome).write_bytes(b"x")
        _, arquivos = projetos.alvos_apagar("tf")
        self.assertEqual(sorted(f.name for f in arquivos), ["trocafoto_tf_1_rosto.png", "trocafoto_tf_2_roupa.png", "trocafoto_tf_rosto.png", "trocafoto_tf_roupa.png"])

    def test_descartar_uma_leva_a_copia_de_cada_passada(self):
        self.criar()
        saida = self.saida / "texto" / "tf"
        saida.mkdir(parents=True)
        for nome in ("imagem2_rosto_00001_.png", "imagem2_roupa_00001_.png", "imagem1_rosto_00001_.png"):
            (saida / nome).write_bytes(b"x")
        _, arquivos = projetos.alvos_apagar_imagem("tf", "imagem_2.png")
        self.assertEqual(sorted(f.name for f in arquivos), ["imagem2_rosto_00001_.png", "imagem2_roupa_00001_.png", "imagem_2.png"])


class Iniciar(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.iniciados = []
        tarefa = types.SimpleNamespace(rodando=lambda: False, projeto=None, iniciar_texto=self.iniciados.append)
        for n in ("base.png", "roupa.png"):
            (self.d / n).write_bytes(b"png")
        for alvo, nome, valor in ((config, "PROJETOS", self.d), (config, "ENTRADA", self.d), (acoes.tarefa, "tarefa", tarefa),
                                  (acoes, "exigir_comfy_livre", lambda: None), (validacao, "faltam_texto", lambda k: [])):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def test_grava_um_projeto_de_texto_sem_pedir_autorizacao(self):
        # A confirmacao de autorizacao saiu em 23/11/2026 (uso pessoal, decisao do usuario)
        pedido = {"projeto": "minha_troca", "ajustes": {"partida": "base.png", "roupa": "roupa.png"}}
        acoes.acao_iniciar_troca_foto(pedido)
        p = json.loads((self.d / "minha_troca" / "interface.json").read_text(encoding="utf-8"))
        self.assertEqual((p["tipo"], p["troca_foto"], p["modelo"]), ("texto", {"rosto": None, "roupa": "roupa.png"}, "klein_edit"))
        self.assertIn("autorizado_em", p)
        self.assertEqual(self.iniciados, ["minha_troca"])
        # Carregar as configuracoes: uma foto que sumiu da entrada volta vazia, e a autorizacao nao vem junto
        (self.d / "roupa.png").unlink()
        r = acoes.acao_reusar({"projeto": "minha_troca"})
        self.assertEqual((r["tipo"], r["config"]["troca_foto"]["roupa"]), ("texto", None))
        self.assertNotIn("autorizado_em", r["config"])


if __name__ == "__main__":
    unittest.main()
