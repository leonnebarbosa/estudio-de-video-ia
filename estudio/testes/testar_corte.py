"""Visual Corte (22/11/2026): a interface refeita sobre o desenho do Director's Cut. O corte.css vem por cima do
estilo.css e do nova.css, o historico de cada tela vira a tira "Feitos" na coluna da direita e o cabecalho ganha o
botao Fila. Estes testes vigiam o que liga as pecas; o visual em si foi conferido no navegador.

Uso: python -I testar_corte.py
"""
import re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, servidor

PAGINA = Path(__file__).resolve().parent.parent / "pagina"


def ler(*partes):
    return PAGINA.joinpath(*partes).read_text(encoding="utf-8")


class Camadas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = ler("index.html")
        cls.css = ler("corte.css")

    def test_o_corte_vem_por_cima_dos_outros_dois(self):
        folhas = re.findall(r'<link rel="stylesheet" href="/pagina/([a-z]+\.css)">', self.html)
        # A doca da geração (24/11/2026) vem por último: só mexe nela e na aba recolhida
        self.assertEqual(folhas, ["estilo.css", "nova.css", "corte.css", "doca.css"])

    def test_a_fonte_esta_na_pasta_e_o_servidor_a_entrega(self):
        fonte = re.search(r'src: url\((fontes/[a-z-]+\.ttf)\)', self.css)
        self.assertIsNotNone(fonte, "o corte.css não aponta a Space Grotesk")
        self.assertTrue((PAGINA / fonte.group(1)).is_file(), fonte.group(1))
        self.assertEqual(servidor.TIPOS_PAGINA.get(".ttf"), "font/ttf")
        # A licença da fonte vai junto dela (SIL OFL)
        self.assertIn("SIL Open Font License", ler("fontes", "OFL-SpaceGrotesk.txt"))

    def test_as_cores_do_estudio_viram_as_do_corte(self):
        raiz = re.search(r':root \{(.*?)\n\}', self.css, re.S).group(1)
        for nome, valor in (("--chao", "#000"), ("--cor", "#becc00"), ("--cor-tinta", "#000")):
            self.assertRegex(raiz, rf'{nome}: {re.escape(valor)};', nome)
        # O verde de "deu certo" continua diferente do destaque: no resumo de modelos os dois aparecem lado a lado
        self.assertNotIn("--bom:", raiz)

    def test_letra_preta_sobre_o_verde(self):
        # O destaque é claro: branco por cima dele não dá leitura. Vale para a área aberta, as pílulas e o botão principal
        for seletor in (r'\.areas button\[aria-current="page"\]', r'\.segmento-botao\[aria-pressed="true"\]', r'\.principal'):
            regra = re.search(seletor + r'[^{]*\{([^}]*)\}', self.css)
            self.assertIsNotNone(regra, seletor)
            self.assertRegex(regra.group(1), r'color: #000', seletor)
        # Apagar e parar continuam vermelhos, com letra branca
        self.assertRegex(self.css, r'\.principal\.perigo[^{]*\{[^}]*color: #fff')

    def test_as_pilulas_ganham_do_botao_comum(self):
        # Vários botões de .modos não têm classe nem role: sem o peso extra, a regra do botão comum pintava o fundo deles
        # e o escolhido ficava com letra preta sobre fundo escuro (visto na tela Personagem em 22/11/2026)
        self.assertRegex(self.css, r'\.modos button:not\(\.a\):not\(\.b\):is\(\[aria-selected="true"\], \[aria-pressed="true"\]\) \{[^}]*var\(--cor\)')

    def test_tres_colunas_e_a_tira_desce_em_janela_estreita(self):
        self.assertRegex(self.css, r'\.area \{ grid-template-columns: calc\(var\(--insp-w\) \+ var\(--vao\)\) minmax\(0, 1fr\) auto;')
        self.assertRegex(self.css, r'\.tira \{ grid-column: 3; grid-row: 1;')
        estreita = re.search(r'@media \(max-width: 1280px\) \{(.*?)\n\}', self.css, re.S)
        self.assertIsNotNone(estreita, "não achei as regras de 1280 px")
        self.assertRegex(estreita.group(1), r'\.tira \{ grid-column: 2; grid-row: 2;')
        # O painel de criação acompanha as duas linhas, senão sobra um buraco embaixo dele
        self.assertRegex(estreita.group(1), r'\.lado \{ grid-row: 1 / span 2; \}')

    def test_a_ordem_do_html_e_a_ordem_na_tela(self):
        # O .sistema é display: contents e os botões ganham order: o Tab segue o HTML, então os dois têm que bater
        menu = re.search(r'<div class="sistema">(.*?)</div>\s*</nav>', self.html, re.S).group(1)
        ids = re.findall(r'<(?:button|p)[^>]*\bid="([a-z-]+)"', menu)
        # Modelos e Fechar foram para o menu do estúdio, à esquerda (24/11/2026)
        self.assertEqual(ids, ["area-projetos", "fila-botao", "recursos-botao", "luz", "aviso-comfy", "ligar"])
        ordem = {i: int(re.search(seletor + r'[^{]*\{[^}]*\border: (\d+);', self.css).group(1)) for i, seletor in (
            ("area-projetos", r'\.atalho-projetos'), ("fila-botao", r'\.fila-botao'), ("recursos-botao", r'\.recursos-botao, html\.lateral-estreita \.recursos-botao'),
            ("luz", r'\.luz, html\.lateral-estreita \.luz'), ("ligar", r'\.sistema #ligar'))}
        visiveis = [i for i in ids if i in ordem]
        self.assertEqual(visiveis, sorted(visiveis, key=ordem.get))

    def test_o_recado_ganha_da_regra_antiga(self):
        # O estilo.css posiciona o recado com html[data-aba="x"]:not(.sem-inspetor) .recado, contando com o painel à
        # direita; sem o mesmo peso, o aviso parava no meio do palco (revisão de 22/11/2026)
        self.assertRegex(self.css, r'html\[data-aba\]:not\(\.a\) \.recado \{ right: 22px;')
        self.assertRegex(self.css, r'\[data-aba="texto"\]\):not\(\.a\) \.recado \{ right: calc\(var\(--tira-w\)')

    def test_alertas_valem_com_a_barra_estreita(self):
        # Abaixo de 1180 px a página ganha html.lateral-estreita, e as regras com esse prefixo pesam mais
        self.assertRegex(self.css, r'html\.lateral-estreita \.recursos-botao\.quente \{[^}]*var\(--erro\)')
        self.assertRegex(self.css, r'html\.lateral-estreita \.luz\.ligado \{ color: var\(--cor-texto\)')

    def test_o_cabecalho_cabe_em_janela_estreita(self):
        # Entre 641 e 860 px o cabeçalho passava da largura (medido no navegador em 22/11/2026)
        self.assertRegex(self.css, r'@media \(max-width: 860px\) \{\n  \.lateral \.marca[^{]*\{[^}]*font-size: 0;')
        bloco = re.search(r'@media \(max-width: 720px\) \{(.*?)\n\}', self.css, re.S)
        self.assertIsNotNone(bloco, "não achei as regras de 720 px")
        self.assertRegex(bloco.group(1), r'\.lateral[^{]*\{[^}]*flex-wrap: wrap')
        self.assertRegex(bloco.group(1), r'\.areas \{ order: 10; flex-basis: 100%; \}')

    def test_o_cabecalho_nao_corta_as_areas(self):
        # Em janela estreita quem encolhe é a luz do motor (com reticências), nunca o menu
        self.assertRegex(self.css, r'\.areas \{ flex: none;')
        self.assertRegex(self.css, r'\.luz, html\.lateral-estreita \.luz \{ order: 4; flex: 0 1 auto; min-width: 0;')


class Fila(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = ler("index.html")
        cls.js = ler("js", "fila.js")

    def test_o_botao_fica_no_cabecalho_com_a_contagem(self):
        menu = re.search(r'<nav class="lateral".*?</nav>', self.html, re.S).group(0)
        botao = re.search(r'<button[^>]*id="fila-botao"[^>]*>.*?</button>', menu, re.S)
        self.assertIsNotNone(botao, "o botão Fila não está no menu de cima")
        self.assertIn('type="button"', botao.group(0))
        self.assertIn('id="fila-conta"', botao.group(0))
        self.assertIn('href="#s-fila"', botao.group(0))
        self.assertIn('<symbol id="s-fila"', self.html)

    def test_a_contagem_soma_o_que_esta_gerando(self):
        funcao = re.search(r'^function desenharBotaoFila\([\s\S]*?^}', self.js, re.M)
        self.assertIsNotNone(funcao, "não achei o desenharBotaoFila no fila.js")
        self.assertIn("(rodando ? 1 : 0)", funcao.group(0))
        # O desenharFila sai cedo quando a fila está vazia: o botão é atualizado antes disso
        desenhar = re.search(r'^function desenharFila\(d\) \{\n(.*)', self.js.replace("\r\n", "\n"), re.M)
        self.assertEqual(desenhar.group(1).strip(), "desenharBotaoFila(d);")

    def test_o_botao_tem_nome_mesmo_sem_o_texto(self):
        # Em janela estreita a palavra "Fila" some e sobra o número: o aria-label acompanha o título
        self.assertIn('botao.setAttribute("aria-label", titulo)', self.js)
        self.assertIn("(fila pausada)", self.js)

    def test_clicar_sem_nada_gerando_avisa(self):
        # Desde a doca (24/11/2026) o botão abre o painel, que diz que está vazio em vez de um recado
        self.assertIn('abrirDoca(!S.docaAberta, true)', self.js)
        vazia = re.search(r'<p class="doca-vazia" id="doca-vazia"[^>]*>([^<]*)</p>', self.html)
        self.assertIsNotNone(vazia, "a doca não tem o aviso de vazia")
        self.assertIn("Nada gerando agora e a fila está vazia.", vazia.group(1))


class Doca(unittest.TestCase):
    """Andamento e fila na coluna da direita (doca.js e doca.css, 24/11/2026)."""
    @classmethod
    def setUpClass(cls):
        cls.html = ler("index.html")
        cls.js = ler("js", "doca.js")
        cls.css = ler("doca.css")
        cls.base = ler("js", "base.js")

    def test_andamento_e_fila_moram_na_doca(self):
        doca = re.search(r'<aside class="doca" id="doca".*?</aside>', self.html, re.S)
        self.assertIsNotNone(doca, "não achei a doca no index.html")
        for ident in ("andamento", "fila-painel", "doca-origem", "doca-envio"):
            self.assertIn(f'id="{ident}"', doca.group(0))
            self.assertEqual(self.html.count(f'id="{ident}"'), 1, ident)

    def test_o_irpara_nao_tira_o_andamento_da_doca(self):
        self.assertNotIn('prepend($("andamento"))', self.base)
        self.assertNotIn('after($("fila-painel"))', self.base)

    def test_a_doca_e_desenhada_depois_do_andamento_e_da_fila(self):
        # Ela lê a porcentagem que o andamento escreveu (#pct) para o anel da aba recolhida
        consulta = ler("js", "projetos.js")
        self.assertRegex(consulta, r'desenharAndamento\(d\);\s*desenharFila\(d\);\s*desenharDoca\(d\);')
        self.assertIn('$("pct")?.textContent', self.js)
        self.assertLess(self.html.index("/pagina/js/fila.js"), self.html.index("/pagina/js/doca.js"))
        self.assertLess(self.html.index("/pagina/js/doca.js"), self.html.index("/pagina/js/projetos.js"))

    def test_cada_tipo_de_pedido_tem_uma_aba(self):
        abas = set(re.findall(r'aba: "([a-z]+)"', re.search(r'function abaDoPedido[\s\S]*?^}', self.js, re.M).group(0)))
        for aba in abas:
            self.assertIn(f'id="aba-{aba}"', self.html, aba)

    def test_animacao_para_com_reduzir_movimento(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        reduzir = self.css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        for seletor in (".doca.gerando::after", ".fila-botao.gerando .anel-cometa", ".doca.gerando .doca-sinal i"):
            self.assertIn(seletor, reduzir)

    def test_um_indicador_so_no_cabecalho(self):
        # A aba da borda direita repetia o botão Fila: saiu, e o anel com a porcentagem ficou no botão
        self.assertNotIn("doca-aba", self.html)
        self.assertNotIn("doca-aba", self.js)
        botao = re.search(r'<button[^>]*id="fila-botao".*?</button>', self.html, re.S).group(0)
        for ident in ("fila-anel", "fila-rotulo", "fila-conta"):
            self.assertIn(f'id="{ident}"', botao)
        self.assertIn('$("luz").classList.toggle("com-geracao", rodando)', self.js)


class MenuEstudio(unittest.TestCase):
    """Modelos e Fechar o estúdio no menu da esquerda, onde vão entrar as configurações (24/11/2026)."""
    @classmethod
    def setUpClass(cls):
        cls.html = ler("index.html")

    def test_o_botao_abre_o_menu(self):
        nav = re.search(r'<nav class="lateral".*?</nav>', self.html, re.S).group(0)
        self.assertRegex(nav, r'<button[^>]*id="menu-botao"[^>]*popovertarget="menu-estudio"')
        self.assertNotIn('id="area-modelos"', nav)
        self.assertNotIn('id="fechar-estudio"', nav)

    def test_modelos_e_fechar_estao_no_menu(self):
        menu = re.search(r'<div id="menu-estudio"[^>]*popover[^>]*>.*?</div>\s*</div>', self.html, re.S)
        self.assertIsNotNone(menu, "não achei o menu do estúdio")
        self.assertIn('id="area-modelos"', menu.group(0))
        self.assertIn('id="fechar-estudio"', menu.group(0))
        self.assertIn('<symbol id="s-menu"', self.html)


class Tira(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = ler("js", "historico.js").replace("\r\n", "\n")
        cls.funcao = re.search(r'^function garantirHistorico\([\s\S]*?^}', cls.js, re.M).group(0)

    def test_a_tira_e_uma_coluna_da_tela(self):
        # A .tela é display: contents; para a tira ser um item da grade da .area ela precisa ser filha direta da tela
        self.assertIn('h.className = "historico tira";', self.funcao)
        self.assertIn("tela.append(h);", self.funcao)
        self.assertNotIn("bloco.append(h)", self.funcao)

    def test_a_barra_do_item_aberto_fica_embaixo_da_previa(self):
        self.assertIn("previa.after(barra);", self.funcao)
        self.assertIn("barra.dataset.histBarra = aba;", self.funcao)
        # Quem abre e fecha a prévia acha a barra pelo id, não mais dentro da faixa
        self.assertEqual(self.js.count("$(`hist-barra-${aba}`)"), 2)
        self.assertNotIn('querySelector(".hist-barra")', self.js)
        # A prévia esconde o que está no bloco do palco, menos ela mesma e a barra
        self.assertIn('el.classList.contains("hist-barra")', self.js)

    def test_nao_ha_mais_faixa_recolhida(self):
        for sobra in ("estudio_historico_aberto", "alternarHistorico", "hist-alternar", "recolhido"):
            self.assertNotIn(sobra, self.js, sobra)
        # E nenhum outro script chama o que saiu
        for arquivo in sorted((PAGINA / "js").glob("*.js")):
            self.assertNotIn("alternarHistorico", arquivo.read_text(encoding="utf-8"), arquivo.name)

    def test_a_tira_trava_junto_com_a_tela(self):
        # Durante a geração o bloco do palco fica inerte; a tira, que saiu de dentro dele, precisa travar também, senão a
        # prévia abre e os botões dela não respondem (revisão de 22/11/2026)
        layout = ler("js", "layout.js")
        self.assertRegex(layout, r'querySelectorAll\("\.centro > :not\(#andamento\), \.lado-corpo > \*, \.lado-pe > \.marcar, :scope > \.tira"\)')

    def test_todas_as_telas_com_historico_tem_o_bloco_do_palco(self):
        html = ler("index.html")
        abas = re.search(r'const ABAS_HISTORICO = \{(.*?)\n\};', self.js, re.S).group(1)
        for aba in re.findall(r'^  ([a-z]+): \{', abas, re.M):
            tela = re.search(rf'<form id="tela-{aba}".*?</form>', html, re.S)
            self.assertIsNotNone(tela, aba)
            self.assertIn("palco-bloco", tela.group(0), aba)


if __name__ == "__main__":
    unittest.main()
