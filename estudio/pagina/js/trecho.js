/* Editor do trecho da troca em vídeo (interface nova; a ideia é do Henge): uma tira de miniaturas do vídeo, a janela
   do trecho que será trocado, que se arrasta para escolher o começo, e os cortes de câmera (cortes.py, /cortes/video).
   Num corte a troca recomeça limpa (trocar_personagem.janelas); perto de um corte, o começo gruda nele. */
const MINIATURAS_TRECHO = 12;

async function carregarTrecho(v) {
  if (!v?.arquivo || S.trechoDe === v.arquivo) return;
  S.trechoDe = v.arquivo;
  S.cortesTroca = [];
  S.miniaturasTroca = [];
  desenharTrecho();
  const url = `/entrada/video/${encodeURIComponent(v.arquivo)}`;
  fetch(`/cortes/video/${encodeURIComponent(v.arquivo)}`).then(r => r.ok ? r.json() : { cortes: [] }).then(r => {
    if (S.trechoDe !== v.arquivo) return;
    S.cortesTroca = r.cortes || [];
    atualizarTroca();
  }).catch(() => {});
  // As miniaturas saem de um vídeo fora da tela: busca cada instante e desenha num canvas pequeno
  const video = document.createElement("video");
  video.muted = true; video.preload = "auto"; video.src = url;
  try {
    await new Promise((ok, erro) => { video.onloadeddata = ok; video.onerror = erro; });
    const canvas = document.createElement("canvas"), alto = 54;
    canvas.height = alto; canvas.width = Math.round(alto * video.videoWidth / video.videoHeight);
    const ctx = canvas.getContext("2d");
    for (let i = 0; i < MINIATURAS_TRECHO; i++) {
      if (S.trechoDe !== v.arquivo) return;
      video.currentTime = Math.min(video.duration - .05, (i + .5) * video.duration / MINIATURAS_TRECHO);
      await new Promise(ok => { video.onseeked = ok; });
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      S.miniaturasTroca.push(canvas.toDataURL("image/jpeg", .7));
      desenharTrecho();
    }
  } catch { /* sem miniaturas, a tira fica lisa e o editor continua funcionando */ }
  finally { video.removeAttribute("src"); video.load(); }
}

/* Duração do trecho em segundos, como o fluxo usa (troca.js: quadrosTroca) */
function segundosTrecho() {
  return quadrosTroca(Number($("t-duracao").value) || 0, lerTroca().megapixels) / S.dados.constantes.fps;
}

function desenharTrecho() {
  const v = S.tvideo, caixa = $("t-trecho");
  caixa.hidden = !v;
  if (!v) return;
  if (S.trechoDe !== v.arquivo) carregarTrecho(v);
  const tira = $("t-tira"), dur = v.duracao || 1, inicio = Math.max(0, Number($("t-inicio").value) || 0), largura = Math.min(dur, segundosTrecho());
  const fotos = S.miniaturasTroca || [];
  const marca = fotos.length + "|" + (S.cortesTroca || []).length + "|" + v.arquivo;
  if (tira.dataset.marca !== marca) {
    tira.dataset.marca = marca;
    tira.querySelectorAll(".trecho-quadro, .trecho-corte").forEach(e => e.remove());
    for (let i = 0; i < MINIATURAS_TRECHO; i++) {
      const q = document.createElement("span");
      q.className = "trecho-quadro";
      if (fotos[i]) q.style.backgroundImage = `url(${fotos[i]})`;
      tira.insertBefore(q, $("t-janela"));
    }
    for (const c of S.cortesTroca || []) {
      const m = document.createElement("i");
      m.className = "trecho-corte";
      m.style.left = `${(c.segundos / dur) * 100}%`;
      m.title = `Corte de câmera em ${num(c.segundos, 2)} s`;
      tira.append(m);
    }
  }
  $("t-janela").style.left = `${(inicio / dur) * 100}%`;
  $("t-janela").style.width = `${(largura / dur) * 100}%`;
  tira.setAttribute("aria-valuemax", String(Math.max(0, dur - largura).toFixed(1)));
  tira.setAttribute("aria-valuenow", String(inicio));
  tira.setAttribute("aria-valuetext", `Começa em ${num(inicio, 1)} s, termina em ${num(inicio + largura, 1)} s`);
  const cortes = S.cortesTroca || [], dentro = cortes.filter(c => c.segundos > inicio + .05 && c.segundos < inicio + largura - .05);
  $("t-trecho-nota").textContent = !cortes.length ? `Trecho de ${num(inicio, 1)} a ${num(inicio + largura, 1)} s. Nenhum corte de câmera neste vídeo.`
    : dentro.length ? `Trecho de ${num(inicio, 1)} a ${num(inicio + largura, 1)} s, com corte de câmera em ${dentro.map(c => `${num(c.segundos, 1)} s`).join(", ")}: ali a troca recomeça limpa.`
    : `Trecho de ${num(inicio, 1)} a ${num(inicio + largura, 1)} s, num plano só. Cortes de câmera em ${cortes.map(c => `${num(c.segundos, 1)} s`).join(", ")} (as linhas na tira).`;
}

/* Arrastar a janela (ou clicar na tira) muda o começo; perto de um corte (0,3 s), gruda nele */
function moverTrecho(segundos, soltar = false) {
  const v = S.tvideo;
  if (!v) return;
  const largura = Math.min(v.duracao, segundosTrecho());
  let inicio = Math.max(0, Math.min(v.duracao - largura, segundos));
  const perto = (S.cortesTroca || []).find(c => Math.abs(c.segundos - inicio) < .3);
  if (perto && perto.segundos <= v.duracao - largura) inicio = perto.segundos;
  inicio = Math.round(inicio * 10) / 10;
  $("t-inicio").value = inicio;
  const palco = $("zona-tvideo").querySelector(".midia video");
  if (palco && palco.readyState >= 1) palco.currentTime = inicio;
  // A marcação é no primeiro quadro do trecho: mudou o começo, a pessoa pode estar em outro lugar
  if (S.marcaTroca && S.marcaTroca.inicio !== inicio) { S.marcaTroca = null; desenharMarca(); }
  if (soltar) atualizarTroca(); else desenharTrecho();
}

/* Marcar quem trocar (Henge): clicar na pessoa no primeiro quadro do trecho. O SAM 3.1 a acha e segue pelo trecho
   (trocar_personagem.mascaras_da_pessoa) e só ela é redesenhada. */
function videoDoPalcoTroca() { return $("zona-tvideo").querySelector(".midia video"); }
function areaDoVideo(v) {
  // A parte da caixa onde a imagem aparece (o vídeo fica inteiro dentro dela, com faixas nas sobras)
  const r = v.getBoundingClientRect(), a = (v.videoWidth || 16) / (v.videoHeight || 9);
  let w = r.width, h = r.height, x = r.left, y = r.top;
  if (a > w / h) { h = w / a; y += (r.height - h) / 2; } else { w = h * a; x += (r.width - w) / 2; }
  return { x, y, w, h };
}
function desenharMarca() {
  const v = videoDoPalcoTroca(), midia = v?.closest(".midia");
  $("t-marcar").setAttribute("aria-pressed", String(!!S.marcando));
  $("t-marcar").textContent = S.marcando ? "Clique na pessoa no vídeo" : S.marcaTroca ? "Marcar de novo" : "Marcar quem trocar";
  $("t-desmarcar").hidden = !S.marcaTroca;
  $("t-marcar-nota").textContent = S.marcando ? `O vídeo parou em ${num(Number($("t-inicio").value) || 0, 1)} s, o começo do trecho. Clique em cima da pessoa que vai ser trocada.`
    : S.marcaTroca ? "Só a pessoa marcada vai ser trocada; o resto de cada quadro fica igual ao vídeo. Depois da geração, a pessoa_marcada.mp4 do projeto mostra o que o SAM seguiu."
    : "Sem marcação, a troca redesenha o quadro inteiro. Marque a pessoa para trocar só ela (o resto fica igual ao vídeo) ou para escolher uma entre várias.";
  if (!midia) return;
  let camada = midia.querySelector(".marcar-camada");
  if (!camada) {
    camada = document.createElement("span");
    camada.className = "marcar-camada";
    camada.innerHTML = `<i class="marcar-ponto" hidden></i>`;
    midia.append(camada);
    camada.addEventListener("click", e => {
      e.preventDefault(); e.stopPropagation();
      if (!S.marcando) return;
      const a = areaDoVideo(v), x = (e.clientX - a.x) / a.w, y = (e.clientY - a.y) / a.h;
      if (x < 0 || x > 1 || y < 0 || y > 1) return;
      S.marcaTroca = { x: Math.round(x * 1e4) / 1e4, y: Math.round(y * 1e4) / 1e4, inicio: Number($("t-inicio").value) || 0 };
      S.marcando = false;
      desenharMarca();
      atualizarTroca();
    });
  }
  camada.classList.toggle("ativa", !!S.marcando);
  const ponto = camada.querySelector(".marcar-ponto");
  ponto.hidden = !S.marcaTroca;
  if (S.marcaTroca) {
    const a = areaDoVideo(v), r = midia.getBoundingClientRect();
    ponto.style.left = `${a.x - r.left + S.marcaTroca.x * a.w}px`;
    ponto.style.top = `${a.y - r.top + S.marcaTroca.y * a.h}px`;
  }
}
$("t-marcar").addEventListener("click", () => {
  const v = videoDoPalcoTroca();
  if (!v) return;
  S.marcando = !S.marcando;
  if (S.marcando) { v.pause(); v.currentTime = Number($("t-inicio").value) || 0; }
  desenharMarca();
});
$("t-desmarcar").addEventListener("click", () => { S.marcaTroca = null; S.marcando = false; desenharMarca(); atualizarTroca(); });
new ResizeObserver(() => desenharMarca()).observe($("zona-tvideo"));
$("t-tira").addEventListener("pointerdown", e => {
  const v = S.tvideo;
  if (!v) return;
  e.preventDefault();
  const tira = $("t-tira"), r = tira.getBoundingClientRect(), janela = $("t-janela").getBoundingClientRect();
  // Pegando a janela, ela anda junto com o ponteiro; fora dela, a janela começa onde clicou
  const pega = e.clientX >= janela.left && e.clientX <= janela.right ? e.clientX - janela.left : 0;
  const ir = x => moverTrecho(((x - pega - r.left) / r.width) * v.duracao);
  tira.setPointerCapture(e.pointerId);
  tira.classList.add("arrastando");
  ir(e.clientX);
  const mover = m => ir(m.clientX);
  const fim = () => { tira.classList.remove("arrastando"); tira.removeEventListener("pointermove", mover); tira.removeEventListener("pointerup", fim); tira.removeEventListener("pointercancel", fim); atualizarTroca(); };
  tira.addEventListener("pointermove", mover);
  tira.addEventListener("pointerup", fim);
  tira.addEventListener("pointercancel", fim);
});
$("t-tira").addEventListener("keydown", e => {
  const passo = { ArrowLeft: -.1, ArrowRight: .1, PageDown: -1, PageUp: 1 }[e.key];
  if (passo === undefined && e.key !== "Home") return;
  e.preventDefault();
  moverTrecho(e.key === "Home" ? 0 : (Number($("t-inicio").value) || 0) + passo, true);
});
