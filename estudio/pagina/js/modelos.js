/* Modelos: o que ha na pasta models do ComfyUI, o que o aplicativo usa e o que pode ser apagado */
const M = { itens: null, total: 0, tipo: "", busca: "", ordem: "tamanho", agrupar: "tipo", abertos: new Set(), fechados: new Set(["fixo"]), carregando: false };
const gb = bytes => num(bytes / 2 ** 30, bytes >= 2 ** 30 ? 1 : 2);
const ONDE_USO = { fixo: i => `em uso: ${i.onde.join(", ")}`, opcao: () => "opção em Vídeo, Continuar", nenhum: () => "não usado pelo estúdio" };
/* A tela separa os arquivos pelo que importam a quem usa, não pela pasta: o que o estúdio precisa (sem Apagar, fechado
   ao abrir), o que é opção e o que só ocupa espaço. A pasta técnica vira um nome que se entende. */
const GRUPOS_MODELO = [
  ["nenhum", "Não usados pelo estúdio", "Nenhuma tela usa estes arquivos. Se você não os usa em fluxos próprios do ComfyUI, pode apagar para liberar espaço."],
  ["opcao", "Opções que você pode escolher", "Aparecem como escolha nas abas. Apagar um deles só tira essa opção da lista."],
  ["fixo", "O estúdio precisa destes", "As abas dependem deles para funcionar, por isso não têm o botão Apagar."],
];
const TIPOS_MODELO = { diffusion_models: "Modelo principal", checkpoints: "Modelo auxiliar", loras: "LoRA (estilo ou ajuste)", text_encoders: "Leitor de texto", vae: "Conversor de imagem (VAE)",
  vae_approx: "Prévia da geração", clip_vision: "Leitor de imagem", upscale_models: "Ampliador", latent_upscale_models: "Ampliador", mmaudio: "Som", background_removal: "Recorte de fundo",
  RMBG: "Recorte de fundo", model_patches: "Complemento de modelo" };
const tipoModelo = t => TIPOS_MODELO[t] || t;
// O que cada tipo faz, em uma frase, para quem nunca abriu a pasta models
const AJUDA_TIPO = {
  "Modelo principal": "É quem cria a imagem ou o vídeo. São os arquivos maiores.",
  "LoRA (estilo ou ajuste)": "Complemento pequeno que muda o estilo ou ensina algo ao modelo principal. As de aceleração e de troca o estúdio usa por conta própria.",
  "Leitor de texto": "Entende o que você escreve e passa para o modelo principal.",
  "Conversor de imagem (VAE)": "Transforma o resultado do modelo numa imagem ou vídeo que dá para ver.",
  "Ampliador": "Aumenta a resolução depois da geração.",
  "Som": "Cria som e efeitos para o vídeo.",
  "Recorte de fundo": "Separa a pessoa ou o objeto do fundo.",
  "Modelo auxiliar": "Ajuda em tarefas de apoio, como recortar pessoas e ler poses.",
  "Leitor de imagem": "Entende uma imagem de referência.",
  "Complemento de modelo": "Peça extra que guia o modelo principal (pose, estrutura).",
  "Prévia da geração": "Mostra a imagem se formando enquanto a geração roda.",
};
const ROTULO_USO = { fixo: "o estúdio precisa", opcao: "opção nas abas", nenhum: "não usado" };

async function carregarModelos() {
  if (M.carregando) return;
  M.carregando = true;
  try {
    const r = await fetch("/api/modelos");
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "Não foi possível listar os modelos.");
    // LoRA de estilo que aparece nas listas das abas de criar é uma opção, não um arquivo sem uso: o servidor só conhece
    // as do Continuar, então as outras são achadas aqui, pelas mesmas listas que as abas mostram
    const d = S.dados || {}, wan = d.opcoes?.loras_wan || [];
    const escolhiveis = new Set([...(d.opcoes?.loras_estilo || []), ...wan.flatMap(x => [x.alta, x.baixa]), ...(d.texto?.modelos || []).flatMap(m => m.loras || [])].map(n => n.toLowerCase()));
    M.itens = j.modelos.map(i => i.uso === "nenhum" && i.tipo === "loras" && escolhiveis.has(i.caminho.split("/").pop().toLowerCase()) ? { ...i, uso: "opcao" } : i);
    M.total = j.total;
    desenharModelos();
  } catch (e) {
    $("modelos-lista").innerHTML = `<p class="vazio-lista">${esc(e.message)}</p>`;
  } finally {
    M.carregando = false;
  }
}
const somaModelos = lista => lista.reduce((s, i) => s + i.tamanho, 0);
/* O resumo: quanto do disco é de cada grupo, numa barra, com a legenda que leva ao grupo */
function desenharResumoModelos() {
  const partes = GRUPOS_MODELO.map(([uso, nome]) => ({ uso, nome, itens: M.itens.filter(i => i.uso === uso) })).map(p => ({ ...p, bytes: somaModelos(p.itens) }));
  const livre = partes.find(p => p.uso === "nenhum");
  $("modelos-resumo").innerHTML = `<p class="resumo-titulo"><strong>${gb(M.total)} GB</strong> em ${M.itens.length} arquivos de modelo${livre.bytes ? `. <span>Até ${gb(livre.bytes)} GB podem ser liberados.</span>` : "."}</p>
    <div class="resumo-barra" aria-hidden="true">${partes.filter(p => p.bytes).map(p => `<span class="resumo-${p.uso}" style="flex:${p.bytes} 1 0"></span>`).join("")}</div>
    <div class="resumo-legenda">${partes.map(p => `<button type="button" data-ir-grupo="${p.uso}"><i class="resumo-${p.uso}"></i><span><b>${esc(p.nome)}</b><small>${gb(p.bytes)} GB · ${p.itens.length} ${p.itens.length === 1 ? "arquivo" : "arquivos"}</small></span></button>`).join("")}</div>`;
}
function desenharModelos() {
  const tipos = [...new Set(M.itens.map(i => tipoModelo(i.tipo)))].sort((a, b) => a.localeCompare(b));
  // Separando por tipo, o filtro de tipo não tem o que fazer: cada tipo já é uma seção
  $("modelos-tipo").closest(".campo").hidden = M.agrupar === "tipo";
  if (M.agrupar === "tipo" || (M.tipo && !tipos.includes(M.tipo))) M.tipo = "";
  $("modelos-tipo").innerHTML = `<option value="">Todos os tipos</option>` + tipos.map(t => `<option value="${esc(t)}"${t === M.tipo ? " selected" : ""}>${esc(t)} (${M.itens.filter(i => tipoModelo(i.tipo) === t).length})</option>`).join("");
  desenharResumoModelos();
  const busca = M.busca.trim().toLowerCase(), filtrando = !!(busca || M.tipo);
  const vistos = M.itens.filter(i => (!M.tipo || tipoModelo(i.tipo) === M.tipo) && (!busca || [i.nome, i.caminho, i.faz, i.serve_para].some(t => (t || "").toLowerCase().includes(busca))))
    .sort((a, b) => M.ordem === "nome" ? a.nome.localeCompare(b.nome) : b.tamanho - a.tamanho);
  $("modelos-total").textContent = filtrando ? `${vistos.length} de ${M.itens.length} arquivos, ${gb(somaModelos(vistos))} GB` : "";
  // Por tipo (o padrão): uma seção para cada tipo de arquivo, as maiores primeiro, fechadas até a pessoa abrir.
  // Por uso: os três grupos do resumo. Procurando, abrem todos: o que foi achado não pode ficar escondido.
  const porTipo = M.agrupar === "tipo";
  const grupos = porTipo ? [...new Set(vistos.map(i => tipoModelo(i.tipo)))].map(t => [t, t, AJUDA_TIPO[t] || ""]).sort((a, b) => somaModelos(vistos.filter(i => tipoModelo(i.tipo) === b[0])) - somaModelos(vistos.filter(i => tipoModelo(i.tipo) === a[0])))
    : GRUPOS_MODELO.map(([uso, nome, ajuda]) => [uso, nome, ajuda + (uso !== "fixo" ? " Apagar não manda para a Lixeira e não dá para desfazer." : "")]);
  $("modelos-lista").innerHTML = vistos.length ? grupos.map(([chave, nome, ajuda]) => {
    const itens = vistos.filter(i => (porTipo ? tipoModelo(i.tipo) : i.uso) === chave);
    const aberto = filtrando || (porTipo ? M.abertos.has(chave) : !M.fechados.has(chave));
    const livres = porTipo ? itens.filter(i => i.uso === "nenhum") : [];
    return itens.length ? `<details class="grupo-modelos" data-grupo="${esc(chave)}"${aberto ? " open" : ""}>
      <summary><span class="grupo-nome">${porTipo ? "" : `<i class="resumo-${chave}"></i>`}${esc(nome)}</span><span class="grupo-conta">${itens.length} ${itens.length === 1 ? "arquivo" : "arquivos"} · ${gb(somaModelos(itens))} GB${livres.length ? ` · ${livres.length} não ${livres.length === 1 ? "usado" : "usados"}` : ""}</span></summary>
      ${ajuda ? `<p class="ajuda">${esc(ajuda)}</p>` : ""}
      ${itens.map(desenharModelo).join("")}</details>` : "";
  }).join("") : `<p class="vazio-lista">Nenhum arquivo com esse filtro.</p>`;
}
function desenharModelo(i) {
  const arquivo = i.caminho.split("/").pop(), semNome = i.nome === arquivo;
  return `<article class="modelo" data-caminho="${esc(i.caminho)}">
    <div class="modelo-topo">
      <div class="modelo-nome"><strong>${esc(semNome ? semExt(arquivo) : i.nome)}</strong><small class="modelo-tipo">${M.agrupar === "tipo" ? `<i class="resumo-${i.uso}"></i>${esc(i.uso === "fixo" ? ONDE_USO.fixo(i) : ROTULO_USO[i.uso])}` : `${esc(tipoModelo(i.tipo))}${i.uso === "fixo" ? ` · ${esc(ONDE_USO.fixo(i))}` : ""}`}</small></div>
      <span class="modelo-tamanho">${gb(i.tamanho)} GB</span>
    </div>
    ${i.faz ? `<p>${esc(i.faz)}</p>` : ""}
    <details class="modelo-editar"><summary>Detalhes${i.uso !== "fixo" ? " e apagar" : ""}</summary>
      <dl class="modelo-ficha">
        <dt>Arquivo</dt><dd><code>models/${esc(i.caminho)}</code></dd>
        ${i.serve_para ? `<dt>Serve para</dt><dd>${esc(i.serve_para)}</dd>` : ""}
        ${i.testado ? `<dt>Testado</dt><dd>${esc(i.testado)}</dd>` : ""}
        ${i.nota ? `<dt>Nota</dt><dd>${esc(i.nota)}</dd>` : ""}
      </dl>
      <label class="campo"><span class="rotulo">Nome para mostrar</span><input type="text" maxlength="200" data-campo="nome" value="${esc(semNome ? "" : i.nome)}" placeholder="${esc(arquivo)}"></label>
      <label class="campo"><span class="rotulo">Nota</span><input type="text" maxlength="200" data-campo="nota" value="${esc(i.nota)}" placeholder="Para você lembrar para que serve"></label>
      <div class="botoes"><button type="button" data-modelo="salvar">Salvar nome e nota</button>${i.uso !== "fixo" ? `<button type="button" class="simples perigo" data-modelo="apagar">Apagar do disco (${gb(i.tamanho)} GB)</button>` : ""}</div>
    </details>
  </article>`;
}
function textoApagar(i, tamanho) {
  let t = `Apagar "${i.nome}" (${gb(tamanho)} GB)? O arquivo não vai para a Lixeira e não dá para desfazer.`;
  if (i.uso === "opcao") t += " Ele some das opções das abas.";
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
$("modelos-busca").addEventListener("input", e => { M.busca = e.target.value; desenharModelos(); });
$("modelos-ordem").addEventListener("change", e => { M.ordem = e.target.value; desenharModelos(); });
// Grupo aberto ou fechado fica como a pessoa deixou (o evento toggle não sobe: escuta na captura)
$("modelos-lista").addEventListener("toggle", e => {
  if (!e.target.matches?.("details.grupo-modelos") || M.busca.trim() || M.tipo) return;
  if (M.agrupar === "tipo") M.abertos[e.target.open ? "add" : "delete"](e.target.dataset.grupo);
  else M.fechados[e.target.open ? "delete" : "add"](e.target.dataset.grupo);
}, true);
$("modelos-agrupar").addEventListener("change", e => { M.agrupar = e.target.value; desenharModelos(); });
$("modelos-resumo").addEventListener("click", e => {
  const b = e.target.closest("[data-ir-grupo]");
  if (!b) return;
  // A legenda do resumo é por uso: leva à separação por uso, com o grupo aberto
  M.agrupar = $("modelos-agrupar").value = "uso";
  M.fechados.delete(b.dataset.irGrupo);
  M.busca = $("modelos-busca").value = "";
  M.tipo = "";
  desenharModelos();
  document.querySelector(`.grupo-modelos[data-grupo="${b.dataset.irGrupo}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" });
});
$("modelos-lista").addEventListener("click", e => {
  const b = e.target.closest("[data-modelo]");
  if (b) acaoModelo(b);
});
