/* Tela inicial (a marca Estúdio no menu): cartões com o que dá para fazer, cada um com a mídia do último projeto
   daquele tipo, e a galeria de tudo o que já foi gerado. Tudo vem do /api/estado (S.dados). */
const MODOS_EXPLORAR = [
  { aba: "troca", tipo: "troca", selo: "Troca", titulo: "Troque quem está no vídeo", texto: "Outra pessoa no lugar, com os mesmos gestos, a boca e o áudio. Até 15 s, em janelas emendadas.", icone: "s-troca" },
  { aba: "editar", tipo: "editar", selo: "Editar", titulo: "Mude o céu, o cenário ou um objeto", texto: "Tempestade, praia vazia, um monstro no mar: muda o vídeo e mantém as pessoas, os gestos e o som. Até 14 s.", icone: "s-editar" },
  { aba: "imagem", tipo: "imagem", selo: "Vídeo", titulo: "Dê vida a uma foto", texto: "Movimento, fala e som a partir de uma imagem, em tomadas com a mesma voz.", icone: "s-imagem" },
  { aba: "tvideo", tipo: "imagem", sem_imagem: true, selo: "Texto", titulo: "Escreva e vire vídeo", texto: "Um vídeo com som só a partir do texto, sem imagem de partida.", icone: "s-tvideo" },
  { aba: "texto", tipo: "texto", selo: "Imagem", titulo: "Crie uma imagem", texto: "Descreva e gere fotos; dá para editar e usar como partida de um vídeo.", icone: "s-texto" },
  { aba: "novo", tipo: "continuar", selo: "Continuar", titulo: "Estenda um vídeo", texto: "Continua um vídeo seu em rodadas; a LLM local escreve cada trecho.", icone: "s-continuar" },
];

/* A mídia de um projeto para os cartões: o vídeo final ou a primeira imagem. O #t=0.1 faz o navegador mostrar um quadro
   do vídeo parado; sem ele a miniatura ficava preta. */
function midiaExplorar(p, cartao = false) {
  const nome = encodeURIComponent(p.nome);
  if (p.final) return midia(`<video muted loop playsinline preload="none" data-capa src="/video/${nome}/final.mp4?m=${p.final.marca}#t=0.1"></video>`, "Vídeo oculto", cartao ? "exp-fundo" : "");
  const img = p.imagens?.[0];
  if (img) return midia(`<img loading="lazy" src="/imagem/${nome}/${encodeURIComponent(img.arquivo)}?m=${img.marca}" alt="">`, "", cartao ? "exp-fundo" : "");
  return "";
}
const tipoDoProjeto = p => p.config?.avancado ? "avancado" : p.tipo === "imagem" && p.sem_imagem ? "tvideo" : p.tipo;
const ROTULO_TIPO = { troca: "Troca de personagem", imagem: "Imagem para vídeo", tvideo: "Texto para vídeo", avancado: "Vídeo avançado", texto: "Texto para imagem", continuar: "Continuar vídeo", editar: "Editar vídeo" };

/* Galeria "Feitos" (reforma de 20/11/2026): tudo o que tem mídia, do mais novo ao mais antigo, com filtro por tipo.
   Cada projeto entra em um filtro só; tipo que a página não conhece aparece apenas em "Tudo". */
const FILTROS_GALERIA = [["tudo", "Tudo"], ["video", "Vídeo"], ["imagem", "Imagem"], ["troca", "Troca"]], FILTRO_GALERIA = "estudio_filtro_galeria";
function filtroDoProjeto(p) {
  if (p.tipo === "troca" || (p.tipo === "texto" && p.troca_foto)) return "troca";
  if (p.tipo === "texto") return "imagem";
  return ["imagem", "wan", "continuar", "editar"].includes(p.tipo) ? "video" : null;
}
function projetosDaGaleria(projetos, filtro) {
  return (projetos || []).filter(p => (p.final || p.imagens?.length) && (filtro === "tudo" || filtroDoProjeto(p) === filtro))
    .sort((a, b) => (b.quando || 0) - (a.quando || 0));
}
function filtroDaGaleria() {
  if (!S.filtroGaleria) {
    let salvo = null;
    try { salvo = localStorage.getItem(FILTRO_GALERIA); } catch {}
    S.filtroGaleria = FILTROS_GALERIA.some(([f]) => f === salvo) ? salvo : "tudo";
  }
  return S.filtroGaleria;
}

function desenharExplorar() {
  const d = S.dados, secao = $("tela-explorar");
  if (!d || secao.hidden) return;
  // O irPara poe o andamento e o aviso de pacote no comeco da tela: o conteudo vai num bloco proprio para nao apaga-los
  let tela = secao.querySelector(":scope > .exp-conteudo");
  if (!tela) { tela = document.createElement("div"); tela.className = "exp-conteudo"; secao.append(tela); }
  const projetos = [...(d.projetos || [])].sort((a, b) => (b.quando || 0) - (a.quando || 0)), filtro = filtroDaGaleria();
  const marca = JSON.stringify([filtro, projetos.map(p => [p.nome, p.final?.marca, p.imagens?.length]), Object.entries(d.abas || {}).map(([k, v]) => [k, v.pronto])]);
  if (marca === S.marcaExplorar && tela.childElementCount) return;
  S.marcaExplorar = marca;
  const ultimo = m => projetos.find(p => !p.config?.avancado && (m.sem_imagem ? tipoDoProjeto(p) === "tvideo" : tipoDoProjeto(p) === m.aba || p.tipo === m.tipo && m.aba !== "tvideo") && (p.final || p.imagens?.length));
  const cartoes = MODOS_EXPLORAR.map(m => {
    const p = ultimo(m), pronto = d.abas?.[m.aba]?.pronto !== false;
    return `<button type="button" class="exp-cartao" data-ir="${m.aba}">${p ? midiaExplorar(p, true) : `<span class="exp-fundo exp-vazio"><svg class="ico" aria-hidden="true"><use href="#${m.icone}"/></svg></span>`}
      <span class="exp-selo">${esc(m.selo)}</span>${pronto ? "" : `<span class="exp-selo exp-falta">Baixar modelos</span>`}
      <span class="exp-cartao-texto"><strong class="display">${esc(m.titulo)}</strong><small>${esc(m.texto)}</small></span></button>`;
  }).join("");
  const filtros = FILTROS_GALERIA.map(([f, nome]) => {
    const n = projetosDaGaleria(projetos, f).length;
    return `<button type="button" role="tab" data-filtro="${f}" aria-selected="${f === filtro}">${nome}${n ? ` <span class="exp-conta">${n}</span>` : ""}</button>`;
  }).join("");
  const feitos = projetosDaGaleria(projetos, filtro).map(p =>
    `<button type="button" class="exp-recente" data-projeto="${esc(p.nome)}">${midiaExplorar(p)}<span class="exp-recente-nome">${esc(p.nome)}<small>${esc(ROTULO_TIPO[tipoDoProjeto(p)] || "")}</small></span></button>`).join("");
  tela.innerHTML = `<div class="exp">
    <div class="exp-faixa" aria-label="O que dá para fazer">${cartoes}</div>
    <section class="exp-secao" aria-labelledby="exp-feitos">
      <div class="exp-topo"><h2 class="display" id="exp-feitos">Feitos</h2>
        <div class="modos exp-filtros" role="tablist" aria-label="Filtrar o que já foi gerado">${filtros}</div>
        <button type="button" class="simples" data-ir="projetos">Ver todos</button></div>
      ${feitos ? `<div class="exp-grade">${feitos}</div>` : `<p class="exp-nada">Nada gerado aqui ainda.</p>`}
    </section>
  </div>`;
  observarCapas(tela);
}

$("tela-explorar").addEventListener("click", e => {
  const ir = e.target.closest("[data-ir]");
  if (ir) return irPara(ir.dataset.ir);
  const f = e.target.closest("[data-filtro]");
  if (f) { S.filtroGaleria = f.dataset.filtro; try { localStorage.setItem(FILTRO_GALERIA, S.filtroGaleria); } catch {} return desenharExplorar(); }
  const p = e.target.closest(".exp-recente");
  if (p) { S.abertos = new Set([p.dataset.projeto]); S.marcaProjetos = null; if (S.dados) desenharProjetos(S.dados); irPara("projetos"); }
});
/* Os vídeos dos cartões tocam só com o mouse em cima: doze vídeos tocando juntos pesam e distraem */
for (const [tipo, tocar] of [["pointerover", true], ["pointerout", false]]) {
  $("tela-explorar").addEventListener(tipo, e => {
    const alvo = e.target.closest(".exp-cartao, .exp-recente"), v = alvo?.querySelector("video");
    if (!v || (e.relatedTarget && alvo.contains(e.relatedTarget))) return;
    if (tocar) v.play().catch(() => {}); else { v.pause(); }
  });
}
