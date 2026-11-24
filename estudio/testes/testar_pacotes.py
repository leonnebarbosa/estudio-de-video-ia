"""Pacotes de modelos: catalogo, situacao e download (com servidor falso, sem rede)."""
import hashlib, io, tempfile, threading, unittest, urllib.error
from pathlib import Path

import pacotes
from erros import Erro


class Resposta(io.BytesIO):
    def __init__(self, dados, status=200):
        super().__init__(dados)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def servidor_falso(dados: bytes, ignora_range=False, quebra_em=None):
    """Imita o Hugging Face: aceita Range. `quebra_em`: corta a primeira resposta nesse byte (conexao caiu)."""
    pedidos = []

    def abrir(pedido, timeout=None):
        pedidos.append(dict(pedido.header_items()))
        rng = pedido.get_header("Range")
        inicio = int(rng[6:-1]) if rng and not ignora_range else 0
        corpo = dados[inicio:]
        if quebra_em is not None and len(pedidos) == 1:
            corpo = corpo[:quebra_em]
        return Resposta(corpo, 206 if inicio else 200)
    return abrir, pedidos


def item(dados, caminho="vae/teste.safetensors", url="https://huggingface.co/x/y/resolve/main/teste.safetensors"):
    return {"caminho": caminho, "url": url, "tamanho": len(dados), "sha256": hashlib.sha256(dados).hexdigest()}


class TestCatalogo(unittest.TestCase):
    def test_catalogo_real_e_valido(self):
        ps = pacotes.carregar()
        self.assertEqual(len([p for p in ps if p.get("inicial")]), 1, "um pacote inicial")
        ids = [p["id"] for p in ps]
        self.assertEqual(len(ids), len(set(ids)))
        for p in ps:
            self.assertTrue(p["nome"] and p["descricao"] and p["libera"] and p["arquivos"])

    def test_pacote_inicial_traz_o_z_image_turbo(self):
        """O pacote inicial traz tudo que o Z-Image Turbo da aba Texto para imagem pede."""
        from texto_para_imagem import MODELOS_TEXTO
        m = MODELOS_TEXTO["z_image_turbo"]
        inicial = next(p for p in pacotes.carregar() if p.get("inicial"))
        nomes = {a["caminho"].rsplit("/", 1)[-1] for a in inicial["arquivos"]}
        self.assertLessEqual({m["unet"], m["encoder"], m["vae"]}, nomes)

    def test_pacote_de_varias_referencias_traz_o_qwen_21(self):
        """O pacote referencias traz tudo que o Várias referências (Qwen Image 2.1) do Texto para imagem pede."""
        from texto_para_imagem import MODELOS_TEXTO
        m = MODELOS_TEXTO["qwen21_edit"]
        p = next(p for p in pacotes.carregar() if p["id"] == "referencias")
        self.assertLessEqual({m["unet"], m["encoder"], m["vae"]}, {a["caminho"].rsplit("/", 1)[-1] for a in p["arquivos"]})

    def test_recusa_origem_e_caminho_ruins(self):
        base = item(b"abc")
        for ruim in ({**base, "url": "http://huggingface.co/x"}, {**base, "url": "https://exemplo.com/x"},
                     {**base, "caminho": "../fora.safetensors"}, {**base, "caminho": "vae/x.exe"}, {**base, "caminho": "C:/x.safetensors"},
                     {**base, "tamanho": 0}, {**base, "sha256": "x" * 64}):
            with self.assertRaises(Erro):
                pacotes._conferir(ruim)


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = Path(self.tmp.name) / "models"
        self.dados = bytes(range(256)) * 4000  # ~1 MB
        self.final = self.models / "vae" / "teste.safetensors"
        self.parte = self.models / "vae" / "teste.safetensors.parte"

    def tearDown(self):
        self.tmp.cleanup()

    def baixar(self, a, abrir, **kw):
        contado = []
        pacotes.baixar_arquivo(a, self.models, contado.append, abrir=abrir, esperar=lambda s: None, **kw)
        return sum(contado)

    def test_baixa_confere_e_renomeia(self):
        abrir, _ = servidor_falso(self.dados)
        self.assertEqual(self.baixar(item(self.dados), abrir), len(self.dados))
        self.assertEqual(self.final.read_bytes(), self.dados)
        self.assertFalse(self.parte.exists())

    def test_retoma_depois_de_cair(self):
        abrir, pedidos = servidor_falso(self.dados, quebra_em=300_000)
        self.baixar(item(self.dados), abrir)
        self.assertEqual(self.final.read_bytes(), self.dados)
        self.assertEqual(pedidos[1].get("Range"), "bytes=300000-")

    def test_retoma_parte_de_antes(self):
        self.parte.parent.mkdir(parents=True)
        self.parte.write_bytes(self.dados[:5000])
        abrir, pedidos = servidor_falso(self.dados)
        self.assertEqual(self.baixar(item(self.dados), abrir), len(self.dados) - 5000)
        self.assertEqual(pedidos[0].get("Range"), "bytes=5000-")
        self.assertEqual(self.final.read_bytes(), self.dados)

    def test_servidor_que_ignora_range_recomeca(self):
        self.parte.parent.mkdir(parents=True)
        self.parte.write_bytes(self.dados[:5000])
        abrir, _ = servidor_falso(self.dados, ignora_range=True)
        self.baixar(item(self.dados), abrir)
        self.assertEqual(self.final.read_bytes(), self.dados)

    def test_corrompido_e_descartado(self):
        abrir, _ = servidor_falso(self.dados[:-1] + b"\0")
        with self.assertRaisesRegex(Erro, "corrompido"):
            self.baixar(item(self.dados), abrir)
        self.assertFalse(self.final.exists())
        self.assertFalse(self.parte.exists())

    def test_404_nao_tenta_de_novo(self):
        chamadas = []

        def abrir(pedido, timeout=None):
            chamadas.append(1)
            raise urllib.error.HTTPError(pedido.full_url, 404, "x", {}, None)
        with self.assertRaisesRegex(Erro, "não está mais disponível"):
            self.baixar(item(self.dados), abrir)
        self.assertEqual(len(chamadas), 1)

    def test_conexao_que_nao_volta_desiste(self):
        def abrir(pedido, timeout=None):
            raise ConnectionResetError()
        with self.assertRaisesRegex(Erro, "conexão caiu"):
            self.baixar(item(self.dados), abrir)

    def test_cancelar(self):
        abrir, _ = servidor_falso(self.dados)
        parar = threading.Event()
        parar.set()
        with self.assertRaises(pacotes.Cancelado):
            self.baixar(item(self.dados), abrir, parar=parar)
        self.assertFalse(self.final.exists())


class TestBaixador(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = Path(self.tmp.name) / "models"
        self.a, self.b = b"a" * 1000, b"b" * 2000
        comum = item(self.a, "text_encoders/comum.safetensors", "https://huggingface.co/a")
        self.ps = [{"id": "um", "nome": "Um", "arquivos": [comum, item(self.b, "loras/h3/b.safetensors", "https://huggingface.co/b")]},
                   {"id": "dois", "nome": "Dois", "arquivos": [comum]}]
        self.abrir = lambda pedido, timeout=None: Resposta(self.a if pedido.full_url.endswith("/a") else self.b)

    def tearDown(self):
        self.tmp.cleanup()

    def test_situacao_e_download_sem_repetir_arquivo(self):
        s = {x["id"]: x for x in pacotes.situacao(self.ps, self.models)}
        self.assertFalse(s["um"]["pronto"])
        self.assertEqual(s["um"]["falta"], 3000)
        b = pacotes.Baixador(abrir=self.abrir, esperar=lambda s: None)
        nomes, f = b.preparar(["um", "dois"], self.ps, self.models)
        self.assertEqual(len(f), 2, "o arquivo comum entra uma vez")
        b.baixar(nomes, f, self.models)
        self.assertEqual(b.resumo()["situacao"], "pronto")
        s = {x["id"]: x for x in pacotes.situacao(self.ps, self.models)}
        self.assertTrue(s["um"]["pronto"] and s["dois"]["pronto"])
        with self.assertRaisesRegex(Erro, "já estão baixados"):
            b.preparar(["dois"], self.ps, self.models)

    def test_arquivo_em_outra_subpasta_conta_como_presente(self):
        """O ComfyUI acha a LoRA pelo nome em qualquer subpasta: quem ja tem loras/b.safetensors nao baixa de novo."""
        (self.models / "loras").mkdir(parents=True)
        (self.models / "loras" / "b.safetensors").write_bytes(self.b)
        f = pacotes.faltando(self.ps[0], self.models)
        self.assertEqual([a["caminho"] for a in f], ["text_encoders/comum.safetensors"])

    def test_sem_espaco_recusa_antes_de_comecar(self):
        b = pacotes.Baixador(abrir=self.abrir)
        original = pacotes.livre
        pacotes.livre = lambda pasta: 100
        try:
            with self.assertRaisesRegex(Erro, "Falta espaço"):
                b.preparar(["um"], self.ps, self.models)
        finally:
            pacotes.livre = original

    def test_em_segundo_plano(self):
        b = pacotes.Baixador(abrir=self.abrir, esperar=lambda s: None)
        b.iniciar(["um"], self.ps, self.models)
        b.fio.join(5)
        self.assertEqual(b.resumo()["situacao"], "pronto")
        with self.assertRaises(Erro):
            b.iniciar(["xyz"], self.ps, self.models)


if __name__ == "__main__":
    unittest.main()
