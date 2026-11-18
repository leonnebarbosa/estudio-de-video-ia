"""Testes da biblioteca de personagens (personagens.py) e do uso dos ângulos na troca. Não usam o ComfyUI nem a placa.

Uso: python -I testar_personagens.py
"""
import json, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, personagens, validacao
import trocar_personagem
from trocar_personagem import GRAFO, com_angulos, montar_grafo

P = {"duracao": 3, "proporcao": "16:9 (Widescreen)", "megapixels": 0.2, "upscale": False, "upscale_mesma": False, "upscale_megapixels": 1.0, "upscaler": "h3_upscaler_lms_v0.1.safetensors",
     "audio_original": True, "modelo": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "troca": ["minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", 1.0],
     "turbo": ["minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", 1.0], "nitidez": None, "pouca_vram": False, "dividir_blocos": False,
     "passos": 8, "agendador": "simple", "sampler": "euler", "semente": 42, "roupa": "foto"}
BASE = json.loads(GRAFO.read_text(encoding="utf-8"))


def ligacoes_validas(g):
    return all(v[0] in g for n in g.values() for v in n["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int))


class ComPastas(unittest.TestCase):
    """personagens/ e a input do ComfyUI numa pasta temporária."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("personagens", "entrada", "saida", "projetos", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((personagens, "PASTA", self.raiz / "personagens"), (config, "ENTRADA", self.raiz / "entrada"), (config, "SAIDA", self.raiz / "saida"),
                                  (config, "PROJETOS", self.raiz / "projetos"), (config, "ENVIOS", self.raiz / "envios")):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)
        self.foto = self.raiz / "ana.jpg"
        Image.new("RGB", (64, 96), "gray").save(self.foto)

    def criar(self, nome="Ana Souza", angulos=()):
        pid = personagens.criar(nome, "mulher de óculos", self.foto)
        for a in angulos:
            Image.new("RGB", (64, 96), "white").save(personagens.PASTA / pid / f"{a}.png")
        return pid


class Biblioteca(ComPastas):
    def test_id_sem_acento_e_unico(self):
        self.assertEqual(self.criar("Ána  Souza!"), "ana_souza")
        self.assertEqual(self.criar("Ana Souza"), "ana_souza_2")
        self.assertEqual(self.criar("###"), "personagem")

    def test_criar_grava_a_frente_em_png_e_a_ficha(self):
        pid = self.criar()
        self.assertTrue((personagens.PASTA / pid / "frente.png").is_file())
        f = personagens.ler(pid)
        self.assertEqual((f["nome"], f["descricao"], f["origem"]), ("Ana Souza", "mulher de óculos", "ana.jpg"))
        self.assertEqual(f["angulos"], {"frente": "frente.png", "tres_quartos": None, "perfil": None, "costas": None})
        self.assertEqual(personagens.faltam(pid), ["tres_quartos", "perfil", "costas"])

    def test_criar_recusa_sem_nome_ou_sem_foto(self):
        with self.assertRaises(ValueError):
            personagens.criar("  ", "", self.foto)
        with self.assertRaises(ValueError):
            personagens.criar("Ana", "", self.raiz / "nao_existe.png")
        self.assertEqual(list(personagens.PASTA.iterdir()), [])

    def test_criar_com_fotos_dos_outros_angulos(self):
        # Jeito 1 (desenho de 17/11/2026): perfil e três quartos viram referência de rosto; as costas entram como vieram
        perfil, costas = self.raiz / "perfil.webp", self.raiz / "costas.jpg"
        Image.new("RGB", (64, 96), "red").save(perfil)
        Image.new("RGB", (64, 96), "blue").save(costas, quality=100)
        with mock.patch("rostos_video.olha_para_direita", lambda img: False):
            pid = personagens.criar("Ana", "", self.foto, {"perfil": perfil, "costas": costas, "tres_quartos": None})
        pasta = personagens.PASTA / pid
        self.assertTrue((pasta / "ref_perfil.png").is_file() and (pasta / "costas.png").is_file())
        self.assertFalse((pasta / "perfil.png").exists())
        r, g, b = Image.open(pasta / "costas.png").getpixel((32, 48))
        self.assertTrue(b > 200 and r < 50 and g < 50)
        self.assertEqual(personagens.ler(pid).get("referencias"), ["perfil"])
        self.assertEqual(personagens.ler(pid)["enviadas"], ["costas"])
        # O Klein gera os três quartos e o perfil (este com a referência)
        self.assertEqual(personagens.faltam(pid), ["tres_quartos", "perfil"])

    def foto_meio_a_meio(self):
        """Metade esquerda preta, direita branca: mostra se a referência foi espelhada."""
        f = self.raiz / "lado.png"
        im = Image.new("RGB", (64, 96), "white")
        im.paste((0, 0, 0), (0, 0, 32, 96))
        im.save(f)
        return f

    def test_referencia_espelhada_quando_olha_para_a_direita(self):
        with mock.patch("rostos_video.olha_para_direita", lambda img: True):
            pid = personagens.criar("Ana", "", self.foto, {"perfil": self.foto_meio_a_meio()})
        self.assertEqual(Image.open(personagens.PASTA / pid / "ref_perfil.png").getpixel((2, 48)), (255, 255, 255))

    def test_lado_ja_medido_no_video_nao_detecta_de_novo(self):
        # Revisão de 18/11: num recorte de perfil o YuNet muitas vezes não acha o rosto; o lado medido no vídeo vale
        def nao_chamar(img):
            raise AssertionError("não devia detectar de novo")
        with mock.patch("rostos_video.olha_para_direita", nao_chamar):
            pid = personagens.criar("Ana", "", self.foto, {"perfil": self.foto_meio_a_meio()}, lados={"perfil": True})
        self.assertEqual(Image.open(personagens.PASTA / pid / "ref_perfil.png").getpixel((2, 48)), (255, 255, 255))

    def test_falha_ao_gravar_referencia_nao_deixa_pasta(self):
        # Revisão de 18/11: sobrava uma pasta com frente.png e sem ficha, o id ficava preso e a página via um 500
        def quebra(*a):
            raise OSError("disco cheio")
        with mock.patch.object(personagens, "gravar_referencia", quebra):
            with self.assertRaises(ValueError):
                personagens.criar("Ana", "", self.foto, {"perfil": self.foto})
        self.assertEqual(list(personagens.PASTA.iterdir()), [])

    def test_referencia_sem_rosto_nao_espelha(self):
        with mock.patch("rostos_video.olha_para_direita", lambda img: None):
            pid = personagens.criar("Ana", "", self.foto, {"perfil": self.foto_meio_a_meio()})
        self.assertEqual(Image.open(personagens.PASTA / pid / "ref_perfil.png").getpixel((2, 48)), (0, 0, 0))

    def test_pedido_com_rosto(self):
        self.assertEqual(personagens.pedido_com_rosto("perfil", ""), personagens.PEDIDOS["perfil"] + "." + personagens.FACE)
        self.assertEqual(personagens.pedido_com_rosto("perfil", "mulher"), personagens.PEDIDOS["perfil"] + ". The person: mulher." + personagens.FACE)
        self.assertNotIn("freckles", personagens.FACE)

    def gerar(self, pid):
        """Roda gerar_angulos com um ComfyUI falso; devolve {ângulo: grafo}."""
        grafos = {}

        def rodar(g, limite):
            angulo = g["9"]["inputs"]["filename_prefix"].split(f"{pid}_", 1)[1]
            grafos[angulo] = g
            Image.new("RGB", (8, 8), "red").save(config.SAIDA / f"{angulo}.png")
            return {"status": "success", "erro": "", "segundos": 40, "pico_vram": 7000, "temp_max": 60, "saidas": {"9": {"images": [{"filename": f"{angulo}.png", "subfolder": ""}]}}}

        with mock.patch("comfy_api.rodar", rodar):
            personagens.gerar_angulos(pid, avisar=lambda *a, **k: None)
        return grafos

    def test_gerar_angulos_com_referencia(self):
        with mock.patch("rostos_video.olha_para_direita", lambda img: False):
            pid = personagens.criar("Ana", "mulher de óculos", self.foto, {"perfil": self.foto})
        grafos = self.gerar(pid)
        g = grafos["perfil"]
        self.assertEqual(g["4"]["inputs"]["text"], personagens.pedido_com_rosto("perfil", "mulher de óculos"))
        self.assertTrue(g["32"]["inputs"]["image"].endswith("_ref_perfil.png"))
        self.assertNotIn("32", grafos["tres_quartos"])
        self.assertEqual(list(config.ENTRADA.iterdir()), [])

    def test_refazer_mantem_a_referencia(self):
        with mock.patch("rostos_video.olha_para_direita", lambda img: False):
            pid = personagens.criar("Ana", "", self.foto, {"perfil": self.foto})
        self.gerar(pid)
        personagens.apagar_angulo(pid, "perfil")
        self.assertTrue((personagens.PASTA / pid / "ref_perfil.png").is_file())
        self.assertEqual(personagens.ler(pid)["refeitos"]["perfil"], 1)
        g = self.gerar(pid)["perfil"]
        self.assertEqual(g["43"]["inputs"]["noise_seed"], 1001 + 100)
        self.assertIn("32", g)

    def test_ficha_antiga_com_perfil_enviado(self):
        pid = self.criar(angulos=("perfil",))
        ficha = personagens.PASTA / pid / personagens.FICHA
        f = json.loads(ficha.read_text(encoding="utf-8"))
        f["enviadas"] = ["perfil"]
        ficha.write_text(json.dumps(f), encoding="utf-8")
        self.assertNotIn("perfil", personagens.faltam(pid))
        self.assertNotIn("perfil", self.gerar(pid))

    def test_criar_recusa_angulo_desconhecido_ou_foto_que_falta(self):
        with self.assertRaises(ValueError):
            personagens.criar("Ana", "", self.foto, {"frente": self.foto})
        with self.assertRaises(ValueError):
            personagens.criar("Ana", "", self.foto, {"perfil": self.raiz / "nao_existe.png"})
        self.assertEqual(list(personagens.PASTA.iterdir()), [])

    def test_sem_fotos_a_ficha_nao_tem_enviadas(self):
        self.assertNotIn("enviadas", personagens.ler(self.criar()))

    def test_id_invalido_ou_desconhecido(self):
        for pid in ("../x", "Ana", "", "nao_existe"):
            with self.assertRaises(ValueError):
                personagens.pasta_de(pid)

    def test_listar_e_apagar(self):
        a, b = self.criar("Ana"), self.criar("Bruno")
        self.assertEqual({p["id"] for p in personagens.listar()}, {a, b})
        personagens.apagar(a)
        self.assertEqual([p["id"] for p in personagens.listar()], [b])

    def test_apagar_angulo_nao_apaga_a_frente(self):
        pid = self.criar(angulos=("perfil",))
        personagens.apagar_angulo(pid, "perfil")
        self.assertIn("perfil", personagens.faltam(pid))
        personagens.apagar_angulo(pid, "perfil")
        self.assertEqual(personagens.ler(pid)["refeitos"], {"perfil": 2})
        with self.assertRaises(ValueError):
            personagens.apagar_angulo(pid, "frente")

    def test_para_entrada(self):
        pid = self.criar(angulos=("tres_quartos", "perfil", "costas"))
        foto, angulos = personagens.para_entrada(pid)
        self.assertTrue(foto.endswith("_frente.png") and (config.ENTRADA / foto).is_file())
        self.assertEqual([n.rsplit("_", 1)[-1] for n in angulos], ["quartos.png", "perfil.png", "costas.png"])
        # Head Swap: sem as costas; sem ângulos: só a frente
        self.assertFalse(any("costas" in n for n in personagens.para_entrada(pid, sem_costas=True)[1]))
        self.assertEqual(personagens.para_entrada(pid, com_angulos=False)[1], [])

    def test_gerar_angulos_copia_a_saida_e_limpa_a_entrada(self):
        pid = self.criar(angulos=("perfil",))
        chamados = []

        def rodar(g, limite):
            angulo = g["9"]["inputs"]["filename_prefix"].rsplit("_", 1)[-1]
            chamados.append((g["4"]["inputs"]["text"], g["30"]["inputs"]["image"]))
            Image.new("RGB", (8, 8), "red").save(config.SAIDA / f"{angulo}.png")
            return {"status": "success", "erro": "", "segundos": 40, "pico_vram": 7000, "temp_max": 60, "saidas": {"9": {"images": [{"filename": f"{angulo}.png", "subfolder": ""}]}}}

        with mock.patch("comfy_api.rodar", rodar):
            tempos = personagens.gerar_angulos(pid, avisar=lambda *a, **k: None)
        # O perfil já existia: só três quartos e costas
        self.assertEqual(set(tempos), {"tres_quartos", "costas"})
        self.assertEqual(chamados[0][0], personagens.PEDIDOS["tres_quartos"] + ". The person: mulher de óculos.")
        self.assertEqual(personagens.pedido_angulo("perfil", ""), personagens.PEDIDOS["perfil"])
        self.assertEqual(personagens.faltam(pid), [])
        self.assertEqual(list(config.ENTRADA.iterdir()), [])

    def test_gerar_angulos_falha_sem_imagem(self):
        pid = self.criar()
        with mock.patch("comfy_api.rodar", lambda g, l: {"status": "error", "erro": "sem memória", "segundos": 1, "pico_vram": 0, "temp_max": 0, "saidas": {}}):
            with self.assertRaises(RuntimeError):
                personagens.gerar_angulos(pid, avisar=lambda *a, **k: None)
        self.assertEqual(list(config.ENTRADA.iterdir()), [])


class AngulosNaTroca(unittest.TestCase):
    def test_sem_angulos_nada_muda(self):
        g = montar_grafo(BASE, P, "v.mp4", "f.png", "troca/x", 42, 7)
        antes = json.dumps(g, sort_keys=True)
        com_angulos(g, [], 1)
        self.assertEqual(json.dumps(g, sort_keys=True), antes)

    def test_uma_passada(self):
        g = montar_grafo(BASE, P, "v.mp4", "f.png", "troca/x", 42, 7)
        com_angulos(g, ["a.png", "b.png"], 1)
        for no in ("400", "587"):
            self.assertEqual(g[no]["inputs"]["ref_images.ref_image_1"], ["990", 0])
            self.assertEqual(g[no]["inputs"]["ref_images.ref_image_2"], ["991", 0])
        self.assertEqual(g["980"]["inputs"]["image"], "a.png")
        # O prompt da LLM ganha a frase; o 827 (o que fica registrado) continua sendo o da LLM
        self.assertEqual(g["400"]["inputs"]["prompt"], ["979", 0])
        self.assertEqual(g["979"]["inputs"]["string_b"], " <Picture 2> and <Picture 3> show the same character from other angles.")
        self.assertEqual(g["827"]["inputs"]["source"], ["835", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_janela_seguinte_numera_depois_do_quadro_de_referencia(self):
        j = trocar_personagem.janelas(120, 73)[1]
        g = trocar_personagem.grafo_janela(BASE, {**P, "angulos": ["a.png"]}, j, "c.mp4", "f.png", "troca/x/j2", 42, 7, "PROMPT", "ref.png")
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_1"], ["960", 0])
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_2"], ["990", 0])
        self.assertTrue(g["400"]["inputs"]["prompt"].startswith("PROMPT"))
        self.assertTrue(g["400"]["inputs"]["prompt"].endswith(" <Picture 3> shows the same character from other angles."))
        self.assertNotIn("979", g)
        self.assertTrue(ligacoes_validas(g))

    def test_primeira_janela_numera_logo_depois_da_foto(self):
        j = trocar_personagem.janelas(120, 73)[0]
        g = trocar_personagem.grafo_janela(BASE, {**P, "angulos": ["a.png"]}, j, "c.mp4", "f.png", "troca/x/j1", 42, 7)
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_1"], ["990", 0])
        self.assertIn("<Picture 2>", g["979"]["inputs"]["string_b"])
        self.assertTrue(ligacoes_validas(g))

    def test_head_swap_tambem_recebe(self):
        g = montar_grafo(BASE, {**P, "roupa": "video"}, "v.mp4", "f.png", "troca/x", 42, 7)
        com_angulos(g, ["a.png"], 1)
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_0"], ["902", 0])
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_1"], ["990", 0])
        self.assertTrue(ligacoes_validas(g))


class Acoes(ComPastas):
    def setUp(self):
        super().setUp()
        import acoes, tarefa
        self.acoes = acoes
        (config.ENVIOS / "v.mp4").write_bytes(b"x")
        self.lancados = []
        t = types.SimpleNamespace(rodando=lambda: False, iniciar_troca=self.lancados.append, iniciar_personagem=self.lancados.append, projeto=None, tipo=None)
        for alvo, nome, valor in ((acoes, "exigir_comfy_livre", lambda: None), (acoes, "examinar_video", lambda v: {"quadros": 240, "duracao": 10.0, "audio": True}),
                                  (acoes, "validar_troca", lambda a: {**P, **a}), (acoes.caminhos, "guardar_envio", lambda v: str(v)), (tarefa, "tarefa", t)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_criar_de_foto_enviada_e_gerar(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_personagem_criar({"nome": "Cida", "foto": "env.png"})
        r = self.acoes.acao_personagem_criar({"nome": "Cida", "foto": "env.png", "autorizacao": True, "angulos": True})
        self.assertEqual(r, {"id": "cida"})
        self.assertEqual(self.lancados, ["cida"])

    def test_criar_de_imagem_de_projeto(self):
        (config.PROJETOS / "p1").mkdir()
        Image.new("RGB", (32, 32)).save(config.PROJETOS / "p1" / "imagem_2.png")
        r = self.acoes.acao_personagem_criar({"nome": "Bruno", "projeto": "p1", "imagem": "imagem_2.png", "autorizacao": True})
        self.assertEqual(personagens.ler(r["id"])["origem"], "imagem_2.png")
        self.assertEqual(self.lancados, [])
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_personagem_criar({"nome": "X", "projeto": "p1", "imagem": "../a.png", "autorizacao": True})

    def test_angulos_e_refazer_um(self):
        pid = self.criar(angulos=("tres_quartos", "perfil", "costas"))
        with self.assertRaises(validacao.Erro) as e:
            self.acoes.acao_personagem_angulos({"id": pid})
        self.assertEqual(e.exception.codigo, 409)
        self.acoes.acao_personagem_angulos({"id": pid, "angulo": "perfil"})
        self.assertEqual(personagens.faltam(pid), ["perfil"])
        self.assertEqual(self.lancados, [pid])

    def test_apagar_pede_confirmacao(self):
        pid = self.criar()
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_personagem_apagar({"id": pid})
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True})
        self.assertEqual(personagens.listar(), [])

    # Rostos de um vídeo (rostos_video.py): extrair na CPU, sem a fila, e usar um rosto no personagem novo
    EXTRAIDO = {"frente": [{"arquivo": "frente_0.png", "t": 1.0, "giro": 0.0, "nota": 9.0, "quadro": "frente_0_quadro.png"}], "tres_quartos": [],
                "perfil": [{"arquivo": "perfil_0.png", "t": 2.0, "giro": 0.7, "nota": 8.0}], "legenda": True}

    def extrair_falso(self, resultado):
        m = mock.patch.object(self.acoes.rostos_video, "extrair", lambda video, pasta: json.loads(json.dumps(resultado)))
        m.start()
        self.addCleanup(m.stop)
        m2 = mock.patch.object(self.acoes, "exigir_comfy_livre", lambda: self.fail("a extração não pode exigir o ComfyUI livre"))
        m2.start()
        self.addCleanup(m2.stop)

    def test_rostos_de_video(self):
        self.extrair_falso(self.EXTRAIDO)
        r = self.acoes.acao_personagem_rostos({"video": "v.mp4"})
        self.assertEqual(r["pasta"], "rostos_v")
        self.assertEqual(r["perfil"][0]["url"], "/rostos/rostos_v/perfil_0.png")
        self.assertEqual(r["frente"][0]["url_quadro"], "/rostos/rostos_v/frente_0_quadro.png")
        self.assertTrue(r["legenda"])
        self.assertEqual(self.lancados, [])

    def test_rostos_de_video_sem_rosto(self):
        self.extrair_falso({"frente": [], "tres_quartos": [], "perfil": [], "legenda": False})
        r = self.acoes.acao_personagem_rostos({"video": "v.mp4"})
        self.assertEqual((r["frente"], r["tres_quartos"], r["perfil"]), ([], [], []))

    def test_rostos_do_mesmo_video_ao_mesmo_tempo(self):
        def ocupado(video, pasta):
            raise self.acoes.rostos_video.Ocupado("Já estou procurando rostos nesse vídeo.")
        with mock.patch.object(self.acoes.rostos_video, "extrair", ocupado):
            with self.assertRaises(validacao.Erro) as e:
                self.acoes.acao_personagem_rostos({"video": "v.mp4"})
        self.assertEqual(e.exception.codigo, 409)

    def test_rostos_video_inexistente(self):
        self.extrair_falso(self.EXTRAIDO)
        for video in ("nao.mp4", "../v.mp4", ""):
            with self.assertRaises(validacao.Erro) as e:
                self.acoes.acao_personagem_rostos({"video": video})
            self.assertEqual(e.exception.codigo, 404)

    def test_rosto_usar_copia_para_a_entrada(self):
        (config.ENVIOS / "rostos_v").mkdir()
        Image.new("RGB", (40, 50)).save(config.ENVIOS / "rostos_v" / "perfil_0.png")
        (config.ENVIOS / "rostos_v" / "candidatos.json").write_text(json.dumps(self.EXTRAIDO), encoding="utf-8")
        r = self.acoes.acao_personagem_rosto_usar({"pasta": "rostos_v", "arquivo": "perfil_0.png"})
        # "direita": o lado medido no vídeo (giro 0,7 > 0), para a referência ser espelhada sem detectar de novo
        self.assertEqual(r, {"arquivo": "rostos_v_perfil_0.png", "largura": 40, "altura": 50, "direita": True})
        self.assertTrue((config.ENTRADA / "rostos_v_perfil_0.png").is_file())
        with self.assertRaises(validacao.Erro) as e:
            self.acoes.acao_personagem_rosto_usar({"pasta": "rostos_v", "arquivo": "../x.png"})
        self.assertEqual(e.exception.codigo, 404)

    def test_criar_com_rosto_do_video(self):
        (config.ENVIOS / "rostos_v").mkdir()
        Image.new("RGB", (40, 50)).save(config.ENVIOS / "rostos_v" / "perfil_0.png")
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        nome = self.acoes.acao_personagem_rosto_usar({"pasta": "rostos_v", "arquivo": "perfil_0.png"})["arquivo"]
        with mock.patch("rostos_video.olha_para_direita", lambda img: self.fail("o lado veio da página")):
            r = self.acoes.acao_personagem_criar({"nome": "Dora", "foto": "env.png", "autorizacao": True, "fotos": {"perfil": nome}, "lados": {"perfil": False, "costas": "x"}})
        self.assertEqual(personagens.ler(r["id"]).get("referencias"), ["perfil"])
        # Depois de criar, a pasta de rostos daquele vídeo não serve mais (~18 MB): sai
        self.assertFalse((config.ENVIOS / "rostos_v").exists())

    def test_troca_com_personagem(self):
        pid = self.criar(angulos=("tres_quartos", "perfil", "costas"))
        self.acoes.acao_iniciar_troca({"projeto": "t1", "video": "v.mp4", "duracao": 3, "autorizacao": True, "personagem": {"id": pid, "angulos": True}, "ajustes": {"megapixels": 0.2}})
        p = json.loads((config.PROJETOS / "t1" / validacao.PARAMETROS).read_text(encoding="utf-8"))
        e = json.loads((config.PROJETOS / "t1" / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual(p["personagem_id"], pid)
        self.assertEqual(len(p["angulos"]), 3)
        self.assertTrue(e["personagem"].endswith("_frente.png") and (config.ENTRADA / e["personagem"]).is_file())
        # Head Swap (roupa do vídeo): sem as costas; sem ângulos: só a frente
        self.acoes.acao_iniciar_troca({"projeto": "t2", "video": "v.mp4", "duracao": 3, "autorizacao": True, "personagem": {"id": pid, "angulos": True}, "ajustes": {"megapixels": 0.2, "roupa": "video"}})
        self.assertEqual(len(json.loads((config.PROJETOS / "t2" / validacao.PARAMETROS).read_text(encoding="utf-8"))["angulos"]), 2)
        self.acoes.acao_iniciar_troca({"projeto": "t3", "video": "v.mp4", "duracao": 3, "autorizacao": True, "personagem": {"id": pid}, "ajustes": {"megapixels": 0.2}})
        self.assertEqual(json.loads((config.PROJETOS / "t3" / validacao.PARAMETROS).read_text(encoding="utf-8"))["angulos"], [])
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_iniciar_troca({"projeto": "t4", "video": "v.mp4", "duracao": 3, "autorizacao": True, "personagem": {"id": "nao_existe"}, "ajustes": {"megapixels": 0.2}})
        self.assertEqual(self.lancados, ["t1", "t2", "t3"])



class Rotas(ComPastas):
    """As rotas da biblioteca no servidor no ar, numa porta de teste, com a pasta personagens/ temporária."""
    PORTA = 8197

    def setUp(self):
        super().setUp()
        import threading, servidor
        self.s = servidor.criar(self.PORTA)
        fio = threading.Thread(target=self.s.serve_forever, daemon=True)
        fio.start()
        self.addCleanup(fio.join, 5)
        self.addCleanup(self.s.server_close)
        self.addCleanup(self.s.shutdown)

    def pedir(self, caminho, dados=None):
        import urllib.request
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.PORTA}{caminho}", headers={"Host": f"127.0.0.1:{self.PORTA}", "Content-Type": "application/json"},
                                        data=None if dados is None else json.dumps(dados).encode(), method="GET" if dados is None else "POST")
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_lista_imagem_e_usar(self):
        import urllib.error
        pid = self.criar(angulos=("perfil",))
        codigo, _, corpo = self.pedir("/api/personagens")
        j = json.loads(corpo)
        self.assertEqual([p["id"] for p in j["personagens"]], [pid])
        self.assertEqual([a["id"] for a in j["angulos"]], list(personagens.ORDEM))
        codigo, tipo, corpo = self.pedir(f"/personagem/{pid}/perfil.png")
        self.assertEqual((codigo, tipo), (200, "image/png"))
        for caminho in (f"/personagem/{pid}/costas.png", f"/personagem/{pid}/ficha.json", "/personagem/..%2F..%2Fconfig/frente.png", "/personagem/nao_existe/frente.png"):
            with self.assertRaises(urllib.error.HTTPError, msg=caminho) as c:
                self.pedir(caminho)
            self.assertEqual(c.exception.code, 404, caminho)
        _, _, corpo = self.pedir("/api/personagem-usar", {"id": pid})
        r = json.loads(corpo)
        self.assertEqual((r["id"], r["nome"], len(r["angulos"])), (pid, "Ana Souza", 1))
        self.assertTrue((config.ENTRADA / r["foto"]).is_file())
        with self.assertRaises(urllib.error.HTTPError) as c:
            self.pedir("/api/personagem-usar", {"id": "nao_existe"})
        self.assertEqual(c.exception.code, 404)

    def test_rostos_miniatura_e_usar(self):
        import urllib.error
        (config.ENVIOS / "rostos_v").mkdir()
        Image.new("RGB", (40, 50)).save(config.ENVIOS / "rostos_v" / "perfil_0.png")
        codigo, tipo, _ = self.pedir("/rostos/rostos_v/perfil_0.png")
        self.assertEqual((codigo, tipo), (200, "image/png"))
        for caminho in ("/rostos/rostos_v/perfil_1.png", "/rostos/rostos_v/..%2F..%2Fconfig.py", "/rostos/outra/perfil_0.png"):
            with self.assertRaises(urllib.error.HTTPError, msg=caminho) as c:
                self.pedir(caminho)
            self.assertEqual(c.exception.code, 404, caminho)
        _, _, corpo = self.pedir("/api/personagem-rosto-usar", {"pasta": "rostos_v", "arquivo": "perfil_0.png"})
        self.assertEqual(json.loads(corpo)["arquivo"], "rostos_v_perfil_0.png")
        with self.assertRaises(urllib.error.HTTPError) as c:
            self.pedir("/api/personagem-rostos", {"video": "nao.mp4"})
        self.assertEqual(c.exception.code, 404)


class Gatilho(unittest.TestCase):
    """A Realism People (fal) pede a palavra r34l1sm no prompt."""
    REAL = ["h3-realism-people-t2v-i2v-r2v.safetensors", 1.0]

    def test_palavra_so_com_a_lora(self):
        import loras
        self.assertEqual(loras.gatilho([self.REAL]), "r34l1sm")
        self.assertEqual(loras.gatilho([["natural_face_speech_h3_lora_v2_500.safetensors", 0.7]]), "")
        self.assertEqual(loras.gatilho(None), "")

    def test_troca_uma_passada_e_janela(self):
        g = montar_grafo(BASE, P, "v.mp4", "f.png", "troca/x", 42, 7)
        com_angulos(g, ["a.png"], 1, "r34l1sm")
        self.assertEqual(g["978"]["inputs"]["string_a"], "r34l1sm ")
        self.assertEqual(g["979"]["inputs"]["string_a"], ["978", 0])
        self.assertEqual(g["400"]["inputs"]["prompt"], ["979", 0])
        self.assertEqual(g["550"]["inputs"]["string_a"], ["979", 0])
        self.assertTrue(ligacoes_validas(g))
        # Só o gatilho, sem ângulos
        g = montar_grafo(BASE, P, "v.mp4", "f.png", "troca/x", 42, 7)
        com_angulos(g, [], 1, "r34l1sm")
        self.assertEqual(g["400"]["inputs"]["prompt"], ["978", 0])
        self.assertNotIn("979", g)
        j = trocar_personagem.janelas(120, 73)[1]
        g = trocar_personagem.grafo_janela(BASE, {**P, "loras": [self.REAL]}, j, "c.mp4", "f.png", "troca/x/j2", 42, 7, "PROMPT", "ref.png")
        self.assertTrue(g["400"]["inputs"]["prompt"].startswith("r34l1sm PROMPT"))

    def test_imagem_para_video(self):
        import imagem_para_video as ipv
        self.assertEqual(ipv.com_gatilho({"loras": [self.REAL]}, "abc"), "r34l1sm abc")
        self.assertEqual(ipv.com_gatilho({"loras": []}, "abc"), "abc")

    def test_turnaround_nao_e_lora_de_estilo(self):
        import ambiente
        self.assertFalse(ambiente.lora_de_estilo("h3/minimax_h3_five_view_512_s1500.safetensors"))
        self.assertTrue(ambiente.lora_de_estilo("h3/h3-realism-people-t2v-i2v-r2v.safetensors"))
        self.assertTrue(ambiente.lora_de_estilo("h3/natural_face_speech_h3_lora_v2_500.safetensors"))


class CabecaDaFoto(ComPastas):
    """Head Swap: só a cabeça da foto (máscaras head + hair do SAM 3.1) num fundo cinza."""

    def sam_falso(self, caixas):
        """rodar() falso: grava uma máscara por texto (head, hair) com o retângulo branco dado."""
        def rodar(g, limite):
            saidas = {}
            for no, caixa in zip(("60", "61"), caixas):
                m = Image.new("L", (64, 96), 0)
                if caixa:
                    m.paste(255, caixa)
                nome = f"{no}.png"
                m.save(config.SAIDA / nome)
                saidas[no] = {"images": [{"filename": nome, "subfolder": ""}]}
            self.grafo = g
            return {"status": "success", "saidas": saidas, "erro": ""}
        return rodar

    def setUp(self):
        super().setUp()
        Image.new("RGB", (64, 96), "red").save(config.ENTRADA / "foto.png")
        # Descarregar o SAM depois do recorte: sem ComfyUI de verdade nem espera
        for alvo in (mock.patch.object(trocar_personagem, "posta"), mock.patch.object(trocar_personagem.time, "sleep")):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.posta = trocar_personagem.posta

    def test_recorta_a_uniao_das_mascaras(self):
        with mock.patch.object(trocar_personagem, "rodar", self.sam_falso([(20, 10, 44, 40), (16, 8, 48, 50)])), mock.patch.object(trocar_personagem, "VAZIA", 4):
            nome = trocar_personagem.cabeca_da_foto("foto.png")
        self.assertTrue(nome.startswith("cab_"))
        with Image.open(config.ENTRADA / nome) as im:
            # a união vai de x 16 a 47 e de y 8 a 49 (32 x 42), com folga de 12% do lado maior (5 px)
            self.assertEqual(im.size, (42, 52))
            self.assertEqual(im.getpixel((21, 26)), (255, 0, 0))
            self.assertEqual(im.getpixel((0, 0)), trocar_personagem.FUNDO_CABECA)
        self.assertEqual([self.grafo[n]["inputs"]["text"] for n in ("20", "21")], ["head", "hair"])
        self.assertEqual(list(config.SAIDA.iterdir()), [])
        self.posta.assert_called_once_with("/free", {"unload_models": True, "free_memory": True})

    def test_preenche_buracos(self):
        import numpy as np
        m = np.zeros((20, 20), bool)
        m[2:12, 2:12] = True
        m[5:8, 5:8] = False           # a boca que o SAM deixou de fora: cercada, vira mascara
        m[12:, 9:11] = False          # aberto para a borda: continua fora
        r = trocar_personagem.sem_buracos(m)
        self.assertTrue(r[5:8, 5:8].all())
        self.assertFalse(r[15, 10])
        self.assertEqual(int(r.sum()), 100)

    def test_sem_cabeca_devolve_nada(self):
        with mock.patch.object(trocar_personagem, "rodar", self.sam_falso([None, None])):
            self.assertIsNone(trocar_personagem.cabeca_da_foto("foto.png"))

    def test_opcao_na_validacao(self):
        self.assertTrue(validacao.PADRAO_TROCA["recortar_cabeca"])
        self.assertFalse(validacao.validar_troca({"recortar_cabeca": False, "esrgan": False})["recortar_cabeca"])


class RostoBorradoNoGuia(ComPastas):
    """source_blur: o rosto de quem esta no video-guia borrado, a boca nitida, o som mantido."""

    def test_borrar_so_onde_o_peso_vale(self):
        import numpy as np
        q = np.zeros((64, 96, 3), np.uint8)
        q[::2, ::2] = 255                     # xadrez fino: o borrao acaba com ele
        peso = np.zeros((64, 96), np.float32)
        peso[:, 48:] = 1
        r = trocar_personagem.borrar(q, peso)
        self.assertTrue((r[:, :40] == q[:, :40]).all())
        self.assertLess(int(r[10:50, 60:90].std()), 20)
        self.assertGreater(int(q[10:50, 60:90].std()), 100)

    def test_crescer_e_peso_suave(self):
        import numpy as np
        m = np.zeros((20, 20), bool)
        m[10, 10] = True
        self.assertEqual(int(trocar_personagem.crescer(m, 2).sum()), 25)
        p = trocar_personagem.peso_suave(np.ones((10, 10), bool), 40, 40)
        self.assertEqual(p.shape, (40, 40))
        self.assertAlmostEqual(float(p[20, 20]), 1.0, places=3)

    def gravar_video(self, nome, n=6, som=True):
        import imageio_ffmpeg, subprocess
        args = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=96x64:rate=24:duration={n / 24}"]
        if som:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={n / 24}", "-c:a", "aac"]
        subprocess.run(args + ["-pix_fmt", "yuv420p", "-shortest", str(config.ENTRADA / nome)], check=True)

    def test_troca_o_guia_pelo_borrado(self):
        import numpy as np, av
        self.gravar_video("v.mp4")
        def sam(video, texto, total, w, h, limiar):
            m = np.zeros((total, h, w), bool)
            if texto == "face":
                m[:, 10:50, 20:70] = True
            else:
                m[:, 40:46, 40:50] = True
            return m
        pasta = config.PROJETOS / "p"
        pasta.mkdir()
        with mock.patch.object(trocar_personagem, "mascaras_sam_texto", sam), mock.patch.object(trocar_personagem, "posta"), \
                mock.patch.object(trocar_personagem.time, "sleep"):
            self.assertTrue(trocar_personagem.borrar_rosto_do_guia("v.mp4", 4, pasta))
        self.assertTrue((pasta / "guia_borrado.mp4").is_file())
        self.assertFalse((pasta / "borrao_trab").exists())
        with av.open(str(config.ENTRADA / "v.mp4")) as c:
            self.assertTrue(c.streams.audio)
            self.assertEqual(sum(1 for _ in c.decode(video=0)), 4)

    def test_sem_rosto_o_guia_fica(self):
        import numpy as np
        self.gravar_video("v.mp4", som=False)
        antes = (config.ENTRADA / "v.mp4").read_bytes()
        pasta = config.PROJETOS / "p"
        pasta.mkdir()
        with mock.patch.object(trocar_personagem, "mascaras_sam_texto", lambda v, t, n, w, h, l: np.zeros((n, h, w), bool)):
            self.assertFalse(trocar_personagem.borrar_rosto_do_guia("v.mp4", 4, pasta))
        self.assertEqual((config.ENTRADA / "v.mp4").read_bytes(), antes)
        self.assertFalse((pasta / "borrao_trab").exists())

    def test_opcao_desligada_por_padrao(self):
        self.assertFalse(validacao.PADRAO_TROCA["borrar_rosto"])
        self.assertTrue(validacao.validar_troca({"borrar_rosto": True, "esrgan": False})["borrar_rosto"])


if __name__ == "__main__":
    unittest.main()
