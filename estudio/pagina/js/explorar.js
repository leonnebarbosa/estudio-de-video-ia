/* Explorar (interface nova, no estilo do freefield): a entrada do estúdio. Cartões com o que dá para fazer, cada um com
   a mídia do último projeto daquele tipo, e uma grade com os feitos recentes. Tudo vem do /api/estado (S.dados). */
const MODOS_EXPLORAR = [
  { aba: "troca", tipo: "troca", selo: "Troca", titulo: "Troque quem está no vídeo", texto: "Outra pessoa no lugar, com os mesmos gestos, a boca e o áudio. Até 15 s, em janelas emendadas.", icone: "s-troca" },
  { aba: "imagem", tipo: "imagem", selo: "Vídeo", titulo: "Dê vida a uma foto", texto: "Movimento, fala e som a partir de uma imagem, em tomadas com a mesma voz.", icone: "s-imagem" },
  { aba: "tvideo", tipo: "imagem", sem_imagem: true, selo: "Texto", titulo: "Escreva e vire vídeo", texto: "Um vídeo com som só a partir do texto, sem imagem de partida.", icone: "s-tvideo" },
  { aba: "texto", tipo: "texto", selo: "Imagem", titulo: "Crie uma imagem", texto: "Descreva e gere fotos; dá para editar e usar como partida de um vídeo.", icone: "s-texto" },
  { aba: "novo", tipo: "continuar", selo: "Continuar", titulo: "Estenda um vídeo", texto: "Continua um vídeo seu em rodadas; a LLM local escreve cada trecho.", icone: "s-continuar" },
];

/* A mídia de um projeto para os cartões: o vídeo final ou a primeira imagem */
function midiaExplorar(p, cartao = false) {
  const nome = encodeURIComponent(p.nome);
  if (p.final) return midia(`<video muted loop playsinline preload="metadata" src="/video/${nome}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto", cartao ? "exp-fundo" : "");
  const img = p.imagens?.[0];
  if (img) return midia(`<img loading="lazy" src="/imagem/${nome}/${encodeURIComponent(img.arquivo)}?m=${img.marca}" alt="">`, "", cartao ? "exp-fundo" : "");
  return "";
}
const tipoDoProjeto = p => p.tipo === "imagem" && p.sem_imagem ? "tvideo" : p.tipo;
const ROTULO_TIPO = { troca: "Troca de personagem", imagem: "Imagem para vídeo", tvideo: "Texto para vídeo", texto: "Texto para imagem", continuar: "Continuar vídeo" };

function desenharExplorar() {
  const d = S.dados, secao = $("tela-explorar");
  if (!d || secao.hidden) return;
  // O irPara poe o andamento e o aviso de pacote no comeco da tela: o conteudo vai num bloco proprio para nao apaga-los
  let tela = secao.querySelector(":scope > .exp-conteudo");
  if (!tela) { tela = document.createElement("div"); tela.className = "exp-conteudo"; secao.append(tela); }
  const projetos = [...(d.projetos || [])].sort((a, b) => (b.quando || 0) - (a.quando || 0));
  const marca = JSON.stringify([projetos.map(p => [p.nome, p.final?.marca, p.imagens?.length]), Object.entries(d.abas || {}).map(([k, v]) => [k, v.pronto])]);
  if (marca === S.marcaExplorar && tela.childElementCount) return;
  S.marcaExplorar = marca;
  const ultimo = m => projetos.find(p => (m.sem_imagem ? tipoDoProjeto(p) === "tvideo" : tipoDoProjeto(p) === m.aba || p.tipo === m.tipo && m.aba !== "tvideo") && (p.final || p.imagens?.length));
  const cartoes = MODOS_EXPLORAR.map(m => {
    const p = ultimo(m), pronto = d.abas?.[m.aba]?.pronto !== false;
    return `<button type="button" class="exp-cartao" data-ir="${m.aba}">${p ? midiaExplorar(p, true) : `<span class="exp-fundo exp-vazio"><svg class="ico" aria-hidden="true"><use href="#${m.icone}"/></svg></span>`}
      <span class="exp-selo">${esc(m.selo)}</span>${pronto ? "" : `<span class="exp-selo exp-falta">Baixar modelos</span>`}
      <span class="exp-cartao-texto"><strong class="display">${esc(m.titulo)}</strong><small>${esc(m.texto)}</small></span></button>`;
  }).join("");
  const contar = aba => projetos.filter(p => tipoDoProjeto(p) === aba || (aba === "imagem" && tipoDoProjeto(p) === "imagem")).length;
  const blocos = [
    { aba: "texto", icone: "s-texto", nome: "Imagem", texto: "Texto para imagem, edição e troca em foto." },
    { aba: "imagem", icone: "s-imagem", nome: "Vídeo", texto: "Imagem para vídeo, texto para vídeo e continuar." },
    { aba: "troca", icone: "s-troca", nome: "Trocar personagem", texto: "Em vídeo ou em foto: rosto, roupa ou a pessoa inteira." },
    { aba: "projetos", icone: "s-projetos", nome: "Projetos", texto: "Tudo o que você já gerou, para ver, continuar ou apagar." },
    { aba: "modelos", icone: "s-modelos", nome: "Modelos", texto: "Os arquivos de modelo no computador e o espaço que ocupam." },
  ].map(b => `<button type="button" class="exp-bloco" data-ir="${b.aba}"><span class="exp-bloco-ico"><svg class="ico" aria-hidden="true"><use href="#${b.icone}"/></svg></span><strong>${esc(b.nome)}${b.aba !== "projetos" && b.aba !== "modelos" && contar(b.aba) ? ` <span class="exp-conta">${contar(b.aba)}</span>` : ""}${b.aba === "projetos" && projetos.length ? ` <span class="exp-conta">${projetos.length}</span>` : ""}</strong><small>${esc(b.texto)}</small></button>`).join("");
  const recentes = projetos.filter(p => p.final || p.imagens?.length).slice(0, 12).map(p =>
    `<button type="button" class="exp-recente" data-projeto="${esc(p.nome)}">${midiaExplorar(p)}<span class="exp-recente-nome">${esc(p.nome)}<small>${esc(ROTULO_TIPO[tipoDoProjeto(p)] || "")}</small></span></button>`).join("");
  tela.innerHTML = `<div class="exp">
    <div class="exp-faixa" aria-label="O que dá para fazer">${cartoes}</div>
    <div class="exp-meio">
      <section class="exp-heroi"><h2 class="display">Seu estúdio de <em>vídeo, imagem e troca</em>, neste computador</h2>
        <p>Cada função é um fluxo do ComfyUI com modelos abertos, rodando na sua placa. Nada sai daqui.</p>
        <div class="exp-acoes"><button type="button" class="principal" data-ir="texto">Começar a criar</button><button type="button" class="botao" data-ir="projetos">Ver projetos</button></div></section>
      <div class="exp-blocos">${blocos}</div>
    </div>
    ${recentes ? `<section class="exp-secao"><h2 class="display">Feitos recentemente</h2><div class="exp-grade">${recentes}</div></section>` : ""}
  </div>`;
}

$("tela-explorar").addEventListener("click", e => {
  const ir = e.target.closest("[data-ir]");
  if (ir) return irPara(ir.dataset.ir);
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
