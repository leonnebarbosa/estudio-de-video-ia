/* Personagens: a biblioteca (personagens.py no servidor). Criar com uma foto ou uma imagem recente, gerar os ângulos com o
   Klein, refazer um ângulo, apagar; e escolher um personagem na Trocar personagem e no Imagem para vídeo. */
const PERS = { lista: null, angulos: [], carregando: false, marca: "" };

async function carregarPersonagens() {
  if (PERS.carregando) return;
  PERS.carregando = true;
  try {
    const r = await fetch("/api/personagens");
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "Não foi possível listar os personagens.");
    PERS.lista = j.personagens;
    PERS.angulos = j.angulos;
    desenharPersonagens();
  } catch (e) {
    $("pers-lista").innerHTML = `<p class="vazio-lista">${esc(e.message)}</p>`;
  } finally {
    PERS.carregando = false;
  }
}
const gerandoAngulos = id => { const t = S.dados?.tarefa; return !!t?.rodando && t.tipo === "personagem" && (!id || t.projeto === id); };
function desenharPersonagens() {
  if (!PERS.lista) return;
  const marca = JSON.stringify([PERS.lista, S.dados?.tarefa?.rodando, S.dados?.tarefa?.projeto]);
  if (marca === PERS.marca) return;
  PERS.marca = marca;
  $("pers-lista").innerHTML = PERS.lista.length ? PERS.lista.map(desenharPersonagem).join("") : `<p class="vazio-lista">Nenhum personagem ainda. Crie o primeiro acima.</p>`;
}
function desenharPersonagem(p) {
  // Com outra geração rodando, gerar ou refazer vai para a fila; só os ângulos deste personagem em geração travam os botões
  const gerando = gerandoAngulos(p.id), ocupado = gerando, faltam = PERS.angulos.filter(a => !p.angulos[a.id]).length;
  const vistas = PERS.angulos.map(a => p.angulos[a.id]
    ? `<figure class="pers-vista"><button type="button" class="pers-ver" data-pers="ver" data-angulo="${a.id}" aria-label="Ver ${esc(a.nome.toLowerCase())} de ${esc(p.nome)} em tamanho grande"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/${a.id}.png?m=${p.marca}" alt="${esc(p.nome)}, ${esc(a.nome.toLowerCase())}"></span></button>
        <figcaption>${esc(a.nome)}${(p.enviadas || []).includes(a.id) ? " (foto)" : (p.referencias || []).includes(a.id) ? " (rosto da foto)" : ""}${a.id !== "frente" ? ` <button type="button" class="simples" data-pers="refazer" data-angulo="${a.id}"${ocupado ? " disabled" : ""}>Refazer</button>` : ""}</figcaption></figure>`
    : `<figure class="pers-vista falta"><span class="pers-vazio">${gerando ? "gerando" : "falta"}</span><figcaption>${esc(a.nome)}</figcaption></figure>`).join("");
  return `<article class="pers" data-pers-id="${esc(p.id)}">
    <div class="modelo-topo"><div class="modelo-nome"><strong>${esc(p.nome)}</strong>${p.descricao ? `<small>${esc(p.descricao)}</small>` : ""}</div><span class="modelo-tamanho">${PERS.angulos.length - faltam} de ${PERS.angulos.length} vistas</span></div>
    <div class="pers-vistas">${vistas}</div>
    <div class="botoes">
      ${faltam ? `<button type="button" data-pers="angulos"${ocupado ? " disabled" : ""}>${gerando ? "Gerando os ângulos" : `Gerar ${faltam === 1 ? "o ângulo que falta" : `os ${faltam} ângulos que faltam`}`}</button>` : ""}
      <button type="button" class="simples perigo" data-pers="apagar"${gerando ? " disabled" : ""}>Apagar</button>
    </div>
  </article>`;
}
async function acaoPersonagem(botao) {
  const caixa = botao.closest("[data-pers-id]"), id = caixa.dataset.persId, p = PERS.lista.find(x => x.id === id);
  if (botao.dataset.pers === "ver") { abrirVisor(id, botao.dataset.angulo); return; }
  try {
    if (botao.dataset.pers === "apagar") {
      if (!await perguntar(`Apagar o personagem ${p.nome} e as imagens dele? Os vídeos já feitos com ele continuam.`, "Apagar", "Cancelar")) return;
      await postar("/api/personagem-apagar", { id, confirmar: true });
      recado(`${p.nome} foi apagado.`, true);
    } else {
      botao.disabled = true;
      await postar("/api/personagem-angulos", botao.dataset.pers === "refazer" ? { id, angulo: botao.dataset.angulo } : { id });
      recado(vaiParaFila() ? `Os ângulos de ${p.nome} entraram na fila.` : `Gerando os ângulos de ${p.nome}.`, true);
    }
  } catch (e) { recado(e.message); botao.disabled = false; }
  PERS.marca = "";
  await consultar(true);
  carregarPersonagens();
}

/* Novo personagem */
function desenharRecentesPersonagem() {
  const sel = $("p-recente"), atual = sel.value;
  const imagens = (S.dados?.projetos || []).filter(p => p.tipo === "texto" && !p.troca_foto && p.imagens?.length)
    .flatMap(p => p.imagens.map(i => ({ valor: `${p.nome}/${i.arquivo}`, rotulo: `${p.nome}, ${i.arquivo.replace(/^imagem_(\d+)\.png$/, "imagem $1")}` }))).slice(0, 40);
  const marca = imagens.map(i => i.valor).join("|");
  if (sel.dataset.marca === marca) return;
  sel.dataset.marca = marca;
  sel.innerHTML = `<option value="">Nenhuma</option>` + imagens.map(i => `<option value="${esc(i.valor)}"${i.valor === atual ? " selected" : ""}>${esc(i.rotulo)}</option>`).join("");
}
/* Fotos reais dos outros ângulos (opcionais): a caixa de envio e o ângulo que ela preenche */
const ENVIO_ANGULO = { ptres: "tres_quartos", pperfil: "perfil", pcostas: "costas" };
const anguloEnviados = () => Object.keys(ENVIO_ANGULO).filter(t => S[t]);
function atualizarPersonagemNovo() {
  desenharRecentesPersonagem();
  $("tirar-pfoto").hidden = !S.pfoto;
  for (const t of Object.keys(ENVIO_ANGULO)) $(`tirar-${t}`).hidden = !S[t];
  // Jeito 1: a foto de três quartos ou de perfil é só a referência do rosto, e o Klein gera o ângulo mesmo assim; só as costas entram como vieram
  const tem = !!S.pfoto || !!$("p-recente").value, gerar = 3 - (S.pcostas ? 1 : 0);
  $("p-criar").disabled = !tem || !$("p-nome").value.trim() || !$("p-autorizacao").checked || S.enviando > 0;
  $("p-criar").textContent = !$("p-angulos").checked || !gerar ? "Criar personagem" : gerar === 3 ? "Criar e gerar os ângulos" : gerar === 1 ? "Criar e gerar o ângulo que falta" : `Criar e gerar os ${gerar} ângulos que faltam`;
}
async function criarPersonagem(e) {
  e.preventDefault();
  $("p-erro").hidden = true;
  $("p-criar").disabled = true;
  const recente = $("p-recente").value, [projeto, imagem] = recente ? recente.split("/") : [], ocupado = !!S.dados?.tarefa?.rodando;
  const fotos = Object.fromEntries(anguloEnviados().map(t => [ENVIO_ANGULO[t], S[t].arquivo])), angulos = $("p-angulos").checked;
  // Rosto tirado do vídeo: o lado para onde a pessoa olha já foi medido no quadro inteiro (espelhar a referência sem detectar de novo)
  const lados = Object.fromEntries(anguloEnviados().filter(t => typeof S[t].direita === "boolean").map(t => [ENVIO_ANGULO[t], S[t].direita]));
  try {
    await postar("/api/personagem-criar", { nome: $("p-nome").value, descricao: $("p-descricao").value, autorizacao: $("p-autorizacao").checked,
      angulos, fotos, lados, ...(S.pfoto ? { foto: S.pfoto.arquivo } : { projeto, imagem }) });
    recado(!angulos ? "Personagem criado." : ocupado || vaiParaFila() ? "Personagem criado. Os ângulos entraram na fila e começam depois da geração atual." : "Personagem criado. Gerando os ângulos que faltam.", true);
    for (const t of ["pfoto", ...Object.keys(ENVIO_ANGULO)]) { S[t] = null; $(t).value = ""; limparZona(t); }
    tirarVideoPersonagem();
    $("p-nome").value = $("p-descricao").value = ""; $("p-recente").value = "";
  } catch (err) {
    $("p-erro").textContent = err.message;
    $("p-erro").hidden = false;
  }
  PERS.marca = "";
  await consultar(true);
  carregarPersonagens();
  atualizarPersonagemNovo();
}

/* Rostos de um vídeo (rostos_video.py no servidor): os melhores de cada ângulo; um clique põe o rosto na vaga do ângulo.
   Três quartos e perfil viram referência de rosto do Klein; a frente usa o quadro inteiro. */
const VAGA_ROSTO = { frente: "pfoto", tres_quartos: "ptres", perfil: "pperfil" };
const NOMES_ROSTO = { frente: "Frente", tres_quartos: "Três quartos", perfil: "Perfil" };
async function aoEscolherVideoPersonagem(r) {
  const caixa = $("p-rostos");
  PERS.rostos = null;
  caixa.hidden = false;
  caixa.innerHTML = `<p class="ajuda">Procurando rostos no vídeo… Leva uns 15 s.</p>`;
  $("tirar-pvideo").hidden = false;
  try {
    const resp = await postar("/api/personagem-rostos", { video: r.arquivo });
    if (S.pvideo?.arquivo !== r.arquivo) return;  // trocou ou tirou o vídeo enquanto procurava
    PERS.rostos = resp;
    desenharRostos(resp);
  } catch (e) {
    if (S.pvideo?.arquivo !== r.arquivo) return;  // a falha é de um vídeo que já foi trocado: não esconde os rostos do novo
    caixa.hidden = true;
    $("pvideo-aviso").textContent = e.message;
    $("pvideo-aviso").hidden = false;
  }
}
function desenharRostos(resp) {
  $("p-rostos").hidden = false;
  $("p-rostos").innerHTML = Object.keys(VAGA_ROSTO).map(a => {
    const lista = resp[a] || [], outro = a === "perfil" ? "tres_quartos" : "perfil";
    const itens = lista.map((c, i) => `<div class="pers-rosto">
        <button type="button" class="pers-rosto-usar" data-rosto="${a}" data-i="${i}" aria-label="Usar o rosto de ${num(c.t)} s como ${esc(NOMES_ROSTO[a].toLowerCase())}"><img loading="lazy" src="${esc(c.url)}" alt=""><small>${num(c.t)} s</small></button>
        ${a !== "frente" ? `<button type="button" class="simples" data-rosto="${a}" data-i="${i}" data-como="${outro}">Usar como ${esc(NOMES_ROSTO[outro].toLowerCase())}</button>` : ""}
      </div>`).join("");
    const aviso = a === "frente" && resp.legenda && lista.length ? `<p class="ajuda">A legenda do vídeo vai junto na foto de frente; prefira uma foto sem texto.</p>` : "";
    return `<div class="pers-rostos-fileira"><span class="rotulo">${NOMES_ROSTO[a]}</span>${aviso}${lista.length ? `<div class="pers-rostos-lista">${itens}</div>` : `<p class="vazio-lista">Nenhum rosto bom desse ângulo no vídeo.</p>`}</div>`;
  }).join("");
}
async function usarRosto(angulo, cand) {
  const t = VAGA_ROSTO[angulo], frente = angulo === "frente";
  if (frente && (S.pfoto || $("p-recente").value)) { recado("Tire a foto de frente antes de usar a do vídeo."); return; }
  try {
    const arquivo = frente ? cand.quadro : cand.arquivo;
    const r = await postar("/api/personagem-rosto-usar", { pasta: PERS.rostos.pasta, arquivo });
    S[t] = null; $(t).value = ""; limparZona(t);
    S[t] = r;
    mostrarEscolhido(t, r, `Do vídeo, ${num(cand.t)} s`, frente ? cand.url_quadro : cand.url);
  } catch (e) { recado(e.message); }
  atualizarPersonagemNovo();
}
function tirarVideoPersonagem() {
  S.pvideo = null; PERS.rostos = null;
  $("pvideo").value = ""; limparZona("pvideo");
  $("p-rostos").hidden = true; $("p-rostos").innerHTML = "";
  $("tirar-pvideo").hidden = true;
}
$("p-rostos").addEventListener("click", e => {
  const b = e.target.closest("[data-rosto]");
  if (!b || !PERS.rostos) return;
  const cand = PERS.rostos[b.dataset.rosto]?.[Number(b.dataset.i)];
  if (cand) usarRosto(b.dataset.como || b.dataset.rosto, cand);
});
$("tirar-pvideo").addEventListener("click", tirarVideoPersonagem);

/* Escolher um personagem em outra tela: devolve o que /api/personagem-usar respondeu, ou null */
async function escolherPersonagem(opcoes = {}) {
  await carregarPersonagens();
  const d = $("dialogo-personagem"), lista = PERS.lista || [];
  $("dp-lista").innerHTML = lista.length ? lista.map(p => `<button type="button" class="dp-item" data-id="${esc(p.id)}"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/frente.png?m=${p.marca}" alt=""></span><span><strong>${esc(p.nome)}</strong><small>${PERS.angulos.filter(a => p.angulos[a.id]).length} de ${PERS.angulos.length} vistas${p.descricao ? `. ${esc(p.descricao)}` : ""}</small></span></button>`).join("")
    : `<p class="vazio-lista">Nenhum personagem ainda. Crie na aba Personagens.</p>`;
  const id = await new Promise(ok => {
    const fim = v => { d.close(); ok(v); };
    $("dp-lista").onclick = e => { const b = e.target.closest("[data-id]"); if (b) fim(b.dataset.id); };
    $("dp-fechar").onclick = () => fim(null);
    d.oncancel = e => { e.preventDefault(); fim(null); };
    d.showModal();
  });
  if (!id) return null;
  try { return await postar("/api/personagem-usar", { id, ...opcoes }); } catch (e) { recado(e.message); return null; }
}
/* Trocar personagem (vídeo): a frente vira a foto; os outros ângulos vão como referências extras (opção) */
async function usarPersonagemTroca() {
  const r = await escolherPersonagem();
  if (!r) return;
  preencherArquivo("tfoto", { arquivo: r.foto });
  S.tpersonagem = r;
  desenharPersonagemTroca();
  atualizarTroca();
}
function desenharPersonagemTroca() {
  const caixa = $("t-personagem");
  // Se a foto mudou depois de escolher, o personagem não vale mais
  if (S.tpersonagem && S.tfoto?.arquivo !== S.tpersonagem.foto) S.tpersonagem = null;
  const r = S.tpersonagem;
  caixa.hidden = !r;
  if (!r) { caixa.innerHTML = ""; caixa.dataset.id = ""; return; }
  const n = r.angulos.length;
  if (caixa.dataset.id === r.foto) return;
  caixa.dataset.id = r.foto;
  caixa.innerHTML = `<p><strong>${esc(r.nome)}</strong>, da biblioteca.</p>${n ? `<label class="marcar"><input type="checkbox" id="t-pers-angulos"><span>Mandar também os outros ângulos como referências extras</span></label><p class="ajuda">Experimental. Nos testes de 17/11 deu resultado misto: os cachos de uma senhora ficaram mais fiéis, mas a nuca de um homem de cabeça raspada ganhou cabelo. Uns 40 s a mais.</p>` : `<p class="ajuda">Este personagem ainda não tem os outros ângulos.</p>`}`;
}
/* O que a Trocar personagem manda junto quando a foto é de um personagem da biblioteca */
const personagemDaTroca = () => S.tpersonagem && S.tfoto?.arquivo === S.tpersonagem.foto ? { personagem: { id: S.tpersonagem.id, angulos: !!$("t-pers-angulos")?.checked } } : {};
/* Imagem para vídeo: a frente e os ângulos viram os outros ângulos do personagem; sem imagem principal, a frente vira ela */
async function usarPersonagemImagem() {
  const r = await escolherPersonagem();
  if (!r) return;
  const max = S.dados?.imagem?.max_referencias || 4;
  S.irefs = [r.foto, ...r.angulos].slice(0, max);
  desenharRefs();
  if (!S.ifoto) { preencherArquivo("ifoto", { arquivo: r.foto }); depoisDeEscolher("ifoto", S.ifoto); }
  recado(`${r.nome}: ${S.irefs.length} vistas nos outros ângulos do personagem.`, true);
  atualizarImagem();
}

$("tela-personagens").addEventListener("click", e => { const b = e.target.closest("[data-pers]"); if (b) acaoPersonagem(b); });
$("pers-novo").addEventListener("submit", criarPersonagem);
for (const t of ["pfoto", ...Object.keys(ENVIO_ANGULO)]) $(`tirar-${t}`).addEventListener("click", () => { S[t] = null; $(t).value = ""; limparZona(t); atualizarPersonagemNovo(); });

/* Ver as vistas em tamanho grande: clique numa vista da biblioteca; as setas (ou ← e →) passam pelas vistas de todos os
   personagens, na ordem dos cartões; Esc ou um clique fora da foto fecha */
const VISOR = { lista: [], i: 0 };
function abrirVisor(id, angulo) {
  VISOR.lista = PERS.lista.flatMap(p => PERS.angulos.filter(a => p.angulos[a.id]).map(a => ({ id: p.id, angulo: a.id, nome: p.nome, rotulo: a.nome,
    origem: (p.enviadas || []).includes(a.id) ? " (foto enviada)" : (p.referencias || []).includes(a.id) ? " (rosto da foto)" : "", src: `/personagem/${encodeURIComponent(p.id)}/${a.id}.png?m=${p.marca}` })));
  VISOR.i = Math.max(0, VISOR.lista.findIndex(v => v.id === id && v.angulo === angulo));
  mostrarVisor();
  if (!$("visor").open) $("visor").showModal();
}
function mostrarVisor() {
  const v = VISOR.lista[VISOR.i], n = VISOR.lista.length;
  if (!v) return;
  $("visor-img").src = v.src;
  $("visor-img").alt = `${v.nome}, ${v.rotulo.toLowerCase()}`;
  $("visor-legenda").textContent = `${v.nome} · ${v.rotulo}${v.origem} · ${VISOR.i + 1} de ${n}`;
  $("visor-ant").hidden = $("visor-prox").hidden = n < 2;
}
const passarVisor = d => { const n = VISOR.lista.length; if (n) { VISOR.i = (VISOR.i + d + n) % n; mostrarVisor(); } };
$("visor-ant").addEventListener("click", () => passarVisor(-1));
$("visor-prox").addEventListener("click", () => passarVisor(1));
$("visor-fechar").addEventListener("click", () => $("visor").close());
$("visor").addEventListener("keydown", e => { if (e.key === "ArrowLeft") { e.preventDefault(); passarVisor(-1); } else if (e.key === "ArrowRight") { e.preventDefault(); passarVisor(1); } });
$("visor").addEventListener("click", e => { if (e.target === $("visor") || e.target.tagName === "FIGURE") $("visor").close(); });
$("pers-novo").addEventListener("input", atualizarPersonagemNovo);
$("pers-novo").addEventListener("change", atualizarPersonagemNovo);
$("t-usar-personagem").addEventListener("click", usarPersonagemTroca);
$("i-usar-personagem").addEventListener("click", usarPersonagemImagem);

/* Andamento da geração dos ângulos: um ângulo de cada vez, uns 45 s cada (o script escreve "ângulo X" e, pronto, "ângulo X: N s") */
function desenharAndamentoPersonagem(t) {
  const caixa = $("andamento");
  const mostrar = t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo);
  if (!mostrar) { caixa.hidden = true; document.title = TITULO; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  const p = PERS.lista?.find(x => x.id === t.projeto), nome = p?.nome || t.projeto;
  const linhas = (t.registro || "").split("\n"), feitos = linhas.filter(l => /^ângulo .+: \d+ s/.test(l)).length;
  const total = Math.max(1, Number((t.registro || "").match(/^(\d+) ângulos a gerar/m)?.[1]) || 3);
  const atual = [...linhas].reverse().find(l => /^ângulo [^:]+$/.test(l));
  const pct = Math.min(99, Math.floor(feitos / total * 100));
  S.relogio = t.rodando ? { total: t.segundos, etapa: 0, quando: Date.now() } : null;
  document.title = t.rodando ? `${pct}%, ângulos de ${nome} – ${TITULO}` : TITULO;
  const marca = JSON.stringify([t.rodando, t.codigo, t.registro]);
  if (marca === S.marcaAndamento) { atualizarPlaca(t); return; }
  S.marcaAndamento = marca;
  const aberto = caixa.querySelector("details")?.open;
  let h = "", anuncio;
  if (t.rodando) {
    anuncio = atual ? `Gerando o ${atual.replace(/^ângulo /, "")}` : "Preparando";
    const faixas = Array.from({ length: total }, (_, i) => `<span class="${i < feitos ? "feita" : i === feitos ? "atual vivo" : ""}" style="flex:1 1 0"></span>`).join("");
    h += `<div class="cabeca"><div><p class="grande">Ângulos de ${esc(nome)}</p><p>${esc(anuncio)} (${Math.min(feitos + 1, total)} de ${total}).</p></div><span class="pct" id="pct">${pct}%</span></div>`;
    h += `<div class="barra" role="progressbar" aria-label="Progresso dos ângulos" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita">${faixas}</div></div>`;
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div></dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
  } else {
    anuncio = t.parada ? "Geração dos ângulos parada. Os prontos ficaram guardados." : mensagemFim(t).replace(/ As rodadas prontas.*$/, " Os ângulos prontos ficaram guardados.");
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}"><button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
