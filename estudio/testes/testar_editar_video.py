"""Testes da aba Editar video (editar_video.py e as regras do tipo "editar"). Nao usam o WanGP, o ComfyUI nem a placa.

Uso: python -I testar_editar_video.py
"""
import json, os, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import editar_video as ev

SECOES = ["subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"]


class Contas(unittest.TestCase):
    def test_tamanho_na_proporcao_do_video(self):
        self.assertEqual(ev.tamanho_editar(1920, 1080, "melhor"), (960, 544))
        self.assertEqual(ev.tamanho_editar(1920, 1080, "rapido"), (864, 480))

    def test_tamanho_vertical(self):
        self.assertEqual(ev.tamanho_editar(1080, 1920, "rapido"), (480, 864))

    def test_tarefa_do_viggle(self):
        t = ev.tarefa_viggle(Path("o.mp4"), Path("p.png"), "R", 124, 24, 864, 480, 2**40 + 7, Path("v.mp4"))
        s = t["settings"]
        self.assertEqual((t["etapa"], s["model_type"], s["video_prompt_type"], s["frames_positions"]), ("viggle", "viggle_remake_edit", "FIVU", "25"))
        self.assertEqual((s["video_length"], s["sliding_window_size"], s["resolution"], s["seed"]), (124, 345, "864x480", 7))
        self.assertEqual((s["audio_prompt_type"], s["num_inference_steps"], s["flow_shift"], s["config"]), ("K", 6, 12, "nvfp4_awq"))
        self.assertEqual((s["sample_solver"], s["guidance_phases"], s["guidance_scale"], s["multi_prompts_gen_type"]), ("euler", 1, 1, "PW"))
        self.assertEqual(s["image_refs"], [str(Path("p.png"))])
        self.assertEqual((s["video_guide"], s["prompt"], t["destino"]), (str(Path("o.mp4")), "R", str(Path("v.mp4"))))

    def test_roteiro_reserva_tem_as_seis_secoes(self):
        r = ev.roteiro_reserva("Turn the sky stormy.", 24, 5.2)
        self.assertEqual([s.split(":")[0] for s in r.split("\n\n")], SECOES)
        self.assertIn("00:01.000", r)
        self.assertIn("Turn the sky stormy.", r)
        self.assertNotIn(" dim", r.lower())

    def test_roteiro_invalido_vira_none(self):
        self.assertIsNone(ev.limpar_roteiro(""))
        self.assertIsNone(ev.limpar_roteiro("summary:\nso isso"))
        bom = ev.roteiro_reserva("x", 24, 5)
        self.assertEqual(ev.limpar_roteiro("<think>hmm</think>```\n" + bom + "\n```"), bom)
        self.assertNotIn("dim", ev.limpar_roteiro(bom.replace("Realistic", "A dimly lit, realistic")).lower())

    def test_pedido_klein_reserva(self):
        self.assertTrue(ev.pedido_klein_reserva("vira tempestade").startswith("vira tempestade"))
        self.assertIn(ev.CLAUSULA_KLEIN, ev.pedido_klein_reserva("x"))

    def test_perguntas_citam_o_pedido(self):
        self.assertIn("vira tempestade", ev.pergunta_pedido_klein("vira tempestade"))
        self.assertIn(ev.CLAUSULA_KLEIN, ev.pergunta_pedido_klein("x"))
        p = ev.pergunta_roteiro("vira tempestade", "Make it stormy.", 24, 5.2)
        self.assertIn("vira tempestade", p)
        self.assertIn("00:01.000", p)
        for s in SECOES:
            self.assertIn(s, p)

    def test_pergunta_do_roteiro_da_exemplos_e_nao_instrucoes_para_copiar(self):
        # No teste real de 18/11 a IA copiou "[Shot 1], opening with its framing..." e repetiu ", exactly as in <Picture 1>,."
        p = ev.pergunta_roteiro("vira tempestade", "Make it stormy.", 24, 5.2)
        self.assertNotIn("opening with its framing", p)
        self.assertIn('"[Shot 1] A ', p)
        self.assertIn('"At 00:01.000, exactly as in <Picture 1>, ', p)
        self.assertIn("<Subject 1> is the ", p)

    def test_apaga_so_temporarios_velhos(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        entrada, saida = Path(d.name) / "input", Path(d.name) / "output"
        (saida / "editar").mkdir(parents=True)
        entrada.mkdir()
        velho = time.time() - 3 * 86400
        velha, nova, outro = entrada / "editar_pintura_a_1.png", entrada / "editar_pintura_b_1.png", entrada / "troca_x.mp4"
        saida_velha = saida / "editar" / "a_1_00001_.png"
        for f in (velha, nova, outro, saida_velha):
            f.write_bytes(b"x")
        for f in (velha, outro, saida_velha):
            os.utime(f, (velho, velho))
        with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(config, "SAIDA", saida):
            apagadas = ev.apagar_temporarios()
        self.assertEqual(set(apagadas), {velha, saida_velha})
        self.assertTrue(nova.exists() and outro.exists())
        self.assertFalse(velha.exists() or saida_velha.exists())


class Script(unittest.TestCase):
    def test_abre_com_python_isolado(self):
        # A tarefa roda "python -I editar_video.py": sem o sys.path.insert, o -I nao acha o config (falhou no teste real de 18/11)
        import subprocess
        r = subprocess.run([sys.executable, "-I", str(Path(ev.__file__)), "--help"], capture_output=True, text=True, timeout=120,
                           creationflags=config.SEM_JANELA)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertIn("--projeto", r.stdout)


class Trecho(unittest.TestCase):
    def test_trecho_sai_a_24_fps_e_curto(self):
        # O WanGP conta frames_positions num guia a 24 fps: um video de celular a 30 fps deslocava o quadro pinado
        chamadas = []
        with mock.patch.object(ev, "ffmpeg", lambda *a: chamadas.append(a)):
            ev.cortar_trecho(Path("o.mp4"), Path("t.mp4"), 2.5)
            ev.cortar_trecho(Path("o.mp4"), Path("t0.mp4"), 0)
        for args in chamadas:
            self.assertIn("fps=24", " ".join(args))
            self.assertIn("-t", args)
            self.assertTrue(args[-1].endswith(".mp4"))
        self.assertIn("2.500", chamadas[0])


class PlacaUmaCoisaPorVez(unittest.TestCase):
    def setUp(self):
        import acoes, tarefa
        self.acoes = acoes
        for alvo, nome, valor in ((tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: False, projeto=None)),
                                  (acoes.ambiente, "ler_comfy", lambda: {"ligado": True, "ocupado": False})):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_geracao_espera_a_pintura(self):
        # O ComfyUI fica parado entre os passos da pintura: sem a trava, uma geracao comecava junto e as duas usavam a placa
        self.acoes._editando.acquire()
        self.addCleanup(self.acoes._editando.release)
        with self.assertRaises(self.acoes.Erro) as e:
            self.acoes.exigir_comfy_livre()
        self.assertEqual(e.exception.codigo, 409)
        self.acoes.exigir_comfy_livre(pintando_ok=True)

    def test_sem_pintura_passa(self):
        self.acoes.exigir_comfy_livre()


class Validar(unittest.TestCase):
    def setUp(self):
        import validacao
        self.v = validacao
        for alvo, valor in ((config, "WANGP_PYTHON"), (validacao, "MODELO_ESRGAN")):
            p = mock.patch.object(alvo, valor, Path(__file__))
            p.start()
            self.addCleanup(p.stop)

    def test_padrao(self):
        self.assertEqual(self.v.validar_editar({}), self.v.PADRAO_EDITAR)

    def test_qualidade_desconhecida(self):
        with self.assertRaises(self.v.Erro):
            self.v.validar_editar({"qualidade": "4k"})

    def test_roteiro_sem_secoes(self):
        with self.assertRaises(self.v.Erro):
            self.v.validar_editar({"roteiro": "oi"})

    def test_roteiro_valido_fica_limpo(self):
        bom = ev.roteiro_reserva("x", 24, 5)
        self.assertEqual(self.v.validar_editar({"roteiro": "```\n" + bom + "\n```"})["roteiro"], bom)

    def test_sem_wangp(self):
        with mock.patch.object(config, "WANGP_PYTHON", Path("nao_existe") / "python.exe"):
            with self.assertRaises(self.v.Erro):
                self.v.validar_editar({})

    def test_chave_desconhecida_sai(self):
        self.assertNotIn("x", self.v.validar_editar({"x": 1}))

    def test_semente(self):
        self.assertEqual(self.v.validar_editar({"semente": "77"})["semente"], 77)
        with self.assertRaises(self.v.Erro):
            self.v.validar_editar({"semente": 2**48})


class IniciarEditar(unittest.TestCase):
    def setUp(self):
        import acoes, tarefa, validacao
        self.acoes, self.v = acoes, validacao
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        raiz = Path(d.name)
        for nome in ("projetos", "envios", "entrada"):
            (raiz / nome).mkdir()
        (raiz / "envios" / "v.mp4").write_bytes(b"video")
        (raiz / "entrada" / "editar_pintura_ab_1.png").write_bytes(b"png")
        self.raiz, self.lancados = raiz, []
        self.video = {"quadros": 240, "fps": 24, "duracao": 10.0, "audio": True, "largura": 1920, "altura": 1080}
        for alvo, nome, valor in ((config, "PROJETOS", raiz / "projetos"), (config, "ENVIOS", raiz / "envios"), (config, "ENTRADA", raiz / "entrada"),
                                  (acoes, "exigir_comfy_livre", lambda **k: None), (acoes, "examinar_video", lambda v: dict(self.video)),
                                  (acoes, "validar_editar", lambda a: {**validacao.PADRAO_EDITAR, **a}),
                                  (tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: False, iniciar_editar=self.lancados.append, projeto=None))):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def iniciar(self, nome="a", **extra):
        d = {"projeto": nome, "video": "v.mp4", "inicio": 0, "duracao": 5, "quadro": 24, "pintura": "editar_pintura_ab_1.png",
             "pedido": "vira tempestade", "ajustes": {}, "autorizacao": True}
        self.acoes.acao_iniciar_editar({**d, **extra})
        return self.raiz / "projetos" / nome

    def test_cria_o_projeto(self):
        pasta = self.iniciar()
        cfg = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
        estado = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["tipo"], cfg["quadro"], cfg["pedido"], cfg["duracao"]), ("editar", 24, "vira tempestade", 5))
        self.assertEqual((estado["tipo"], estado["pintura"]), ("editar", "pintado.png"))
        self.assertEqual((pasta / "pintado.png").read_bytes(), b"png")
        self.assertNotIn("audio_original", cfg)
        self.assertEqual(self.lancados, ["a"])

    def test_recusa_sem_autorizacao(self):
        with self.assertRaises(self.v.Erro):
            self.iniciar(autorizacao=False)
        self.assertEqual(self.lancados, [])

    def test_recusa_mais_de_14_s(self):
        with self.assertRaises(self.v.Erro):
            self.iniciar(duracao=15)

    def test_recusa_trecho_sem_90_quadros(self):
        # Video de 10 s: a partir de 7 s sobram 72 quadros, e o Viggle precisa de 90
        with self.assertRaises(self.v.Erro):
            self.iniciar(inicio=7, duracao=2, quadro=10)
        self.assertEqual(self.lancados, [])

    def test_recusa_quadro_fora_do_trecho(self):
        with self.assertRaises(self.v.Erro) as e:
            self.iniciar(quadro=200)
        self.assertIn("fora do trecho", e.exception.mensagem)

    def test_recusa_pintura_que_sumiu(self):
        with self.assertRaises(self.v.Erro):
            self.iniciar(pintura="editar_pintura_zz_1.png")

    def test_recusa_sem_pedido(self):
        with self.assertRaises(self.v.Erro):
            self.iniciar(pedido="  ")

    def test_video_sem_audio(self):
        self.video["audio"] = False
        cfg = json.loads((self.iniciar() / "interface.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["audio_original"], False)

    def test_ler_editar(self):
        import projetos
        p = projetos.ler_projeto(self.iniciar())
        self.assertEqual((p["tipo"], p["ideia"], p["pintura"], p["completo"]), ("editar", "vira tempestade", True, False))

    def test_reusar_devolve_a_pintura(self):
        pasta = self.iniciar()
        r = self.acoes.acao_reusar({"projeto": "a"})
        self.assertEqual(r["tipo"], "editar")
        self.assertTrue((config.ENTRADA / r["pintura"]).is_file())
        self.assertEqual(r["config"]["pedido"], "vira tempestade")
        self.assertNotIn("tipo", r["config"])
        self.assertEqual(r["video"]["arquivo"], "v.mp4")

    def test_continuar_lanca_de_novo(self):
        self.iniciar()
        self.acoes.acao_continuar({"projeto": "a"})
        self.assertEqual(self.lancados, ["a", "a"])


class Pintar(unittest.TestCase):
    """Pintar o quadro, a imagem propria e o roteiro, sem o ComfyUI: o Klein, a IA e o ffmpeg sao trocados por falsos."""

    def setUp(self):
        import acoes, tarefa
        from PIL import Image
        self.acoes, self.Image = acoes, Image
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        raiz = Path(d.name)
        for nome in ("envios", "entrada", "output"):
            (raiz / nome).mkdir()
        (raiz / "envios" / "v.mp4").write_bytes(b"video")
        self.raiz, self.rodando, self.texto_ia, self.chamadas_ia = raiz, False, "", 0
        self.video = {"quadros": 240, "fps": 24, "duracao": 10.0, "audio": True, "largura": 1920, "altura": 1080}

        def ffmpeg(*args):
            # O ultimo argumento e o arquivo de saida: o quadro sai no tamanho do video
            Image.new("RGB", (self.video["largura"], self.video["altura"]), "blue").save(args[-1])

        def rodar(g, limite):
            prefixo = g["9"]["inputs"]["filename_prefix"]
            arq = raiz / "output" / (prefixo + "_00001_.png")
            arq.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (2 * self.video["largura"], 2 * self.video["altura"]), "gray").save(arq)
            return {"status": "success", "saidas": {"9": {"images": [{"filename": arq.name, "subfolder": str(Path(prefixo).parent), "type": "output"}]}}}

        def chamar_llm(pergunta, imagem, rotulo, mon, pensar=True):
            self.chamadas_ia += 1
            return {"status": "success"}, self.texto_ia

        for alvo, nome, valor in ((config, "ENVIOS", raiz / "envios"), (config, "ENTRADA", raiz / "entrada"), (config, "SAIDA", raiz / "output"),
                                  (ev, "ffmpeg", ffmpeg), (ev, "cortar_trecho", lambda o, dst, i: Path(dst).write_bytes(b"trecho")),
                                  (ev, "rodar", rodar), (ev, "chamar_llm", chamar_llm),
                                  (acoes, "exigir_comfy_livre", lambda **k: None), (acoes, "examinar_video", lambda v: dict(self.video)),
                                  (acoes.lmstudio, "descarregar", lambda: None),
                                  (tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: self.rodando, projeto=None))):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def pintar(self, **extra):
        return self.acoes.acao_editar_pintar({"video": "v.mp4", "inicio": 0, "quadro": 24, "pedido": "vira tempestade", **extra})

    def test_pintar_devolve_duas_opcoes(self):
        self.texto_ia = "Make the sky dark and stormy. " + ev.CLAUSULA_KLEIN
        r = self.pintar()
        self.assertEqual(len(r["pinturas"]), 2)
        for nome in r["pinturas"] + [r["quadro"]]:
            self.assertTrue((config.ENTRADA / nome).is_file())
        self.assertTrue(r["ia"])
        self.assertEqual(r["pedido_klein"], self.texto_ia)
        self.assertTrue(all(n.startswith(f"editar_pintura_{r['codigo']}_") for n in r["pinturas"]))

    def test_pedido_klein_reserva_quando_a_ia_falha(self):
        self.texto_ia = ""
        r = self.pintar()
        self.assertFalse(r["ia"])
        self.assertTrue(r["pedido_klein"].startswith("vira tempestade"))

    def test_pedido_klein_do_usuario_nao_chama_a_ia(self):
        r = self.pintar(pedido_klein="Make it snow. " + ev.CLAUSULA_KLEIN, codigo="ab12cd34")
        self.assertEqual((self.chamadas_ia, r["codigo"]), (0, "ab12cd34"))

    def test_pintura_reduzida_ao_tamanho_do_video(self):
        self.video.update(largura=1080, altura=1920)
        r = self.pintar(pedido_klein="x. " + ev.CLAUSULA_KLEIN)
        with self.Image.open(config.ENTRADA / r["pinturas"][0]) as im:
            self.assertEqual(im.size, (544, 960))

    def test_recusa_durante_uma_geracao(self):
        self.rodando = True
        with self.assertRaises(self.acoes.Erro) as e:
            self.pintar()
        self.assertEqual(e.exception.codigo, 409)
        self.assertIn("placa livre", e.exception.mensagem)

    def test_recusa_duas_ao_mesmo_tempo(self):
        self.acoes._editando.acquire()
        self.addCleanup(self.acoes._editando.release)
        with self.assertRaises(self.acoes.Erro) as e:
            self.pintar()
        self.assertEqual(e.exception.codigo, 409)

    def test_recusa_codigo_estranho(self):
        with self.assertRaises(self.acoes.Erro):
            self.pintar(codigo="../x")

    def test_imagem_minha_na_proporcao(self):
        self.Image.new("RGB", (1000, 563)).save(config.ENTRADA / "minha.png")
        self.Image.new("RGB", (1000, 1000)).save(config.ENTRADA / "quadrada.png")
        r = self.acoes.acao_editar_imagem_minha({"arquivo": "minha.png", "video": "v.mp4", "codigo": "ab12cd34"})
        with self.Image.open(config.ENTRADA / r["pintura"]) as im:
            self.assertEqual(im.size, (960, 544))
        with self.assertRaises(self.acoes.Erro) as e:
            self.acoes.acao_editar_imagem_minha({"arquivo": "quadrada.png", "video": "v.mp4", "codigo": "ab12cd34"})
        self.assertIn("mesmo quadro", e.exception.mensagem)

    def test_roteiro_pela_ia(self):
        r0 = self.pintar(pedido_klein="x. " + ev.CLAUSULA_KLEIN)
        self.texto_ia = ev.roteiro_reserva("Stormy sky.", 24, 5).replace("Realistic", "Moody realistic")
        r = self.acoes.acao_editar_roteiro({"codigo": r0["codigo"], "quadro_png": r0["quadro"], "pintura": r0["pinturas"][0], "pedido": "vira tempestade",
                                            "pedido_klein": r0["pedido_klein"], "quadro": 24, "duracao": 5})
        self.assertTrue(r["ia"])
        self.assertIn("Moody realistic", r["roteiro"])
        self.assertTrue((config.ENTRADA / f"editar_par_{r0['codigo']}.png").is_file())

    def test_roteiro_reserva_quando_a_ia_falha(self):
        r0 = self.pintar(pedido_klein="x. " + ev.CLAUSULA_KLEIN)
        self.texto_ia = "um texto qualquer"
        r = self.acoes.acao_editar_roteiro({"codigo": r0["codigo"], "quadro_png": r0["quadro"], "pintura": r0["pinturas"][0], "pedido": "vira tempestade",
                                            "pedido_klein": r0["pedido_klein"], "quadro": 24, "duracao": 5})
        self.assertFalse(r["ia"])
        self.assertEqual([s.split(":")[0] for s in r["roteiro"].split("\n\n")], SECOES)


class Gerar(unittest.TestCase):
    """O miolo do script (editar_video.gerar), sem o WanGP: o laco, a montagem e a IA sao trocados por falsos."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        raiz = Path(d.name)
        self.pasta, entrada = raiz / "projetos" / "p1", raiz / "entrada"
        self.pasta.mkdir(parents=True)
        entrada.mkdir()
        (entrada / "editar_p1.mp4").write_bytes(b"video")
        from PIL import Image
        Image.new("RGB", (960, 544)).save(self.pasta / "pintado.png")
        self.quadros, self.roteiros, self.avisos = 240, [], []

        def executar(pedido, mon, ao_avisar):
            ao_avisar({"etapa": "viggle", "tarefa": 1, "de": 1})
            ao_avisar({"passo": 3, "total": 6})
            (self.pasta / "wangp" / "viggle.mp4").write_bytes(b"v")
            return 0, types.SimpleNamespace(pico_vram=8000, temp_max=72)

        def escrever(*a):
            self.roteiros.append(a)
            return self.roteiro_ia

        self.roteiro_ia = (ev.roteiro_reserva("Stormy.", 24, 5).replace("Realistic", "Moody"), True)
        for alvo, nome, valor in ((config, "ENTRADA", entrada), (config, "WANGP_PYTHON", Path(__file__)),
                                  (ev, "executar_wangp", executar), (ev, "montar_final", lambda *a: None), (ev, "liberar_comfy", lambda: None),
                                  (ev, "contar_quadros", lambda v: self.quadros), (ev, "ffmpeg", lambda *a: None),
                                  (ev, "examinar_video", lambda v: {"largura": 1920, "altura": 1080, "quadros": 240, "fps": 24, "duracao": 10, "audio": True}),
                                  (ev, "escrever_roteiro", escrever)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)
        self.mon = types.SimpleNamespace(rotulo="", quente=False)
        self.progresso = types.SimpleNamespace(etapa="roteiro", valor=0, maximo=0, tempos={}, inicio=time.time(), monitor=self.mon, gravar=lambda: None)
        self.p = {"tipo": "editar", "duracao": 5, "inicio": 0, "quadro": 24, "pedido": "vira tempestade", "qualidade": "rapido", "semente": None,
                  "esrgan": False, "pedido_klein": "Make it stormy. " + ev.CLAUSULA_KLEIN, "roteiro": ""}

    def gerar(self):
        return ev.gerar(self.pasta, self.p, "editar_p1.mp4", 777, self.mon, self.progresso)

    def test_gerar_monta_a_tarefa_do_viggle(self):
        r, roteiro = self.gerar()
        pedido = json.loads((self.pasta / "wangp" / "tarefas.json").read_text(encoding="utf-8"))
        self.assertEqual(len(pedido["tarefas"]), 1)
        s = pedido["tarefas"][0]["settings"]
        self.assertEqual((s["model_type"], s["frames_positions"], s["video_length"], s["resolution"]), ("viggle_remake_edit", "25", 124, "864x480"))
        self.assertEqual(s["image_refs"], [str(self.pasta / "pintado.png")])
        self.assertEqual(s["prompt"], roteiro)
        self.assertIn(roteiro, (self.pasta / "prompt.txt").read_text(encoding="utf-8"))
        self.assertEqual((r["pico_vram"], r["temp_max"]), (8000, 72))
        self.assertEqual(self.progresso.etapa, "montar")
        self.assertEqual(self.p["proporcao"], "1920:1080")

    def test_usa_o_roteiro_do_usuario(self):
        self.p["roteiro"] = ev.roteiro_reserva("Snow.", 24, 5)
        _, roteiro = self.gerar()
        self.assertEqual((self.roteiros, roteiro), ([], self.p["roteiro"]))

    def test_roteiro_reserva_quando_a_ia_falha(self):
        self.roteiro_ia = (ev.roteiro_reserva("x", 24, 5), False)
        impressas = []
        with mock.patch("builtins.print", lambda *a, **k: impressas.append(" ".join(map(str, a)))):
            _, roteiro = self.gerar()
        self.assertEqual(roteiro, self.roteiro_ia[0])
        self.assertTrue(any(l.startswith("AVISO: a IA não escreveu o roteiro") for l in impressas))

    def test_sai_com_4_sem_quadros(self):
        self.quadros = 60
        with mock.patch("builtins.print"), self.assertRaises(SystemExit) as e:
            self.gerar()
        self.assertEqual(e.exception.code, 4)


if __name__ == "__main__":
    unittest.main()
