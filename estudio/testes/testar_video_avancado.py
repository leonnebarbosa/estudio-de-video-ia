"""Referências, pedido salvo e grafo do modo avançado, sem gerar na placa."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acoes
import config
import imagem_para_video
import projetos
import validacao
import video_avancado


class VideoAvancado(unittest.TestCase):
    def setUp(self):
        raiz = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for chave in ("ENTRADA", "ENVIOS", "PROJETOS"):
            pasta = raiz / chave
            pasta.mkdir()
            self.enterContext(patch.object(config, chave, pasta))
        for pasta, nome in ((config.ENTRADA, "foto.png"), (config.ENTRADA, "fundo.jpg"), (config.ENVIOS, "guia.mp4"),
                            (config.ENTRADA, "voz.wav"), (config.ENTRADA, "musica.mp3")):
            (pasta / nome).touch()
        self.refs = [{"tipo": tipo, "nome": nome, "arquivo": arquivo} for tipo, nome, arquivo in (
            ("audio", "voz", "voz.wav"), ("foto", "pessoa", "foto.png"), ("video", "guia", "guia.mp4"),
            ("foto", "lugar", "fundo.jpg"), ("audio", "musica", "musica.mp3"))]
        self.pedido = {"projeto": "cena", "prompt": "  @PESSOA in @lugar, as in @guia.\n\n<d>Oi</d> @voz and @musica.  ",
                       "referencias": self.refs, "proporcao": validacao.PROPORCOES[5], "megapixels": 0.4746,
                       "duracao": 5, "semente": "4321", "autorizacao": True}

    def test_prompt_livre_e_midias_numeradas_por_tipo(self):
        p = validacao.validar_avancado(self.pedido)
        self.assertEqual(p["avancado"]["prompt"], self.pedido["prompt"])
        g = imagem_para_video.grafo_avancado(p, self.refs, "imagem/cena/tomada1", p["semente"])
        no = g["20"]["inputs"]
        self.assertEqual(no["prompt"], "  <Picture 1> in <Picture 2>, as in <Video 1>.\n\n<d>Oi</d> <Audio 1> and <Audio 2>.  ")
        self.assertEqual(no["length"], 124)
        self.assertEqual(g[no["ref_images.ref_image_1"][0]]["inputs"]["image"], "fundo.jpg")
        self.assertEqual(g[no["ref_audios.ref_audio_1"][0]]["inputs"]["audio"], "musica.mp3")
        extrair = g[no["ref_videos.ref_video_0"][0]]
        self.assertEqual(extrair["class_type"], "GetVideoComponents")
        self.assertEqual(g[extrair["inputs"]["video"][0]]["inputs"]["file"], "guia.mp4")
        self.assertEqual(g["21"]["inputs"]["seed"], 4321)
        self.assertFalse(any(k.startswith("ref_video_audios.") for k in no))

    def test_rejeita_alias_duplicado_desconhecido_e_arquivo_fora_da_entrada(self):
        duplicado = dict(self.refs[0], nome="PESSOA")
        for mudanca in ({"referencias": [*self.refs, duplicado]}, {"prompt": "@ausente"},
                       {"prompt": "<Video 2>"}, {"referencias": [dict(self.refs[0], arquivo="../voz.wav")]},
                       {"referencias": [dict(self.refs[0], arquivo="guia.mp4")]}, {"duracao": 10, "megapixels": 1.2}):
            with self.subTest(mudanca=mudanca), self.assertRaises(validacao.Erro):
                validacao.validar_avancado({**self.pedido, **mudanca})

    def test_prepara_e_limpa_referencias_mesmo_quando_a_geracao_falha(self):
        def preparar(origem, destino, *args):
            destino.write_text(origem.name, encoding="utf-8")

        with patch.object(video_avancado, "preparar_arquivo", side_effect=preparar), self.assertRaises(RuntimeError):
            with video_avancado.preparar_referencias(self.refs, "cena", 1234567890, 124, 24) as refs:
                self.assertEqual(refs[1]["arquivo"], "foto.png")
                self.assertEqual((config.ENTRADA / refs[2]["arquivo"]).read_text(encoding="utf-8"), "guia.mp4")
                raise RuntimeError("geração interrompida")
        self.assertEqual(list(config.ENTRADA.glob("imagem_cena_*")), [])

    def test_salva_projeto_pede_geracao_e_reabre_com_as_referencias(self):
        with patch.object(acoes, "exigir_comfy_livre"), patch.object(video_avancado, "faltam", return_value=[]), \
                patch.object(acoes.tarefa.tarefa, "iniciar_imagem") as iniciar:
            acoes.acao_iniciar_avancado(self.pedido)
        iniciar.assert_called_once_with("cena")
        pasta = config.PROJETOS / "cena"
        estado = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual(estado["personagem"], "foto.png")
        self.assertEqual(projetos.ler_projeto(pasta)["ideia"], self.pedido["prompt"])
        with self.assertRaisesRegex(validacao.Erro, "Atualize a página") as erro:
            acoes.acao_reusar({"projeto": "cena"})
        self.assertEqual(erro.exception.codigo, 409)
        reuso = acoes.acao_reusar({"projeto": "cena", "aceita_video_avancado": True})
        self.assertEqual(reuso["tipo"], "avancado")
        self.assertEqual(reuso["config"]["avancado"]["referencias"], self.refs)
