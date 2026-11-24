"""Testes dos arquivos que o estudio guarda pelo nome na entrada do ComfyUI (entrada.py): os novos em input/estudio/envios,
os antigos ainda valendo na raiz do input.

Uso: python -I testar_entrada.py
"""
import io, json, sys, tempfile, threading, unittest, urllib.request
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, entrada, envio, midias, projetos, validacao


def png(cor="red"):
    b = io.BytesIO()
    Image.new("RGB", (30, 20), cor).save(b, "PNG")
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="estudio_entrada_")
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        self.entrada = self.raiz / "input"
        self.entrada.mkdir()
        self.envios = self.entrada / "estudio" / "envios"
        for alvo, valor in (("ENTRADA", self.entrada), ("ENVIOS", self.raiz / "envios"), ("PROJETOS", self.raiz / "projetos"), ("SAIDA", self.raiz / "saida")):
            p = mock.patch.object(config, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(midias, "ARQUIVO", self.raiz / "midias.json")
        p.start()
        self.addCleanup(p.stop)

    def na_raiz(self, nome, dados=b"raiz"):
        (self.entrada / nome).write_bytes(dados)
        return self.entrada / nome

    def em_envios(self, nome, dados=b"envios"):
        self.envios.mkdir(parents=True, exist_ok=True)
        (self.envios / nome).write_bytes(dados)
        return self.envios / nome


class Caminho(Base):
    def test_pasta_segue_config(self):
        self.assertEqual(entrada.pasta_envios(), self.envios)

    def test_envios_primeiro(self):
        self.na_raiz("a.png")
        self.em_envios("a.png")
        self.assertEqual(entrada.caminho("a.png"), self.envios / "a.png")
        self.assertEqual(entrada.no_grafo("a.png"), "estudio/envios/a.png")

    def test_arquivo_antigo_na_raiz_continua_valendo(self):
        self.na_raiz("velho.png")
        self.assertEqual(entrada.caminho("velho.png"), self.entrada / "velho.png")
        self.assertEqual(entrada.no_grafo("velho.png"), "velho.png")
        self.assertTrue(entrada.existe("velho.png"))

    def test_nome_que_nao_existe_vai_para_envios(self):
        self.assertEqual(entrada.caminho("novo.png"), self.envios / "novo.png")
        self.assertEqual(entrada.no_grafo("novo.png"), "novo.png")
        self.assertFalse(entrada.existe("novo.png"))
        self.assertFalse(self.envios.exists())  # caminho nao cria a pasta

    def test_novo_cria_a_pasta(self):
        self.assertEqual(entrada.novo("x.png"), self.envios / "x.png")
        self.assertTrue(self.envios.is_dir())
        with self.assertRaises(ValueError):
            entrada.novo("estudio/temp/p/x.png")

    def test_nome_com_subpasta_fica_como_veio(self):
        nome = "estudio/temp/proj/x.png"
        self.assertEqual(entrada.caminho(nome), self.entrada / "estudio" / "temp" / "proj" / "x.png")
        self.assertEqual(entrada.no_grafo(nome), nome)
        self.assertEqual(entrada.no_grafo("estudio\\temp\\proj\\x.png"), nome)

    def test_recusa_nome_que_sai_da_pasta(self):
        for ruim in ("..", "../x.png", "a/../x.png", "/x.png", "c:x.png", "C:/x.png", "", ".", "a//b.png", "\\x.png"):
            with self.assertRaises(ValueError, msg=ruim):
                entrada.caminho(ruim)
            with self.assertRaises(ValueError, msg=ruim) if ruim else self.subTest(ruim):
                entrada.no_grafo(ruim)
            self.assertFalse(entrada.existe(ruim), ruim)

    def test_no_grafo_deixa_ligacao_e_vazio(self):
        self.assertEqual(entrada.no_grafo(["1", 0]), ["1", 0])
        self.assertIsNone(entrada.no_grafo(None))
        self.assertEqual(entrada.no_grafo(""), "")

    def test_onde_lista_os_dois_lugares(self):
        self.assertEqual(entrada.onde("a.png"), [self.envios / "a.png", self.entrada / "a.png"])


class ResolverGrafo(Base):
    def test_carregadores_e_midia_do_h3(self):
        self.em_envios("foto.png")
        self.em_envios("voz.wav")
        self.na_raiz("velho.mp4")
        g = {"1": {"class_type": "LoadImage", "inputs": {"image": "foto.png"}},
             "2": {"class_type": "LoadVideo", "inputs": {"file": "velho.mp4"}},
             "3": {"class_type": "LoadAudio", "inputs": {"audio": "voz.wav"}},
             "4": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": "estudio/temp/p/v.mp4"}},
             "5": {"class_type": "MiniMaxH3MediaLoader", "inputs": {"media_state": json.dumps([{"kind": "picture", "name": "foto.png", "file": "foto.png"},
                                                                                              {"kind": "audio", "name": "voz.wav", "file": "voz.wav"}])}},
             "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "foto.png"}},
             "7": {"class_type": "LoadImage", "inputs": {"image": ["1", 0]}}}
        entrada.resolver_grafo(g)
        self.assertEqual(g["1"]["inputs"]["image"], "estudio/envios/foto.png")
        self.assertEqual(g["2"]["inputs"]["file"], "velho.mp4")
        self.assertEqual(g["3"]["inputs"]["audio"], "estudio/envios/voz.wav")
        self.assertEqual(g["4"]["inputs"]["video"], "estudio/temp/p/v.mp4")
        midia = json.loads(g["5"]["inputs"]["media_state"])
        self.assertEqual([m["file"] for m in midia], ["estudio/envios/foto.png", "estudio/envios/voz.wav"])
        self.assertEqual([m["name"] for m in midia], ["foto.png", "voz.wav"])
        self.assertEqual(g["6"]["inputs"]["text"], "foto.png")
        self.assertEqual(g["7"]["inputs"]["image"], ["1", 0])

    def test_rodar_resolve_antes_de_mandar(self):
        import comfy_api
        self.em_envios("foto.png")
        mandado = {}

        def posta(caminho, dados):
            mandado.update(dados)
            raise OSError("sem ComfyUI no teste")
        g = {"1": {"class_type": "LoadImage", "inputs": {"image": "foto.png"}}}
        with mock.patch.object(comfy_api, "posta", posta):
            r = comfy_api.rodar(g, 1)
        self.assertEqual(r["status"], "servidor caiu")
        self.assertEqual(mandado["prompt"]["1"]["inputs"]["image"], "estudio/envios/foto.png")


class Envio(Base):
    def test_foto_vai_para_envios(self):
        r = envio.receber_arquivo(io.BytesIO(png()), len(png()), "foto", "ana.png")
        self.assertEqual(r["arquivo"], "ana.png")
        self.assertEqual((self.envios / "ana.png").read_bytes(), png())
        self.assertFalse((self.entrada / "ana.png").exists())
        self.assertEqual(midias.tipo_de("ana.png"), "foto")
        self.assertEqual([m["nome"] for m in midias.listar()], ["ana.png"])
        self.assertEqual(sorted(p.name for p in self.envios.iterdir()), ["ana.png"])  # sem .parte sobrando

    def test_nome_de_arquivo_antigo_diferente_ganha_outro_nome(self):
        self.na_raiz("ana.png", png("blue"))
        r = envio.receber_arquivo(io.BytesIO(png()), len(png()), "foto", "ana.png")
        self.assertEqual(r["arquivo"], "ana_2.png")
        self.assertEqual((self.entrada / "ana.png").read_bytes(), png("blue"))  # o antigo fica intacto e continua sendo o ana.png
        self.assertEqual(entrada.caminho("ana.png"), self.entrada / "ana.png")
        self.assertEqual((self.envios / "ana_2.png").read_bytes(), png())

    def test_mesmo_conteudo_de_arquivo_antigo_reaproveita_o_nome(self):
        self.na_raiz("ana.png", png())
        r = envio.receber_arquivo(io.BytesIO(png()), len(png()), "foto", "ana.png")
        self.assertEqual(r["arquivo"], "ana.png")
        self.assertFalse((self.envios / "ana.png").exists())

    def test_video_continua_em_envios_do_estudio(self):
        self.assertEqual(envio.destino_livre(config.ENVIOS, "v.mp4", self.na_raiz("x.bin")), config.ENVIOS / "v.mp4")


class Leitores(Base):
    def test_validacao_aceita_foto_que_so_existe_em_envios(self):
        self.em_envios("partida.png", png())
        r = validacao.validar_texto({"prompt": "a cat", "partida": "partida.png"})
        self.assertEqual(r["partida"], "partida.png")
        with self.assertRaises(validacao.Erro):
            validacao.validar_texto({"prompt": "a cat", "partida": "sumiu.png"})

    def test_quadro_da_continuacao_em_envios_ou_na_raiz(self):
        self.assertIsNone(projetos.ultimo_quadro("p", 1))
        self.na_raiz("cont_p_r00.png")
        self.assertEqual(projetos.ultimo_quadro("p", 1), self.entrada / "cont_p_r00.png")
        self.em_envios("cont_p_r01.png")
        self.assertEqual(projetos.ultimo_quadro("p", 1), self.envios / "cont_p_r01.png")

    def test_foto_do_cartao_da_troca(self):
        pasta = config.PROJETOS / "t"
        pasta.mkdir(parents=True)
        (pasta / "estado.json").write_text(json.dumps({"tipo": "troca", "personagem": "pessoa.png"}), encoding="utf-8")
        self.assertFalse(projetos.ler_projeto(pasta)["foto_existe"])
        self.em_envios("pessoa.png")
        self.assertTrue(projetos.ler_projeto(pasta)["foto_existe"])

    def test_apagar_projeto_leva_os_arquivos_dos_dois_lugares(self):
        for nome in ("p", "outro"):
            (config.PROJETOS / nome).mkdir(parents=True)
        (config.PROJETOS / "p" / "estado.json").write_text("{}", encoding="utf-8")
        # Outro projeto usa o r01 de p: ele fica
        (config.PROJETOS / "outro" / "estado.json").write_text(json.dumps({"personagem": "cont_p_r01.png"}), encoding="utf-8")
        velho = self.na_raiz("troca_p.mp4")
        novo = self.em_envios("troca_p.mp4")
        r00 = self.em_envios("cont_p_r00.png")
        self.em_envios("cont_p_r01.png")
        self.em_envios("foto.png")
        _, arquivos = projetos.alvos_apagar("p")
        self.assertEqual(sorted(arquivos), sorted([velho, novo, r00]))

    def test_video_avancado_aceita_referencia_em_envios(self):
        import video_avancado
        self.em_envios("ref.png")
        self.na_raiz("velha.png")
        self.assertEqual(video_avancado.caminho_referencia("foto", "ref.png"), self.envios / "ref.png")
        self.assertEqual(video_avancado.caminho_referencia("foto", "velha.png"), self.entrada / "velha.png")
        with self.assertRaises(validacao.Erro):
            video_avancado.caminho_referencia("foto", "nao.png")


class Rota(Base):
    """/entrada/foto/<nome> serve a foto de envios ou, nos antigos, da raiz."""

    def setUp(self):
        super().setUp()
        import servidor
        self.s = servidor.criar(0)
        self.porta = self.s.server_address[1]
        fio = threading.Thread(target=self.s.serve_forever, daemon=True)
        fio.start()
        self.addCleanup(fio.join, 5)
        self.addCleanup(self.s.server_close)
        self.addCleanup(self.s.shutdown)

    def pedir(self, caminho):
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.porta}{caminho}", headers={"Host": f"127.0.0.1:{self.porta}"})
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, r.read()

    def test_foto_de_envios_e_da_raiz(self):
        import urllib.error
        self.em_envios("nova.png", png("red"))
        self.na_raiz("velha.png", png("blue"))
        self.assertEqual(self.pedir("/entrada/foto/nova.png"), (200, png("red")))
        self.assertEqual(self.pedir("/entrada/foto/velha.png"), (200, png("blue")))
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.pedir("/entrada/foto/nenhuma.png")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
