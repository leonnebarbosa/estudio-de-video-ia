/* Fila de gerações (fila.py no servidor). Com uma geração rodando, o botão de gerar vira "Pôr na fila": o pedido é
   conferido na hora e começa sozinho depois da atual, com 15 s entre uma e outra. Se uma falhar ou for parada, a fila
   pausa e diz por quê. O painel fica logo abaixo da caixa de andamento, em todas as abas de geração. */
const NOMES_TIPO_FILA = { troca: "Trocar personagem", imagem: "Imagem para vídeo", texto: "Texto para imagem", wan: "Imagem para vídeo (Wan)",
                          continuar: "Continuar vídeo", personagem: "Ângulos de personagem" };
/* Um pedido novo vai para a fila? (o servidor decide igual: tarefa._pedir) */
const vaiParaFila = () => !!S.dados?.tarefa?.rodando || (!!S.dados?.fila?.itens?.length && !S.dados.fila.pausada);
/* Troca o texto do botão para "Pôr na fila" enquanto houver fila; o texto de antes volta quando ela acaba. Chamar depois de
   quem escreve o texto do botão (texto.js e trocafoto.js mudam o texto pela quantidade). */
function rotuloFila(...botoes) {
  for (const b of botoes) {
    if (vaiParaFila()) {
      if (b.textContent !== "Pôr na fila") b.dataset.rotulo = b.textContent;
      b.textContent = "Pôr na fila";
    } else if (b.textContent === "Pôr na fila") b.textContent = b.dataset.rotulo || b.textContent;
  }
}
function nomeTipoFila(i) {
  if (i.tipo === "imagem" && i.modo === "acabar") return "Acabamento";
  if (i.tipo === "continuar") return i.modo === "plano" ? "Plano do vídeo" : i.modo === "juntar" ? "Juntar as rodadas" : "Continuar vídeo";
  return NOMES_TIPO_FILA[i.tipo] || i.tipo;
}
function situacaoFila(f, t) {
  if (f.pausada) return f.motivo || "Pausada.";
  if (t?.rodando) return `Começa depois de ${t.projeto}, com ${f.intervalo} s de intervalo.`;
  if (f.proxima_em != null) return `Próximo em ${f.proxima_em} s.`;
  return "Esperando o ComfyUI ficar livre.";
}
function desenharFila(d) {
  const f = d.fila, caixa = $("fila-painel");
  if (!f || !f.itens.length) { caixa.hidden = true; caixa.innerHTML = ""; S.marcaFila = ""; return; }
  caixa.hidden = false;
  const situacao = situacaoFila(f, d.tarefa);
  const marca = JSON.stringify([f.pausada, f.motivo, f.itens.map(i => i.id), !!d.tarefa?.rodando]);
  if (marca === S.marcaFila) { const s = caixa.querySelector(".fila-situacao"); if (s && s.textContent !== situacao) s.textContent = situacao; return; }
  S.marcaFila = marca;
  const n = f.itens.length;
  caixa.innerHTML = `<div class="fila-topo"><div><p class="fila-titulo">Fila <span>${n === 1 ? "1 pedido" : `${n} pedidos`}</span></p><p class="fila-situacao${f.pausada ? " pausada" : ""}">${esc(situacao)}</p></div>
      <button type="button" class="${f.pausada ? "principal" : "simples"}" data-fila="${f.pausada ? "continuar" : "pausar"}">${f.pausada ? "Continuar a fila" : "Pausar a fila"}</button></div>
    <ol class="fila-lista">${f.itens.map((i, k) => `<li data-id="${esc(i.id)}"><span class="fila-pos">${k + 1}</span><div class="fila-nome"><strong>${esc(i.projeto)}</strong><small>${esc(nomeTipoFila(i))}</small></div>
      <div class="fila-botoes"><button type="button" class="simples" data-fila="subir"${k === 0 ? " disabled" : ""} aria-label="Subir ${esc(i.projeto)} na fila">↑</button><button type="button" class="simples" data-fila="descer"${k === n - 1 ? " disabled" : ""} aria-label="Descer ${esc(i.projeto)} na fila">↓</button><button type="button" class="simples" data-fila="tirar">Tirar</button></div></li>`).join("")}</ol>`;
}
async function acaoFila(botao) {
  const acao = botao.dataset.fila, li = botao.closest("[data-id]");
  botao.disabled = true;
  try {
    await postar("/api/fila", { acao, ...(li ? { id: li.dataset.id } : {}) });
    if (acao === "tirar") recado(`${li.querySelector("strong").textContent} saiu da fila. O projeto continua na lista, sem gerar.`, true);
  } catch (e) { recado(e.message); }
  S.marcaFila = "";
  await consultar(true);
}
$("fila-painel").addEventListener("click", e => { const b = e.target.closest("[data-fila]"); if (b) acaoFila(b); });
/* Na tela travada (a geração dela rodando): destrava com um nome livre para montar outro pedido para a fila */
function prepararOutro(modo) {
  const campo = $(CAMPO_NOME[modo]), base = (campo.value || S.enviado[modo] || "").replace(/_\d+$/, "");
  soltarTrava(modo);
  campo.value = nomeLivre(base);
  atualizar();
}
