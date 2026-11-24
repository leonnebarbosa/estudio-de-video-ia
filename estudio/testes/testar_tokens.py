"""O aviso de prompt comprido (tokens.py): conta e avisa nos modelos de 512 tokens, nunca corta nem bloqueia.

O contador e um duble (1 token por palavra) para o teste valer em qualquer PC; a classe Reais confere os tokenizadores do ComfyUI
quando eles existem. Uso: python -I rodar_testes.py"""
import sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, planos, texto_para_imagem, tokens

LONGO = "palavra " * 600
CURTO = "palavra " * 100


class Duble(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(tokens, "_contador", lambda nome: lambda texto: len(texto.split()))
        p.start()
        self.addCleanup(p.stop)


class Aviso(Duble):
    def test_no_limite_cabe_e_acima_avisa(self):
        self.assertEqual(tokens.aviso("chroma", "a " * 512), "")
        x = tokens.aviso("chroma", "a " * 513)
        self.assertIn("513 tokens", x)
        self.assertIn("Chroma foi feito para até 512", x)

    def test_modelos_com_e_sem_limite(self):
        for id_, m in texto_para_imagem.MODELOS_TEXTO.items():
            x = tokens.aviso_imagem({"modelo": id_, "prompt": LONGO})
            self.assertEqual(bool(x), m.get("tipo_encoder") in ("flux2", "lumina2", "krea2", "chroma"), id_)
            self.assertEqual(tokens.aviso_imagem({"modelo": id_, "prompt": CURTO}), "", id_)
        self.assertEqual(tokens.aviso_imagem({"modelo": "qwen21_edit", "prompt": LONGO}), "")

    def test_estilo_conta_o_pedido_pronto(self):
        self.assertIn("tokens", tokens.aviso_imagem({"modelo": "klein_edit", "estilo": "lapis", "prompt": LONGO}))
        self.assertEqual(tokens.aviso_imagem({"modelo": "klein_edit", "estilo": "nao_existe", "prompt": LONGO}), "")

    def test_wan_avisa_so_a_tomada_que_passa(self):
        a = {"modelo": "wan22", "loras": [], "tomadas": [{"camera": "parada", "olhar": False, "acao": CURTO}, {"camera": "parada", "olhar": True, "acao": LONGO}]}
        r = tokens.avisos_wan(a)
        self.assertEqual(len(r), 1)
        self.assertIn("a tomada 2 tem", r[0])
        self.assertEqual(tokens.avisos_wan({**a, "modelo": "h3"}), [])

    def test_a_rota(self):
        self.assertEqual(len(tokens.do_pedido({"alvo": "imagem", "ajustes": {"modelo": "z_image_turbo", "prompt": LONGO}})["avisos"]), 1)
        self.assertEqual(len(tokens.do_pedido({"alvo": "pintura", "ajustes": {"prompt": LONGO}})["avisos"]), 1)
        for d in ({}, {"alvo": "imagem"}, {"alvo": "imagem", "ajustes": []}, {"alvo": "imagem", "ajustes": {"modelo": ["x"]}},
                  {"alvo": "wan", "ajustes": {"modelo": "wan22", "tomadas": [1, {"camera": "x"}], "loras": [1, []]}}):
            self.assertEqual(tokens.do_pedido(d), {"avisos": []}, d)

    def test_resumo_do_plano_de_imagem(self):
        a = {"modelo": "z_image_turbo", "prompt": LONGO.strip(), "quantidade": 1, "passos": 8, "megapixels": 0.9, "proporcao": "1:1 (Square)"}
        linhas = planos.resumo_imagem({"ajustes": a}).split("\n")
        i = next(i for i, x in enumerate(linhas) if x.startswith("Aviso: o prompt tem"))
        self.assertEqual(linhas[i + 1], "Prompt:")
        self.assertNotIn("tokens", planos.resumo_imagem({"ajustes": {**a, "prompt": "um gato"}}))


class SemContador(unittest.TestCase):
    def test_sem_tokenizador_nao_avisa_nem_quebra(self):
        with mock.patch.object(tokens, "_contador", side_effect=OSError("falta")):
            self.assertIsNone(tokens.contar("wan", LONGO))
            self.assertEqual(tokens.aviso_imagem({"modelo": "klein_t2i", "prompt": LONGO}), "")


class Pagina(unittest.TestCase):
    def test_o_script_esta_na_pagina_e_os_campos_existem(self):
        pagina = Path(tokens.__file__).parent / "pagina"
        html = (pagina / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/pagina/js/tokens.js"></script>', html)
        for campo in ("t2i-prompt", "i-tomadas", "e-pedido-klein"):
            self.assertIn(f'id="{campo}"', html)
            self.assertIn(f'campo: "{campo}"', (pagina / "js" / "tokens.js").read_text(encoding="utf-8"))


class Reais(unittest.TestCase):
    def test_qwen_e_t5_do_comfyui(self):
        if not (tokens.CODIFICADORES / "qwen25_tokenizer" / "vocab.json").is_file():
            self.skipTest("ComfyUI não está nesta máquina")
        self.assertEqual(tokens.contar("flux2", ""), 12)  # o molde do Klein
        self.assertEqual(tokens.contar("lumina2", ""), 8)
        self.assertEqual(tokens.contar("chroma", "hello"), 2)  # a palavra e o fim de texto
        self.assertIsNone(tokens.contar("qwen_image", "hello"))

    def test_umt5(self):
        if not any((config.MODELOS / d / "umt5_xxl_fp8_e4m3fn_scaled.safetensors").is_file() for d in ("text_encoders", "clip")):
            self.skipTest("o codificador do Wan não está nesta máquina")
        self.assertEqual(tokens.contar("wan", "hello"), 2)


if __name__ == "__main__":
    unittest.main()
