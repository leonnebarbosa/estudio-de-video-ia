"""LoRAs em subpastas: o estudio usa o nome do arquivo e o envio ao ComfyUI troca pelo caminho atual.
Tudo numa pasta temporaria: nada da pasta de modelos real e tocado."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, loras


class Loras(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.models = Path(d.name)
        for rel in ("loras/h3/minimax_h3_lms.safetensors", "loras/wan/Wan_Rapida.safetensors", "loras/solta.safetensors", "loras/h3/leia.txt"):
            (self.models / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.models / rel).write_bytes(b"x")
        antigo = config.MODELOS
        config.MODELOS = self.models
        self.addCleanup(setattr, config, "MODELOS", antigo)

    def test_mapa_acha_em_subpasta_e_na_raiz(self):
        m = loras.mapa()
        self.assertEqual(m["minimax_h3_lms.safetensors"], str(Path("h3/minimax_h3_lms.safetensors")))
        self.assertEqual(m["solta.safetensors"], "solta.safetensors")
        self.assertNotIn("leia.txt", m)

    def test_caminho_aceita_nome_caminho_antigo_e_maiusculas(self):
        esperado = str(Path("wan/Wan_Rapida.safetensors"))
        for pedido in ("Wan_Rapida.safetensors", "wan_rapida.safetensors", "outra\\Wan_Rapida.safetensors", "outra/Wan_Rapida.safetensors"):
            self.assertEqual(loras.caminho(pedido), esperado, pedido)
        self.assertEqual(loras.caminho("nao_existe.safetensors"), "nao_existe.safetensors")

    def test_nomes_unicos(self):
        self.assertEqual(loras.nomes_unicos(["h3\\a.safetensors", "b.safetensors", "wan/a.safetensors"]), ["a.safetensors", "b.safetensors"])

    def test_resolver_grafo(self):
        estado = {"version": 1, "loras": [{"name": "minimax_h3_lms.safetensors", "on": True, "sm": 1, "sc": 1}]}
        g = {"1": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["0", 0], "lora_name": "minimax_h3_lms.safetensors", "strength_model": 1}},
             "2": {"class_type": "PixaromaLoraLoader", "inputs": {"LoraLoaderState": json.dumps(estado)}},
             "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "solta.safetensors"}},
             "4": {"class_type": "Algum", "inputs": {"lora_02": "Wan_Rapida.safetensors", "texto": "minimax_h3_lms.safetensors"}},
             "5": {"class_type": "Quebrado", "inputs": {"LoraLoaderState": "{nao e json"}}}
        loras.resolver_grafo(g)
        h3 = str(Path("h3/minimax_h3_lms.safetensors"))
        self.assertEqual(g["1"]["inputs"]["lora_name"], h3)
        estado_novo = json.loads(g["2"]["inputs"]["LoraLoaderState"])
        self.assertEqual(estado_novo["loras"][0]["name"], h3)
        self.assertEqual(estado_novo["version"], 1)
        # So campos de LoRA mudam: o unet com nome igual e o texto ficam
        self.assertEqual(g["3"]["inputs"]["unet_name"], "solta.safetensors")
        self.assertEqual(g["4"]["inputs"]["lora_02"], str(Path("wan/Wan_Rapida.safetensors")))
        self.assertEqual(g["4"]["inputs"]["texto"], "minimax_h3_lms.safetensors")
        self.assertEqual(g["5"]["inputs"]["LoraLoaderState"], "{nao e json")

    def test_compativeis_do_texto_vem_pelo_nome(self):
        import texto_para_imagem as t
        with mock.patch.object(t, "familia_lora", lambda p: "chroma" if "lms" in p.name else None):
            self.assertEqual(t.loras_compativeis("chroma_flash"), ["minimax_h3_lms.safetensors"])

    def test_faltando_procura_em_subpasta(self):
        import trocar_personagem, wan_para_video
        (self.models / "loras" / "h3" / trocar_personagem.HEAD_SWAP).write_bytes(b"x")
        self.assertIn(trocar_personagem.HEAD_SWAP.lower(), loras.mapa())
        m = wan_para_video.MODELOS_WAN["wan22"]
        for n in m["lora"]:
            (self.models / "loras" / "wan" / n).write_bytes(b"x")
        self.assertFalse(set(m["lora"]) & set(wan_para_video.arquivos_que_faltam("wan22")))


class ForcaRecomendada(unittest.TestCase):
    """Força que o autor recomenda (tabela forca_lora da seção pagina do arquivo local), ou o padrão do vídeo."""
    def test_acha_pelo_nome_com_ou_sem_pasta_e_sem_maiusculas(self):
        import extras
        tabela = {"forca_lora": {"H3-Estilo.safetensors": 1, "quebrada.safetensors": "x", "booleana.safetensors": True}}
        with mock.patch.object(extras, "secao", lambda nome: tabela if nome == "pagina" else {}):
            self.assertEqual(loras.forca_recomendada("h3\\h3-estilo.safetensors"), 1.0)
            self.assertEqual(loras.forca_recomendada("outra.safetensors"), loras.FORCA_PADRAO_VIDEO)
            self.assertEqual(loras.forca_recomendada("outra.safetensors", 1), 1)
            self.assertEqual(loras.forca_recomendada("quebrada.safetensors"), 0.8)
            self.assertEqual(loras.forca_recomendada("booleana.safetensors"), 0.8)
        with mock.patch.object(extras, "secao", lambda nome: {}):
            self.assertEqual(loras.forca_recomendada("H3-Estilo.safetensors"), 0.8)


class Gatilhos(unittest.TestCase):
    """Palavras-chave: a fixa entra sozinha no começo do prompt; a que depende da cena só é avisada na página."""
    FELT = ["feltStopMotionStyle_H3_v01.safetensors", 0.8]
    REAL = ["h3\\h3-realism-people-t2v-i2v-r2v.safetensors", 1.0]
    LOCAL = {"estilo_da_casa": "c4s4", "movimento_x": {"frases": ["she waves", "he waves"], "nota": "Uma por cena."},
             "frase_fixa": {"palavra": "Photograph of Fulana"}, "quebrada": {"nota": "sem palavra nem frases"}, "numero": 3,
             "_sobre": "anotação do arquivo local"}

    def com_local(self):
        import extras
        antigo = extras._lido
        extras._lido = {"gatilhos": self.LOCAL}
        self.addCleanup(setattr, extras, "_lido", antigo)

    def test_palavra_fixa_do_codigo(self):
        self.assertEqual(loras.gatilho([self.FELT]), "felt_stopmotion_style")
        self.assertEqual(loras.gatilho([self.REAL, self.FELT]), "r34l1sm felt_stopmotion_style")
        self.assertEqual(loras.gatilho([["sem_cadastro.safetensors", 1]]), "")

    def test_arquivo_local_soma_ao_codigo(self):
        self.com_local()
        g = loras.gatilhos()
        self.assertEqual(g["estilo_da_casa"], {"palavra": "c4s4"})
        self.assertEqual(g["movimento_x"]["frases"], ["she waves", "he waves"])
        self.assertIn("h3-realism-people", g)
        # Entrada sem palavra nem frases, ou que não é texto nem dicionário, fica de fora
        self.assertNotIn("quebrada", g)
        self.assertNotIn("numero", g)
        self.assertNotIn("_sobre", g)

    def test_frases_que_dependem_da_cena_nao_entram_sozinhas(self):
        self.com_local()
        self.assertEqual(loras.gatilho([["Movimento_X_HIGH.safetensors", 1]]), "")
        self.assertEqual(loras.com_gatilho([["Movimento_X_HIGH.safetensors", 1]], "abc"), "abc")

    def test_com_gatilho_nao_repete_o_que_ja_esta_escrito(self):
        self.com_local()
        self.assertEqual(loras.com_gatilho([self.FELT], "a cat"), "felt_stopmotion_style a cat")
        self.assertEqual(loras.com_gatilho([self.FELT], "a cat", ", "), "felt_stopmotion_style, a cat")
        self.assertEqual(loras.com_gatilho([self.FELT], "Felt_Stopmotion_Style, a cat", ", "), "Felt_Stopmotion_Style, a cat")
        # Frase fixa com espaços entra inteira; duas LoRAs, só a palavra que falta
        self.assertEqual(loras.com_gatilho([["frase_fixa.safetensors", 1]], "at the beach", ", "), "Photograph of Fulana, at the beach")
        self.assertEqual(loras.com_gatilho([self.REAL, self.FELT], "r34l1sm woman", ", "), "felt_stopmotion_style, r34l1sm woman")
        self.assertEqual(loras.com_gatilho(None, "abc"), "abc")

    def test_wan_aceita_alta_baixa_e_forca(self):
        self.com_local()
        self.assertEqual(loras.gatilho([["estilo_da_casa_HIGH.safetensors", "estilo_da_casa_LOW.safetensors", 0.8]]), "c4s4")

    def test_texto_para_imagem_poe_a_palavra(self):
        import texto_para_imagem as t
        self.com_local()
        p = {"modelo": "chroma_flash", "prompt": "a red car", "negativo": "", "proporcao": "1:1 (quadrado)", "megapixels": 1.0, "passos": 12,
             "loras": [["estilo_da_casa_v2.safetensors", 0.8]]}
        self.assertEqual(t.grafo(p, 1, "x")["4"]["inputs"]["text"], "c4s4, a red car")
        self.assertEqual(t.grafo({**p, "loras": []}, 1, "x")["4"]["inputs"]["text"], "a red car")

    def test_wan_poe_a_palavra(self):
        import wan_para_video as w
        self.com_local()
        p = {"modelo": "wan22", "prompt": "she smiles", "negativo": "", "proporcao": "9:16 (vertical)", "megapixels": 0.475, "duracao": 3,
             "loras": [["estilo_da_casa_HIGH.safetensors", "estilo_da_casa_LOW.safetensors", 0.8]]}
        self.assertEqual(w.grafo(p, "foto.png", 1, "x")["31"]["inputs"]["text"], "c4s4, she smiles")


if __name__ == "__main__":
    unittest.main()
