/* Palavras-chave das LoRAs (aba Modelos, segunda visão): cada LoRA instalada, a palavra-chave que vale para ela, de onde
   veio (você, o cadastro do estúdio ou a ficha do Civitai) e como entra no texto. Servidor: palavras_lora.py. */
const L = { itens: null, pendentes: 0, pasta: "", busca: "", soCom: false, aberta: null, carregando: false, relogio: null, visao: "arquivos" };
const ORIGEM_LORA = { meu: "editado por você", estudio: "cadastro do estúdio", ficha: "da ficha do Civitai", nenhuma: "sem palavra-chave" };
const MODOS_LORA = [
  ["fixa", "Entra sozinha no texto", "O estúdio escreve a palavra no começo do texto em toda geração com esta LoRA. Você não precisa lembrar."],
  ["aviso", "Só me avisa", "Para palavras que dependem da cena. Você escreve a que combina e o estúdio avisa enquanto nenhuma estiver no texto."],
  ["nenhuma", "Não usar palavra-chave", "A LoRA entra sem palavra e sem aviso."],
];

function verNosModelos(visao) {
  L.visao = visao;
  $("modelos-ver-arquivos").setAttribute("aria-pressed", visao === "arquivos");
  $("modelos-ver-loras").setAttribute("aria-pressed", visao === "loras");
  $("modelos-arquivos").hidden = visao !== "arquivos";
  $("modelos-loras").hidden = visao !== "loras";
  if (visao === "loras") carregarLoras();
  else clearTimeout(L.relogio);
}
/* A lista não é redesenhada por baixo de quem está editando: enquanto um "Editar" está aberto, só o contador muda */
async function carregarLoras(forcar = false) {
  if (L.carregando) return;
  L.carregando = true;
  clearTimeout(L.relogio);
  try {
    const r = await fetch("/api/loras");
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "Não foi possível listar as LoRAs.");
    const editando = !!$("loras-lista").querySelector("details[open]");
    L.itens = j.loras;
    L.pendentes = j.pendentes;
    if (forcar || !editando) desenharLoras();
    else contarLoras();
  } catch (e) {
    if (!L.itens) $("loras-lista").innerHTML = `<p class="vazio-lista">${esc(e.message)}</p>`;
  } finally {
    L.carregando = false;
    // Enquanto há fichas por consultar, a tela se atualiza sozinha
    if (L.visao === "loras" && S.aba === "modelos" && L.pendentes) L.relogio = setTimeout(carregarLoras, 5000);
  }
}
function lorasVistas() {
  const busca = L.busca.trim().toLowerCase();
  return L.itens.filter(i => (!L.pasta || i.pasta === L.pasta) && (!L.soCom || i.modo !== "nenhuma")
    && (!busca || i.nome.toLowerCase().includes(busca) || i.palavras.some(p => p.toLowerCase().includes(busca)) || i.ficha.modelo.toLowerCase().includes(busca)));
}
function contarLoras() {
  const vistas = lorasVistas(), com = L.itens.filter(i => i.modo !== "nenhuma").length;
  $("loras-total").textContent = `${vistas.length} de ${L.itens.length} LoRAs, ${com} com palavra-chave` + (L.pendentes ? `. Consultando a ficha de ${L.pendentes}…` : "");
  return vistas;
}
function desenharLoras() {
  const pastas = [...new Set(L.itens.map(i => i.pasta))].sort((a, b) => a.localeCompare(b));
  if (L.pasta && !pastas.includes(L.pasta)) L.pasta = "";
  $("loras-pasta").innerHTML = `<option value="">Todas as pastas (${L.itens.length})</option>` + pastas.map(p => `<option value="${esc(p)}"${p === L.pasta ? " selected" : ""}>${esc(p || "raiz da pasta loras")} (${L.itens.filter(i => i.pasta === p).length})</option>`).join("");
  const vistas = contarLoras();
  $("loras-lista").innerHTML = vistas.length ? vistas.map(desenharLora).join("") : `<p class="vazio-lista">${L.itens.length ? "Nenhuma LoRA com esse filtro." : "Nenhuma LoRA de estilo na pasta models/loras do ComfyUI."}</p>`;
}
const chipsLora = palavras => palavras.map(p => `<code>${esc(p)}</code>`).join(" ");
function resumoLora(i) {
  if (i.modo === "fixa") return `<span class="lora-como lora-fixa">Entra sozinha no texto</span> ${chipsLora(i.palavras)}`;
  if (i.modo === "aviso") return `<span class="lora-como lora-aviso">${i.opcional ? "Ajuda, sem ser obrigatória" : "Você escreve, o estúdio avisa"}</span> ${chipsLora(i.palavras)}`;
  if (i.origem === "meu") return `<span class="legenda">Você marcou que esta LoRA não usa palavra-chave.</span>`;
  const f = i.ficha.estado;
  return `<span class="legenda">${f === "pendente" ? "Consultando a ficha no Civitai…" : f === "erro" ? "Não consegui consultar a ficha (sem internet?). Tente em Editar, \"Consultar a ficha de novo\"."
    : f === "nao_achou" ? "Esta LoRA não está no Civitai. Se ela pede palavra-chave, escreva em Editar." : "A ficha no Civitai não cita palavra-chave."}</span>`;
}
function desenharLora(i) {
  const daFicha = i.ficha.palavras, difere = daFicha.length && JSON.stringify(daFicha) !== JSON.stringify(i.palavras);
  const ficha = i.ficha.modelo ? `Ficha: ${esc(i.ficha.modelo)}${i.ficha.versao ? ` · ${esc(i.ficha.versao)}` : ""}` : "";
  const pagina = i.pagina ? `<a href="${esc(i.pagina)}" target="_blank" rel="noopener">Ver a página</a>` : "";
  const id = `lora-${i.nome.replace(/[^A-Za-z0-9]/g, "_")}`;
  return `<article class="modelo lora" data-lora="${esc(i.nome)}">
    <div class="modelo-topo">
      <div class="modelo-nome"><strong>${esc(semExt(i.nome))}</strong><small>${esc(i.pasta ? `loras/${i.pasta}` : "loras")}</small></div>
      <span class="uso ${i.origem === "meu" ? "uso-opcao" : i.origem === "nenhuma" ? "" : "uso-fixo"}">${ORIGEM_LORA[i.origem]}</span>
    </div>
    <p class="lora-resumo">${resumoLora(i)}</p>
    ${i.nota ? `<p class="legenda">${esc(i.nota)}</p>` : ""}
    ${ficha || pagina ? `<p class="legenda">${[ficha, pagina].filter(Boolean).join(" · ")}</p>` : ""}
    <details class="modelo-editar lora-editar"${L.aberta === i.nome ? " open" : ""}><summary>Editar palavras-chave</summary>
      <label class="campo" for="${id}-palavras"><span class="rotulo">Palavras-chave</span>
        <textarea id="${id}-palavras" data-campo="palavras" rows="${Math.min(6, Math.max(2, i.palavras.length))}" spellcheck="false" placeholder="uma por linha">${esc(i.palavras.join("\n"))}</textarea>
        <span class="ajuda">Uma por linha. Pode ser uma palavra ou uma frase.</span></label>
      ${difere ? `<p class="lora-da-ficha"><span class="legenda">Na ficha do Civitai:</span> ${chipsLora(daFicha)} <button type="button" class="simples" data-lora-acao="usar-ficha">Usar as da ficha</button></p>` : ""}
      <fieldset class="lora-modos"><legend class="rotulo">Como entra no texto</legend>
        ${MODOS_LORA.map(([valor, nome, ajuda]) => `<label class="lora-modo"><input type="radio" name="${id}-modo" value="${valor}"${i.modo === valor ? " checked" : ""}><span><b>${nome}</b><small>${ajuda}</small></span></label>`).join("")}
      </fieldset>
      <label class="campo"><span class="rotulo">Nota <span class="opcional">opcional</span></span><input type="text" maxlength="300" data-campo="nota" value="${esc(i.nota)}" placeholder="Ex.: força de 0,6 a 0,8"></label>
      <div class="botoes">
        <button type="button" class="principal" data-lora-acao="salvar">Salvar</button>
        ${i.origem === "meu" ? `<button type="button" data-lora-acao="restaurar" title="Apaga o que você editou e volta ao cadastro do estúdio ou à ficha">Voltar ao original</button>` : ""}
        <button type="button" class="simples" data-lora-acao="consultar">Consultar a ficha de novo</button>
      </div>
    </details>
  </article>`;
}
async function acaoLora(botao) {
  const caixa = botao.closest("[data-lora]"), nome = caixa.dataset.lora, acao = botao.dataset.loraAcao;
  const item = L.itens.find(i => i.nome === nome), texto = caixa.querySelector('[data-campo="palavras"]');
  if (acao === "usar-ficha") {
    texto.value = item.ficha.palavras.join("\n");
    const marcado = caixa.querySelector('input[type="radio"]:checked');
    if (!marcado || marcado.value === "nenhuma") caixa.querySelector('input[type="radio"][value="aviso"]').checked = true;
    return texto.focus();
  }
  botao.disabled = true;
  try {
    if (acao === "salvar") {
      const modo = caixa.querySelector('input[type="radio"]:checked')?.value;
      const palavras = texto.value.split("\n").map(p => p.trim()).filter(Boolean);
      await postar("/api/loras/salvar", { nome, modo, palavras, nota: caixa.querySelector('[data-campo="nota"]').value });
      recado(modo === "fixa" ? `Salvo: ${palavras.join(", ")} entra sozinha no texto com ${semExt(nome)}.` : modo === "aviso" ? `Salvo: o estúdio avisa a palavra-chave de ${semExt(nome)}.` : `Salvo: ${semExt(nome)} sem palavra-chave.`, true);
      L.aberta = null;
    } else if (acao === "restaurar") {
      await postar("/api/loras/restaurar", { nome });
      recado(`${semExt(nome)} voltou ao original.`, true);
      L.aberta = null;
    } else {
      botao.textContent = "Consultando…";
      await postar("/api/loras/consultar", { nome });
      L.aberta = nome;
    }
    await carregarLoras(true);
  } catch (e) {
    recado(e.message);
    botao.disabled = false;
    if (acao === "consultar") botao.textContent = "Consultar a ficha de novo";
  }
}
/* Do aviso de uma aba de criar ("Editar") direto para a LoRA, já aberta para edição */
function editarLora(nome) {
  L.aberta = nome;
  L.pasta = "";
  L.busca = $("loras-busca").value = "";
  L.soCom = $("loras-so-com").checked = false;
  irPara("modelos");
  verNosModelos("loras");
  carregarLoras(true).then(() => document.querySelector(`[data-lora="${CSS.escape(nome)}"]`)?.scrollIntoView({ block: "center" }));
}
$("modelos-ver-arquivos").addEventListener("click", () => verNosModelos("arquivos"));
$("modelos-ver-loras").addEventListener("click", () => verNosModelos("loras"));
$("loras-pasta").addEventListener("change", e => { L.pasta = e.target.value; desenharLoras(); });
$("loras-busca").addEventListener("input", e => { L.busca = e.target.value; desenharLoras(); });
$("loras-so-com").addEventListener("change", e => { L.soCom = e.target.checked; desenharLoras(); });
$("loras-lista").addEventListener("click", e => {
  const b = e.target.closest("[data-lora-acao]");
  if (b) acaoLora(b);
});
// Qual "Editar" está aberto, para reabrir o mesmo depois de redesenhar (o evento toggle não sobe: escuta na captura)
$("loras-lista").addEventListener("toggle", e => {
  const caixa = e.target.closest?.("[data-lora]");
  if (!caixa || !e.target.matches("details.lora-editar")) return;
  if (e.target.open) L.aberta = caixa.dataset.lora;
  else if (L.aberta === caixa.dataset.lora) L.aberta = null;
}, true);
document.addEventListener("click", e => {
  const a = e.target.closest("[data-editar-lora]");
  if (a) { e.preventDefault(); editarLora(a.dataset.editarLora); }
});
