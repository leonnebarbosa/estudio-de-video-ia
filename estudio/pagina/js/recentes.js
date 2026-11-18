/* Escolher entre as imagens geradas há pouco, sem procurar nos arquivos: cada caixa de foto ganha "Escolher entre as recentes",
   que abre as últimas imagens do Texto para imagem e da troca em foto. A escolhida é copiada para a entrada do ComfyUI
   (/api/usar-imagem, o mesmo do Transformar em vídeo) e entra na caixa como se tivesse sido enviada. */
const TIPOS_RECENTES = ["tfbase", "tfrosto", "tfroupa", "tfoto", "tfundo", "ifoto", "t2ifoto", "t2iref", "foto"], MAX_RECENTES = 12;

function imagensRecentes() {
  const lista = [];
  // Os projetos já vêm do mais novo para o mais antigo
  for (const p of S.dados?.projetos || []) {
    if (p.tipo !== "texto") continue;
    for (const i of p.imagens || []) {
      lista.push({ projeto: p.nome, arquivo: i.arquivo, marca: i.marca, troca: !!p.troca_foto });
      if (lista.length >= MAX_RECENTES) return lista;
    }
  }
  return lista;
}
/* Os botões e as faixas entram logo depois de cada caixa, uma vez só */
function prepararRecentes() {
  for (const tipo of TIPOS_RECENTES) {
    const zona = $(`zona-${tipo}`);
    if (!zona || $(`recentes-${tipo}`)) continue;
    zona.insertAdjacentHTML("afterend", `<button type="button" class="simples recentes-abrir" data-recentes-abrir="${tipo}" aria-expanded="false" aria-controls="recentes-${tipo}" hidden>Escolher entre as recentes</button>`
      + `<div class="recentes" id="recentes-${tipo}" role="list" aria-label="Imagens geradas há pouco" hidden></div>`);
  }
}
function desenharFaixaRecentes(tipo, lista = imagensRecentes()) {
  $(`recentes-${tipo}`).innerHTML = lista.map(r => {
    const src = `/imagem/${encodeURIComponent(r.projeto)}/${encodeURIComponent(r.arquivo)}?m=${r.marca}`;
    return `<button type="button" class="recente" role="listitem" data-recente-tipo="${tipo}" data-recente-projeto="${esc(r.projeto)}" data-recente-arquivo="${esc(r.arquivo)}" title="${esc(r.projeto)}${r.troca ? " (troca em foto)" : ""}">${midia(`<img src="${src}" alt="" loading="lazy">`, "Foto oculta")}</button>`;
  }).join("");
}
/* Chamada a cada atualização da página: o botão só aparece quando há imagem gerada, e a faixa aberta acompanha as novas */
function atualizarRecentes() {
  const lista = imagensRecentes(), marca = JSON.stringify(lista.map(r => [r.projeto, r.arquivo, r.marca]));
  const mudou = marca !== S.marcaRecentes;
  S.marcaRecentes = marca;
  for (const tipo of TIPOS_RECENTES) {
    const botao = document.querySelector(`[data-recentes-abrir="${tipo}"]`), faixa = $(`recentes-${tipo}`);
    if (!botao) continue;
    botao.hidden = !lista.length;
    if (!lista.length) fecharRecentes(tipo);
    else if (mudou && !faixa.hidden) desenharFaixaRecentes(tipo, lista);
  }
}
function fecharRecentes(tipo) {
  const faixa = $(`recentes-${tipo}`), botao = document.querySelector(`[data-recentes-abrir="${tipo}"]`);
  if (!faixa) return;
  faixa.hidden = true;
  botao.setAttribute("aria-expanded", "false");
  botao.textContent = "Escolher entre as recentes";
}
function alternarRecentes(tipo) {
  const faixa = $(`recentes-${tipo}`), botao = document.querySelector(`[data-recentes-abrir="${tipo}"]`);
  if (!faixa.hidden) return fecharRecentes(tipo);
  desenharFaixaRecentes(tipo);
  faixa.hidden = false;
  botao.setAttribute("aria-expanded", "true");
  botao.textContent = "Fechar as recentes";
}
async function escolherRecente(tipo, projeto, arquivo, botao) {
  botao.disabled = true;
  try {
    const info = await postar("/api/usar-imagem", { projeto, arquivo });
    preencherArquivo(tipo, info);
    depoisDeEscolher(tipo, info);
    fecharRecentes(tipo);
    atualizar();
  } catch (e) {
    recado(e.message);
  }
  botao.disabled = false;
}
prepararRecentes();
document.addEventListener("click", e => {
  const abrir = e.target.closest("[data-recentes-abrir]");
  if (abrir) { alternarRecentes(abrir.dataset.recentesAbrir); return; }
  const b = e.target.closest("[data-recente-tipo]");
  if (b) escolherRecente(b.dataset.recenteTipo, b.dataset.recenteProjeto, b.dataset.recenteArquivo, b);
});
