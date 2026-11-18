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


if __name__ == "__main__":
    unittest.main()
