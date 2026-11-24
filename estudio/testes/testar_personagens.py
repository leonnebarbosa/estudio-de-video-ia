"""Testes da biblioteca de personagens (personagens.py) e do uso dos ângulos na troca. Não usam o ComfyUI nem a placa.

Uso: python -I testar_personagens.py
"""
import json, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, entrada, personagens, validacao
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
    def test_agrupa_visuais_pela_raiz(self):
        import visuais
        f = [{"id": "mov", "nome": "mov", "criado": "1"},
             {"id": "mov_bikini", "nome": "mov (bikini)", "criado": "2", "copia_de": "mov"},
             {"id": "mov_bikini_2", "nome": "mov (bikini 2)", "criado": "3", "copia_de": "mov_bikini"},
             {"id": "orfa", "nome": "Lia (praia)", "criado": "4", "copia_de": "apagada"},
             {"id": "a", "nome": "A", "criado": "5", "copia_de": "b"}, {"id": "b", "nome": "B", "criado": "6", "copia_de": "a"},
             {"id": "vest", "nome": "qualquer", "criado": "7", "copia_de": "mov", "visual": "Vestido"}]
        g = visuais.agrupar(f)
        self.assertEqual(g["mov"], ("mov", "Original"))
        self.assertEqual(g["mov_bikini"], ("mov", "bikini"))
        self.assertEqual(g["mov_bikini_2"], ("mov", "bikini 2"))
        self.assertEqual(g["orfa"], ("orfa", "Original"))
        self.assertEqual(g["vest"], ("mov", "Vestido"))
        self.assertIn(g["a"][0], ("a", "b"))  # ciclo não trava

    def test_listar_traz_pessoa_visual_e_pronto(self):
        pid = self.criar()
        novo = personagens.criar_com_nova_roupa(pid, "", "vestido", None, visual="Vestido")
        itens = {p["id"]: p for p in personagens.listar()}
        self.assertEqual((itens[pid]["pessoa"], itens[pid]["visual"], itens[pid]["pronto"]), (pid, "Original", True))
        self.assertEqual((itens[novo]["pessoa"], itens[novo]["visual"], itens[novo]["pronto"]), (pid, "Vestido", False))
        self.assertEqual(personagens.ler(novo)["nome"], f"{personagens.ler(pid)['nome']} (Vestido)")
        neto = personagens.criar_com_nova_roupa(novo, "", "biquíni", None, visual="Biquíni")
        self.assertEqual(personagens.ler(neto)["copia_de"], pid)

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
        self.assertTrue(g["32"]["inputs"]["image"].startswith(f"estudio/temp/personagem_{pid}/"))
        self.assertEqual([f for f in config.ENTRADA.rglob("*") if f.is_file()], [])

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
        self.assertTrue(foto.endswith("_frente.png") and entrada.existe(foto))
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
        self.assertEqual([f for f in config.ENTRADA.rglob("*") if f.is_file()], [])

    def test_gerar_angulos_falha_sem_imagem(self):
        pid = self.criar()
        with mock.patch("comfy_api.rodar", lambda g, l: {"status": "error", "erro": "sem memória", "segundos": 1, "pico_vram": 0, "temp_max": 0, "saidas": {}}):
            with self.assertRaises(RuntimeError):
                personagens.gerar_angulos(pid, avisar=lambda *a, **k: None)
        self.assertEqual([f for f in config.ENTRADA.rglob("*") if f.is_file()], [])


class Frente(ComPastas):
    """Preparar a frente: o Klein troca a roupa e o fundo da foto de frente em 2 opções (docs/superpowers/specs/2026-11-19-preparar-frente-design.md)."""

    def test_pedido_frente(self):
        base = "The same person with the same face, the same hair and the same expression"
        self.assertEqual(personagens.pedido_frente("a denim jacket", True),
                         base + ", now wearing a denim jacket, " + personagens.FUNDO_CINZA + ", the same framing")
        self.assertEqual(personagens.pedido_frente("", True), base + ", " + personagens.FUNDO_CINZA + ", the same framing")
        self.assertEqual(personagens.pedido_frente("a red dress", False), base + ", now wearing a red dress, the same framing")
        with self.assertRaises(ValueError):
            personagens.pedido_frente("  ", False)

    def test_limpar_roupa(self):
        L = personagens.limpar_roupa
        self.assertEqual(L('"A dark blue denim jacket over a white t-shirt."'), "a dark blue denim jacket over a white t-shirt")
        self.assertEqual(L("<think>hmm</think>\n\nWearing a red dress\nextra"), "a red dress")
        self.assertEqual(L("now wearing black jeans"), "black jeans")
        self.assertEqual(L("NASA t-shirt"), "NASA t-shirt")
        self.assertEqual(L("   "), "")
        self.assertEqual(len(L("x" * 500)), 300)

    def test_traduzir_roupa_com_e_sem_ia(self):
        import continuar_video
        with mock.patch.object(continuar_video, "chamar_llm", lambda *a, **k: ({"status": "success"}, "A denim jacket.")):
            self.assertEqual(personagens.traduzir_roupa("jaqueta jeans", "x.png"), ("a denim jacket", True))
        with mock.patch.object(continuar_video, "chamar_llm", lambda *a, **k: ({"status": "error"}, "")):
            self.assertEqual(personagens.traduzir_roupa("jaqueta  jeans", "x.png"), ("jaqueta jeans", False))

        def quebra(*a, **k):
            raise RuntimeError("sem ComfyUI")
        with mock.patch.object(continuar_video, "chamar_llm", quebra):
            self.assertEqual(personagens.traduzir_roupa("jaqueta", "x.png"), ("jaqueta", False))

    def test_preparar_frente_duas_opcoes_e_limpa_a_partida(self):
        import comfy_api, continuar_video
        pedidos = []

        def rodar(g, t):
            pedidos.append((g["4"]["inputs"]["text"], g["30"]["inputs"]["image"], g["43"]["inputs"]["noise_seed"]))
            (config.SAIDA / f"o{len(pedidos)}.png").write_bytes(self.foto.read_bytes())
            return {"status": "success", "saidas": {"9": {"images": [{"filename": f"o{len(pedidos)}.png", "subfolder": ""}]}}, "segundos": 30, "pico_vram": 1, "temp_max": 60}
        with mock.patch.object(comfy_api, "rodar", rodar), \
             mock.patch.object(continuar_video, "chamar_llm", lambda *a, **k: ({"status": "success"}, "a denim jacket")):
            r = personagens.preparar_frente(self.foto, "jaqueta jeans", True, "abcd1234", [5, 9])
        self.assertEqual(r["opcoes"], ["frentenova_abcd1234_5.png", "frentenova_abcd1234_9.png"])
        self.assertEqual((r["roupa_en"], r["ia"]), ("a denim jacket", True))
        self.assertTrue(all(entrada.existe(n) for n in r["opcoes"]))
        self.assertEqual([p[2] for p in pedidos], [5, 9])
        self.assertIn("now wearing a denim jacket", pedidos[0][0])
        # A partida vai para os temporarios (entrada_temp) e a pasta sai no fim; as opcoes ficam na raiz
        self.assertEqual(pedidos[0][1], "estudio/temp/frente_abcd1234/frentenova_abcd1234_partida.png")
        self.assertFalse((config.ENTRADA / "estudio" / "temp" / "frente_abcd1234").exists())

    def test_preparar_frente_sem_roupa_nao_chama_a_ia_e_falha_limpa(self):
        import comfy_api, continuar_video
        chamadas = []

        def rodar(g, t):
            chamadas.append(g)
            if len(chamadas) == 1:
                (config.SAIDA / "o1.png").write_bytes(self.foto.read_bytes())
                return {"status": "success", "saidas": {"9": {"images": [{"filename": "o1.png", "subfolder": ""}]}}, "segundos": 30, "pico_vram": 1, "temp_max": 60}
            return {"status": "error", "erro": "OOM", "saidas": {}}

        def sem_ia(*a, **k):
            raise AssertionError("não devia chamar a IA")
        with mock.patch.object(comfy_api, "rodar", rodar), mock.patch.object(continuar_video, "chamar_llm", sem_ia):
            with self.assertRaises(RuntimeError):
                personagens.preparar_frente(self.foto, "", True, "abcd1234", [5, 9])
        self.assertNotIn("now wearing", chamadas[0]["4"]["inputs"]["text"])
        self.assertEqual(list(config.ENTRADA.rglob("frentenova_*")), [])

    def test_limpar_frentes_antigas(self):
        import os, time
        velha, nova, outra = (config.ENTRADA / n for n in ("frentenova_aaaaaaaa_1.png", "frentenova_bbbbbbbb_1.png", "pers_x.png"))
        for f in (velha, nova, outra):
            f.write_bytes(b"x")
        os.utime(velha, (time.time() - 3 * 86400,) * 2)
        os.utime(outra, (time.time() - 3 * 86400,) * 2)
        # As novas ficam em input/estudio/envios; as de antes, na raiz: a limpeza olha os dois lugares
        envios = entrada.pasta_envios()
        envios.mkdir(parents=True)
        velha2, nova2 = envios / "frentenova_cccccccc_1.png", envios / "frentenova_dddddddd_1.png"
        for f in (velha2, nova2):
            f.write_bytes(b"x")
        os.utime(velha2, (time.time() - 3 * 86400,) * 2)
        personagens.limpar_frentes_antigas()
        self.assertEqual((velha.exists(), nova.exists(), outra.exists()), (False, True, True))
        self.assertEqual((velha2.exists(), nova2.exists()), (False, True))


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
        for alvo, nome, valor in ((acoes, "exigir_comfy_livre", lambda **k: None), (acoes, "examinar_video", lambda v: {"quadros": 240, "duracao": 10.0, "audio": True}),
                                  (acoes, "validar_troca", lambda a: {**P, **a}), (acoes.caminhos, "guardar_envio", lambda v: str(v)), (tarefa, "tarefa", t)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_usar_visual_aprovado_manda_a_ficha(self):
        import ficha_personagem as ficha
        pid = self.criar()
        pasta = personagens.pasta_de(pid)
        for v in ("frente", "rosto", "perfil"):
            Image.new("RGB", (16, 16), "red").save(pasta / ficha.ARQUIVOS[v])
        (pasta / ficha.APROVACAO).write_text(ficha.estado(pasta)[0]["frente"])
        foto, angulos = personagens.para_entrada(pid)
        self.assertTrue(foto.endswith("_ficha_frente.png"))
        self.assertEqual(sorted(a.rsplit("_", 1)[-1] for a in angulos), ["perfil.png", "rosto.png"])
        cabeca, _ = personagens.para_entrada(pid, modo="cabeca")
        self.assertTrue(cabeca.endswith("_ficha_rosto.png"))

    def test_usar_visual_sem_aprovacao_recusa(self):
        pid = self.criar()
        novo = personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        with self.assertRaises(validacao.Erro) as c:
            self.acoes.acao_personagem_usar({"id": novo})
        self.assertIn("Aprove a frente do visual Biquíni", c.exception.mensagem)
        self.assertTrue(self.acoes.acao_personagem_usar({"id": pid})["foto"].endswith("_frente.png"))

    def test_apagar_original_promove_o_visual_mais_antigo(self):
        pid = self.criar("mov")
        b1 = personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        b2 = personagens.criar_com_nova_roupa(pid, "", "biquíni 2", None, visual="Biquíni 2")
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "visual"})
        itens = {p["id"]: p for p in personagens.listar()}
        self.assertNotIn(pid, itens)
        self.assertEqual((itens[b1]["pessoa"], itens[b1]["visual"], itens[b1]["nome"]), (b1, "Biquíni", "mov"))
        self.assertEqual((itens[b2]["pessoa"], itens[b2]["visual"]), (b1, "Biquíni 2"))

    def test_apagar_original_nao_aprovado_nao_deixa_o_promovido_pronto(self):
        pid = self.criar("mov")
        b = personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "visual"})
        item = {p["id"]: p for p in personagens.listar()}[b]
        self.assertFalse(item["pronto"])
        with self.assertRaises(validacao.Erro) as c:
            self.acoes.acao_personagem_usar({"id": b})
        self.assertIn("Aprove a frente do visual Biquíni", c.exception.mensagem)

    def test_apagar_original_promove_copia_antiga_sem_campo_visual(self):
        pid = self.criar("mov")
        b = personagens.criar_com_nova_roupa(pid, "mov (bikini)", "biquíni", None, visual="")
        self.assertNotIn("visual", personagens.ler(b))
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "visual"})
        item = {p["id"]: p for p in personagens.listar()}[b]
        self.assertFalse(item["pronto"])
        self.assertEqual(personagens.ler(b)["visual"], "bikini")
        with self.assertRaises(validacao.Erro) as c:
            self.acoes.acao_personagem_usar({"id": b})
        self.assertIn("Aprove a frente do visual bikini", c.exception.mensagem)

    def test_apagar_personagem_leva_os_visuais(self):
        pid = self.criar("mov")
        personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        outro = self.criar("Bia")
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True})
        self.assertEqual([p["id"] for p in personagens.listar()], [outro])

    def test_criar_de_foto_enviada_e_gerar(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        # Sem a confirmacao de autorizacao desde 23/11/2026
        r = self.acoes.acao_personagem_criar({"nome": "Cida", "foto": "env.png", "angulos": True})
        self.assertEqual(r, {"id": "cida"})
        self.assertEqual(self.lancados, ["cida"])

    def test_criar_ficha_por_foto_enviada(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        pedido = {"nome": "Cida", "foto": "env.png", "autorizacao": True, "ficha": True}
        with mock.patch.object(self.acoes.t2i, "arquivos_que_faltam", return_value=[]), \
             mock.patch.object(self.acoes.tarefa.tarefa, "iniciar_ficha", return_value={"fila": 1}, create=True) as iniciar:
            self.assertEqual(self.acoes.acao_personagem_criar(pedido), {"id": "cida", "fila": 1})
            iniciar.assert_called_once_with("cida")
        self.assertEqual(self.lancados, [])
        self.assertTrue((personagens.pasta_de("cida") / "frente.png").is_file())

    def test_ficha_aprova_a_frente_antes_de_gerar_os_closes_e_montar(self):
        import comfy_api, ficha_personagem as ficha
        pid = self.criar()
        pasta = personagens.pasta_de(pid)
        Image.new("RGB", (1024, 1024), "gray").save(config.SAIDA / "resultado.png")
        resposta = {"status": "success", "saidas": {"9": {"images": [{"filename": "resultado.png"}]}}}
        with mock.patch.object(comfy_api, "rodar", return_value=resposta) as rodar, \
             mock.patch.object(ficha, "recortar_rosto", return_value=False):
            ficha.gerar(pasta, "frente", "")
            rodar.assert_called_once()
            self.assertEqual(set(ficha.estado(pasta)[0]), {"frente"})
            with self.assertRaises(ValueError):
                ficha.gerar(pasta, "completar", "")
            self.assertFalse((pasta / ficha.FOLHA).exists())
            ficha.gerar(pasta, "aprovar", "")
            self.assertEqual(rodar.call_count, 4)
            grafo_costas = rodar.call_args.args[0]
            self.assertIn("approved outfit", grafo_costas["4"]["inputs"]["text"])
            # O rosto parte da frente aprovada (a roupa), não da foto original
            grafo_rosto = rodar.call_args_list[1].args[0]
            self.assertIn("never for the clothing", grafo_rosto["4"]["inputs"]["text"])
            self.assertTrue(grafo_rosto["30"]["inputs"]["image"].endswith("_ficha_rosto_0.png"))
            self.assertTrue(ficha.estado(pasta)[1])
        folha = pasta / ficha.FOLHA
        marca = personagens.ler(pid)["folha"]
        with Image.open(folha) as im:
            self.assertEqual(im.size, ficha.TAMANHO_FOLHA)
        with mock.patch.object(comfy_api, "rodar", return_value={"status": "error", "erro": "erro de teste"}):
            with self.assertRaises(RuntimeError):
                ficha.gerar(pasta, "perfil", "")
        self.assertEqual(personagens.ler(pid)["folha"], marca)
        self.assertFalse(list(config.ENTRADA.glob(f"personagem_{pid}_ficha_*.png")))

    def test_ficha_frente_com_roupa_troca_a_roupa_inteira(self):
        import comfy_api, ficha_personagem as ficha
        pid = self.criar()
        pasta = personagens.pasta_de(pid)
        Image.new("RGB", (64, 64), "green").save(pasta / ficha.ROUPA)
        Image.new("RGB", (1024, 1024), "gray").save(config.SAIDA / "resultado.png")
        resposta = {"status": "success", "saidas": {"9": {"images": [{"filename": "resultado.png"}]}}}
        with mock.patch.object(comfy_api, "rodar", return_value=resposta) as rodar:
            ficha.gerar(pasta, "frente", "")
        texto = rodar.call_args.args[0]["4"]["inputs"]["text"]
        self.assertIn("Replace all of the clothing", texto)
        self.assertNotIn("hair, clothing", texto)
        self.assertIn(ficha.REALISMO, texto)
        self.assertNotIn(ficha.CABELO, texto)

    def test_ficha_h3_monta_o_grafo_e_salva_a_folha(self):
        import comfy_api, ficha_personagem as ficha
        pid = self.criar()
        pasta = personagens.pasta_de(pid)
        with self.assertRaises(ValueError):
            ficha.gerar(pasta, "h3", "")
        Image.new("RGB", (64, 96), "gray").save(pasta / ficha.ARQUIVOS["frente"])
        (pasta / ficha.APROVACAO).write_text(ficha.estado(pasta)[0]["frente"])
        Image.new("RGB", (4096, 1536), "white").save(config.SAIDA / "folha_h3.png")
        resposta = {"status": "success", "saidas": {"9": {"images": [{"filename": "folha_h3.png"}]}}}
        with mock.patch.object(comfy_api, "rodar", return_value=resposta) as rodar, \
             mock.patch.object(ficha, "recortar_rosto", return_value=False):
            ficha.gerar(pasta, "h3", "óculos redondos")
        g = rodar.call_args.args[0]
        self.assertEqual(g["40"]["class_type"], "FizgigH3StillLatent")
        self.assertEqual(g["41"]["class_type"], "FizgigH3StillDecode")
        self.assertEqual((g["21"]["inputs"]["steps"], g["21"]["inputs"]["sampler_name"]), (18, "er_sde"))
        self.assertEqual(g["21"]["inputs"]["latent_image"], ["40", 0])
        self.assertNotIn("11", g)
        self.assertFalse(any(n["class_type"] == "LoraLoaderModelOnly" for n in g.values()))
        self.assertIn("ref_images.ref_image_1", g["20"]["inputs"])
        self.assertIn("óculos redondos", g["20"]["inputs"]["prompt"])
        self.assertTrue((pasta / ficha.FOLHA_H3).is_file())
        self.assertIsNotNone(personagens.ler(pid)["ficha_h3"])
        self.assertFalse(list(config.ENTRADA.glob(f"personagem_{pid}_ficha_h3_*.png")))

    def test_ficha_h3_pede_frente_aprovada_e_o_no(self):
        import ficha_personagem as ficha
        pid = self.criar()
        with self.assertRaises(validacao.Erro) as c:
            self.acoes.acao_personagem_ficha({"id": pid, "etapa": "h3"})
        self.assertEqual(c.exception.codigo, 409)
        pasta = personagens.pasta_de(pid)
        Image.new("RGB", (64, 96), "gray").save(pasta / ficha.ARQUIVOS["frente"])
        (pasta / ficha.APROVACAO).write_text(ficha.estado(pasta)[0]["frente"])
        with mock.patch.object(ficha, "faltam_h3", return_value=[ficha.NO_FIZGIG]):
            with self.assertRaises(validacao.Erro) as c:
                self.acoes.acao_personagem_ficha({"id": pid, "etapa": "h3"})
        self.assertIn(ficha.NO_FIZGIG, c.exception.mensagem)
        with mock.patch.object(ficha, "faltam_h3", return_value=[]), \
             mock.patch.object(self.acoes, "exigir_comfy_livre", lambda: None), \
             mock.patch.object(self.acoes.tarefa.tarefa, "iniciar_ficha", return_value={"fila": 0}, create=True) as iniciar:
            self.acoes.acao_personagem_ficha({"id": pid, "etapa": "h3"})
        iniciar.assert_called_once_with(pid, "h3")

    def test_pedido_da_frente_com_roupa_em_texto(self):
        import ficha_personagem as ficha
        so_texto = ficha.pedido_vista("frente", 1, "", "a red slip dress")
        self.assertIn("Replace all of the clothing with a red slip dress", so_texto)
        self.assertNotIn("hair, clothing", so_texto)
        com_foto = ficha.pedido_vista("frente", 2, "", "a red slip dress")
        self.assertIn("second image", com_foto)
        self.assertIn("Outfit notes: a red slip dress.", com_foto)
        self.assertIn("hair, clothing", ficha.pedido_vista("frente", 1, "", ""))

    def test_nova_roupa_cria_copia_e_deixa_o_original(self):
        import ficha_personagem as ficha
        pid = self.criar()
        original = personagens.pasta_de(pid)
        antes = sorted(f.name for f in original.iterdir())
        with self.assertRaises(ValueError):
            personagens.criar_com_nova_roupa(pid, "Lia 2", "", None)
        novo = personagens.criar_com_nova_roupa(pid, "", "  vestido   vermelho ", None)
        f = personagens.ler(novo)
        self.assertEqual((f["nome"], f["roupa_texto"], f["copia_de"]), (f"{personagens.ler(pid)['nome']} (nova roupa)", "vestido vermelho", pid))
        self.assertTrue((personagens.pasta_de(novo) / "frente.png").is_file())
        self.assertFalse((personagens.pasta_de(novo) / ficha.ROUPA).exists())
        Image.new("RGB", (40, 80), "green").save(config.ENTRADA / "roupa.png")
        com_foto = personagens.criar_com_nova_roupa(pid, "Com foto", "", config.ENTRADA / "roupa.png")
        self.assertTrue((personagens.pasta_de(com_foto) / ficha.ROUPA).is_file())
        self.assertNotIn("roupa_texto", personagens.ler(com_foto))
        self.assertEqual(sorted(f.name for f in original.iterdir()), antes)

    def test_klein_encadeia_varias_referencias(self):
        import texto_para_imagem as t2i
        m = t2i.MODELOS_TEXTO["klein_edit"]
        um = t2i.grafo_edicao_klein({"partida": "a.png", "referencia": "b.png", "prompt": "x", "passos": 4}, m, 1, "p")
        self.assertEqual((um["32"]["inputs"]["image"], um["40"]["inputs"]["positive"]), ("b.png", ["26", 0]))
        tres = t2i.grafo_edicao_klein({"partida": "a.png", "referencias": ["b.png", "c.png"], "prompt": "x", "passos": 4}, m, 1, "p")
        self.assertEqual(tres["132"]["inputs"]["image"], "c.png")
        self.assertEqual(tres["126"]["inputs"]["conditioning"], ["26", 0])
        self.assertEqual(tres["127"]["inputs"]["conditioning"], ["27", 0])
        self.assertEqual((tres["40"]["inputs"]["positive"], tres["40"]["inputs"]["negative"]), (["126", 0], ["127", 0]))
        nenhuma = t2i.grafo_edicao_klein({"partida": "a.png", "prompt": "x", "passos": 4}, m, 1, "p")
        self.assertEqual(nenhuma["40"]["inputs"]["positive"], ["24", 0])

    def test_nova_roupa_leva_o_corpo_e_a_frente_parte_dele(self):
        import comfy_api, ficha_personagem as ficha
        pid = self.criar()
        Image.new("RGB", (64, 96), "blue").save(personagens.pasta_de(pid) / ficha.ARQUIVOS["frente"])
        (personagens.pasta_de(pid) / ficha.APROVACAO).write_text(ficha.estado(personagens.pasta_de(pid))[0]["frente"])  # só frente aprovada vira corpo
        Image.new("RGB", (40, 80), "green").save(config.ENTRADA / "roupa.png")
        novo = personagens.criar_com_nova_roupa(pid, "Lia praia", "biquíni preto", config.ENTRADA / "roupa.png")
        pasta = personagens.pasta_de(novo)
        self.assertTrue((pasta / ficha.CORPO).is_file())
        Image.new("RGB", (896, 1344), "gray").save(config.SAIDA / "resultado.png")
        resposta = {"status": "success", "saidas": {"9": {"images": [{"filename": "resultado.png"}]}}}
        with mock.patch.object(comfy_api, "rodar", return_value=resposta) as rodar, \
             mock.patch.object(personagens, "traduzir_roupa", return_value=("a black bikini", True)):
            ficha.gerar(pasta, "frente", "", "biquíni preto")
        g = rodar.call_args.args[0]
        texto = g["4"]["inputs"]["text"]
        self.assertIn("first image is the person in full body", texto)
        self.assertIn("outfit from the third image", texto)
        self.assertIn("Outfit notes: a black bikini.", texto)
        self.assertIn("132", g)  # três imagens: corpo, rosto e roupa
        self.assertFalse(list(config.ENTRADA.glob(f"personagem_{novo}_ficha_frente_*.png")))
        sem_corpo = personagens.criar_com_nova_roupa(self.criar("Bia"), "", "vestido", None)
        self.assertFalse((personagens.pasta_de(sem_corpo) / ficha.CORPO).exists())

    def test_novo_visual_de_visual_nao_aprovado_nao_leva_a_frente_candidata(self):
        import ficha_personagem as ficha
        pid = self.criar()
        a = personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        Image.new("RGB", (64, 96), "red").save(personagens.pasta_de(a) / ficha.ARQUIVOS["frente"])  # candidata, sem aprovação
        b = personagens.criar_com_nova_roupa(a, "", "vestido", None, visual="Vestido")
        self.assertFalse((personagens.pasta_de(b) / ficha.CORPO).exists())
        # com a frente da raiz aprovada, o corpo vem dela e não da candidata
        raiz = personagens.pasta_de(pid)
        Image.new("RGB", (64, 96), "blue").save(raiz / ficha.ARQUIVOS["frente"])
        (raiz / ficha.APROVACAO).write_text(ficha.estado(raiz)[0]["frente"])
        c = personagens.criar_com_nova_roupa(a, "", "saia", None, visual="Saia")
        self.assertEqual(Image.open(personagens.pasta_de(c) / ficha.CORPO).getpixel((1, 1)), (0, 0, 255))

    def test_apagar_visual_do_meio_da_cadeia_antiga_reaponta_os_descendentes(self):
        pid = self.criar("mov")
        meio = personagens.criar_com_nova_roupa(pid, "", "biquíni", None, visual="Biquíni")
        neto = personagens.criar_com_nova_roupa(pid, "", "saia", None, visual="Saia")
        ficha = personagens.PASTA / neto / personagens.FICHA
        d = json.loads(ficha.read_text(encoding="utf-8"))
        d["copia_de"] = meio  # cadeia do formato antigo: neto -> meio -> raiz
        ficha.write_text(json.dumps(d), encoding="utf-8")
        personagens.apagar_visual(meio)
        itens = {p["id"]: p for p in personagens.listar()}
        self.assertEqual((itens[neto]["pessoa"], itens[neto]["visual"]), (pid, "Saia"))
        self.assertEqual(personagens.ler(neto)["copia_de"], pid)

    def test_apagar_por_partes(self):
        import ficha_personagem as ficha
        pid = self.criar()
        pasta = personagens.pasta_de(pid)
        todos = [ficha.FOLHA, ficha.FOLHA_H3, ficha.ROUPA, *ficha.ARQUIVOS.values()]
        for nome in todos:
            Image.new("RGB", (8, 8)).save(pasta / nome)
        (pasta / ficha.APROVACAO).write_text("x")
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "outra"})
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "h3"})
        self.assertFalse((pasta / ficha.FOLHA_H3).exists())
        self.assertTrue((pasta / ficha.FOLHA).exists())
        self.acoes.acao_personagem_apagar({"id": pid, "confirmar": True, "parte": "ficha"})
        restam = sorted(f.name for f in pasta.iterdir())
        self.assertEqual(restam, sorted([personagens.FICHA, "frente.png", ficha.ARQUIVOS["frente"], ficha.ROUPA]))
        self.assertIsNone(personagens.ler(pid)["folha"])
        self.assertFalse(personagens.ler(pid)["ficha_aprovada"])

    def test_acao_nova_roupa_prepara_a_frente(self):
        pid = self.criar()
        with mock.patch.object(self.acoes.t2i, "arquivos_que_faltam", return_value=[]), \
             mock.patch.object(self.acoes, "exigir_comfy_livre", lambda: None), \
             mock.patch.object(self.acoes.tarefa.tarefa, "iniciar_ficha", return_value={"fila": 0}, create=True) as iniciar:
            with self.assertRaises(validacao.Erro):
                self.acoes.acao_personagem_nova_roupa({"id": pid, "roupa": ""})
            with self.assertRaises(validacao.Erro):
                self.acoes.acao_personagem_nova_roupa({"id": pid, "roupa": "x" * 301})
            r = self.acoes.acao_personagem_nova_roupa({"id": pid, "nome": "Lia de vermelho", "roupa": "vestido vermelho"})
        self.assertEqual(r["id"], "lia_de_vermelho")
        iniciar.assert_called_once_with("lia_de_vermelho")

    def test_frente_valida_e_devolve_opcoes(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        chamadas = []

        def preparar(partida, roupa, cinza, codigo, sementes):
            chamadas.append((partida.name, roupa, cinza, codigo, len(sementes)))
            return {"opcoes": [f"frentenova_{codigo}_1.png", f"frentenova_{codigo}_2.png"], "roupa_en": "a jacket", "ia": True}
        with mock.patch.object(personagens, "preparar_frente", preparar), mock.patch.object(self.acoes.lmstudio, "descarregar", lambda: None):
            for ruim in ({"foto": "env.png", "roupa": "", "fundo": "manter"}, {"foto": "env.png", "fundo": "azul"},
                         {"foto": "env.png", "roupa": "x" * 301}, {"foto": "nao.png", "fundo": "cinza"}, {"foto": "env.png", "fundo": "cinza", "codigo": "../x"}):
                with self.assertRaises(validacao.Erro, msg=ruim):
                    self.acoes.acao_personagem_frente(ruim)
            r = self.acoes.acao_personagem_frente({"foto": "env.png", "roupa": " jaqueta ", "fundo": "cinza"})
        self.assertEqual(chamadas, [("env.png", "jaqueta", True, r["codigo"], 2)])
        self.assertRegex(r["codigo"], r"^[0-9a-f]{8}$")
        self.assertEqual(r["opcoes"][0], {"arquivo": f"frentenova_{r['codigo']}_1.png", "url": f"/entrada/foto/frentenova_{r['codigo']}_1.png"})
        self.assertEqual((r["roupa_en"], r["ia"]), ("a jacket", True))

    def test_frente_trava(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")
        self.acoes._editando.acquire()
        try:
            with self.assertRaises(validacao.Erro) as c:
                self.acoes.acao_personagem_frente({"foto": "env.png", "fundo": "cinza"})
            self.assertEqual(c.exception.codigo, 409)
        finally:
            self.acoes._editando.release()

    def test_frente_falha_do_klein_vira_erro_500(self):
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "env.png")

        def quebra(*a):
            raise RuntimeError("OOM")
        with mock.patch.object(personagens, "preparar_frente", quebra), mock.patch.object(self.acoes.lmstudio, "descarregar", lambda: None):
            with self.assertRaises(validacao.Erro) as c:
                self.acoes.acao_personagem_frente({"foto": "env.png", "fundo": "cinza"})
        self.assertEqual(c.exception.codigo, 500)
        self.assertFalse(self.acoes._editando.locked())

    def test_criar_com_frente_preparada_limpa_as_opcoes(self):
        for n in ("frentenova_abcd1234_1.png", "frentenova_abcd1234_2.png", "frentenova_ffff0000_1.png"):
            Image.new("RGB", (32, 32)).save(config.ENTRADA / n)
        self.acoes.acao_personagem_criar({"nome": "Lia", "foto": "frentenova_abcd1234_2.png", "autorizacao": True})
        self.assertEqual(sorted(f.name for f in config.ENTRADA.glob("frentenova_*")), ["frentenova_ffff0000_1.png"])

    def test_criar_com_angulos_e_comfy_fora_nao_cria_nem_apaga_as_opcoes(self):
        # Revisão final: antes, o personagem era criado e as opções apagadas antes do 409; o segundo clique dava "foto não encontrada"
        Image.new("RGB", (32, 32)).save(config.ENTRADA / "frentenova_abcd1234_1.png")

        def fora(**k):
            raise validacao.Erro("O ComfyUI está desligado.", 409)
        with mock.patch.object(self.acoes, "exigir_comfy_livre", fora):
            with self.assertRaises(validacao.Erro):
                self.acoes.acao_personagem_criar({"nome": "Lia", "foto": "frentenova_abcd1234_1.png", "autorizacao": True, "angulos": True})
        self.assertEqual(personagens.listar(), [])
        self.assertTrue((config.ENTRADA / "frentenova_abcd1234_1.png").is_file())

    def test_continuar_a_fila_recusado_enquanto_pinta(self):
        # Revisão final: com a fila pausada, "Continuar" no meio do preparo da frente punha dois trabalhos na placa
        continuados = []
        self.acoes.tarefa.tarefa.fila = types.SimpleNamespace(continuar=lambda: continuados.append(1), resumo=lambda: {})
        self.acoes._editando.acquire()
        try:
            with self.assertRaises(validacao.Erro) as c:
                self.acoes.acao_fila({"acao": "continuar"})
            self.assertEqual(c.exception.codigo, 409)
        finally:
            self.acoes._editando.release()
        self.assertEqual(continuados, [])
        self.acoes.acao_fila({"acao": "continuar"})
        self.assertEqual(continuados, [1])

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
        self.assertTrue(entrada.existe("rostos_v_perfil_0.png"))
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
        self.assertTrue(e["personagem"].endswith("_frente.png") and entrada.existe(e["personagem"]))
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
        self.assertTrue(entrada.existe(r["foto"]))
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

    def test_frente_rota(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as c:
            self.pedir("/api/personagem-frente", {"foto": "nao.png", "fundo": "cinza"})
        self.assertEqual(c.exception.code, 404)
        self.assertIn("A foto do personagem não foi encontrada", json.loads(c.exception.read())["erro"])


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
            nome = trocar_personagem.cabeca_da_foto("foto.png", "proj")
        self.assertTrue(nome.startswith("estudio/temp/proj/cab_"))
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
            self.assertIsNone(trocar_personagem.cabeca_da_foto("foto.png", "proj"))

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
