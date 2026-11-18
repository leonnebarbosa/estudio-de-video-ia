/* Modelos: o que ha na pasta models do ComfyUI, o que o aplicativo usa e o que pode ser apagado */
const M = { itens: null, total: 0, tipo: "", soNaoUsados: false, carregando: false };
const gb = bytes => num(bytes / 2 ** 30, bytes >= 2 ** 30 ? 1 : 2);
const ONDE_USO = { fixo: i => `usado pelo aplicativo: ${i.onde.join(", ")}`, opcao: () => "aparece como opção na aba Continuar", nenhum: () => "não usado" };

async function carregarModelos() {
  if (M.carregando) return;
  M.carregando = true;
  try {
    const r = await fetch("/api/modelos");
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "Não foi possível listar os modelos.");
    M.itens = j.modelos;
    M.total = j.total;
    desenharModelos();
  } catch (e) {
    $("modelos-lista").innerHTML = `<p class="vazio-lista">${esc(e.message)}</p>`;
  } finally {
    M.carregando = false;
  }
}
function desenharModelos() {
  const tipos = [...new Set(M.itens.map(i => i.tipo))].sort((a, b) => a.localeCompare(b));
  if (M.tipo && !tipos.includes(M.tipo)) M.tipo = "";
  $("modelos-tipo").innerHTML = `<option value="">Todos os tipos (${M.itens.length})</option>` + tipos.map(t => `<option value="${esc(t)}"${t === M.tipo ? " selected" : ""}>${esc(t)} (${M.itens.filter(i => i.tipo === t).length})</option>`).join("");
  const vistos = M.itens.filter(i => (!M.tipo || i.tipo === M.tipo) && (!M.soNaoUsados || i.uso !== "fixo"));
  const soma = vistos.reduce((s, i) => s + i.tamanho, 0);
  $("modelos-total").textContent = `${vistos.length} ${vistos.length === 1 ? "arquivo" : "arquivos"}, ${gb(soma)} GB` + (vistos.length < M.itens.length ? ` (de ${M.itens.length} arquivos, ${gb(M.total)} GB no total)` : "");
  $("modelos-lista").innerHTML = vistos.length ? vistos.map(desenharModelo).join("") : `<p class="vazio-lista">Nenhum arquivo com esse filtro.</p>`;
}
function desenharModelo(i) {
  const arquivo = i.caminho.split("/").pop();
  return `<article class="modelo" data-caminho="${esc(i.caminho)}">
    <div class="modelo-topo">
      <div class="modelo-nome"><strong>${esc(i.nome)}</strong><small>${esc(i.caminho)}</small></div>
      <span class="modelo-tamanho">${gb(i.tamanho)} GB</span>
    </div>
    <p><span class="uso uso-${i.uso}">${esc(ONDE_USO[i.uso](i))}</span>${i.serve_para ? ` <span class="legenda">Serve para: ${esc(i.serve_para)}</span>` : ""}</p>
    <p>${i.faz ? esc(i.faz) : `<span class="legenda">sem descrição</span>`}</p>
    ${i.testado ? `<p class="legenda">Testado: ${esc(i.testado)}</p>` : ""}
    ${i.nota ? `<p class="legenda">Nota: ${esc(i.nota)}</p>` : ""}
    <details class="modelo-editar"><summary>Editar nome e nota</summary>
      <label class="campo"><span class="rotulo">Nome</span><input type="text" maxlength="200" data-campo="nome" value="${esc(i.nome === arquivo ? "" : i.nome)}" placeholder="${esc(arquivo)}"></label>
      <label class="campo"><span class="rotulo">Nota</span><input type="text" maxlength="200" data-campo="nota" value="${esc(i.nota)}"></label>
      <div class="botoes"><button type="button" data-modelo="salvar">Salvar</button></div>
    </details>
    ${i.uso !== "fixo" ? `<div class="botoes"><button type="button" class="simples perigo" data-modelo="apagar">Apagar</button></div>` : ""}
  </article>`;
}
function textoApagar(i, tamanho) {
  let t = `Apagar "${i.nome}" (${gb(tamanho)} GB)? O arquivo não vai para a Lixeira e não dá para desfazer.`;
  if (i.uso === "opcao") t += " Ele some das opções da aba Continuar.";
  if (/^Fluxos? antigos?/i.test(i.serve_para)) t += " Os fluxos antigos da pasta workflows que o usam deixam de funcionar.";
  return t;
}
async function acaoModelo(botao) {
  const caixa = botao.closest("[data-caminho]"), caminho = caixa.dataset.caminho;
  const item = M.itens.find(i => i.caminho === caminho);
  botao.disabled = true;
  try {
    if (botao.dataset.modelo === "salvar") {
      await postar("/api/modelos/anotar", { caminho, nome: caixa.querySelector('[data-campo="nome"]').value, nota: caixa.querySelector('[data-campo="nota"]').value });
      recado("Anotação salva.", true);
      await carregarModelos();
    } else {
      const previa = await postar("/api/modelos/apagar", { caminho, confirmar: false });
      botao.disabled = false;
      if (!await perguntar(textoApagar(item, previa.tamanho), "Apagar de vez", "Cancelar")) return;
      botao.disabled = true;
      await postar("/api/modelos/apagar", { caminho, confirmar: true });
      recado(`Apagado: ${item.nome} (${gb(previa.tamanho)} GB).`, true);
      await carregarModelos();
    }
  } catch (e) {
    recado(e.message);
    // O arquivo pode ter sumido ou mudado: a lista nao pode continuar mostrando o que nao existe
    if (botao.dataset.modelo === "apagar") await carregarModelos();
  } finally {
    botao.disabled = false;
  }
}
$("modelos-tipo").addEventListener("change", e => { M.tipo = e.target.value; desenharModelos(); });
$("modelos-nao-usados").addEventListener("change", e => { M.soNaoUsados = e.target.checked; desenharModelos(); });
$("modelos-lista").addEventListener("click", e => {
  const b = e.target.closest("[data-modelo]");
  if (b) acaoModelo(b);
});
