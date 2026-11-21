"""Palavras-chave por LoRA: o que o usuário edita vence o cadastro do estúdio, que vence a ficha do Civitai.
Tudo numa pasta temporária e sem internet: a consulta recebe um `baixar` falso."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, loras, palavras_lora as pl

FICHA = {"modelId": 77, "name": "v2", "model": {"name": "Estilo Novo"}, "trainedWords": ["novo_estilo", " novo_estilo ", "x" * 300, "outra frase,"]}


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for rel in ("loras/z/Novo_Estilo_v2.safetensors", "loras/h3/feltStopMotionStyle_H3_v01.safetensors", "loras/h3/minimax_h3_turbo_8step.safetensors"):
            (self.raiz / "models" / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.raiz / "models" / rel).write_bytes(rel.encode())
        for alvo, nome, valor in ((config, "MODELOS", self.raiz / "models"), (config, "WORKFLOWS", self.raiz), (pl, "_dados", None), (pl, "ARQUIVO", "palavras.json")):
            self.addCleanup(setattr, alvo, nome, getattr(alvo, nome))
            setattr(alvo, nome, valor)
        self.addCleanup(pl._com_erro.clear)
        self.pedidos = []

    def baixar(self, codigo=200, corpo=FICHA):
        def f(url):
            self.pedidos.append(url)
            return codigo, json.dumps(corpo)
        return f

    def item(self, nome):
        return next(i for i in pl.listar() if i["nome"] == nome)


class Consulta(Base):
    def test_ficha_vira_aviso_e_nao_entra_sozinha(self):
        ficha = pl.consultar("Novo_Estilo_v2.safetensors", self.baixar())
        self.assertEqual(ficha["estado"], "achou")
        # Repetida e prompt inteiro (longo demais) ficam de fora; a vírgula do fim sai
        self.assertEqual(ficha["palavras"], ["novo_estilo", "outra frase"])
        self.assertEqual(ficha["pagina"], "https://civitai.com/models/77")
        self.assertIn(pl.sha256(self.raiz / "models/loras/z/Novo_Estilo_v2.safetensors"), self.pedidos[0])
        g = loras.gatilho_de("z\\Novo_Estilo_v2.safetensors")
        self.assertEqual(g["frases"], ["novo_estilo", "outra frase"])
        self.assertEqual(loras.com_gatilho([["Novo_Estilo_v2.safetensors", 1]], "abc"), "abc")
        i = self.item("Novo_Estilo_v2.safetensors")
        self.assertEqual((i["origem"], i["modo"], i["pasta"], i["ficha"]["modelo"]), ("ficha", "aviso", "z", "Estilo Novo"))
        self.assertIn("novo_estilo_v2.safetensors", loras.para_a_pagina())

    def test_nao_calcula_nem_consulta_de_novo_sem_o_arquivo_mudar(self):
        pl.consultar("Novo_Estilo_v2.safetensors", self.baixar())
        self.assertEqual(pl.pendentes(), ["feltstopmotionstyle_h3_v01.safetensors"])
        pl.consultar("Novo_Estilo_v2.safetensors", self.baixar(), forcar=False)
        self.assertEqual(len(self.pedidos), 1)
        (self.raiz / "models/loras/z/Novo_Estilo_v2.safetensors").write_bytes(b"outro arquivo, maior")
        self.assertIn("novo_estilo_v2.safetensors", pl.pendentes())

    def test_fora_do_civitai_e_erro_de_rede(self):
        self.assertEqual(pl.consultar("Novo_Estilo_v2.safetensors", self.baixar(404, {}))["estado"], "nao_achou")
        self.assertNotIn("novo_estilo_v2.safetensors", pl.pendentes())
        self.assertIsNone(loras.gatilho_de("Novo_Estilo_v2.safetensors"))
        self.assertEqual(pl.consultar("Novo_Estilo_v2.safetensors", self.baixar(503, {}))["estado"], "erro")
        self.assertIn("novo_estilo_v2.safetensors", pl.pendentes())

        def cai(url):
            raise OSError("sem rede")
        self.assertEqual(pl.consultar("Novo_Estilo_v2.safetensors", cai)["estado"], "erro")

    def test_tecnicas_ficam_de_fora(self):
        self.assertNotIn("minimax_h3_turbo_8step.safetensors", pl.pendentes())
        self.assertNotIn("minimax_h3_turbo_8step.safetensors", [i["nome"] for i in pl.listar()])

    def test_desligado_nos_testes_nao_liga_o_fio(self):
        self.assertFalse(pl.LIGADO)
        pl.vigiar()
        self.assertIsNone(pl._fio)


class Edicao(Base):
    def test_o_que_o_usuario_salva_vence_o_cadastro_e_a_ficha(self):
        felt = "feltStopMotionStyle_H3_v01.safetensors"
        i = self.item(felt)
        self.assertEqual((i["origem"], i["modo"], i["palavras"]), ("estudio", "fixa", ["felt_stopmotion_style"]))
        pl.salvar(felt, "aviso", ["felt_stopmotion_style", "needle felted"], "  só   quando quero  ")
        i = self.item(felt)
        self.assertEqual((i["origem"], i["modo"], i["palavras"], i["nota"]), ("meu", "aviso", ["felt_stopmotion_style", "needle felted"], "só quando quero"))
        self.assertEqual(loras.gatilho([[felt, 1]]), "")
        # Gravado em disco: outra leitura acha o mesmo
        pl._dados = None
        self.assertEqual(self.item(felt)["origem"], "meu")
        pl.restaurar(felt)
        self.assertEqual(loras.gatilho([[felt, 1]]), "felt_stopmotion_style")

    def test_passar_a_ficha_para_fixa_poe_no_prompt(self):
        nome = "Novo_Estilo_v2.safetensors"
        pl.consultar(nome, self.baixar())
        pl.salvar(nome, "fixa", ["novo_estilo", "Novo_Estilo", ""])
        self.assertEqual(loras.com_gatilho([[nome, 1]], "a cat", ", "), "novo_estilo, a cat")
        g = loras.gatilho_de(nome)
        self.assertEqual((g["palavra"], g["pagina"]), ("novo_estilo", "https://civitai.com/models/77"))
        pl.salvar(nome, "fixa", ["um", "dois"])
        self.assertEqual(loras.com_gatilho([[nome, 1]], "a cat", ", "), "um, dois, a cat")

    def test_nenhuma_cala_o_cadastro(self):
        felt = "feltStopMotionStyle_H3_v01.safetensors"
        pl.salvar(felt, "nenhuma", ["ignorada"])
        self.assertIsNone(loras.gatilho_de(felt))
        self.assertNotIn(felt.lower(), loras.para_a_pagina())
        i = self.item(felt)
        self.assertEqual((i["origem"], i["modo"], i["palavras"]), ("meu", "nenhuma", []))

    def test_recusa_o_que_nao_faz_sentido(self):
        felt = "feltStopMotionStyle_H3_v01.safetensors"
        for modo, palavras in (("fixa", []), ("aviso", ["  "]), ("outro", ["a"]), ("fixa", "texto solto"), ("fixa", ["x" * 201]), ("aviso", [str(n) for n in range(13)])):
            with self.assertRaises(pl.Erro, msg=(modo, palavras)):
                pl.salvar(felt, modo, palavras)
        with self.assertRaises(pl.Erro):
            pl.salvar("nao_existe.safetensors", "fixa", ["a"])
        with self.assertRaises(pl.Erro):
            pl.consultar("../fora.safetensors", self.baixar())


if __name__ == "__main__":
    unittest.main()
