"""Menu de quatro áreas: o index.html tem os botões de área e as abas de vídeo ficam no seletor de modo da tela.
Roda tambem os testes de Node do areas.js e da galeria.

Uso: python -I testar_navegacao.py
"""
import re, shutil, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

AQUI = Path(__file__).resolve().parent
PAGINA = AQUI.parent / "pagina"
NODE = shutil.which("node")
ABAS = ["explorar", "novo", "troca", "editar", "personagens", "imagem", "tvideo", "avancado", "texto", "projetos", "modelos"]


def rodar_node(arquivo):
    return subprocess.run([NODE, str(AQUI / arquivo)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                          creationflags=config.SEM_JANELA)


class Menu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PAGINA / "index.html").read_text(encoding="utf-8")
        cls.ids = set(re.findall(r'\bid="([^"]+)"', cls.html))

    def test_as_areas_existem(self):
        for area in ("inicio", "personagem", "troca", "video", "imagem", "projetos", "modelos"):
            self.assertIn(f"area-{area}", self.ids)
            self.assertRegex(self.html, rf'id="area-{area}"[^>]*data-area="{area}"')

    def test_os_botoes_de_aba_existem(self):
        self.assertEqual([a for a in ABAS if f"aba-{a}" not in self.ids], [])

    def test_os_modos_de_video_ficam_no_seletor(self):
        seletor = re.search(r'<div[^>]*id="modos-video"[^>]*>(.*?)</div>', self.html, re.S)
        self.assertIsNotNone(seletor, "não achei o seletor de modo do vídeo")
        self.assertEqual(re.findall(r'id="(aba-[a-z]+)"', seletor.group(1)), ["aba-imagem", "aba-tvideo", "aba-avancado", "aba-novo", "aba-editar"])
        for rotulo in ("De uma imagem", "De um texto", "Avançado", "Continuar", "Editar"):
            self.assertIn(f">{rotulo}<", seletor.group(1))

    def test_o_menu_de_cima_so_tem_as_quatro_areas(self):
        menu = re.search(r'<nav class="lateral".*?</nav>', self.html, re.S).group(0)
        self.assertNotIn('id="aba-', menu, "botão de aba dentro do menu de cima")
        for sobra in ("Explorar", "Continuar", "Texto para vídeo"):
            self.assertNotIn(sobra, menu)
        for area in ("Personagem", "Trocar", "Vídeo", "Imagem"):
            self.assertIn(f">{area}<", menu)

    def test_a_pasta_de_projetos_fica_no_canto_direito_com_a_contagem(self):
        # Pedido de 20/11/2026: achar o que já foi gerado sem procurar. A pasta fica junto dos botões da direita, com o
        # nome escrito e quantos projetos existem (o projetos.js escreve em projetos-conta).
        menu = re.search(r'<nav class="lateral".*?</nav>', self.html, re.S).group(0)
        direita = menu[menu.index('<div class="sistema">'):]
        botao = re.search(r'<button[^>]*id="area-projetos"[^>]*>.*?</button>', direita, re.S)
        self.assertIsNotNone(botao, "a pasta de Projetos não está no canto direito do menu")
        self.assertIn('href="#s-projetos"', botao.group(0))
        self.assertIn(">Projetos<", botao.group(0))
        self.assertIn('id="projetos-conta"', botao.group(0))
        self.assertEqual(self.html.count('id="projetos-conta"'), 1)
        eventos = (PAGINA / "js" / "eventos.js").read_text(encoding="utf-8")
        self.assertRegex(eventos, r'\$\("area-projetos"\)\.addEventListener\("click", \(\) => irPara\("projetos"\)\)')

    def test_a_pasta_mostra_o_nome_so_ao_passar_o_mouse(self):
        # Pedido de 20/11/2026: só a pasta; o nome aparece, deslizando, com o mouse em cima ou o foco do teclado
        css = (PAGINA / "nova.css").read_text(encoding="utf-8")
        self.assertRegex(css, r'\.atalho-nome \{[^}]*max-width: 0;')
        self.assertRegex(css, r'\.atalho-projetos:is\(:hover, :focus-visible\) \.atalho-nome \{[^}]*max-width: \d+px')
        self.assertNotIn("@media (max-width: 1100px) { .atalho-nome", css)

    def test_em_tela_estreita_a_marca_continua_no_menu(self):
        # O estilo.css esconde a .marca abaixo de 640 px; como ela é o caminho para a tela inicial, o nova.css a mostra de novo.
        # E o menu precisa crescer para a segunda linha (as áreas), senão elas ficam por cima da barra da tela.
        css = (PAGINA / "nova.css").read_text(encoding="utf-8")
        bloco = re.search(r'@media \(max-width: 640px\) \{\n  \.app \{ display: block; \}(.*?)\n\}', css, re.S)
        self.assertIsNotNone(bloco, "não achei as regras de 640 px do menu")
        self.assertRegex(bloco.group(1), r'\.marca[^{]*\{[^}]*display: flex')
        self.assertRegex(bloco.group(1), r'html\.lateral-estreita \.lateral \{[^}]*height: auto')

    def test_areas_js_vem_logo_depois_do_base(self):
        scripts = re.findall(r'<script src="/pagina/js/([a-z]+)\.js">', self.html)
        self.assertEqual(scripts[scripts.index("base") + 1], "areas")


@unittest.skipUnless(NODE, "Node não instalado")
class TestesDeNode(unittest.TestCase):
    def test_areas_js(self):
        r = rodar_node("areas.test.js")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_personagens_visuais_js(self):
        r = rodar_node("personagens_visuais.test.js")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_projetos_js(self):
        r = rodar_node("projetos.test.js")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_galeria_js(self):
        r = rodar_node("galeria.test.js")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Galeria(unittest.TestCase):
    def test_projetos_tem_os_modos_galeria_e_lista(self):
        # Pedido de 20/11/2026: ver o que já foi gerado como nas outras plataformas, em grade ou em lista
        html = (PAGINA / "index.html").read_text(encoding="utf-8")
        tela = re.search(r'<section class="biblioteca-tela" id="tela-projetos".*?</section>', html, re.S).group(0)
        for modo, nome in (("galeria", "Galeria"), ("lista", "Lista")):
            self.assertRegex(tela, rf'<button[^>]*data-modo-projetos="{modo}"[^>]*>.*?{nome}</span></button>')
        self.assertRegex(tela, r'<button[^>]*id="fechar-projeto"[^>]*>.*?Todos os projetos</button>')
        # "Voltar para a galeria" levava à tela inicial: com o modo Galeria aqui, o nome confundia (a marca e a pasta do menu já fazem isso)
        self.assertNotIn("voltar-galeria", html + (PAGINA / "js" / "eventos.js").read_text(encoding="utf-8"))
        projetos = (PAGINA / "js" / "projetos.js").read_text(encoding="utf-8")
        self.assertIn('"estudio_modo_projetos"', projetos)
        self.assertIn("comCapa(p, desenharProjeto(", projetos)

    def test_na_galeria_nenhum_projeto_abre_sozinho(self):
        # Na lista, entrar em Projetos abre o mais recente (layout.js); na galeria isso esconderia a grade
        layout = (PAGINA / "js" / "layout.js").read_text(encoding="utf-8")
        self.assertRegex(layout, r'S\.modoProjetos === "galeria"\) return;')

    def test_video_aberto_ja_carrega_o_primeiro_quadro(self):
        # O vídeo do projeto aberto aparecia como um quadro preto até dar play: carrega o começo e mostra o primeiro quadro
        projetos = (PAGINA / "js" / "projetos.js").read_text(encoding="utf-8")
        funcao = re.search(r'^function carregarVideosAbertos\([\s\S]*?^}', projetos, re.M)
        self.assertIsNotNone(funcao, "não achei o carregarVideosAbertos no projetos.js")
        self.assertIn('preload = "metadata"', funcao.group(0))
        self.assertIn("#t=0.1", funcao.group(0))
        self.assertIn("carregarVideosAbertos()", (PAGINA / "js" / "layout.js").read_text(encoding="utf-8"))
        # E aparece no formato dele, sem faixas pretas dos lados
        css = (PAGINA / "nova.css").read_text(encoding="utf-8")
        self.assertRegex(css, r'\.corpo > \.midia > video \{[^}]*width: auto;[^}]*max-width: 100%')

    def test_tela_inicial_sem_os_blocos_que_repetem_o_menu(self):
        js = (PAGINA / "js" / "explorar.js").read_text(encoding="utf-8")
        for sobra in ("exp-heroi", "exp-blocos", "exp-meio"):
            self.assertNotIn(sobra, js)
        self.assertIn("Nada gerado aqui ainda.", js)
        self.assertIn("#t=0.1", js, "a miniatura do vídeo precisa pedir um quadro, senão fica preta")


class Personagem(unittest.TestCase):
    # 21/11/2026: um personagem por vez, visuais em abas, biblioteca em lista ou galeria e "Novo personagem" atrás de um botão
    def test_tela_tem_os_modos_o_botao_de_novo_e_o_detalhe(self):
        html = (PAGINA / "index.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for i in ("pers-modo-lista", "pers-modo-galeria", "pers-novo-abrir", "pers-detalhe", "dr-visual"):
            self.assertIn(i, ids)

    def test_nova_roupa_saiu_do_cartao(self):
        # A roupa nova virou a aba "+ Novo visual"; o botão solto do cartão saiu
        js = (PAGINA / "js" / "personagens.js").read_text(encoding="utf-8")
        self.assertNotIn('data-pers="nova-roupa"', js)


if __name__ == "__main__":
    unittest.main()
