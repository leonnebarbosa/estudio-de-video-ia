/* Doca da geração (24/11/2026): o andamento e a fila saem do topo das telas e ficam numa coluna à direita, por cima,
   que abre e recolhe pelo botão Fila do cabeçalho. Enquanto gera, esse botão mostra o anel e a porcentagem (era uma
   aba na borda direita, que repetia o botão e saiu no mesmo dia). Aberta, a doca mostra de que aba veio o pedido
   (com o atalho para ela), o andamento, o que foi enviado e a fila. A caixa #andamento continua sendo desenhada pelo
   andamento.js e a lista pela fila.js; aqui só entram a moldura, a origem, o envio e a aba recolhida.
   Abre sozinha quando começa uma geração nova ou quando uma para com erro; recolher fica valendo até a próxima. */
const DOCA = "estudio-doca";
S.doca = (() => { try { return JSON.parse(sessionStorage.getItem(DOCA)) || {}; } catch { return {}; } })();
S.docaAberta = !!S.doca.aberta;
function guardarDoca() { try { sessionStorage.setItem(DOCA, JSON.stringify(S.doca)); } catch {} }

function abrirDoca(abrir, foco = false) {
  S.docaAberta = S.doca.aberta = !!abrir;
  if (!abrir && S.dados?.tarefa?.rodando) S.doca.recolheu = true;
  guardarDoca();
  if (S.dados) desenharDoca(S.dados);
  if (foco) (abrir ? $("doca-recolher") : $("fila-botao"))?.focus({ preventScroll: true });
}
$("doca-recolher").addEventListener("click", () => abrirDoca(false, true));
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && S.docaAberta && $("doca").contains(document.activeElement) && !document.querySelector("dialog[open]")) abrirDoca(false, true);
});

/* De que aba veio um pedido, pelo tipo e pelo que foi enviado. O resto do código chama de "tela" o que o menu chama de aba. */
function abaDoPedido(tipo, modo, p) {
  const c = p?.config || {};
  if (tipo === "personagem") return { aba: "personagens", nome: "Personagem" };
  if (tipo === "troca") return { aba: "troca", troca: "video", nome: "Trocar personagem, vídeo" };
  if (tipo === "texto" && (p?.troca_foto || c.troca_foto)) return { aba: "troca", troca: "foto", nome: "Trocar personagem, foto" };
  if (tipo === "texto") return { aba: "texto", nome: "Imagem" };
  if (tipo === "editar") return { aba: "editar", nome: "Vídeo, editar" };
  if (tipo === "imagem" && c.avancado) return { aba: "avancado", nome: "Vídeo avançado" };
  if (tipo === "imagem" && p?.sem_imagem) return { aba: "tvideo", nome: "Vídeo de um texto" };
  if (tipo === "imagem" || tipo === "wan") return { aba: "imagem", nome: modo === "acabar" ? "Vídeo de uma imagem, acabamento" : "Vídeo de uma imagem" };
  return { aba: "novo", nome: "Continuar vídeo" };
}
function irParaPedido(nome, tipo, modo) {
  const p = S.dados?.projetos?.find(x => x.nome === nome);
  const alvo = abaDoPedido(tipo || p?.tipo, modo, p);
  if (alvo.troca) { S.modoTroca = alvo.troca; for (const b of document.querySelectorAll("[data-modo-troca]")) b.setAttribute("aria-pressed", String(b.dataset.modoTroca === S.modoTroca)); }
  irPara(alvo.aba);
}
function abrirProjeto(nome) {
  S.abertos.add(nome);
  S.rolar = nome;
  S.marcaProjetos = "";
  irPara("projetos");
  desenharProjetos(S.dados);
}
document.addEventListener("click", e => {
  const ir = e.target.closest("[data-ir-aba]"), proj = e.target.closest("[data-abrir-projeto]");
  if (!ir && !proj) return;
  e.preventDefault();
  if (ir) irParaPedido(ir.dataset.irAba, ir.dataset.irTipo, ir.dataset.irModo);
  else abrirProjeto(proj.dataset.abrirProjeto);
});

const EXT_IMAGEM = /\.(png|jpe?g|webp)$/i;
const MODELOS_DOCA = { h3: "H3", wan: "Wan", klein_edit: "Klein", qwen21_edit: "Qwen 2.1" };
/* O que foi enviado, do interface.json do projeto (p.config): mídias, texto ou falas e a ficha (modelo, formato, qualidade) */
function htmlEnvio(t, p) {
  const c = p?.config || {};
  // partida: a foto que o Editar imagem (e o estilo) muda; referencia e referencias: as outras do Texto para imagem
  const fotos = [...new Set([p?.personagem, c.partida, c.referencia,...(c.referencias || []).slice(0, 1), c.cenario, c.fundo].filter(n => typeof n === "string" && EXT_IMAGEM.test(n)))].slice(0, 4);
  const pessoa = c.personagem_id && (PERS.lista?.find(x => x.id === c.personagem_id)?.nome || c.personagem_id);
  const texto = (p?.ideia || p?.prompt || c.prompt || "").trim();
  const tomadas = (c.tomadas || []).filter(x => x && (x.fala || x.acao));
  const ficha = [];
  if (c.modelo) ficha.push(["Modelo", MODELOS_DOCA[c.modelo] || semExt(c.modelo)]);
  if (c.proporcao) ficha.push(["Formato", nomeProporcao(c.proporcao)]);
  if (c.megapixels) ficha.push(["Resolução", `${num(c.megapixels, Number(c.megapixels) >= 1 ? 1 : 2)} MP${c.pele ? ", pele natural" : ""}`]);
  if (c.quantidade > 1) ficha.push(["Quantidade", String(c.quantidade)]);
  if (c.duracao) ficha.push(["Duração", `${num(c.duracao, 0)} s`]);
  const loras = (c.loras || []).map(l => semExt(Array.isArray(l) ? l[0] : l?.nome || l)).filter(Boolean);
  if (loras.length) ficha.push(["LoRAs", loras.join(", ")]);
  if (!fotos.length && !pessoa && !texto && !tomadas.length && !ficha.length && !p?.origem) return "";
  let h = `<p class="doca-secao">O que foi enviado</p>`;
  if (fotos.length || pessoa || p?.origem) {
    h += `<div class="envio-midias">${fotos.map(f => midia(`<img src="/entrada/foto/${encodeURIComponent(f)}" alt="" loading="lazy" onerror="this.closest('.midia').remove()">`, "Imagem oculta", "envio-foto")).join("")}`;
    h += `<div class="envio-quem">${pessoa ? `<strong>${esc(pessoa)}</strong><small>Personagem da biblioteca</small>` : ""}${p?.origem ? `<strong title="${esc(p.origem)}">${esc(p.origem)}</strong><small>Vídeo de origem</small>` : ""}</div></div>`;
  }
  if (tomadas.length) {
    const n = t?.progresso?.tomada || 0;
    h += `<ol class="envio-tomadas">${tomadas.map((x, i) => `<li class="${t?.rodando && i + 1 === n ? "agora" : t?.rodando && i + 1 < n ? "feita" : ""}"><span>${i + 1}</span><p>${x.fala ? `“${esc(x.fala)}”` : `<i>${esc(x.acao)}</i>`}${x.duracao ? `<small>${num(x.duracao, 1)} s</small>` : ""}</p></li>`).join("")}</ol>`;
  } else if (texto) h += `<p class="envio-texto">${esc(texto)}</p>`;
  if (ficha.length) h += `<dl class="envio-ficha">${ficha.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
  // O que já ficou pronto nesta geração: o vídeo até a última tomada ou as imagens feitas
  if (t?.rodando && p?.tipo === "imagem" && p.feitas?.length && p.final) h += `<p class="doca-secao">Já pronto</p>` + midia(`<video src="/video/${encodeURIComponent(p.nome)}/final.mp4?m=${p.final.marca}" muted loop autoplay playsinline></video>`, "Vídeo oculto", "envio-pronto");
  if (t?.rodando && p?.tipo === "texto" && p.imagens?.length) h += `<p class="doca-secao">Já pronto</p><div class="envio-prontas">${p.imagens.map(i => midia(`<img src="/imagem/${encodeURIComponent(p.nome)}/${encodeURIComponent(i.arquivo)}?m=${i.marca}" alt="Imagem ${i.n}" loading="lazy">`, "Imagem oculta", "envio-foto")).join("")}</div>`;
  return h;
}

function desenharDoca(d) {
  const t = d.tarefa, f = d.fila || { itens: [] }, nFila = f.itens?.length || 0;
  const rodando = !!t?.rodando, andamento = !$("andamento").hidden;
  const temAlgo = rodando || nFila > 0 || andamento;
  const erro = andamento && !rodando;
  // Abre sozinha numa geração nova (de qualquer origem: aba, fila ou MCP) e quando uma para com erro
  const chave = t ? `${t.projeto}:${rodando ? "r" : t.codigo}` : "";
  // Quem recolheu durante uma geração não vê a doca abrir de novo a cada pedido da fila; um erro abre sempre
  if (chave && chave !== S.doca.visto) {
    if (erro || (rodando && !S.doca.recolheu)) S.docaAberta = S.doca.aberta = true;
    S.doca.visto = chave;
    guardarDoca();
  }
  if (!temAlgo && S.doca.recolheu) { S.doca.recolheu = false; guardarDoca(); }
  const aberta = S.docaAberta;
  document.documentElement.classList.toggle("doca-aberta", aberta);
  $("doca").hidden = !aberta;
  $("doca").classList.toggle("gerando", rodando);
  $("doca").classList.toggle("parou", erro);
  $("doca-recolher").setAttribute("aria-expanded", String(aberta));

  // Botão Fila do cabeçalho: enquanto gera, o ícone vira um anel com a porcentagem que o andamento escreveu (#pct);
  // sem porcentagem (plano, preparo), o anel só gira. Parado com erro, fica vermelho. O nome do botão é do fila.js.
  const botao = $("fila-botao");
  botao.setAttribute("aria-expanded", String(aberta));
  const pct = Number.parseInt($("pct")?.textContent, 10);
  const comPct = rodando && Number.isFinite(pct);
  botao.classList.toggle("gerando", rodando);
  botao.classList.toggle("parou", erro);
  botao.classList.toggle("sem-pct", !comPct);
  $("fila-anel").style.strokeDashoffset = String(100 - (comPct ? pct : 0));
  trocarTexto($("fila-rotulo"), comPct ? `${pct}%` : rodando ? "Gerando" : erro ? "Parou" : "Fila");
  // Gerando, a contagem diz só quantos esperam depois ("+2"); sem ninguém esperando, some. Parado, é a do fila.js
  const conta = $("fila-conta");
  if (rodando) trocarTexto(conta, `+${nFila}`);
  conta.hidden = rodando && !nFila;
  // A luz do motor dizia "Gerando" junto com o botão: com uma geração do estúdio rodando, só o botão fala
  $("luz").classList.toggle("com-geracao", rodando);

  trocarTexto($("doca-titulo"), rodando ? "Gerando agora" : erro ? "A geração parou" : nFila ? "Fila" : "Geração");
  $("doca-vazia").hidden = temAlgo;

  // Origem e envio: só redesenham quando o projeto, o estado ou o envio mudam
  const p = t && d.projetos.find(x => x.nome === t.projeto);
  const mostrar = !!t && (rodando || andamento);
  const origem = $("doca-origem"), envio = $("doca-envio");
  origem.hidden = envio.hidden = !mostrar;
  if (!mostrar) { origem.innerHTML = envio.innerHTML = ""; S.marcaDoca = ""; return; }
  const n = t.progresso?.tomada || 0;
  const marca = JSON.stringify([t.projeto, t.tipo, t.modo, rodando, t.codigo, p?.config, p?.feitas?.length, p?.final?.marca, p?.imagens?.length, n, PERS.lista?.length]);
  if (marca === S.marcaDoca) return;
  S.marcaDoca = marca;
  const alvo = abaDoPedido(t.tipo, t.modo, p);
  const ehProjeto = t.tipo !== "personagem" && !!p;
  const nomeVisivel = t.tipo === "personagem" ? (PERS.lista?.find(x => x.id === t.projeto)?.nome || t.projeto) : t.projeto;
  origem.innerHTML = `<div class="origem-linha"><span class="origem-aba">${esc(alvo.nome)}</span><span class="origem-estado">${rodando ? "gerando" : "parou"}</span></div>
    <p class="origem-nome" title="${esc(nomeVisivel)}">${esc(nomeVisivel)}</p>
    <div class="origem-botoes"><button type="button" class="simples" data-ir-aba="${esc(t.projeto)}" data-ir-tipo="${esc(t.tipo)}" data-ir-modo="${esc(t.modo || "")}">Ir para a aba</button>${ehProjeto ? `<button type="button" class="simples" data-abrir-projeto="${esc(t.projeto)}">Abrir o projeto</button>` : ""}</div>`;
  const video = envio.querySelector("video"), tempoVideo = video?.currentTime;
  porHtml(envio, htmlEnvio(t, p));
  const novo = envio.querySelector("video");
  if (novo && tempoVideo && novo.src === video?.src) novo.currentTime = tempoVideo;
  envio.hidden = !envio.innerHTML;
}
