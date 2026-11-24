/* Prompt livre e referências nomeadas. A tradução para as tags do H3 é feita no servidor. */
const RASCUNHO_AVANCADO = "video_avancado_rascunho";
const AV = { refs: [], enviando: false, iniciando: false, versao: 0, opcoes: "" };
const TIPOS_AV = { foto: "imagem", video: "vídeo", audio: "áudio" };
const NOME_REF_AV = /^[a-z][a-z0-9_-]{0,31}$/i;
const DEFAULT_FORMATO_AV = "16:9 (Widescreen)";
const REF_POR_LINHA_AV = new WeakMap();
let proximaPreviaAvancada = 0;

function tipoArquivoAvancado(nome) {
  if (/\.(png|jpe?g|webp)$/i.test(nome)) return "foto";
  if (/\.mp4$/i.test(nome)) return "video";
  if (/\.(mp3|wav|m4a|ogg|flac|aac)$/i.test(nome)) return "audio";
  return null;
}

function nomeReferenciaAvancado(tipo) {
  const base = { foto: "imagem", video: "video", audio: "audio" }[tipo];
  let i = 1;
  while (AV.refs.some(r => r.nome.toLowerCase() === base + i)) i++;
  return base + i;
}

function lerAvancado() {
  return { prompt: $("av-prompt").value, referencias: AV.refs, proporcao: $("av-proporcao").value,
    megapixels: Number($("av-megapixels").value), duracao: Number($("av-duracao").value), semente: $("av-semente").value,
    projeto: $("av-projeto").value };
}

function salvarRascunhoAvancado() {
  const rascunho = lerAvancado();
  try { localStorage.setItem(RASCUNHO_AVANCADO, JSON.stringify(rascunho)); } catch {}
}

function aplicarAvancado(r = {}) {
  AV.versao++;
  $("av-prompt").value = r.prompt || "";
  $("av-proporcao").value = r.proporcao || DEFAULT_FORMATO_AV;
  const m = modeloImagem("h3"), mp = Number(r.megapixels ?? m.padrao.megapixels), lista = opcoesQualidade(m, mp, true);
  $("av-megapixels").innerHTML = lista.map(q => `<option value="${q}">${esc(nomeQualidade(q, m, true))}</option>`).join("");
  $("av-megapixels").value = lista.includes(mp) ? mp : m.padrao.megapixels;
  duracoesAvancado(r.duracao ?? 5);
  $("av-semente").value = r.semente ?? "";
  $("av-projeto").value = r.projeto ?? nomeLivre("video_avancado");
  $("av-erro").hidden = $("av-arquivo-erro").hidden = true;
  AV.refs = Array.isArray(r.referencias) ? r.referencias.filter(ref => ref && Object.hasOwn(TIPOS_AV, ref.tipo)
    && typeof ref.nome === "string" && typeof ref.arquivo === "string") : [];
  desenharRefsAvancado();
  sincronizarControles();
}

function restaurarAvancado() {
  let r;
  try { r = JSON.parse(localStorage.getItem(RASCUNHO_AVANCADO)); } catch {}
  aplicarAvancado(r || {});
}

function limparAvancado() {
  soltarTrava("avancado");
  aplicarAvancado();
  try { localStorage.removeItem(RASCUNHO_AVANCADO); } catch {}
}

function duracoesAvancado(escolhida) {
  const m = modeloImagem("h3");
  const duracoes = duracoesTomada(m, Number($("av-megapixels").value), 0);
  const sel = $("av-duracao");
  porHtml(sel, duracoes.map(s => `<option value="${s}">${num(s, 2)} s</option>`).join(""));
  sel.value = duracoes.includes(Number(escolhida)) ? escolhida : duracoes.at(-1);
}

function preencherAvancado(d) {
  const m = modeloImagem("h3");
  const marca = JSON.stringify([d.proporcoes, m.duracoes, m.qualidades, m.duracao_max_por_mp]);
  if (AV.opcoes === marca) return;
  const anterior = AV.opcoes ? lerAvancado() : {};
  AV.opcoes = marca;
  $("av-prompt").maxLength = d.avancado?.max_prompt || 8000;
  $("av-proporcao").innerHTML = d.proporcoes.map(p => `<option value="${esc(p)}">${esc(nomeProporcao(p))}</option>`).join("");
  // O Vídeo avançado mostra todas as resoluções aceitas, em MP
  const lista = opcoesQualidade(m, anterior.megapixels, true);
  $("av-megapixels").innerHTML = lista.map(mp => `<option value="${mp}">${esc(nomeQualidade(mp, m, true))}</option>`).join("");
  $("av-proporcao").value = anterior.proporcao || DEFAULT_FORMATO_AV;
  $("av-megapixels").value = lista.includes(anterior.megapixels) ? anterior.megapixels : m.padrao.megapixels;
  duracoesAvancado(anterior.duracao ?? 5);
  sincronizarControles();
}

function enderecoReferenciaAvancado(r) {
  return `/entrada/${r.tipo}/${encodeURIComponent(r.arquivo)}`;
}

function criarLinhaReferenciaAvancado(r) {
  const src = enderecoReferenciaAvancado(r), nome = esc(r.arquivo);
  const id = `av-previa-${++proximaPreviaAvancada}`;
  const icone = r.tipo === "foto" ? "s-ampliar" : "s-play";
  const acao = { foto: "Ver imagem", video: "Reproduzir vídeo", audio: "Ouvir áudio" }[r.tipo];
  const miniatura = {
    foto: `<img src="${src}" loading="lazy" alt="">`,
    video: `<video src="${src}#t=0.1" data-capa muted playsinline preload="none"></video>`,
    audio: '<svg class="ico avancado-onda"><use href="#s-audio"/></svg>'
  }[r.tipo];
  const linha = document.createElement("li");
  linha.innerHTML = `<button class="avancado-gatilho" type="button" data-av-abrir="${acao}" aria-expanded="false" aria-controls="${id}" aria-label="${acao} · ${nome}" title="${acao} · ${nome}">
      <span class="avancado-miniatura${r.tipo === "audio" ? "" : " midia"}" data-rotulo="Oculta" aria-hidden="true">${miniatura}
        <span class="avancado-acao">
          <svg class="ico"><use href="#${icone}"/></svg>
          <svg class="ico"><use href="#s-fechar"/></svg>
        </span>
      </span>
      <span class="avancado-arquivo">${nome}</span>
    </button>
    <label class="avancado-alias"><span aria-hidden="true">@</span><input type="text" data-av-nome value="${esc(r.nome)}" maxlength="32" spellcheck="false" aria-label="Nome no prompt para ${nome}"></label>
    <button class="simples" type="button" data-av-inserir aria-label="Inserir referência de ${nome} no prompt">Inserir</button>
    <button class="simples tirar-x" type="button" data-av-tirar aria-label="Remover referência de ${nome}">Remover</button>
    <div class="avancado-previa" id="${id}" hidden></div>`;
  REF_POR_LINHA_AV.set(linha, r);
  return linha;
}

function fecharPreviaReferenciaAvancado(painel = $("av-lista").querySelector(".avancado-previa:not([hidden])")) {
  if (!painel || painel.hidden) return;
  const player = painel.querySelector("video, audio");
  if (player) {
    player.pause();
    player.removeAttribute("src");
    player.load();
  }
  painel.hidden = true;
  painel.replaceChildren();
  const botao = painel.parentElement.querySelector("[data-av-abrir]");
  const r = REF_POR_LINHA_AV.get(painel.parentElement);
  botao.setAttribute("aria-expanded", "false");
  botao.title = `${botao.dataset.avAbrir} · ${r.arquivo}`;
  botao.setAttribute("aria-label", botao.title);
}

function alternarPreviaReferenciaAvancado(botao, r) {
  if (r.tipo !== "audio" && document.documentElement.classList.contains("ocultar")) {
    recado("Mostre as mídias no ícone de olho para abrir a prévia.");
    return;
  }
  const painel = $(botao.getAttribute("aria-controls"));
  const abrir = painel.hidden;
  fecharPreviaReferenciaAvancado();
  if (!abrir) return;
  const el = document.createElement(r.tipo === "foto" ? "img" : r.tipo);
  const erro = document.createElement("p");
  erro.className = "ajuda";
  erro.setAttribute("role", "status");
  erro.hidden = true;
  el.addEventListener("error", () => {
    el.hidden = true;
    erro.hidden = false;
    erro.textContent = "Não foi possível abrir esta prévia no navegador.";
  }, { once: true });
  if (r.tipo === "foto") el.alt = r.arquivo;
  else {
    el.controls = true;
    el.setAttribute("aria-label", r.arquivo);
    if (r.tipo === "video") el.playsInline = true;
  }
  painel.append(el, erro);
  painel.hidden = false;
  botao.setAttribute("aria-expanded", "true");
  botao.title = `Fechar prévia · ${r.arquivo}`;
  botao.setAttribute("aria-label", botao.title);
  el.src = enderecoReferenciaAvancado(r);
  if (r.tipo !== "foto") el.play().catch(() => {});
}

function desenharRefsAvancado() {
  const lista = $("av-lista");
  const presentes = new Set();
  for (const linha of [...lista.children]) {
    const ref = REF_POR_LINHA_AV.get(linha);
    if (AV.refs.includes(ref)) presentes.add(ref);
    else {
      fecharPreviaReferenciaAvancado(linha.querySelector(".avancado-previa"));
      const capa = linha.querySelector("video[data-capa]");
      if (capa) vigiaCapas?.unobserve(capa);
      linha.remove();
    }
  }
  // Preserva a mídia aberta e o foco de uma linha enquanto chegam novos arquivos.
  for (const ref of AV.refs) {
    if (presentes.has(ref)) continue;
    const linha = criarLinhaReferenciaAvancado(ref);
    lista.append(linha);
    observarCapas(linha);
  }
  $("av-vazio").hidden = AV.refs.length > 0;
  $("av-video-ajuda").hidden = !AV.refs.some(r => r.tipo === "video");
  $("av-audio-ajuda").hidden = !AV.refs.some(r => r.tipo === "audio");
  marcarMencoesAvancadas();
  if (!MENU_AV.hidden) atualizarMencoesAvancadas();
}

function erroReferenciasAvancado(prompt, refs) {
  const nomes = new Set();
  const numeros = { foto: 0, video: 0, audio: 0 };
  const rotulos = { foto: "Picture", video: "Video", audio: "Audio" };
  const tags = new Set();
  for (const r of refs) {
    const nome = r.nome.trim().toLowerCase();
    if (!NOME_REF_AV.test(nome)) return "Cada referência precisa de um nome com letras sem acento, números, _ ou -.";
    if (nomes.has(nome)) return `Há duas referências chamadas @${nome}.`;
    nomes.add(nome);
    tags.add(`<${rotulos[r.tipo]} ${++numeros[r.tipo]}>`);
  }
  for (const m of prompt.matchAll(MENCAO_AV)) {
    if (!nomes.has(m[1].toLowerCase())) return `Adicione a referência @${m[1]}.`;
  }
  for (const m of prompt.matchAll(/<(?:Picture|Video|Audio) \d+>/g)) {
    if (!tags.has(m[0])) return `Adicione a referência ${m[0]}.`;
  }
  return "";
}

function atualizarAvancado() {
  if (!AV.opcoes) return;
  const d = S.dados, travada = sincronizarTrava("avancado"), r = lerAvancado();
  const falta = [];
  if (!r.prompt.trim()) falta.push("Escreva o prompt");
  if (!r.referencias.length) falta.push("Adicione uma referência");
  const erroRef = erroReferenciasAvancado(r.prompt, r.referencias);
  if (erroRef) falta.push(erroRef);
  if (!/^[A-Za-z0-9_-]{1,60}$/.test(r.projeto)) falta.push("Confira o nome do projeto");
  else if (d.projetos.some(p => p.nome === r.projeto)) falta.push("Já existe um projeto com este nome");
  if (!d.avancado) falta.push("Reabra o Estúdio para carregar o modo avançado");
  const arquivos = d.avancado?.faltam || [];
  $("av-modelo-ajuda").hidden = !arquivos.length;
  $("av-modelo-ajuda").textContent = arquivos.length ? `Faltam ${arquivos.length} arquivos. Em Modelos, baixe o pacote Continuar e trocar personagem.` : "";
  if (arquivos.length) falta.push("Faltam modelos do H3 ref2va");
  if (AV.enviando) falta.push("Enviando referências");
  if (!vaiParaFila()) {
    if (!d.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto");
    else if (d.comfy.ocupado) falta.push("O ComfyUI está ocupado");
  }
  $("av-adicionar").disabled = AV.enviando || travada || AV.iniciando;
  $("av-gerar").disabled = !!falta.length || travada || AV.iniciando;
  $("av-tamanho").textContent = resolucao(r);
  porHtml($("av-falta"), travada ? notaTravada("avancado") : htmlFalta(falta));
  rotuloFila($("av-gerar"));
  salvarRascunhoAvancado();
}

async function enviarRefsAvancado(arquivos) {
  if ($("av-adicionar").disabled || !arquivos.length) return;
  const versao = AV.versao, erros = [], limites = S.dados?.avancado?.limites || { foto: 9, video: 3, audio: 3 };
  const status = $("av-envio");
  AV.enviando = true;
  $("av-arquivo-erro").hidden = true;
  status.hidden = false;
  atualizarAvancado();
  try {
    for (const f of arquivos) {
      const tipo = tipoArquivoAvancado(f.name);
      if (!tipo) { erros.push(`Formato desconhecido: ${f.name}.`); continue; }
      if (AV.refs.filter(r => r.tipo === tipo).length >= limites[tipo]) {
        erros.push(`Limite de referências para ${TIPOS_AV[tipo]} atingido.`);
        continue;
      }
      status.textContent = `Enviando ${f.name}…`;
      try {
        const r = await enviar(f, tipo, p => { status.textContent = `Enviando ${f.name}… ${Math.round(p * 100)}%`; });
        if (versao !== AV.versao) break;
        AV.refs.push({ tipo, arquivo: r.arquivo, nome: nomeReferenciaAvancado(tipo) });
        desenharRefsAvancado();
        salvarRascunhoAvancado();
      } catch (e) {
        if (versao !== AV.versao) break;
        erros.push(e.message);
      }
    }
  } finally {
    AV.enviando = false;
    status.hidden = true;
    $("av-arquivo-erro").textContent = erros.join(" ");
    $("av-arquivo-erro").hidden = !erros.length || versao !== AV.versao;
    atualizarAvancado();
  }
}

async function iniciarAvancado() {
  if ($("av-gerar").disabled) return;
  AV.iniciando = true;
  $("av-erro").hidden = true;
  atualizarAvancado();
  const pedido = lerAvancado();
  try {
    await postar("/api/iniciar-avancado", pedido);
    S.abertos.add(pedido.projeto);
    S.dispensada = null;
    marcarEnviado("avancado", pedido.projeto);
  } catch (e) {
    $("av-erro").textContent = e.message;
    $("av-erro").hidden = false;
  } finally {
    await consultar(true);
    AV.iniciando = false;
    atualizarAvancado();
  }
}

$("av-adicionar").addEventListener("click", () => $("av-arquivos").click());
$("av-arquivos").addEventListener("change", e => {
  const arquivos = [...e.target.files];
  e.target.value = "";
  enviarRefsAvancado(arquivos);
});
$("av-zona").addEventListener("dragover", e => {
  e.preventDefault();
  if (!$("av-adicionar").disabled) $("av-zona").classList.add("sobre");
});
$("av-zona").addEventListener("dragleave", e => {
  if (!$("av-zona").contains(e.relatedTarget)) $("av-zona").classList.remove("sobre");
});
$("av-zona").addEventListener("drop", e => {
  e.preventDefault();
  $("av-zona").classList.remove("sobre");
  enviarRefsAvancado([...e.dataTransfer.files]);
});
$("av-lista").addEventListener("input", e => {
  if (e.target.matches("[data-av-nome]")) {
    REF_POR_LINHA_AV.get(e.target.closest("li")).nome = e.target.value;
    marcarMencoesAvancadas();
  }
});
$("av-lista").addEventListener("click", e => {
  const linha = e.target.closest("li"), ref = REF_POR_LINHA_AV.get(linha);
  if (!ref) return;
  const abrir = e.target.closest("[data-av-abrir]");
  const remover = e.target.closest("[data-av-tirar]");
  const inserir = e.target.closest("[data-av-inserir]");
  if (abrir) alternarPreviaReferenciaAvancado(abrir, ref);
  if (remover) {
    const i = AV.refs.indexOf(ref);
    AV.refs.splice(i, 1);
    desenharRefsAvancado();
    const vizinha = $("av-lista").children[Math.min(i, AV.refs.length - 1)];
    (vizinha?.querySelector("[data-av-tirar]") || $("av-adicionar")).focus();
    atualizarAvancado();
  }
  if (inserir) {
    const nome = ref.nome.trim();
    if (!NOME_REF_AV.test(nome)) { inserir.parentElement.querySelector("input").focus(); return; }
    inserirMencaoAvancada(nome);
  }
});
$("tela-avancado").addEventListener("input", e => {
  if (e.target.id === "av-megapixels") duracoesAvancado($("av-duracao").value);
  atualizarAvancado();
});
$("tela-avancado").addEventListener("submit", e => { e.preventDefault(); iniciarAvancado(); });
