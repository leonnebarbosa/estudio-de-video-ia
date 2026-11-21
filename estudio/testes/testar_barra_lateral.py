"""Barra lateral enxuta (reforma de 20/11/2026): a ajuda de cada campo fica atras de um "?" (ajuda.js), as areas de envio
ocupam uma linha com o "x" de tirar ao lado, e audio, foto do lugar e outros angulos ficam juntos em Referencias.
O rodape fica com poucas linhas: o aviso de configuracao vai para o centro e a lista do que falta vira uma linha.

Uso: python -I testar_barra_lateral.py
"""
import re, shutil, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

AQUI = Path(__file__).resolve().parent
PAGINA = AQUI.parent / "pagina"
NODE = shutil.which("node")
# Os botoes de tirar que ficam ao lado de uma area de envio da barra lateral
TIRAR = ["tirar-foto", "tirar-tfundo", "tf-tirar-rosto", "tf-tirar-roupa", "tirar-iaudio", "tirar-icenario", "t2i-tirar-ref"]


class BarraLateral(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PAGINA / "index.html").read_text(encoding="utf-8")
        cls.css = (PAGINA / "nova.css").read_text(encoding="utf-8")
        cls.lados = re.findall(r'<aside class="lado".*?</aside>', cls.html, re.S)

    def test_referencias_junta_audio_lugar_e_angulos(self):
        ini = self.html.find('id="i-referencias"')
        self.assertGreater(ini, 0, "não achei o bloco Referências")
        fim = self.html.find('id="i-ajustes"', ini)
        bloco = self.html[ini:fim]
        self.assertIn(">Referências<", bloco)
        campos = re.findall(r'id="(campo-[a-z-]+)"', bloco)
        self.assertEqual(campos, ["campo-iaudio", "campo-icenario", "campo-irefs"])
        self.assertLess(self.html.find('id="campo-i-voz"'), ini, "Como é a voz vem antes das Referências")

    def test_botoes_de_tirar_viram_um_x_com_nome(self):
        for i in TIRAR:
            botao = re.search(rf'<button[^>]*id="{i}"[^>]*>', self.html)
            self.assertIsNotNone(botao, i)
            self.assertRegex(botao.group(0), r'class="[^"]*\btirar-x\b', i)
            self.assertRegex(botao.group(0), r'aria-label="Tirar [^"]+"', i)
            self.assertTrue(any(f'id="{i}"' in lado for lado in self.lados), f"{i} fora da barra lateral")

    def test_ajuda_js_vem_depois_do_layout(self):
        scripts = re.findall(r'<script src="/pagina/js/([a-z]+)\.js">', self.html)
        self.assertIn("ajuda", scripts)
        self.assertGreater(scripts.index("ajuda"), scripts.index("layout"))

    def test_campos_sem_cartao(self):
        regra = re.search(r'\.lado-corpo > \.campo, \.lado-corpo > fieldset[^{]*\{([^}]*)\}', self.css)
        self.assertTrue(regra is None or "background" not in regra.group(1), "os campos ainda têm caixa em volta")

    def test_linhas_de_estado_continuam_a_vista(self):
        # Valor calculado ou resultado de uma escolha: fica visível; o resto vai para o "?"
        for i in ("i-tamanho", "irefs-dica", "i-modelo-ugc-ajuda", "tamanho", "t-tamanho", "t2i-tamanho", "tf-ajuda"):
            self.assertRegex(self.html, rf'<(span|p) class="ajuda" id="{i}" data-estado>', i)
        self.assertNotRegex(self.html, r'id="i-modelo-ajuda" data-estado')

    def test_aviso_de_configuracao_fica_no_centro(self):
        avisos = re.findall(r'<p class="aviso-config" id="([a-z0-9-]+)"', self.html)
        self.assertEqual(sorted(avisos), ["aviso-config", "e-aviso-config", "i-aviso-config", "t-aviso-config", "t2i-aviso-config"])
        for lado in self.lados:
            self.assertNotIn("aviso-config", lado, "aviso de configuração ainda na barra lateral")

    def test_rodape_nao_monta_mais_a_lista_inteira(self):
        # As telas passam o que falta para o htmlFalta (base.js), que mostra uma linha
        for arquivo in ("continuar", "editar", "imagem", "texto", "troca", "trocafoto"):
            js = (PAGINA / "js" / f"{arquivo}.js").read_text(encoding="utf-8")
            linha = next(l for l in js.splitlines() if 'falta").' in l or "falta\")," in l)
            self.assertIn("htmlFalta(falta)", linha, arquivo)


class RevisaoFinal(unittest.TestCase):
    """O que a revisão do ramo achou em 20/11/2026."""
    @classmethod
    def setUpClass(cls):
        cls.html = (PAGINA / "index.html").read_text(encoding="utf-8")
        cls.css = (PAGINA / "nova.css").read_text(encoding="utf-8")
        cls.ajuda = (PAGINA / "js" / "ajuda.js").read_text(encoding="utf-8")

    def test_o_ponto_de_interrogacao_nao_vira_o_controle_do_rotulo(self):
        # Um botão dentro de um <label> sem "for" passa a ser o controle dele: clicar no nome do campo abriria a ajuda
        # em vez de focar o campo. O ajuda.js aponta o label para o campo de verdade antes de pôr o botão.
        self.assertRegex(self.ajuda, r'\.htmlFor = ')

    def test_um_item_faltando_aparece_inteiro(self):
        # Sem "e mais N" não há onde ler o resto: a linha quebra em vez de cortar com reticências
        self.assertRegex(self.css, r'\.falta-linha:not\(:has\(\.falta-mais\)\) \.falta-item \{[^}]*white-space: normal')

    def test_estilo_da_marca_nao_vaza_para_as_etapas(self):
        # .marca também é o número de cada etapa do andamento (andamento.js): o estilo do botão do menu fica preso ao menu
        for linha in self.css.splitlines():
            if re.match(r'\s*\.marca(:hover)? \{', linha) or re.match(r'\s*\.marca, html\.lateral-estreita \.marca \{ display', linha):
                self.fail(f"regra da marca sem o menu na frente: {linha.strip()[:80]}")
        self.assertIn(".lateral .marca:hover", self.css)

    def test_a_marca_acende_na_tela_inicial(self):
        self.assertRegex(self.css, r'\.lateral \.marca\[aria-current="page"\][^{]*\{[^}]*color: var\(--cor\)')

    def test_referencias_some_quando_nao_ha_nenhuma(self):
        # Com um modelo sem fala (Wan) os três campos ficam ocultos: o título não pode sobrar sozinho
        self.assertRegex(self.css, r'\.grupo-refs:not\(:has\(> \.campo:not\(\[hidden\]\)\)\) \{ display: none; \}')

    def test_resultado_da_escolha_fica_a_vista(self):
        # "Sai em 1920×1080" e "o refino fica de fora" são resultado de uma escolha, não explicação
        for i in ("i-acabamento-ajuda", "t-ampliar-ajuda"):
            self.assertRegex(self.html, rf'class="ajuda" id="{i}" data-estado', i)

    def test_textos_nao_citam_as_abas_que_sairam_do_menu(self):
        textos = self.html + "".join(p.read_text(encoding="utf-8") for p in sorted((PAGINA / "js").glob("*.js")))
        # Só o que a pessoa lê na tela; os comentários do código podem continuar dizendo "aba"
        for velho in ("na aba Personagens", "use a aba Trocar personagem", "na aba Imagem para vídeo", "na aba Continuar", "Esta aba ", "Histórico desta aba", "Nenhuma aba", "opções da aba"):
            self.assertNotIn(velho, textos, velho)


class Formato(unittest.TestCase):
    """Todo seletor de formato mostra cada proporção desenhada como um retângulo (controles.js, montarFormato)."""
    def test_todo_seletor_de_formato_tem_o_desenho(self):
        html = (PAGINA / "index.html").read_text(encoding="utf-8")
        js = (PAGINA / "js" / "controles.js").read_text(encoding="utf-8")
        seletores = re.findall(r'<select id="([a-z0-9-]*proporcao)"', html)
        self.assertGreaterEqual(len(seletores), 4)
        lista = re.search(r'formato: \[([^\]]*)\]', js).group(1)
        desenhados = re.findall(r'"([^"]+)"', lista)
        self.assertEqual(sorted(seletores), sorted(desenhados))

    def test_formato_resolucao_e_acabamento_ocupam_a_largura_toda(self):
        # Em meia coluna os retângulos do formato ficavam com 31 px e os nomes da resolução e do acabamento saíam cortados
        html = (PAGINA / "index.html").read_text(encoding="utf-8")
        for i in ("i-megapixels", "i-proporcao", "i-semente", "i-acabamento"):
            campo = html.index(f'id="{i}"')
            antes = html[:campo]
            self.assertLess(antes.rfind('<div class="par">'), antes.rfind("</div>"), f"{i} ainda está dentro de um par")

    def test_o_desenho_acompanha_cada_tela(self):
        # O controle se atualiza depois da função de atualizar de cada tela que tem um seletor de formato
        js = (PAGINA / "js" / "controles.js").read_text(encoding="utf-8")
        telas = re.search(r'for \(const nome of \[([^\]]*)\]\) \{\s*const original = window\[nome\]', js).group(1)
        for funcao in ("atualizar", "atualizarTroca", "atualizarImagem", "atualizarTexto"):
            self.assertIn(f'"{funcao}"', telas)


@unittest.skipUnless(NODE, "Node não instalado")
class Rodape(unittest.TestCase):
    def test_html_falta(self):
        r = subprocess.run([NODE, str(AQUI / "rodape.test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60,
                           creationflags=config.SEM_JANELA)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
