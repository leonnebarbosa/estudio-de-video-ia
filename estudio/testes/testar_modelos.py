"""Testes da tela de modelos. Tudo numa pasta `models` falsa em temporario: nunca toca nos modelos reais.

Uso: python -I testar_modelos.py
"""
import json, os, struct, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import _winapi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, modelos, tarefa
from validacao import Erro


def cabecalho(meta=None):
    h = {"w": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}}
    if meta is not None:
        h["__metadata__"] = meta
    corpo = json.dumps(h).encode()
    return struct.pack("<Q", len(corpo)) + corpo + b"\0\0"


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        self.models = self.raiz / "models"
        self.estudio = self.raiz / "estudio"
        (self.estudio / "grafos").mkdir(parents=True)
        self.models.mkdir()
        for p in (mock.patch.object(config, "MODELOS", self.models), mock.patch.object(config, "ESTUDIO", self.estudio), mock.patch.object(config, "WORKFLOWS", self.raiz)):
            p.start()
            self.addCleanup(p.stop)
        modelos.esquecer()

    def arq(self, rel, conteudo=None, base=None):
        p = (base or self.models) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(cabecalho() if conteudo is None else conteudo)
        return p

    def catalogo(self, dados):
        (self.estudio / "catalogo_modelos.json").write_text(json.dumps(dados), encoding="utf-8")


class Listagem(Base):
    def test_lista_subpastas_e_catalogo_desatualizado(self):
        self.arq("loras/sub/a.safetensors")
        self.arq("vae/novo.safetensors")
        self.arq("vae/leia.txt", b"x")
        self.catalogo({"loras/sub/a.safetensors": {"nome": "A", "serve_para": "Teste", "faz": "Faz A", "testado": "ontem", "nota": "n"},
                       "loras/sumiu.safetensors": {"nome": "Sumiu", "faz": "x"}})
        itens = {i["caminho"]: i for i in modelos.listar()}
        self.assertEqual(set(itens), {"loras/sub/a.safetensors", "vae/novo.safetensors"})
        a = itens["loras/sub/a.safetensors"]
        self.assertEqual((a["tipo"], a["nome"], a["serve_para"], a["faz"], a["testado"], a["nota"]), ("loras", "A", "Teste", "Faz A", "ontem", "n"))
        self.assertEqual(a["tamanho"], (self.models / "loras/sub/a.safetensors").stat().st_size)
        n = itens["vae/novo.safetensors"]
        self.assertEqual((n["faz"], n["nome"]), ("", "novo.safetensors"))

    def test_le_metadados_sem_abrir_o_arquivo_inteiro(self):
        self.arq("loras/h3.safetensors", cabecalho({"ss_base_model_version": "h3"}) + b"\0" * (50 * 2**20))
        self.arq("loras/ruim.safetensors", struct.pack("<Q", 20) + b"isto nao e json!!!!!")
        self.arq("loras/enorme.safetensors", struct.pack("<Q", 2**40) + b"{}")
        self.arq("loras/modelo.gguf", b"GGUF" + b"\0" * 100)
        itens = {i["caminho"]: i for i in modelos.listar()}
        self.assertEqual(itens["loras/h3.safetensors"]["metadados"], {"ss_base_model_version": "h3"})
        self.assertEqual(itens["loras/ruim.safetensors"]["metadados"], {})
        self.assertEqual(itens["loras/enorme.safetensors"]["metadados"], {})
        self.assertEqual(itens["loras/modelo.gguf"]["metadados"], {})
        # so o cabecalho e lido: nenhum read passa de 1 MB
        lidos = []
        abrir = Path.open

        def espiao(self_, *a, **k):
            f = abrir(self_, *a, **k)
            ler = f.read
            f.read = lambda n=-1: (lidos.append(n), ler(n))[1]
            return f
        with mock.patch.object(Path, "open", espiao):
            modelos.listar()
        self.assertTrue(lidos and all(0 <= n <= 2**20 for n in lidos), lidos)

    def test_uso_fixo_opcao_nenhum(self):
        self.arq("loras/fixa_no_codigo.safetensors")
        self.arq("loras/fixa_no_grafo.safetensors")
        self.arq("loras/minimax_h3_so_opcao.safetensors")
        self.arq("loras/outra.safetensors")
        self.arq("vae/minimax_h3_vae.safetensors")  # fora de loras/: a aba Continuar so lista LoRAs
        self.arq("RMBG/BiRefNet/BiRefNet-general.safetensors")
        self.arq("diffusion_models/variante_ref2va.safetensors")  # a aba Continuar lista todo modelo ref2va
        (self.estudio / "validacao.py").write_text('PADRAO_TROCA = {"troca": ["fixa_no_codigo.safetensors", 1.0]}\nOUTRA = 1\n', encoding="utf-8")
        (self.estudio / "continuar_video.py").write_text("X = 'minimax_h3_so_opcao.safetensors'.upper() if False else 0\n", encoding="utf-8")
        (self.estudio / "grafos" / "troca_personagem_api.json").write_text('{"a": {"inputs": {"lora_name": "fixa_no_grafo.safetensors", "model": "BiRefNet-general"}}}', encoding="utf-8")
        itens = {i["caminho"]: i for i in modelos.listar()}
        self.assertEqual((itens["loras/fixa_no_codigo.safetensors"]["uso"], itens["loras/fixa_no_codigo.safetensors"]["onde"]), ("fixo", ["Trocar personagem"]))
        self.assertEqual((itens["loras/fixa_no_grafo.safetensors"]["uso"], itens["loras/fixa_no_grafo.safetensors"]["onde"]), ("fixo", ["Trocar personagem"]))
        self.assertEqual(itens["RMBG/BiRefNet/BiRefNet-general.safetensors"]["uso"], "fixo")
        self.assertEqual(itens["loras/minimax_h3_so_opcao.safetensors"]["uso"], "fixo")  # citada em continuar_video.py
        (self.estudio / "continuar_video.py").write_text("X = 1\n", encoding="utf-8")
        modelos.esquecer()
        itens = {i["caminho"]: i for i in modelos.listar()}
        self.assertEqual((itens["loras/minimax_h3_so_opcao.safetensors"]["uso"], itens["loras/minimax_h3_so_opcao.safetensors"]["onde"]), ("opcao", ["Continuar vídeo"]))
        self.assertEqual((itens["loras/outra.safetensors"]["uso"], itens["loras/outra.safetensors"]["onde"]), ("nenhum", []))
        self.assertEqual(itens["vae/minimax_h3_vae.safetensors"]["uso"], "nenhum")
        self.assertEqual(itens["diffusion_models/variante_ref2va.safetensors"]["uso"], "opcao")


class Apagar(Base):
    def setUp(self):
        super().setUp()
        (self.estudio / "validacao.py").write_text('PADRAO = {"modelo": "fixo.safetensors"}\n', encoding="utf-8")
        self.fixo = self.arq("diffusion_models/fixo.safetensors")
        self.solto = self.arq("loras/solto.safetensors")
        self.fora = self.raiz / "fora"
        self.de_fora = self.arq("alvo.safetensors", base=self.fora)

    def recusa(self, caminho, confirmar=True):
        with self.assertRaises(Erro, msg=caminho):
            modelos.apagar(caminho, confirmar)

    def test_apagar_recusa_fixo_link_e_fora(self):
        self.recusa("diffusion_models/fixo.safetensors")
        self.assertTrue(self.fixo.exists())
        for ruim in ("..\\x", "../fora/alvo.safetensors", "loras/../../fora/alvo.safetensors", str(self.de_fora), "/fora/alvo.safetensors", "C:/x.safetensors", "C:x.safetensors",
                     "loras\\solto.safetensors", "loras/solto.safetensors\0", "", "loras", "loras/", "loras/nao_existe.safetensors", "loras/solto.txt", "loras//solto.safetensors", "loras/./solto.safetensors"):
            self.recusa(ruim)
        self.assertTrue(self.solto.exists() and self.de_fora.exists())
        # pasta nunca e apagada
        (self.models / "loras" / "pasta.safetensors").mkdir()
        self.recusa("loras/pasta.safetensors")
        # juncao dentro de models apontando para fora
        _winapi.CreateJunction(str(self.fora), str(self.models / "loras" / "atalho"))
        self.recusa("loras/atalho/alvo.safetensors")
        self.recusa("loras/atalho")
        self.assertTrue(self.de_fora.exists())
        # arquivo que e um link simbolico, quando o sistema deixa criar
        try:
            os.symlink(self.de_fora, self.models / "loras" / "simbolico.safetensors")
        except OSError:
            pass
        else:
            self.recusa("loras/simbolico.safetensors")
            self.assertTrue(self.de_fora.exists())
        # a propria pasta models e uma juncao
        _winapi.CreateJunction(str(self.models), str(self.raiz / "atalho_models"))
        with mock.patch.object(config, "MODELOS", self.raiz / "atalho_models"):
            self.recusa("loras/solto.safetensors")
        self.assertTrue(self.solto.exists())
        # geracao rodando: recusa ate o que seria permitido
        with mock.patch.object(tarefa.tarefa, "rodando", return_value=True):
            self.recusa("loras/solto.safetensors")
            self.recusa("loras/solto.safetensors", False)
        self.assertTrue(self.solto.exists() and self.fixo.exists() and self.de_fora.exists())
        # a juncao so some como atalho, sem levar o conteudo de fora
        os.rmdir(self.models / "loras" / "atalho")
        os.rmdir(self.raiz / "atalho_models")
        self.assertTrue(self.de_fora.exists())

    def test_apagar_recusa_maiusculas_diferentes(self):
        for ruim in ("diffusion_models/FIXO.safetensors", "diffusion_models/Fixo.SafeTensors", "DIFFUSION_MODELS/fixo.safetensors", "Diffusion_Models/Fixo.safetensors"):
            self.recusa(ruim)
            self.recusa(ruim, False)
        self.assertTrue(self.fixo.exists())
        self.recusa("LORAS/solto.safetensors")
        self.recusa("loras/SOLTO.safetensors")
        self.assertTrue(self.solto.exists())

    def test_apagar_arquivo_em_uso_e_sumido(self):
        with mock.patch.object(modelos.os, "remove", side_effect=PermissionError(32, "em uso")):
            with self.assertRaises(Erro) as e:
                modelos.apagar("loras/solto.safetensors", True)
        self.assertEqual(e.exception.codigo, 409)
        self.assertEqual(e.exception.mensagem, "O arquivo está em uso pelo ComfyUI (espere a geração terminar ou feche o estúdio) e não foi apagado.")
        self.assertTrue(self.solto.exists())
        # some entre a ultima conferencia e o remove: avisa e a listagem e refeita
        self.assertIn("loras/solto.safetensors", [i["caminho"] for i in modelos.listagem()])
        with mock.patch.object(modelos.os, "remove", side_effect=FileNotFoundError(2, "sumiu")), mock.patch.object(modelos, "esquecer", wraps=modelos.esquecer) as esq:
            with self.assertRaises(Erro) as e:
                modelos.apagar("loras/solto.safetensors", True)
        self.assertEqual((e.exception.codigo, e.exception.mensagem), (404, "O arquivo não existe mais."))
        esq.assert_called()
        # arquivo que some entre a varredura e o stat nao derruba a listagem
        real = Path.stat

        def stat(self_, *a, **k):
            if self_.name == "solto.safetensors":
                raise FileNotFoundError(2, "sumiu")
            return real(self_, *a, **k)
        with mock.patch.object(Path, "stat", stat):
            nomes = [i["caminho"] for i in modelos.listar()]
        self.assertNotIn("loras/solto.safetensors", nomes)
        self.assertIn("diffusion_models/fixo.safetensors", nomes)

    def test_apagar_confirmado(self):
        outro = self.arq("loras/outro.safetensors")
        r = modelos.apagar("loras/solto.safetensors", False)
        self.assertEqual(r, {"caminho": "loras/solto.safetensors", "tamanho": self.solto.stat().st_size})
        self.assertTrue(self.solto.exists())
        self.assertEqual(modelos.apagar("loras/solto.safetensors", "sim"), r)  # so True de verdade confirma
        self.assertTrue(self.solto.exists())
        self.assertEqual(modelos.apagar("loras/solto.safetensors", True), r)
        self.assertFalse(self.solto.exists())
        self.assertTrue(outro.exists() and self.fixo.exists() and (self.models / "loras").is_dir())
        self.assertNotIn("loras/solto.safetensors", [i["caminho"] for i in modelos.listagem()])


class Anotar(Base):
    def test_anotar_grava_e_limita(self):
        self.arq("loras/a.safetensors")
        self.catalogo({"loras/a.safetensors": {"nome": "A", "serve_para": "S", "faz": "F", "testado": "T", "nota": ""}})
        modelos.anotar("loras/a.safetensors", "  <b>" + "x" * 300, "nota <script>" + "y" * 300)
        dados = json.loads((self.raiz / "catalogo_local.json").read_text(encoding="utf-8"))  # anotacao vai para o local, fora do git
        e = dados["loras/a.safetensors"]
        self.assertEqual(e["nome"], "b" + "x" * 199)
        self.assertEqual(len(e["nota"]), 200)
        self.assertTrue(e["nota"].startswith("nota script"))
        self.assertNotIn("<", e["nota"] + e["nome"])
        self.assertEqual((e["serve_para"], e["faz"], e["testado"]), ("S", "F", "T"))
        self.assertEqual([p.name for p in self.raiz.iterdir() if p.is_file()], ["catalogo_local.json"])  # sem temporario sobrando
        self.assertEqual(modelos.listagem()[0]["nome"], e["nome"])
        for ruim in ("../x.safetensors", "loras/nao_existe.safetensors", "loras\\a.safetensors", "loras/A.safetensors", "LORAS/a.safetensors"):
            with self.assertRaises(Erro):
                modelos.anotar(ruim, "n", "n")


class CatalogoReal(unittest.TestCase):
    def test_catalogo_do_repositorio_e_valido(self):
        import pacotes
        dados = json.loads((Path(__file__).resolve().parent.parent / "catalogo_modelos.json").read_text(encoding="utf-8"))
        # O catalogo versionado so fala dos modelos oficiais dos pacotes; os da comunidade ficam no catalogo local, fora do git
        oficiais = {a["caminho"] for p in pacotes.carregar() for a in p["arquivos"]}
        self.assertEqual(set(dados), oficiais)
        for caminho, e in dados.items():
            self.assertEqual(set(e), {"nome", "serve_para", "faz", "testado", "nota"}, caminho)
            self.assertTrue(all(isinstance(v, str) for v in e.values()), caminho)
            self.assertNotIn("\\", caminho)


if __name__ == "__main__":
    unittest.main()
