/* Comportamento da janela: inspetor recolhivel, Gerar sempre ao alcance e um projeto aberto por vez no palco. */
const INSPETOR = "estudio_inspetor";
const telaAtiva = () => document.querySelector("form.tela:not([hidden])");

function mostrarInspetor(mostrar) {
  document.documentElement.classList.toggle("sem-inspetor", !mostrar);
  $("alternar-inspetor").setAttribute("aria-expanded", mostrar);
  try { localStorage.setItem(INSPETOR, mostrar ? "1" : "0"); } catch {}
  espelharGerar();
}
$("alternar-inspetor").setAttribute("aria-expanded", !document.documentElement.classList.contains("sem-inspetor"));
$("alternar-inspetor").addEventListener("click", () => mostrarInspetor(document.documentElement.classList.contains("sem-inspetor")));

/* Com o inspetor fechado, a barra mostra o botao principal da tela: mesmo texto, mesmo estado, mesmo clique */
function espelharGerar() {
  const tela = telaAtiva(), copia = $("barra-gerar");
  const real = tela?.querySelector('button[type="submit"]');
  copia.hidden = !real || !document.documentElement.classList.contains("sem-inspetor");
  if (!real) return;
  copia.textContent = real.textContent;
  copia.disabled = real.disabled;
  $("alternar-inspetor").setAttribute("aria-controls", tela.id);
}
$("barra-gerar").addEventListener("click", () => telaAtiva()?.querySelector('button[type="submit"]')?.click());
{
  const vigia = new MutationObserver(espelharGerar);
  document.querySelectorAll('form.tela button[type="submit"]').forEach(b => vigia.observe(b, { attributes: true, attributeFilter: ["disabled"], childList: true, characterData: true, subtree: true }));
  document.querySelectorAll("form.tela").forEach(f => vigia.observe(f, { attributes: true, attributeFilter: ["hidden"] }));
  espelharGerar();
}

/* Projetos: o aberto vai para o palco, entao abrir um fecha os outros */
document.addEventListener("toggle", e => {
  const p = e.target;
  if (!p.matches?.("details.projeto") || !p.open) return;
  document.querySelectorAll("details.projeto[open]").forEach(o => { if (o !== p) o.open = false; });
  carregarVideosAbertos();
}, true);
/* Na lista, ao entrar em Projetos sem nenhum aberto, abre o mais recente. Na galeria não: esconderia as capas */
new MutationObserver(() => {
  if ($("tela-projetos").hidden || document.querySelector("details.projeto[open]") || S.modoProjetos === "galeria") return;
  const primeiro = document.querySelector("details.projeto");
  if (primeiro) primeiro.open = true;
}).observe($("tela-projetos"), { attributes: true, attributeFilter: ["hidden"], childList: true, subtree: true });
/* Um erro do envio aparece no pe do inspetor: se ele estiver fechado, abre para o erro ser visto */
{
  const vigia = new MutationObserver(() => {
    if (document.documentElement.classList.contains("sem-inspetor") && document.querySelector('form.tela:not([hidden]) .lado-pe [role="alert"]:not([hidden])')) mostrarInspetor(true);
  });
  document.querySelectorAll('.lado-pe [role="alert"]').forEach(e => vigia.observe(e, { attributes: true, attributeFilter: ["hidden"] }));
}

/* Linha do tempo como controle de posicao: um cursor acompanha o video e arrastar ou clicar na fita leva o video ate ali.
   Vale no palco (Continuar e Troca) e no player do projeto aberto. A barra de tempo propria do navegador some nesses
   videos (estilo.css), para nao haver dois controles fazendo a mesma coisa.
   Enquanto toca, a etiqueta com o nome do arquivo sai da frente (volta ao pausar ou passar o mouse). */
function parFita(video) {
  if (!video) return null;
  const zona = video.closest(".palco");
  if (zona?.id === "zona-video") return { video, fita: $("fita"), trecho: $("fita").querySelector(".orig") };
  if (zona?.id === "zona-tvideo") return { video, fita: $("t-fita"), trecho: $("t-fita") };
  const corpo = video.closest(".corpo"), fita = corpo?.querySelector(".linha-tempo .fita");
  return fita ? { video, fita, trecho: fita } : null;
}
function videoDaFita(fita) {
  if (fita.id === "fita") return $("zona-video").querySelector(".midia video");
  if (fita.id === "t-fita") return $("zona-tvideo").querySelector(".midia video");
  return fita.closest(".corpo")?.querySelector(":scope > .midia video") || null;
}
function moverCursor(par) {
  const linha = par?.fita.closest(".linha-tempo");
  if (!linha) return;
  let cursor = linha.querySelector(".cursor-fita");
  if (!cursor) { cursor = document.createElement("i"); cursor.className = "cursor-fita"; cursor.setAttribute("aria-hidden", "true"); linha.append(cursor); }
  const { video, trecho } = par;
  // So mexe no atributo quando muda: o vigia abaixo observa "hidden" e nao pode entrar em laco
  const esconder = par.fita.hidden || !trecho || !(video.duration > 0);
  if (cursor.hidden !== esconder) cursor.hidden = esconder;
  if (esconder) return;
  const base = linha.getBoundingClientRect(), r = trecho.getBoundingClientRect();
  cursor.style.transform = `translateX(${(r.left - base.left + Math.min(1, video.currentTime / video.duration) * r.width).toFixed(1)}px)`;
}
const quadros = new WeakMap();
function seguirVideo(video) {
  cancelAnimationFrame(quadros.get(video));
  const passo = () => { moverCursor(parFita(video)); if (!video.paused && video.isConnected) quadros.set(video, requestAnimationFrame(passo)); };
  passo();
}
for (const tipo of ["play", "pause", "ended", "seeked", "loadedmetadata", "emptied", "timeupdate"]) {
  document.addEventListener(tipo, e => {
    const v = e.target;
    if (!(v instanceof HTMLVideoElement)) return;
    v.closest(".palco")?.classList.toggle("tocando", !v.paused && !v.ended);
    if (tipo !== "timeupdate" || v.paused) seguirVideo(v);
  }, true);
}
// Clicar ou arrastar na fita posiciona o video; o ponteiro fica preso a fita durante o arraste
document.addEventListener("pointerdown", e => {
  const fita = e.target.closest?.(".linha-tempo .fita");
  const video = fita && videoDaFita(fita), par = video && parFita(video);
  if (!par?.trecho || !(video.duration > 0)) return;
  const ir = x => { const r = par.trecho.getBoundingClientRect(); video.currentTime = Math.max(0, Math.min(1, (x - r.left) / r.width)) * video.duration; moverCursor(par); };
  if (par.trecho !== fita && !par.trecho.contains(e.target)) return;
  e.preventDefault();
  fita.setPointerCapture(e.pointerId);
  ir(e.clientX);
  const mover = m => ir(m.clientX), soltar = () => { fita.removeEventListener("pointermove", mover); fita.removeEventListener("pointerup", soltar); fita.removeEventListener("pointercancel", soltar); };
  fita.addEventListener("pointermove", mover);
  fita.addEventListener("pointerup", soltar);
  fita.addEventListener("pointercancel", soltar);
});
// A fita e redesenhada a cada mudanca no formulario e na lista de projetos, e a janela muda de largura: o cursor acompanha
function cursoresVisiveis() {
  document.querySelectorAll("#zona-video .midia video, #zona-tvideo .midia video, .projeto[open] > .corpo > .midia video").forEach(v => moverCursor(parFita(v)));
}
new MutationObserver(registros => {
  if (registros.every(r => r.target.classList?.contains("cursor-fita") || [...r.addedNodes].every(n => n.classList?.contains("cursor-fita")) && r.type === "childList" && !r.removedNodes.length)) return;
  cursoresVisiveis();
}).observe(document.querySelector(".area"), { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "open"] });
new ResizeObserver(cursoresVisiveis).observe(document.querySelector(".area"));

/* Menu do estúdio (24/11/2026): painel à esquerda, aberto pelo botão de menu do cabeçalho (popover: Esc e clique fora
   fecham sozinhos). Escolher um item fecha o menu; o que cada item faz continua no eventos.js. */
$("menu-estudio").addEventListener("click", e => { if (e.target.closest(".menu-item")) $("menu-estudio").hidePopover(); });
$("menu-estudio").addEventListener("toggle", e => $("menu-botao").setAttribute("aria-expanded", String(e.newState === "open")));

/* Cmd+Enter (Ctrl+Enter no Windows) dispara o botao principal da tela aberta */
document.addEventListener("keydown", e => {
  if (e.key !== "Enter" || !(e.metaKey || e.ctrlKey) || document.querySelector("dialog[open]")) return;
  const botao = telaAtiva()?.querySelector('button[type="submit"]');
  if (!botao || botao.disabled) return;
  e.preventDefault();
  botao.click();
});

/* Barra lateral: o botao encolhe para so os icones (fica salvo); abaixo de 1180px ela ja fica estreita sozinha */
const LATERAL = "estudio_lateral", janelaEstreita = matchMedia("(max-width: 1180px)");
function aplicarLateral() {
  const raiz = document.documentElement, recolhida = raiz.classList.contains("lateral-recolhida");
  raiz.classList.toggle("lateral-estreita", recolhida || janelaEstreita.matches);
  $("alternar-lateral").setAttribute("aria-expanded", !recolhida);
}
function alternarLateral() {
  if (janelaEstreita.matches) return;
  const recolher = !document.documentElement.classList.contains("lateral-recolhida");
  document.documentElement.classList.toggle("lateral-recolhida", recolher);
  try { localStorage.setItem(LATERAL, recolher ? "0" : "1"); } catch {}
  aplicarLateral();
}
$("alternar-lateral").addEventListener("click", alternarLateral);
janelaEstreita.addEventListener("change", aplicarLateral);
aplicarLateral();
document.addEventListener("keydown", e => {
  if (e.code !== "KeyS" || !e.ctrlKey || !e.altKey || e.metaKey || e.shiftKey || document.querySelector("dialog[open]")) return;
  e.preventDefault();
  alternarLateral();
});

/* Durante a geração, a tela que a disparou continua mostrando o que foi enviado, travada (sem edição), em vez de voltar
   ao padrão. Quando a geração termina, falha ou é parada, a tela destrava com os mesmos valores e um nome de projeto
   livre, pronta para mudar algo e gerar de novo. O nome enviado fica na sessionStorage para a trava sobreviver a um F5. */
const CAMPO_NOME = { novo: "projeto", troca: "t-projeto", trocafoto: "tf-projeto", imagem: "i-projeto", avancado: "av-projeto", texto: "t2i-projeto", editar: "e-projeto" };
S.enviado = (() => { try { return JSON.parse(sessionStorage.getItem("estudio-enviado")) || {}; } catch { return {}; } })();
function guardarEnviado() { try { sessionStorage.setItem("estudio-enviado", JSON.stringify(S.enviado)); } catch {} }
function marcarEnviado(modo, projeto) {
  // Chamado logo depois do envio, antes da consulta: com uma geração rodando, o pedido foi para a fila (fila.js)
  if (vaiParaFila()) recado(`${projeto} entrou na fila. Começa sozinho depois da geração atual.`, true);
  S.enviado[modo] = projeto; guardarEnviado();
}
function soltarTrava(modo) { delete S.enviado[modo]; guardarEnviado(); sincronizarTrava(modo); }
function sincronizarTrava(modo) {
  const enviado = S.enviado[modo], tar = S.dados?.tarefa;
  let travada = false;
  // Só decide quando o servidor já mostra esta geração: antes disso a tarefa ainda pode ser a anterior
  if (enviado && tar?.projeto === enviado) {
    if (tar.rodando) travada = true;
    else {
      delete S.enviado[modo];
      guardarEnviado();
      const campo = $(CAMPO_NOME[modo]);
      campo.value = nomeLivre((campo.value || enviado).replace(/_\d+$/, ""));
    }
  }
  const tela = $(`tela-${modo}`);
  if (tela.classList.contains("travada") !== travada) {
    tela.classList.toggle("travada", travada);
    if (S.aba === modo) $("limpar-tudo").disabled = travada;
    // inert e não disabled: a coluna continua rolando e os estados de cada controle ficam como estavam
    // A tira "Feitos" trava junto: a prévia dela abre dentro do bloco do palco, que está inerte
    tela.querySelectorAll(".centro > :not(#andamento), .lado-corpo > *, .lado-pe > .marcar, :scope > .tira").forEach(el => { el.inert = travada; });
  }
  return travada;
}
function notaTravada(modo) {
  return `<p class="nota-travada" title="Projeto ${esc(S.enviado[modo])}">Gerando com estes ajustes. Quando terminar, dá para mudar o que quiser e gerar de novo.</p>
    <button type="button" class="simples" onclick="prepararOutro('${modo}')">Preparar outro pedido para a fila</button>`;
}
