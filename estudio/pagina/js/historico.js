/* Histórico em cada aba: o que já foi gerado ali, e pelo modelo escolhido, na tira "Feitos" à direita do palco
   (visual Corte, 22/11/2026; em janela estreita a tira vira uma faixa deitada embaixo do palco, corte.css).
   Clicar num item mostra o resultado no palco; "Carregar estas configurações" preenche a tela (com Desfazer). */
const ABAS_HISTORICO = {
  novo: { vazio: "Nenhuma continuação ainda.", pertence: p => !p.tipo },
  troca: { vazio: "Nenhuma troca ainda.", pertence: p => p.tipo === "troca" },
  editar: { vazio: "Nenhuma edição ainda.", pertence: p => p.tipo === "editar" },
  avancado: { vazio: "Nenhum vídeo gerado neste modo ainda.", pertence: p => !!p.config?.avancado },
  trocafoto: { vazio: "Nenhuma troca em foto ainda.", pertence: p => p.tipo === "texto" && !!p.troca_foto },
  // Os projetos da antiga aba Wan entram aqui: o Wan agora é um modelo desta aba
  // A mesma tela serve o Texto para vídeo: cada modo mostra só os seus projetos (sem imagem ou com)
  imagem: { vazio: "Nada gerado com este modelo ainda.", pertence: p => (p.tipo === "imagem" || p.tipo === "wan") && !p.config?.avancado && !!p.sem_imagem === modoTexto(),
            modelo: p => p.config?.modelo || "h3", seletor: "i-modelo", modelos: () => S.dados?.imagem?.modelos || [] },
  texto: { vazio: "Nenhuma imagem gerada ainda.", pertence: p => p.tipo === "texto" && !p.troca_foto,
           modelo: p => p.config?.modelo || "chroma_flash", seletor: "t2i-modelo", modelos: () => S.dados?.texto?.modelos || [] },
};
const MAX_HISTORICO = 40;
S.previa = {};

/* A tira fica sempre à vista, numa coluna própria da tela (a .tela é display: contents, então a tira é mais um item da
   grade da .area). A prévia do item aberto ocupa o lugar do palco e a barra dele, com os botões, fica logo abaixo. */
function garantirHistorico(aba) {
  let h = $(`hist-${aba}`);
  if (h) return h;
  const tela = $(`tela-${aba}`), bloco = tela.querySelector(".palco-bloco");
  h = document.createElement("aside");
  h.className = "historico tira";
  h.id = `hist-${aba}`;
  h.setAttribute("aria-label", "Feitos: o histórico desta tela");
  h.innerHTML = `<div class="hist-topo"><h2 class="hist-titulo">Feitos</h2><span class="hist-qtd"></span></div><p class="hist-modelo"></p>`
    + `${ABAS_HISTORICO[aba].seletor ? `<label class="hist-todos" hidden><input type="checkbox" data-hist-todos="${aba}"> Todos os modelos</label>` : ""}`
    + `<div class="hist-faixa" role="list"></div>`;
  tela.append(h);
  // A prévia ocupa o lugar do palco (mesmo quadro), sem mexer no que estava escolhido ali
  const previa = document.createElement("div");
  previa.className = "palco palco-previa";
  previa.id = `previa-${aba}`;
  previa.hidden = true;
  bloco.prepend(previa);
  const barra = document.createElement("div");
  barra.className = "hist-barra";
  barra.id = `hist-barra-${aba}`;
  barra.dataset.histBarra = aba;
  barra.hidden = true;
  previa.after(barra);
  return h;
}
function projetoDe(nome) { return S.dados?.projetos.find(p => p.nome === nome); }
function miniaturaHistorico(p) {
  const nome = encodeURIComponent(p.nome);
  let src = "";
  if (p.tipo === "texto" && p.imagens?.length) src = `/imagem/${nome}/${p.imagens[0].arquivo}?m=${p.imagens[0].marca}`;
  else if (p.foto_existe) src = `/entrada/foto/${encodeURIComponent(p.personagem)}`;
  else if (p.tem_quadro) src = `/quadro/${nome}?r=${p.rodadas.length}`;
  return src ? midia(`<img loading="lazy" src="${src}" alt="">`, "", "hist-mini") : `<span class="hist-mini"></span>`;
}
/* Quanto a geração levou, somando as tomadas, imagens ou rodadas. Projeto sem a medida (feito fora da página, ou parado) dá 0 */
function segundosGeracao(p) {
  if (p.resultado?.segundos) return p.resultado.segundos;
  const soma = lista => (lista || []).reduce((s, r) => s + (r.segundos || 0), 0);
  return soma(p.feitas) || soma(p.imagens) || soma(p.rodadas);
}
const duracaoCurta = s => { s = Math.round(s); return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min${s % 60 ? ` ${String(s % 60).padStart(2, "0")} s` : ""}`; };
function situacaoHistorico(p, rodando) {
  if (p.tipo === "wan") return rodando ? "gerando agora" : p.final ? "pronto" : "sem vídeo";
  return situacao(p, rodando);
}
function nomeModeloHistorico(aba, p) {
  const c = ABAS_HISTORICO[aba];
  if (!c.modelo) return "";
  return c.modelos().find(m => m.id === c.modelo(p))?.nome || c.modelo(p);
}
function itensHistorico(aba, d) {
  const c = ABAS_HISTORICO[aba];
  let lista = d.projetos.filter(c.pertence);
  const modelo = c.seletor ? $(c.seletor).value : null;
  const todos = !c.seletor || !!$(`hist-${aba}`).querySelector("[data-hist-todos]")?.checked;
  if (c.modelo && modelo && !todos) lista = lista.filter(p => c.modelo(p) === modelo);
  return { lista: lista.slice(0, MAX_HISTORICO), modelo, todos };
}
function desenharHistorico(aba, d = S.dados) {
  if (!d) return;
  const h = garantirHistorico(aba), c = ABAS_HISTORICO[aba];
  const { lista, modelo, todos } = itensHistorico(aba, d);
  const modelos = c.modelos?.() || [];
  const nomeModelo = modelos.find(m => m.id === modelo)?.nome;
  const rodando = d.tarefa?.rodando ? d.tarefa.projeto : null;
  const marca = JSON.stringify([lista.map(p => [p.nome, p.final?.marca, p.completo, p.imagens?.length, p.feitas?.length, p.rodadas.length]), nomeModelo, todos, rodando, modelos.length]);
  if (h.dataset.marca === marca) return;
  h.dataset.marca = marca;
  const caixaTodos = h.querySelector(".hist-todos");
  if (caixaTodos) caixaTodos.hidden = modelos.length < 2;
  // Com o filtro por modelo, o nome dele fica escrito embaixo do título: sem isso a tira parece incompleta
  trocarTexto(h.querySelector(".hist-modelo"), nomeModelo && !todos ? nomeModelo : "");
  h.querySelector(".hist-qtd").textContent = lista.length ? String(lista.length) : "";
  h.querySelector(".hist-faixa").innerHTML = lista.length ? lista.map(p => {
    const sel = S.previa[aba] === p.nome;
    // O tempo que levou vem primeiro; a hora em que terminou fica na dica do item e na barra
    const seg = rodando === p.nome ? 0 : segundosGeracao(p), sit = situacaoHistorico(p, rodando === p.nome);
    const info = [seg ? `levou ${duracaoCurta(seg)}` : "", seg && sit.startsWith("pronto") ? "" : sit, todos && c.modelo ? nomeModeloHistorico(aba, p) : ""].filter(Boolean).join(" · ");
    return `<button type="button" class="hist-item" role="listitem" aria-pressed="${sel}" data-hist-aba="${aba}" data-hist-projeto="${esc(p.nome)}" title="${esc(p.nome)}, ${esc(quando(p.quando))}">`
      + `${miniaturaHistorico(p)}<span class="hist-nome">${esc(p.nome)}</span><span class="hist-info">${esc(info)}</span></button>`;
  }).join("") : `<p class="hist-vazio">${esc(c.vazio)}</p>`;
  // A prévia de um projeto que foi apagado fecha sozinha
  if (S.previa[aba] && !projetoDe(S.previa[aba])) fecharPrevia(aba);
}
function desenharHistoricos(d) {
  for (const aba of Object.keys(ABAS_HISTORICO)) desenharHistorico(aba, d);
}
function resumoHistorico(aba, p) {
  const c = p.config || {};
  const texto = p.ideia || c.prompt || c.tomadas?.find(t => t.acao)?.acao || c.tomadas?.find(t => t.fala)?.fala || "";
  const curto = texto.length > 140 ? `${texto.slice(0, 137)}…` : texto;
  const partes = [];
  if (aba === "imagem" && c.tomadas) partes.push(`${nomeModeloHistorico(aba, p)}, ${c.tomadas.length} ${c.tomadas.length === 1 ? "tomada" : "tomadas"}`);
  else if (p.tipo === "wan") partes.push(`${nomeModeloHistorico(aba, p)}, ${c.duracao} s`);
  else if (p.tipo === "texto") partes.push(`${p.imagens.length} ${p.imagens.length === 1 ? "imagem" : "imagens"}`);
  else if (p.tipo === "troca" && c.duracao) partes.push(`${num(c.duracao, c.duracao % 1 ? 1 : 0)} s, roupa ${c.roupa === "foto" ? "da foto" : "do vídeo"}`);
  else if (c.duracao) partes.push(`${num(c.duracao, 0)} s`);
  if (curto) partes.push(curto);
  return partes.join(" · ");
}
function mostrarPrevia(aba, nome) {
  const p = projetoDe(nome);
  if (!p) return;
  if (aba === "avancado") fecharPreviaReferenciaAvancado();
  garantirHistorico(aba);
  const previa = $(`previa-${aba}`), bloco = previa.parentElement, enc = encodeURIComponent(p.nome);
  for (const el of bloco.children) {
    if (el === previa || el.classList.contains("hist-barra") || el.dataset.previaOculto) continue;
    if (!el.hidden) { el.dataset.previaOculto = "1"; el.hidden = true; }
  }
  let html, src = "", eVideo = false;
  if (p.tipo === "texto" && p.imagens.length) {
    src = `/imagem/${enc}/${p.imagens[0].arquivo}?m=${p.imagens[0].marca}`;
    html = midia(`<div class="t2i-galeria" data-n="${p.imagens.length}">${p.imagens.map(i => `<figure class="t2i-item">${midia(`<img src="/imagem/${enc}/${i.arquivo}?m=${i.marca}" alt="Imagem ${i.n}">`, "Imagem oculta")}${botaoSemente(i.semente)}</figure>`).join("")}</div>`)
      // Troca em foto: as fotos que entraram, para comparar
      + (p.troca_foto ? entradasTrocaFoto(p) : "");
  } else if (p.final) {
    src = `/video/${enc}/final.mp4?m=${p.final.marca}`;
    eVideo = true;
    html = midia(`<video controls playsinline preload="auto" src="${src}"></video>`, "Vídeo oculto");
  } else {
    html = midia(`<span class="hist-sem"><strong>${esc(p.nome)}</strong><small>Este projeto ainda não tem vídeo pronto.</small></span>`);
  }
  // Trocando de um item para outro, a mídia anterior fica até a nova ter o primeiro quadro: sem tela preta no meio.
  // Um clique mais novo vence um carregamento antigo (marca).
  const marca = S.marcaPrevia = (S.marcaPrevia || 0) + 1;
  let feito = false;
  const trocar = () => {
    if (feito || S.marcaPrevia !== marca) return;
    feito = true;
    previa.querySelector("video")?.pause();
    previa.innerHTML = html;
  };
  if (previa.hidden || !src) trocar();
  else {
    const carga = eVideo ? document.createElement("video") : new Image();
    if (eVideo) { carga.preload = "auto"; carga.muted = true; carga.addEventListener("loadeddata", trocar, { once: true }); }
    else carga.onload = trocar;
    carga.onerror = trocar;
    carga.src = src;
    setTimeout(trocar, 1500);
  }
  previa.hidden = false;
  S.previa[aba] = nome;
  const barra = $(`hist-barra-${aba}`);
  barra.dataset.projetoAcao = p.nome;
  const seg = segundosGeracao(p);
  barra.innerHTML = `<p><strong>${esc(p.nome)}</strong> · ${esc(quando(p.quando))}${seg ? ` · levou ${esc(duracaoCurta(seg))}` : ""}${resumoHistorico(aba, p) ? ` · ${esc(resumoHistorico(aba, p))}` : ""}</p>`
    + `<div class="botoes"><button type="button" class="principal" data-acao="reusar" data-historico>Carregar estas configurações</button><button type="button" data-hist-ver>Ver em Projetos</button><button type="button" data-hist-fechar>Fechar</button>`
    + `${S.dados.tarefa?.rodando && S.dados.tarefa.projeto === p.nome ? "" : `<button type="button" class="simples perigo" data-acao="apagar" title="Apaga este resultado do disco (pergunta antes)">Descartar</button>`}</div>`;
  barra.hidden = false;
  marcarSelecionado(aba);
}
/* Só o destaque muda: redesenhar a faixa recarregaria as miniaturas e faria tudo piscar */
function marcarSelecionado(aba) {
  for (const b of $(`hist-${aba}`).querySelectorAll(".hist-item")) b.setAttribute("aria-pressed", String(b.dataset.histProjeto === S.previa[aba]));
}
function fecharPrevia(aba) {
  const previa = $(`previa-${aba}`);
  if (!previa) return;
  S.marcaPrevia = (S.marcaPrevia || 0) + 1;  // um carregamento pendente não reabre a prévia
  previa.querySelector("video")?.pause();
  previa.hidden = true;
  previa.innerHTML = "";
  for (const el of previa.parentElement.querySelectorAll("[data-previa-oculto]")) { el.hidden = false; delete el.dataset.previaOculto; }
  const barra = $(`hist-barra-${aba}`);
  barra.hidden = true;
  barra.innerHTML = "";
  delete S.previa[aba];
  marcarSelecionado(aba);
}

document.addEventListener("click", e => {
  const item = e.target.closest("[data-hist-projeto]");
  if (item) {
    const aba = item.dataset.histAba, nome = item.dataset.histProjeto;
    // Clicar de novo no item aberto fecha a prévia
    S.previa[aba] === nome ? fecharPrevia(aba) : mostrarPrevia(aba, nome);
    return;
  }
  const barra = e.target.closest(".hist-barra");
  if (!barra) return;
  const aba = barra.dataset.histBarra;
  if (e.target.closest("[data-hist-fechar]")) fecharPrevia(aba);
  else if (e.target.closest("[data-hist-ver]")) {
    const nome = barra.dataset.projetoAcao;
    S.abertos = new Set([nome]);
    S.rolar = nome;
    S.marcaProjetos = "";
    // Redesenha antes de mostrar a tela: sem nenhum aberto, a Biblioteca abriria o mais recente no lugar deste
    desenharProjetos(S.dados);
    irPara("projetos");
  }
});
document.addEventListener("change", e => {
  if (e.target.matches("[data-hist-todos]")) desenharHistorico(e.target.dataset.histTodos);
  else if (e.target.id === "i-modelo") desenharHistorico("imagem");
  else if (e.target.id === "t2i-modelo") desenharHistorico("texto");
});
