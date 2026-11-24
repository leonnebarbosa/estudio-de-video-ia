"""Testes do registro de midias (midias.py) e do registro feito por envio.receber_arquivo. Uso: python -I testar_midias.py"""
import contextlib, io, json, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
import config
import entrada, envio, midias, validacao


def png(cor="red", tam=(30, 20)):
    b = io.BytesIO()
    Image.new("RGB", tam, cor).save(b, "PNG")
    return b.getvalue()


class Midias(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("entrada", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "ENTRADA", self.raiz / "entrada"), (config, "ENVIOS", self.raiz / "envios"),
                                  (midias, "ARQUIVO", self.raiz / "midias.json")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def criar(self, nome, tipo, quando, **info):
        """Poe o arquivo no disco e no registro, com a hora combinada."""
        (config.ENVIOS if tipo == "video" else config.ENTRADA).joinpath(nome).write_bytes(b"x")
        with mock.patch.object(midias.time, "time", return_value=quando):
            midias.registrar(nome, tipo, "link", info)

    def test_listar_da_mais_nova_para_a_mais_antiga_com_as_medidas(self):
        self.criar("a.png", "foto", 100, largura=10, altura=20)
        self.criar("b.mp3", "audio", 300, duracao=14.8)
        self.criar("c.mp4", "video", 200, duracao=8.0, largura=1280, altura=720)
        lista = midias.listar()
        self.assertEqual([m["nome"] for m in lista], ["b.mp3", "c.mp4", "a.png"])
        self.assertEqual(lista[0], {"nome": "b.mp3", "tipo": "audio", "quando": 300, "origem": "link", "duracao": 14.8})
        self.assertEqual((lista[2]["largura"], lista[2]["altura"]), (10, 20))

    def test_filtro_por_tipo_e_limite(self):
        for i in range(5):
            self.criar(f"f{i}.png", "foto", 100 + i, largura=1, altura=1)
        self.criar("v.mp4", "video", 50, duracao=1)
        self.assertEqual([m["nome"] for m in midias.listar("video")], ["v.mp4"])
        self.assertEqual([m["nome"] for m in midias.listar("foto", limite=2)], ["f4.png", "f3.png"])
        self.assertEqual(len(midias.listar()), 6)
        self.assertEqual(midias.listar("audio"), [])

    def test_some_quem_foi_apagado_do_disco(self):
        self.criar("a.png", "foto", 1, largura=1, altura=1)
        self.criar("b.png", "foto", 2, largura=1, altura=1)
        (config.ENTRADA / "a.png").unlink()
        self.assertEqual([m["nome"] for m in midias.listar()], ["b.png"])

    def test_sem_arquivo_de_registro_ou_com_lixo(self):
        self.assertEqual(midias.listar(), [])
        midias.ARQUIVO.write_text("{ isto nao e json", encoding="utf-8")
        self.assertEqual(midias.listar(), [])
        self.criar("a.png", "foto", 1, largura=1, altura=1)  # um registro novo recomeca o arquivo
        self.assertEqual([m["nome"] for m in midias.listar()], ["a.png"])

    def test_registrar_guarda_tipo_origem_hora_e_medidas(self):
        antes = time.time()
        midias.registrar("a.png", "foto", "mcp", {"largura": 3, "altura": 4})
        r = json.loads(midias.ARQUIVO.read_text(encoding="utf-8"))["a.png"]
        self.assertEqual((r["tipo"], r["origem"], r["largura"], r["altura"]), ("foto", "mcp", 3, 4))
        self.assertGreaterEqual(r["quando"], antes)

    def test_tipo_de_pelo_registro_e_pelo_sufixo(self):
        # Pelo registro, mesmo com um sufixo que nao diria isso
        self.criar("estranho.dat", "audio", 1, duracao=1)
        self.assertEqual(midias.tipo_de("estranho.dat"), "audio")
        # Sem registro: pelo sufixo, se o arquivo existe na pasta do tipo
        (config.ENTRADA / "foto.jpg").write_bytes(b"x")
        (config.ENTRADA / "voz.wav").write_bytes(b"x")
        (config.ENVIOS / "clipe.mp4").write_bytes(b"x")
        self.assertEqual(midias.tipo_de("foto.jpg"), "foto")
        self.assertEqual(midias.tipo_de("voz.wav"), "audio")
        self.assertEqual(midias.tipo_de("clipe.mp4"), "video")
        # Nao existe, ou esta na pasta errada, ou tenta sair da pasta
        self.assertIsNone(midias.tipo_de("nada.png"))
        (config.ENTRADA / "errado.mp4").write_bytes(b"x")
        self.assertIsNone(midias.tipo_de("errado.mp4"))
        self.assertIsNone(midias.tipo_de("../entrada/foto.jpg"))
        self.assertIsNone(midias.tipo_de(""))

    def test_tipo_de_com_registro_cujo_arquivo_foi_apagado_e_none(self):
        self.criar("sumiu.png", "foto", 1, largura=1, altura=1)
        self.assertEqual(midias.tipo_de("sumiu.png"), "foto")
        (config.ENTRADA / "sumiu.png").unlink()
        self.assertIsNone(midias.tipo_de("sumiu.png"))

    def test_registrar_recusa_origem_fora_da_lista(self):
        for origem in midias.ORIGENS:
            midias.registrar("a.png", "foto", origem, {})
        for ruim in ("", "outra", None):
            with self.assertRaises(ValueError):
                midias.registrar("b.png", "foto", ruim, {})
        self.assertEqual(sorted(json.loads(midias.ARQUIVO.read_text(encoding="utf-8"))), ["a.png"])

    def test_limites(self):
        self.assertEqual(midias.LIMITES, {"foto": 30_000_000, "audio": 50_000_000, "video": 200_000_000})


class Recebimento(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("entrada", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "ENTRADA", self.raiz / "entrada"), (config, "ENVIOS", self.raiz / "envios"),
                                  (midias, "ARQUIVO", self.raiz / "midias.json")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def enviar(self, dados, nome="a.png", **k):
        return envio.receber_arquivo(io.BytesIO(dados), len(dados), "foto", nome, **k)

    def test_foto_recebida_entra_no_registro_com_origem_e_medidas(self):
        r = self.enviar(png(), origem="link")
        self.assertEqual(r["arquivo"], "a.png")
        (m,) = midias.listar()
        self.assertEqual((m["nome"], m["tipo"], m["origem"], m["largura"], m["altura"]), ("a.png", "foto", "link", 30, 20))
        self.assertNotIn("arquivo", m)

    def test_origem_padrao_e_a_pagina_e_o_nome_final_e_o_registrado(self):
        self.enviar(png("red"))
        self.enviar(png("blue"))  # mesmo nome, conteudo diferente: a_2.png
        nomes = {m["nome"]: m["origem"] for m in midias.listar()}
        self.assertEqual(nomes, {"a.png": "pagina", "a_2.png": "pagina"})

    def test_envio_recusado_nao_registra(self):
        with self.assertRaises(validacao.Erro):
            self.enviar(b"nao e imagem")
        self.assertEqual(midias.listar(), [])

    def test_falha_ao_registrar_nao_derruba_o_envio(self):
        aviso = io.StringIO()
        with mock.patch.object(midias, "registrar", side_effect=OSError("disco cheio")), contextlib.redirect_stderr(aviso):
            r = self.enviar(png())
        self.assertIn("midias.json", aviso.getvalue())
        self.assertEqual(r["arquivo"], "a.png")
        self.assertTrue((entrada.pasta_envios() / "a.png").is_file())  # o envio novo vai para input/estudio/envios


class EnviosSimultaneos(Recebimento):
    """Dois envios com o MESMO nome ao mesmo tempo, com bytes diferentes, nunca viram um arquivo misturado."""
    def test_mesmo_nome_ao_mesmo_tempo_nao_mistura_os_arquivos(self):
        import random, threading
        imagens = []
        for semente in (1, 2):
            b = io.BytesIO()
            Image.frombytes("RGB", (40, 40), random.Random(semente).randbytes(40 * 40 * 3)).save(b, "BMP")  # mesmo tamanho, conteudo diferente
            imagens.append(b.getvalue())
        self.assertEqual(len(imagens[0]), len(imagens[1]))
        passo = threading.Barrier(2, timeout=10)

        class AosPoucos:
            """Entrega 512 bytes por vez e espera o outro envio chegar ao mesmo ponto: o entrelacamento nao depende do relogio."""
            def __init__(self, dados):
                self.dados, self.pos = dados, 0

            def read(self, n):
                passo.wait()
                bloco = self.dados[self.pos:self.pos + min(n, 512)]
                self.pos += len(bloco)
                return bloco

        resultados, erros = [], []

        def enviar(dados):
            try:
                resultados.append(envio.receber_arquivo(AosPoucos(dados), len(dados), "foto", "a.png"))
            except Exception as e:
                erros.append(e)

        fios = [threading.Thread(target=enviar, args=(d,)) for d in imagens]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(resultados), 2)
        gravados = {p.name: p.read_bytes() for p in entrada.pasta_envios().iterdir()}
        self.assertEqual(sorted(gravados.values()), sorted(imagens))  # cada imagem inteira, nenhuma misturada
        self.assertFalse([n for n in gravados if n.endswith(".parte")])
        self.assertEqual(sorted(m["nome"] for m in midias.listar()), sorted(gravados))
        self.assertEqual(sorted(r["arquivo"] for r in resultados), sorted(gravados))


if __name__ == "__main__":
    unittest.main()
