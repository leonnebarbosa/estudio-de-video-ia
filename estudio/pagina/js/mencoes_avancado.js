/* O textarea mantém o prompt original. O fundo espelha o texto para destacar as referências. */
const CAMPO_AV = $("av-prompt");
const MARCAS_AV = $("av-marcacoes");
const MENU_AV = $("av-menu");
const LISTA_MENCOES_AV = $("av-sugestoes");
const MENCAO_AV = /(?<![\p{L}\p{N}_@])@([\p{L}\p{N}_-]+)/gu;
let sugestoesAvancadas = [];
let opcaoAvancada = 0;

function alinharMarcacoesAvancadas() {
  MARCAS_AV.style.width = `${CAMPO_AV.clientWidth}px`;
  MARCAS_AV.scrollTop = CAMPO_AV.scrollTop;
  posicionarMencoesAvancadas();
}

function marcarMencoesAvancadas() {
  const nomes = new Set(AV.refs.map(r => r.nome.trim().toLowerCase()).filter(nome => NOME_REF_AV.test(nome)));
  const texto = CAMPO_AV.value;
  let inicio = 0, html = "";
  for (const m of texto.matchAll(MENCAO_AV)) {
    if (!nomes.has(m[1].toLowerCase())) continue;
    html += esc(texto.slice(inicio, m.index)) + `<mark>${esc(m[0])}</mark>`;
    inicio = m.index + m[0].length;
  }
  MARCAS_AV.innerHTML = html + esc(texto.slice(inicio)) + "\u200b";
  alinharMarcacoesAvancadas();
}

function mencaoNoCursor() {
  const { value, selectionStart, selectionEnd } = CAMPO_AV;
  if (selectionStart !== selectionEnd) return null;
  const m = /(?<![\p{L}\p{N}_@])@([\p{L}\p{N}_-]*)$/u.exec(value.slice(0, selectionStart));
  if (!m) return null;
  const sufixo = /^[\p{L}\p{N}_-]*/u.exec(value.slice(selectionStart))[0];
  return { nome: m[1].toLowerCase(), inicio: m.index, fim: selectionStart + sufixo.length };
}

function fecharMencoesAvancadas() {
  MENU_AV.hidden = true;
  CAMPO_AV.removeAttribute("aria-activedescendant");
}

function posicionarMencoesAvancadas() {
  if (MENU_AV.hidden) return;
  const mencao = mencaoNoCursor();
  if (!mencao) { fecharMencoesAvancadas(); return; }
  // Mede o arroba no mesmo texto espelhado que acompanha as quebras e a rolagem do textarea.
  const cursor = document.createTreeWalker(MARCAS_AV, NodeFilter.SHOW_TEXT);
  let no = cursor.nextNode(), indice = mencao.inicio;
  while (no && indice >= no.length) {
    indice -= no.length;
    no = cursor.nextNode();
  }
  if (!no) return;
  const intervalo = document.createRange();
  intervalo.setStart(no, indice);
  intervalo.setEnd(no, indice + 1);
  const ancora = intervalo.getBoundingClientRect(), campo = CAMPO_AV.getBoundingClientRect();
  const centro = CAMPO_AV.closest(".centro").getBoundingClientRect();
  const topo = Math.max(0, centro.top), fundo = Math.min(window.innerHeight, centro.bottom);
  if (ancora.bottom <= Math.max(topo, campo.top) || ancora.top >= Math.min(fundo, campo.bottom)) {
    fecharMencoesAvancadas();
    return;
  }
  const folga = 5;
  const abaixo = fundo - ancora.bottom - folga, acima = ancora.top - topo - folga;
  const altura = Math.min(220, LISTA_MENCOES_AV.scrollHeight) + 12;
  const abrirAcima = abaixo < altura && acima > abaixo;
  MENU_AV.classList.toggle("acima", abrirAcima);
  MENU_AV.style.setProperty("--altura-sugestoes", `${Math.max(0, (abrirAcima ? acima : abaixo) - 12)}px`);
  MENU_AV.style.top = `${(abrirAcima ? ancora.top - folga : ancora.bottom + folga) - campo.top}px`;
  MENU_AV.style.left = `${Math.max(0, Math.min(ancora.left - campo.left, campo.width - MENU_AV.offsetWidth))}px`;
}

function miniaturaSugestaoAvancada(r) {
  const icone = { foto: "s-foto", video: "s-filme", audio: "s-play" }[r.tipo];
  const src = enderecoReferenciaAvancado(r);
  const visual = r.tipo === "foto" ? `<img src="${src}" alt="" loading="lazy">` :
    r.tipo === "video" ? `<video src="${src}#t=0.1" data-capa muted playsinline preload="none"></video>` : "";
  return `<span class="avancado-sugestao-miniatura" aria-hidden="true">
    <svg class="ico"><use href="#${icone}"/></svg>${visual}
  </span>`;
}

function selecionarOpcaoAvancada(indice) {
  opcaoAvancada = indice;
  const itens = LISTA_MENCOES_AV.children;
  for (let i = 0; i < itens.length; i++) itens[i].setAttribute("aria-selected", i === indice);
  const item = itens[indice];
  CAMPO_AV.setAttribute("aria-activedescendant", item.id);
  const caixa = LISTA_MENCOES_AV.getBoundingClientRect(), opcao = item.getBoundingClientRect();
  if (opcao.top < caixa.top) LISTA_MENCOES_AV.scrollTop += opcao.top - caixa.top;
  if (opcao.bottom > caixa.bottom) LISTA_MENCOES_AV.scrollTop += opcao.bottom - caixa.bottom;
}

function atualizarMencoesAvancadas() {
  const mencao = mencaoNoCursor();
  if (document.activeElement !== CAMPO_AV || !mencao || CAMPO_AV.readOnly || CAMPO_AV.disabled) {
    fecharMencoesAvancadas();
    return;
  }
  sugestoesAvancadas = AV.refs.filter(r => NOME_REF_AV.test(r.nome.trim())
    && r.nome.trim().toLowerCase().startsWith(mencao.nome));
  porHtml(LISTA_MENCOES_AV, sugestoesAvancadas.map((r, i) => `<li id="av-sugestao-${i}" role="option" data-av-sugestao="${i}">
    ${miniaturaSugestaoAvancada(r)}
    <span><strong>@${esc(r.nome.trim())}</strong><small>${esc(r.arquivo)}</small></span>
  </li>`).join(""));
  const vazio = $("av-sugestoes-vazio");
  vazio.hidden = !!sugestoesAvancadas.length;
  vazio.textContent = AV.refs.length ? "Nenhuma referência encontrada." : "Adicione mídias em Referências para citá-las aqui.";
  MENU_AV.hidden = false;
  posicionarMencoesAvancadas();
  observarCapas(LISTA_MENCOES_AV);
  LISTA_MENCOES_AV.scrollTop = 0;
  if (sugestoesAvancadas.length) selecionarOpcaoAvancada(0);
  else CAMPO_AV.removeAttribute("aria-activedescendant");
}

function inserirMencaoAvancada(nome, inicio = CAMPO_AV.selectionStart, fim = CAMPO_AV.selectionEnd) {
  const antes = CAMPO_AV.value[inicio - 1] || "";
  const depois = CAMPO_AV.value[fim] || "";
  const trecho = `${/[\p{L}\p{N}_@]/u.test(antes) ? " " : ""}@${nome}${/^[\s,.;!?)]$/.test(depois) ? "" : " "}`;
  if (CAMPO_AV.value.length - (fim - inicio) + trecho.length > CAMPO_AV.maxLength) {
    recado("O prompt atingiu o limite de caracteres.");
    return;
  }
  CAMPO_AV.setRangeText(trecho, inicio, fim, "end");
  CAMPO_AV.focus();
  fecharMencoesAvancadas();
  marcarMencoesAvancadas();
  atualizarAvancado();
}

function escolherMencaoAvancada(indice) {
  const ref = sugestoesAvancadas[indice], mencao = mencaoNoCursor();
  if (ref && mencao) inserirMencaoAvancada(ref.nome.trim(), mencao.inicio, mencao.fim);
}

CAMPO_AV.addEventListener("input", e => {
  marcarMencoesAvancadas();
  if (!e.isComposing) atualizarMencoesAvancadas();
});
CAMPO_AV.addEventListener("compositionend", atualizarMencoesAvancadas);
CAMPO_AV.addEventListener("scroll", alinharMarcacoesAvancadas);
CAMPO_AV.addEventListener("click", atualizarMencoesAvancadas);
CAMPO_AV.addEventListener("blur", fecharMencoesAvancadas);
CAMPO_AV.addEventListener("keyup", e => {
  if (!e.isComposing && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) atualizarMencoesAvancadas();
});
CAMPO_AV.addEventListener("keydown", e => {
  if (e.isComposing || MENU_AV.hidden) return;
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    fecharMencoesAvancadas();
  } else if (sugestoesAvancadas.length && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey
      && ["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
    e.preventDefault();
    if (e.key === "Enter") escolherMencaoAvancada(opcaoAvancada);
    else {
      const n = sugestoesAvancadas.length;
      selecionarOpcaoAvancada((opcaoAvancada + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
    }
  }
});
LISTA_MENCOES_AV.addEventListener("mousedown", e => {
  if (e.target.closest("[data-av-sugestao]")) e.preventDefault();
});
LISTA_MENCOES_AV.addEventListener("click", e => {
  const opcao = e.target.closest("[data-av-sugestao]");
  if (opcao) escolherMencaoAvancada(Number(opcao.dataset.avSugestao));
});
for (const evento of ["load", "loadeddata"]) {
  LISTA_MENCOES_AV.addEventListener(evento, e => e.target.classList.add("pronta"), true);
}
CAMPO_AV.closest(".centro").addEventListener("scroll", posicionarMencoesAvancadas);
window.addEventListener("resize", posicionarMencoesAvancadas);
new ResizeObserver(alinharMarcacoesAvancadas).observe(CAMPO_AV);
