/* Envio de arquivos */
function enviar(arquivo, tipo, progresso) {
  return new Promise((ok, falha) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api/enviar?tipo=${tipo}&nome=${encodeURIComponent(arquivo.name)}`);
    x.upload.onprogress = e => e.lengthComputable && progresso(e.loaded / e.total);
    x.onload = () => {
      let r = {};
      try { r = JSON.parse(x.responseText); } catch {}
      x.status === 200 ? ok(r) : falha(new Error(r.erro || "O envio falhou. Tente de novo."));
    };
    x.onerror = () => falha(new Error("O envio falhou. Confira se o estúdio continua aberto e tente de novo."));
    x.send(arquivo);
  });
}
function limparZona(tipo) {
  $(`zona-${tipo}`).querySelectorAll(".midia").forEach(n => n.remove());
  $(`zona-${tipo}`).closest(".palco-bloco")?.style.removeProperty("--proporcao");
  $(`${tipo}-texto`).innerHTML = `<strong>${AJUDA[tipo][0]}</strong><small>${AJUDA[tipo][1]}</small>`;
  $(`${tipo}-aviso`).hidden = true;
  if (tipo === "foto") $("tirar-foto").hidden = true;
  document.querySelectorAll(`[data-tirar-tipo="${tipo}"]`).forEach(b => { b.hidden = true; });
}
/* Uma imagem que veio do Texto para imagem tem nome de arquivo tecnico (texto_<projeto>_imagem_1.png): a zona mostra de onde veio */
const nomeDaImagem = nome => /^texto_.+_imagem_\d+\.png$/i.test(nome) ? "Imagem do Texto para imagem" : nome;
function mostrarEscolhido(tipo, info, nome, url) {
  const zona = $(`zona-${tipo}`), texto = $(`${tipo}-texto`), ehVideo = BASE(tipo) === "video";
  if (BASE(tipo) === "audio") {
    // Áudio: um tocador pequeno no lugar da prévia (o clique na zona continua trocando o arquivo)
    const caixa = document.createElement("span"), tocador = document.createElement("audio");
    caixa.className = "midia midia-audio";
    tocador.src = url; tocador.controls = true; tocador.preload = "metadata";
    tocador.addEventListener("click", e => e.stopPropagation());
    caixa.append(tocador);
    zona.insertBefore(caixa, texto);
    texto.innerHTML = `<strong>${esc(nome)}</strong><small>${info.duracao ? `${num(info.duracao)} s. ` : ""}Clique para trocar.</small>`;
    return;
  }
  const previa = document.createElement(ehVideo ? "video" : "img");
  previa.src = url;
  previa.alt = "";
  if (ehVideo) { previa.muted = true; previa.preload = "metadata"; }
  if (ehVideo && zona.classList.contains("palco")) { previa.controls = true; previa.muted = false; previa.playsInline = true; }
  const caixa = document.createElement("span");
  caixa.className = "midia";
  caixa.dataset.rotulo = ehVideo ? "Vídeo oculto" : "Foto oculta";
  caixa.append(previa);
  previa.onerror = () => caixa.remove();
  // No palco, o quadro toma o formato da mídia (em pé, quadrada ou larga) em vez de cortá-la num 16:9 fixo
  if (zona.classList.contains("palco")) {
    const moldar = () => {
      const l = previa.videoWidth || previa.naturalWidth, a = previa.videoHeight || previa.naturalHeight;
      if (l && a && caixa.isConnected) zona.closest(".palco-bloco").style.setProperty("--proporcao", `${l} / ${a}`);
    };
    previa.addEventListener(ehVideo ? "loadedmetadata" : "load", moldar);
  }
  zona.insertBefore(caixa, texto);
  texto.innerHTML = ehVideo
    ?`<strong>${esc(nome)}</strong><small>${num(info.duracao)} s, ${info.largura}×${info.altura}. Clique para trocar.</small>`
    : `<strong>${esc(nomeDaImagem(nome))}</strong><small>Clique para trocar.</small>`;
  if (tipo === "foto") $("tirar-foto").hidden = false;
  document.querySelectorAll(`[data-tirar-tipo="${tipo}"]`).forEach(b => { b.hidden = false; });
}
async function escolher(arquivo, tipo) {
  const texto = $(`${tipo}-texto`), aviso = $(`${tipo}-aviso`);
  S[tipo] = null;
  limparZona(tipo);
  S.enviando++;
  texto.innerHTML = `<strong>${esc(arquivo.name)}</strong><small>Enviando…</small>`;
  const zona = $(`zona-${tipo}`);
  zona.style.setProperty("--envio", 0);
  zona.classList.add("enviando");
  atualizar();
  try {
    const r = await enviar(arquivo, BASE(tipo), p => { texto.querySelector("small").textContent = `Enviando… ${Math.round(p * 100)}%`; zona.style.setProperty("--envio", p.toFixed(3)); });
    S[tipo] = r;
    mostrarEscolhido(tipo, r, arquivo.name, URL.createObjectURL(arquivo));
    depoisDeEscolher(tipo, r);
  } catch (e) {
    limparZona(tipo);
    aviso.textContent = e.message;
    aviso.hidden = false;
  }
  zona.classList.remove("enviando");
  S.enviando--;
  atualizar();
}
/* O que cada caixa faz com o arquivo escolhido (enviado agora ou vindo das imagens recentes, recentes.js) */
function depoisDeEscolher(tipo, r) {
  if (tipo === "video") aoEscolherVideo(r);
  if (tipo === "tvideo") aoEscolherVideoTroca(r);
  if (tipo === "ifoto") aoEscolherImagem(r);
  if (tipo === "t2ifoto") aoEscolherPartida(r);
  if (tipo === "tfbase") aoEscolherBaseTroca(r);
  if (["pfoto", "ptres", "pperfil", "pcostas"].includes(tipo)) atualizarPersonagemNovo();
  if (tipo === "pvideo") aoEscolherVideoPersonagem(r);
  if (tipo === "tfundo") atualizarTroca();
  if (tipo === "evideo") aoEscolherVideoEditar(r);
  if (tipo === "epintura") usarImagemMinha(r);
  if (tipo === "iaudio") aoEscolherAudio(r);
  if (tipo === "ivideo") aoEscolherVideoExemplo(r);
  if (tipo === "icenario") atualizarImagem();
}
function avisoVideo(v) {
  const aviso = $("video-aviso");
  aviso.hidden = true;
  if (!v.audio) { aviso.textContent = "Este vídeo não tem áudio. O fluxo usa a faixa original, então escolha um vídeo com som."; aviso.hidden = false; }
  else if (v.duracao > VIDEO_TESTADO) { aviso.textContent = "Até agora só testei com vídeos de cerca de 3 s. Com este, a primeira rodada pode demorar mais e usar mais memória."; aviso.hidden = false; }
}
function ajustarProporcao(v, id) {
  const alvo = v.largura / v.altura;
  let melhor = null, dist = Infinity;
  for (const o of $(id).options) {
    const m = o.value.match(/^(\d+):(\d+)/);
    const e = Math.abs(Math.log((m[1] / m[2]) / alvo));
    if (e < dist) { dist = e; melhor = o.value; }
  }
  if (melhor) $(id).value = melhor;
}
function aoEscolherVideo(v) {
  avisoVideo(v);
  if (!(Number($("duracao").value) > v.duracao)) $("duracao").value = Math.ceil(v.duracao) + 10;
  ajustarProporcao(v, "proporcao");
  if (!S.nomeEditado) $("projeto").value = nomeLivre(v.arquivo);
}
function nomeLivre(arquivo) {
  const base = arquivo.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 50) || "video";
  const usados = new Set((S.dados?.projetos || []).map(p => p.nome));
  let nome = base, i = 2;
  while (usados.has(nome)) nome = `${base}_${i++}`;
  return nome;
}

/* "x" de tirar nas caixas de envio que ainda não tinham um (23/11/2026): no palco ele fica no canto da mídia, dentro da caixa (o clique
   não abre a escolha de arquivo); na barra lateral fica ao lado, como nas outras (nova.css .tirar-x). Tirar deixa a caixa vazia de novo
   e avisa a tela com um "input", que é o que cada tela escuta para se atualizar. */
const TIPOS_TIRAR = ["video", "tvideo", "evideo", "ifoto", "tfoto", "epintura", "tfbase"];
function prepararTirar() {
  for (const tipo of TIPOS_TIRAR) {
    const zona = $(`zona-${tipo}`);
    if (!zona || document.querySelector(`[data-tirar-tipo="${tipo}"]`)) continue;
    const nome = BASE(tipo) === "video" ? "Tirar o vídeo" : "Tirar a imagem";
    // Na barra lateral o "x" vem do CSS (.tirar-x::before), como nos outros; no palco, o ícone
    const html = zona.classList.contains("palco")
      ? `<button type="button" class="tirar-palco" data-tirar-tipo="${tipo}" aria-label="${nome}" title="${nome}" hidden><svg class="ico" aria-hidden="true"><use href="#s-fechar"/></svg></button>`
      : `<button type="button" class="tirar-x" data-tirar-tipo="${tipo}" aria-label="${nome}" title="${nome}" hidden>${nome}</button>`;
    if (zona.classList.contains("palco")) zona.insertAdjacentHTML("beforeend", html);
    else zona.insertAdjacentHTML("afterend", html);
  }
}
function tirarArquivo(tipo) {
  S[tipo] = null;
  $(tipo).value = "";
  limparZona(tipo);
  $(`zona-${tipo}`).closest("form")?.dispatchEvent(new Event("input", { bubbles: true }));
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-tirar-tipo]");
  if (!b) return;
  // Dentro do palco o botão mora no label: sem isso o clique abriria a escolha de arquivo
  e.preventDefault();
  e.stopPropagation();
  tirarArquivo(b.dataset.tirarTipo);
}, true);
prepararTirar();

/* Prévia ao passar o mouse na miniatura de uma caixa de envio da barra lateral (23/11/2026): a mídia aparece grande, ao lado da
   barra, e some quando o mouse sai. Foto e vídeo (o vídeo toca sem som). Não abre no palco, onde a mídia já está grande. */
{
  const previa = document.createElement("div");
  previa.className = "previa-envio";
  previa.setAttribute("aria-hidden", "true");
  previa.hidden = true;
  document.body.append(previa);
  let atual = null;
  function mostrar(caixa) {
    const fonte = caixa.querySelector("img, video");
    if (!fonte?.src || document.documentElement.classList.contains("ocultar")) return;
    atual = caixa;
    previa.innerHTML = fonte.tagName === "VIDEO" ? `<video src="${fonte.src}" muted autoplay loop playsinline></video>` : `<img src="${fonte.src}" alt="">`;
    previa.hidden = false;
    const r = caixa.getBoundingClientRect(), lado = caixa.closest(".lado")?.getBoundingClientRect() || r;
    const largura = previa.offsetWidth, altura = previa.offsetHeight, margem = 12;
    previa.style.left = `${Math.round(Math.min(lado.right + margem, innerWidth - largura - margem))}px`;
    previa.style.top = `${Math.round(Math.max(margem, Math.min(r.top + r.height / 2 - altura / 2, innerHeight - altura - margem)))}px`;
  }
  function esconder() { atual = null; previa.hidden = true; previa.innerHTML = ""; }
  document.addEventListener("pointerover", e => {
    if (e.pointerType !== "mouse") return;
    const caixa = e.target.closest(".lado .escolha:not(.palco) .midia:not(.midia-audio), .lado .ref");
    if (caixa && caixa !== atual) mostrar(caixa);
    else if (!caixa && atual) esconder();
  });
  document.addEventListener("scroll", esconder, true);
}
