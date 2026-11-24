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
const urlFichaPersonagem = p => `/personagem/${encodeURIComponent(p.id)}/ficha.png?m=${p.folha}`;
const VISTAS_FICHA = { frente: "Corpo inteiro de frente", rosto: "Rosto de frente", perfil: "Rosto de perfil", costas: "Corpo inteiro de costas" };
const urlVistaFicha = (p, vista) => `/personagem/${encodeURIComponent(p.id)}/ficha_${vista}.png?m=${p.ficha_vistas[vista]}`;
const urlFichaH3 = p => `/personagem/${encodeURIComponent(p.id)}/ficha_h3.png?m=${p.ficha_h3}`;

// Ficha de 6 vistas pelo H3 (ficha_personagem.gerar_h3): sai da frente aprovada, numa imagem só, uns 7 min na 3080
function desenharFichaH3(p, ocupado) {
  if (!p.ficha_aprovada) return "";
  const imagem = p.ficha_h3 ? `<button class="pers-ver pers-ficha" type="button" data-pers="ver-ficha-h3" aria-label="Ampliar a ficha de 6 vistas de ${esc(p.nome)}">
    ${midia(`<img loading="lazy" src="${urlFichaH3(p)}" alt="Ficha de 6 vistas de ${esc(p.nome)}">`, "Ficha oculta")}</button>` : "";
  // O título vem do <summary> da seção recolhida; apagar fica no menu ⋯ do personagem
  return `<section class="pers-montagem" aria-label="Ficha de 6 vistas pelo H3">
    <p class="legenda">Close, corpo de frente, de lado e de costas, perfil e três-quartos numa imagem só, a partir da frente aprovada. Leva uns 7 minutos.</p>
    ${imagem}
    <div class="botoes">
      <button type="button" class="botao" data-pers="ficha" data-vista="h3"${ocupado ? " disabled" : ""}>${p.ficha_h3 ? "Refazer ficha de 6 vistas" : "Gerar ficha de 6 vistas"}</button>
      ${p.ficha_h3 ? `<a class="simples pers-baixar" href="${urlFichaH3(p)}" download="${esc(p.id)}_ficha_h3.png">Baixar PNG</a>` : ""}
    </div>
  </section>`;
}

// Fotos de expressão (personagens.py): até 3 fotos da mesma pessoa com expressões diferentes. Na troca pelo Viggle ou pelo Wan
// Animate 2, cada quadro pintado leva a de expressão mais parecida com o quadro original (troca_wangp.escolher_cabecas)
const MAX_EXPRESSOES = 3;
function desenharExpressoes(pessoa, ocupado) {
  const fotos = PERS.lista.find(x => x.id === pessoa.id)?.expressoes || [];
  const itens = fotos.map((f, k) => `<figure class="pers-vista">${midia(`<img loading="lazy" src="/personagem/${encodeURIComponent(pessoa.id)}/${f.arquivo}?m=${f.marca}" alt="Foto de expressão ${k + 1} de ${esc(pessoa.nome)}">`, "Foto oculta")}
    <figcaption><button type="button" class="simples" data-pers="apagar-expressao" data-arquivo="${f.arquivo}"${ocupado ? " disabled" : ""}>Apagar</button></figcaption></figure>`).join("");
  return `<section class="pers-montagem" aria-label="Fotos de expressão">
    <p class="legenda">Até ${MAX_EXPRESSOES} fotos da mesma pessoa, de frente, com expressões diferentes: uma neutra e uma com sorriso leve já bastam. Na troca pelo Viggle ou pelo Wan Animate 2, cada quadro usa a foto de expressão mais parecida com a do vídeo, e só a cabeça entra. Use fotos com a pele natural e o cabelo no comprimento do cabelo de quem está no vídeo. Com fotos aqui, a foto principal não é usada nesses dois motores.</p>
    ${itens ? `<div class="pers-vistas">${itens}</div>` : ""}
    <div class="botoes">${fotos.length < MAX_EXPRESSOES ? `<button type="button" class="botao" data-pers="enviar-expressao"${ocupado ? " disabled" : ""}>Enviar foto de expressão</button>` : `<span>Limite de ${MAX_EXPRESSOES} fotos. Apague uma para enviar outra.</span>`}</div>
  </section>`;
}

function desenharVistasFicha(p, ocupado) {
  const vistas = p.ficha_vistas || {}, desativado = ocupado ? " disabled" : "";
  const mostrar = p.ficha_aprovada ? Object.keys(VISTAS_FICHA) : ["frente"];
  return `<section class="pers-montagem" aria-label="Vistas da ficha">
    <div class="pers-vistas">${mostrar.map(vista => {
      const nome = VISTAS_FICHA[vista];
      const imagem = vistas[vista]
        ? `<button class="pers-ver" type="button" data-pers="ver-vista" data-vista="${vista}">${midia(`<img loading="lazy" src="${urlVistaFicha(p, vista)}" alt="${nome}">`, "Foto oculta")}</button>`
        : `<span class="pers-vazio">A gerar</span>`;
      return `<figure class="pers-vista"><figcaption>${nome}</figcaption>${imagem}
        <div class="botoes">
          ${vistas[vista] ? `<button type="button" class="simples" data-pers="ficha" data-vista="${vista}"${desativado}>Refazer</button>` : ""}
          <button type="button" class="simples" data-pers="enviar-vista" data-vista="${vista}"${desativado}>${vistas[vista] ? "Trocar por foto" : "Usar foto"}</button>
        </div></figure>`;
    }).join("")}</div>
    ${!p.ficha_aprovada ? `<div class="botoes">
      <button type="button" class="simples" data-pers="ficha" data-vista="usar-base"${desativado}>Usar imagem-base como frente</button>
      <button type="button" class="simples" data-pers="enviar-vista" data-vista="roupa"${desativado}>${p.ficha_roupa ? "Trocar referência da roupa" : "Adicionar referência da roupa"}</button>
      ${vistas.frente ? `<button type="button" class="principal" data-pers="ficha" data-vista="aprovar"${desativado}>Aprovar frente e gerar vistas</button>` : ""}
    </div>` : ""}
  </section>`;
}
/* Biblioteca (21/11/2026): um personagem por vez, com os visuais (roupas) em abas. Lista (coluna estreita + o personagem
   aberto) ou galeria (grade; abrir ocupa a largura toda, com "← Biblioteca"). O modo e o último personagem/visual aberto
   ficam no localStorage só por conveniência: sem ele (janela anônima, bloqueado) a página abre na lista, no primeiro. */
const PERS_MODO = "pers_modo", PERS_ABERTO = "pers_aberto";
PERS.modo = (() => { try { return localStorage.getItem(PERS_MODO) === "galeria" ? "galeria" : "lista"; } catch { return "lista"; } })();
PERS.aberto = (() => {
  try {
    const v = localStorage.getItem(PERS_ABERTO) || "", i = v.indexOf("|");   // "|" não cabe em nome de pasta no Windows
    return i > 0 ? { pessoa: v.slice(0, i), visual: v.slice(i + 1) } : null;
  } catch { return null; }
})();
PERS.galeriaAberta = false;   // na galeria nada abre sozinho, como em Projetos
PERS.novoAberto = false;      // o formulário "Novo personagem" no lugar do personagem aberto
function guardarAberto(pessoa, visual) {
  PERS.aberto = { pessoa, visual };
  try { localStorage.setItem(PERS_ABERTO, `${pessoa}|${visual}`); } catch {}
}
function guardarModo(modo) {
  PERS.modo = modo;
  try { localStorage.setItem(PERS_MODO, modo); } catch {}
}
/* A pessoa e o visual abertos: o guardado, se ainda existe; procura também pelo visual, porque apagar o Original promove
   o visual mais antigo e o id da pessoa muda. Sem nada guardado, o primeiro personagem, no Original. */
function abertoAgora(pessoas) {
  const a = PERS.aberto;
  const pessoa = (a && (pessoas.find(x => x.id === a.pessoa) || pessoas.find(x => x.visuais.some(v => v.id === a.visual)))) || pessoas[0];
  if (!pessoa) return null;
  return { pessoa, visual: pessoa.visuais.find(v => v.id === a?.visual) || pessoa.visuais[0] };
}
const pessoaDe = id => agruparPessoas(PERS.lista || []).find(x => x.visuais.some(v => v.id === id));
// Com outra geração rodando, gerar ou refazer vai para a fila; só a geração deste visual (rodando ou na fila) trava os botões
function ocupacao(id) {
  const gerando = gerandoAngulos(id), emFila = S.dados?.fila?.itens?.find(i => i.tipo === "personagem" && i.projeto === id);
  return { gerando, modo: gerando ? S.dados?.tarefa?.modo : emFila?.modo, ocupado: gerando || !!emFila };
}
const VAZIO_PERS = `<p class="vazio-lista">Nenhum personagem ainda. Clique em Novo personagem para criar o primeiro.</p>`;
function desenharPersonagens() {
  if (!PERS.lista) return;
  const marca = JSON.stringify([PERS.lista, S.dados?.tarefa?.rodando, S.dados?.tarefa?.projeto, S.dados?.tarefa?.modo, S.dados?.fila?.itens,
    PERS.modo, PERS.aberto, PERS.galeriaAberta, PERS.novoAberto]);
  if (marca === PERS.marca) return;
  PERS.marca = marca;
  const pessoas = agruparPessoas(PERS.lista), atual = abertoAgora(pessoas), galeria = PERS.modo === "galeria";
  const mostrar = !galeria || PERS.galeriaAberta;   // a área do personagem aberto (ou do formulário) aparece
  $("pers-biblioteca").classList.toggle("modo-galeria", galeria);
  document.querySelectorAll("[data-modo-pers]").forEach(b => b.setAttribute("aria-pressed", b.dataset.modoPers === PERS.modo));
  $("pers-coluna").hidden = galeria && mostrar;
  $("pers-principal").hidden = !mostrar;
  $("pers-voltar").hidden = !galeria;
  $("pers-novo").hidden = !PERS.novoAberto;
  $("pers-detalhe").hidden = PERS.novoAberto;
  const marcado = !galeria && !PERS.novoAberto && atual?.pessoa.id;
  $("pers-lista").innerHTML = pessoas.length ? pessoas.map(x => itemPessoa(x, x.id === marcado)).join("") : VAZIO_PERS;
  if (!PERS.novoAberto) desenharDetalhe(atual);
}
/* Na lista, uma linha; na galeria, um cartão (o CSS muda o desenho): a frente do Original, o nome e quantos visuais */
function itemPessoa(x, atual) {
  const raiz = PERS.lista.find(p => p.id === x.capa), n = x.visuais.length;
  return `<button type="button" class="pers-item" data-abrir-pessoa="${esc(x.id)}"${atual ? ` aria-current="true"` : ""}>
    <span class="pers-capa">${midia(`<img loading="lazy" src="/personagem/${encodeURIComponent(x.capa)}/frente.png?m=${raiz?.marca}" alt="">`, "Foto oculta")}</span>
    <span class="pers-item-texto"><strong>${esc(x.nome)}</strong><small>${n === 1 ? "1 visual" : `${n} visuais`}</small></span></button>`;
}
function desenharDetalhe(atual) {
  const caixa = $("pers-detalhe");
  if (!atual) { caixa.innerHTML = ""; return; }   // biblioteca vazia: o aviso já aparece na lista, não repete aqui
  // Redesenhar (a cada mudança da fila) não pode fechar o que o usuário abriu: as seções recolhidas e o menu ⋯
  const abertas = new Set([...caixa.querySelectorAll("details[data-secao][open]")].map(d => d.dataset.secao));
  caixa.innerHTML = desenharPersonagem(PERS.lista.find(p => p.id === atual.visual.id), atual.pessoa);
  caixa.querySelectorAll("details[data-secao]").forEach(d => { if (abertas.has(d.dataset.secao)) d.open = true; });
}
/* O personagem aberto: cabeçalho com o menu ⋯ (os apagar ficam só ali, longe dos botões comuns), as abas dos visuais e o
   conteúdo do visual escolhido */
function desenharPersonagem(p, pessoa) {
  const { gerando, modo, ocupado } = ocupacao(p.id);
  // Raiz não pronta é um visual promovido (o Original foi apagado): precisa aprovar a frente como qualquer cópia
  const copia = p.id !== pessoa.id || !p.pronto;
  const algumOcupado = pessoa.visuais.some(v => ocupacao(v.id).ocupado);
  const fichaEmCurso = modo?.startsWith("ficha"), faltam = PERS.angulos.filter(a => !p.angulos[a.id]).length;
  const temFrente = !!p.ficha_vistas?.frente;
  const faltaVista = Object.keys(p.ficha_vistas || {}).length < Object.keys(VISTAS_FICHA).length;
  // Visual sem frente aprovada: o fluxo de aprovação fica aberto (numa cópia, sempre: ela só vale depois de aprovar)
  const fluxo = !p.ficha_aprovada && (temFrente || fichaEmCurso || copia);
  const desativado = on => on ? " disabled" : "";
  const menu = [
    p.folha ? `<button type="button" class="pers-menu-item" data-pers="apagar-parte" data-parte="ficha"${desativado(ocupado)}>Apagar ficha</button>` : "",
    p.ficha_h3 ? `<button type="button" class="pers-menu-item" data-pers="apagar-parte" data-parte="h3"${desativado(ocupado)}>Apagar ficha de 6 vistas</button>` : "",
    pessoa.visuais.length > 1 ? `<button type="button" class="pers-menu-item" data-pers="apagar-parte" data-parte="visual"${desativado(ocupado)}>Apagar este visual</button>` : "",
    `<button type="button" class="pers-menu-item" data-pers="apagar"${desativado(algumOcupado)}>Apagar personagem</button>`,
  ].join("");
  const abas = pessoa.visuais.map(v => `<button type="button" data-abrir-visual="${esc(v.id)}" aria-pressed="${v.id === p.id}"${v.pronto ? "" : ` title="Aprove a frente deste visual para usá-lo na Trocar personagem e no Vídeo"`}>${esc(v.rotulo)}${v.pronto ? "" : `<span class="pers-pendente"> · a aprovar</span>`}</button>`).join("");
  const ampliar = (acao, src, alt, extra = "") => `<button class="pers-ver pers-imagem" type="button" data-pers="${acao}"${extra} aria-label="Ampliar: ${esc(alt)}">${midia(`<img loading="lazy" src="${src}" alt="${esc(alt)}">`, "Foto oculta")}</button>`;
  // Imagem principal: a ficha 2x2; sem ela, a frente aprovada; sem fluxo de aprovação aberto, a imagem-base
  const principal = p.folha ? ampliar("ver-ficha", urlFichaPersonagem(p), `Ficha de ${p.nome}`)
    : p.ficha_aprovada && temFrente ? ampliar("ver-vista", urlVistaFicha(p, "frente"), `${p.nome}, ${VISTAS_FICHA.frente.toLowerCase()}`, ` data-vista="frente"`)
    : !fluxo ? ampliar("ver-base", `/personagem/${encodeURIComponent(p.id)}/frente.png?m=${p.marca}`, `${p.nome}, imagem-base`) : "";
  const status = !ocupado ? "" : fichaEmCurso ? (modo === "ficha-h3" ? (gerando ? "Gerando a ficha pelo H3…" : "Ficha do H3 na fila") : (gerando ? "Gerando vistas da ficha…" : "Ficha na fila"))
    : gerando ? "Gerando os ângulos…" : "Ângulos na fila";
  const vistas = PERS.angulos.map(a => p.angulos[a.id]
    ? `<figure class="pers-vista"><button type="button" class="pers-ver" data-pers="ver" data-angulo="${a.id}" aria-label="Ver ${esc(a.nome.toLowerCase())} de ${esc(p.nome)} em tamanho grande"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/${a.id}.png?m=${p.marca}" alt="${esc(p.nome)}, ${esc(a.nome.toLowerCase())}"></span></button>
        <figcaption>${esc(a.nome)}${(p.enviadas || []).includes(a.id) ? " (foto)" : (p.referencias || []).includes(a.id) ? " (rosto da foto)" : ""}${a.id !== "frente" ? ` <button type="button" class="simples" data-pers="refazer" data-angulo="${a.id}"${ocupado ? " disabled" : ""}>Refazer</button>` : ""}</figcaption></figure>`
    : p.folha ? "" : `<figure class="pers-vista falta"><span class="pers-vazio">${gerando && !fichaEmCurso ? "gerando" : "falta"}</span><figcaption>${esc(a.nome)}</figcaption></figure>`).join("");
  const avulsos = `<div class="pers-vistas">${vistas}</div>
    ${faltam ? `<button type="button" class="simples" data-pers="angulos"${desativado(ocupado)}>Gerar os ângulos que faltam</button>` : ""}`;
  const h3 = desenharFichaH3(p, ocupado);
  const descricao = PERS.lista.find(x => x.id === pessoa.id)?.descricao;
  return `<article class="pers" data-pers-id="${esc(p.id)}" data-pessoa="${esc(pessoa.id)}">
    <div class="pers-cabeca">
      <div class="modelo-nome"><h2>${esc(pessoa.nome)}</h2>${descricao ? `<small>${esc(descricao)}</small>` : ""}</div>
      <details class="pers-menu" data-secao="menu"><summary aria-label="Mais ações de ${esc(pessoa.nome)}" title="Mais ações">⋯</summary>
        <div class="pers-menu-lista">${menu}</div></details>
    </div>
    <div class="modos pers-abas" role="group" aria-label="Visuais de ${esc(pessoa.nome)}">${abas}<button type="button" data-pers="novo-visual"><svg class="ico" aria-hidden="true"><use href="#s-mais"/></svg>Novo visual</button></div>
    ${principal}
    <div class="botoes">
      ${status ? `<span role="status">${status}</span>` : ""}
      ${!temFrente || (p.ficha_aprovada && faltaVista) ? `<button type="button" class="botao" data-pers="ficha" data-vista="${temFrente ? "completar" : "frente"}"${desativado(ocupado)}>${temFrente ? "Gerar vistas restantes" : "Preparar frente da ficha"}</button>` : ""}
      ${p.folha ? `<a class="simples pers-baixar" href="${urlFichaPersonagem(p)}" download="${esc(p.id)}_ficha.png">Baixar PNG</a>` : ""}
      ${p.ficha_aprovada && !p.ficha_h3 ? `<button type="button" class="simples" data-pers="ficha" data-vista="h3"${desativado(ocupado)}>Gerar ficha de 6 vistas</button>` : ""}
    </div>
    ${fluxo ? `${copia ? `<p class="legenda">Aprove a frente deste visual para usá-lo na Trocar personagem e no Vídeo.</p>` : ""}${desenharVistasFicha(p, ocupado)}`
      : `<details class="pers-avulsos" data-secao="vistas"><summary>Vistas da ficha</summary>${desenharVistasFicha(p, ocupado)}</details>`}
    ${h3 ? `<details class="pers-avulsos" data-secao="h3"><summary>Ficha de 6 vistas</summary>${h3}</details>` : ""}
    <details class="pers-avulsos" data-secao="expressoes"><summary>Fotos de expressão</summary>${desenharExpressoes(pessoa, ocupado)}</details>
    <details class="pers-avulsos" data-secao="base"><summary>Imagem-base e ângulos</summary>${avulsos}</details>
  </article>`;
}
async function acaoPersonagem(botao) {
  const caixa = botao.closest("[data-pers-id]"), id = caixa.dataset.persId, p = PERS.lista.find(x => x.id === id);
  const pessoa = pessoaDe(id), rotulo = pessoa?.visuais.find(v => v.id === id)?.rotulo || p.nome;
  botao.closest(".pers-menu")?.removeAttribute("open");   // escolheu no menu ⋯: ele fecha antes da confirmação
  if (botao.dataset.pers === "ver") { abrirVisor(id, botao.dataset.angulo); return; }
  if (botao.dataset.pers === "enviar-expressao") {
    const seletor = $("pers-ficha-arquivo");
    seletor.onchange = async () => {
      const arquivo = seletor.files[0];
      seletor.value = "";
      if (!arquivo) return;
      botao.disabled = true;
      try {
        const r = await enviar(arquivo, "foto", () => {});
        await postar("/api/personagem-expressao", { id: pessoa.id, foto: r.arquivo });
        recado("Foto de expressão salva.", true);
        PERS.marca = "";
        await carregarPersonagens();
      } catch (e) { recado(e.message); botao.disabled = false; }
    };
    seletor.click();
    return;
  }
  if (botao.dataset.pers === "apagar-expressao") {
    botao.disabled = true;
    try {
      await postar("/api/personagem-expressao", { id: pessoa.id, apagar: botao.dataset.arquivo });
      recado("Foto de expressão apagada.", true);
      PERS.marca = "";
      await carregarPersonagens();
    } catch (e) { recado(e.message); botao.disabled = false; }
    return;
  }
  if (botao.dataset.pers === "ver-ficha") {
    abrirVisorCom([{ src: urlFichaPersonagem(p), nome: p.nome, rotulo: "Ficha de personagem", origem: "" }], 0);
    return;
  }
  if (botao.dataset.pers === "ver-base") {
    abrirVisorCom([{ src: `/personagem/${encodeURIComponent(id)}/frente.png?m=${p.marca}`, nome: p.nome, rotulo: "Imagem-base", origem: "" }], 0);
    return;
  }
  if (botao.dataset.pers === "novo-visual") { abrirNovaRoupa(p, pessoa); return; }
  if (botao.dataset.pers === "ver-ficha-h3") {
    abrirVisorCom([{ src: urlFichaH3(p), nome: p.nome, rotulo: "Ficha de 6 vistas (H3)", origem: "" }], 0);
    return;
  }
  const vista = botao.dataset.vista;
  if (botao.dataset.pers === "ver-vista") {
    abrirVisorCom([{ src: urlVistaFicha(p, vista), nome: p.nome, rotulo: VISTAS_FICHA[vista], origem: "" }], 0);
    return;
  }
  if (botao.dataset.pers === "enviar-vista") {
    const seletor = $("pers-ficha-arquivo");
    seletor.onchange = async () => {
      const arquivo = seletor.files[0];
      seletor.value = "";
      if (!arquivo) return;
      botao.disabled = true;
      try {
        const r = await enviar(arquivo, "foto", () => {});
        await postar("/api/personagem-ficha", { id, etapa: vista, foto: r.arquivo });
        recado(vista === "roupa" ? "Referência salva. Gere a frente para aplicar a roupa." : "Foto salva na ficha.", true);
        PERS.marca = "";
        await carregarPersonagens();
      } catch (e) { recado(e.message); botao.disabled = false; }
    };
    seletor.click();
    return;
  }
  try {
    if (botao.dataset.pers === "apagar") {
      // Sem `parte`, o servidor apaga a pessoa e todos os visuais dela: a confirmação diz quantos são
      const n = pessoa.visuais.length, nome = pessoa.nome;
      const texto = n === 1 ? `Apagar o personagem ${nome} e as imagens dele? Os vídeos já feitos com ele continuam.`
        : `Apagar o personagem ${nome} com os ${n} visuais (${pessoa.visuais.map(v => v.rotulo).join(", ")}) e as imagens deles? Os vídeos já feitos continuam.`;
      if (!await perguntar(texto, n === 1 ? "Apagar" : `Apagar os ${n}`, "Cancelar")) return;
      await postar("/api/personagem-apagar", { id: pessoa.id, confirmar: true });
      if (PERS.aberto?.pessoa === pessoa.id) PERS.aberto = null;
      PERS.galeriaAberta = false;
      recado(`${nome} foi apagado.`, true);
    } else if (botao.dataset.pers === "apagar-parte" && botao.dataset.parte === "visual") {
      // Apagar o Original promove o visual mais antigo (a ordem das abas): ele vira a raiz e o personagem mantém o nome
      const original = id === pessoa.id, proximo = pessoa.visuais.find(v => v.id !== id);
      const texto = original ? `Apagar o visual ${rotulo} de ${pessoa.nome}? O visual ${proximo.rotulo}, o mais antigo, passa a ser o principal e o personagem continua se chamando ${pessoa.nome}. Os vídeos já feitos continuam.`
        : `Apagar o visual ${rotulo} de ${pessoa.nome} e as imagens dele? Os outros visuais e os vídeos já feitos continuam.`;
      if (!await perguntar(texto, "Apagar", "Cancelar")) return;
      await postar("/api/personagem-apagar", { id, confirmar: true, parte: "visual" });
      guardarAberto(original ? proximo.id : pessoa.id, original ? proximo.id : pessoa.id);
      recado(`Visual ${rotulo} apagado.`, true);
    } else if (botao.dataset.pers === "apagar-parte") {
      const h3 = botao.dataset.parte === "h3";
      const texto = h3 ? `Apagar a ficha de 6 vistas de ${p.nome}? O personagem e a ficha de cima continuam.`
        : `Apagar a ficha de ${p.nome}, com o rosto, o perfil e as costas gerados? A frente continua, para aprovar e gerar de novo.`;
      if (!await perguntar(texto, "Apagar", "Cancelar")) return;
      await postar("/api/personagem-apagar", { id, confirmar: true, parte: botao.dataset.parte });
      recado(h3 ? "Ficha de 6 vistas apagada." : "Ficha apagada. A frente continua para aprovar de novo.", true);
    } else if (botao.dataset.pers === "ficha") {
      botao.disabled = true;
      const r = await postar("/api/personagem-ficha", { id, etapa: vista, marca: p.ficha_vistas?.frente });
      recado(vista === "usar-base" ? "Imagem-base pronta para aprovação." : r.fila ? "O pedido entrou na fila." :
        vista === "h3" ? "Gerando a ficha de 6 vistas pelo H3. Leva uns 7 minutos." : "Preparando as vistas da ficha.", true);
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

/* Novo visual: o mesmo personagem com a roupa nova (texto e/ou foto), numa aba nova. Parte do visual aberto (a frente e o
   corpo dele); o servidor dá o nome da pasta ("{pessoa} ({visual})"), liga a cópia à pessoa e já prepara a frente da ficha. */
function abrirNovaRoupa(p, pessoa) {
  const d = $("dialogo-roupa"), seletor = $("dr-foto");
  let foto = null;
  $("dr-visual").value = "";
  $("dr-ajuda").textContent = `O mesmo rosto e cabelo de ${pessoa.nome} com a roupa nova, numa aba nova. Os outros visuais continuam iguais.`;
  $("dr-roupa").value = "";
  $("dr-foto-nome").textContent = "Pode ser outra pessoa vestindo a roupa.";
  $("dr-erro").hidden = true;
  $("dr-criar").disabled = false;
  const erro = texto => { $("dr-erro").textContent = texto; $("dr-erro").hidden = false; };
  $("dr-foto-botao").onclick = () => seletor.click();
  seletor.onchange = async () => {
    const arquivo = seletor.files[0];
    seletor.value = "";
    if (!arquivo) return;
    $("dr-foto-nome").textContent = `Enviando ${arquivo.name}…`;
    try {
      foto = (await enviar(arquivo, "foto", () => {})).arquivo;
      $("dr-foto-nome").textContent = arquivo.name;
    } catch (e) { foto = null; $("dr-foto-nome").textContent = "Pode ser outra pessoa vestindo a roupa."; erro(e.message); }
  };
  $("dr-cancelar").onclick = () => d.close();
  $("dr-form").onsubmit = async e => {
    e.preventDefault();
    const roupa = $("dr-roupa").value.trim(), visual = $("dr-visual").value.trim().replace(/\s+/g, " ");
    // O nome do visual é o rótulo da aba: sem ele, ou repetido, as abas ficariam ambíguas
    if (!visual) { erro("Dê um nome ao visual, como Biquíni ou Terno."); return; }
    if (pessoa.visuais.some(v => v.rotulo.toLowerCase() === visual.toLowerCase())) { erro(`${pessoa.nome} já tem um visual ${visual}.`); return; }
    if (!roupa && !foto) { erro("Descreva a roupa nova ou escolha uma foto dela."); return; }
    $("dr-criar").disabled = true;
    try {
      const r = await postar("/api/personagem-nova-roupa", { id: p.id, roupa, visual, ...(foto ? { foto } : {}) });
      d.close();
      guardarAberto(pessoa.id, r.id);   // abre a aba nova, onde a frente vai aparecer para aprovar
      recado(r.fila ? `Visual ${visual} criado. A frente com a roupa nova entrou na fila.` : `Visual ${visual} criado. Preparando a frente com a roupa nova.`, true);
      PERS.marca = "";
      await consultar(true);
      carregarPersonagens();
    } catch (err) { erro(err.message); $("dr-criar").disabled = false; }
  };
  d.showModal();
  $("dr-visual").focus();
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
  // Preparar a frente: a foto de frente mudou (outra foto, outra imagem recente, tirada) e não é a original nem a opção escolhida
  const f = PERS.frente, chave = chaveFrente();
  if (f.partida && chave !== f.partida && chave !== f.escolhida) limparFrente();
  $("p-preparar").disabled = !tem || f.preparando || S.enviando > 0 || (!$("p-roupa").value.trim() && fundoFrente() === "manter");
  $("p-preparar").textContent = f.preparando ? "Preparando… (1 a 2 min)" : f.opcoes.length ? "Gerar outras 2" : "Preparar a frente";
  $("p-criar").disabled = !tem || !$("p-nome").value.trim() || S.enviando > 0 || f.preparando || PERS.criando;
  const formato = $("p-formato").value;
  $("p-formato-ajuda").hidden = formato !== "ficha";
  $("p-ficha-base-campo").hidden = formato !== "ficha";
  $("p-criar").textContent = formato === "ficha" ? ($("p-ficha-base").checked ? "Criar e revisar frente" : "Criar e preparar frente") :
    formato === "angulos" && gerar ? "Criar e gerar os ângulos" : "Criar personagem";
}
async function criarPersonagem(e) {
  e.preventDefault();
  if ($("p-criar").disabled) return;
  PERS.criando = true;
  $("p-erro").hidden = true;
  $("p-criar").disabled = true;
  const recente = $("p-recente").value, [projeto, imagem] = recente ? recente.split("/") : [], ocupado = !!S.dados?.tarefa?.rodando;
  const formato = $("p-formato").value, ficha = formato === "ficha", angulos = formato === "angulos";
  const usarBase = ficha && $("p-ficha-base").checked;
  const fotos = Object.fromEntries(anguloEnviados().map(t => [ENVIO_ANGULO[t], S[t].arquivo]));
  // Rosto tirado do vídeo: o lado para onde a pessoa olha já foi medido no quadro inteiro (espelhar a referência sem detectar de novo)
  const lados = Object.fromEntries(anguloEnviados().filter(t => typeof S[t].direita === "boolean").map(t => [ENVIO_ANGULO[t], S[t].direita]));
  try {
    const r = await postar("/api/personagem-criar", { nome: $("p-nome").value, descricao: $("p-descricao").value,
      ficha, angulos, usar_base: usarBase, fotos, lados, ...(S.pfoto ? { foto: S.pfoto.arquivo } : { projeto, imagem }) });
    // Criado: o formulário fecha e o personagem novo abre (na galeria, na largura toda)
    guardarAberto(r.id, r.id);
    PERS.novoAberto = false;
    if (PERS.modo === "galeria") PERS.galeriaAberta = true;
    recado(usarBase ? "Personagem criado. Revise a frente na biblioteca." :
      ficha ? (r.fila ? "Personagem criado. A frente entrou na fila." : "Personagem criado. Preparando a frente para aprovação.") :
      !angulos ? "Personagem criado." : ocupado || vaiParaFila() ? "Personagem criado. Os ângulos entraram na fila." : "Personagem criado. Gerando os ângulos que faltam.", true);
    for (const t of ["pfoto", ...Object.keys(ENVIO_ANGULO)]) { S[t] = null; $(t).value = ""; limparZona(t); }
    tirarVideoPersonagem();
    $("p-nome").value = $("p-descricao").value = $("p-roupa").value = ""; $("p-recente").value = "";
    $("p-ficha-base").checked = false;
    limparFrente();
  } catch (err) {
    $("p-erro").textContent = err.message;
    $("p-erro").hidden = false;
  } finally {
    PERS.criando = false;
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

/* Preparar a frente (personagens.preparar_frente no servidor): o Klein troca a roupa e/ou põe o fundo cinza em 2 opções e a
   escolhida vira a foto de frente. Preparar de novo parte sempre da foto original (partida), não da opção escolhida: as edições
   não se acumulam. Trocar ou tirar a foto de frente descarta as opções. */
PERS.frente = { original: null, codigo: null, opcoes: [], escolhida: null, partida: null, preparando: false, vez: 0 };
const chaveFrente = () => S.pfoto?.arquivo || $("p-recente").value || "";
const fundoFrente = () => $("p-frente").querySelector("[data-fundo][aria-pressed='true']")?.dataset.fundo || "cinza";
function partidaFrente() {
  const o = PERS.frente.original, pfoto = o ? o.pfoto : S.pfoto, recente = o ? o.recente : $("p-recente").value;
  if (pfoto) return { chave: pfoto.arquivo, dados: { foto: pfoto.arquivo } };
  const [projeto, imagem] = (recente || "").split("/");
  return projeto ? { chave: recente, dados: { projeto, imagem } } : null;
}
function desenharFrente() {
  const f = PERS.frente, caixa = $("p-frente-opcoes");
  caixa.hidden = !f.opcoes.length;
  caixa.innerHTML = f.opcoes.map((o, i) => `<div class="pers-frente-opcao">
      <button type="button" class="pintura-opcao" data-frente="${i}" aria-pressed="${o.arquivo === f.escolhida}">${midia(`<img src="${esc(o.url)}" alt="Opção ${i + 1}">`, "Imagem oculta")}<span>Opção ${i + 1}${o.arquivo === f.escolhida ? " · escolhida" : ""}</span></button>
      <button type="button" class="simples" data-ampliar="${i}">Ampliar</button>
    </div>`).join("");
  $("p-frente-voltar").hidden = !f.original;
}
function limparFrente() {
  const f = PERS.frente;
  Object.assign(f, { original: null, codigo: null, opcoes: [], escolhida: null, partida: null, vez: f.vez + 1 });
  $("p-frente-aviso").hidden = true;
  desenharFrente();
}
async function prepararFrente() {
  const f = PERS.frente, partida = partidaFrente(), roupa = $("p-roupa").value.trim();
  if (!partida || f.preparando) return;
  const vez = ++f.vez;
  f.partida = partida.chave;
  f.preparando = true;
  $("p-frente-aviso").hidden = true;
  atualizarPersonagemNovo();
  try {
    const r = await postar("/api/personagem-frente", { ...partida.dados, roupa, fundo: fundoFrente(), codigo: f.codigo });
    if (vez !== f.vez) return;  // trocou ou tirou a foto de frente enquanto o Klein trabalhava
    f.codigo = r.codigo;
    f.opcoes = [...r.opcoes, ...f.opcoes].slice(0, 6);
    desenharFrente();
    recado(roupa && !r.ia ? `Pronto em ${tempo(r.segundos)}, com a roupa em português (a IA não respondeu). Confira o rosto e escolha uma opção.`
                          : `Pronto em ${tempo(r.segundos)}. Confira o rosto e escolha uma opção.`, true);
  } catch (e) {
    if (vez !== f.vez) return;
    $("p-frente-aviso").textContent = e.message;
    $("p-frente-aviso").hidden = false;
  } finally {
    f.preparando = false;
    atualizarPersonagemNovo();
  }
}
function escolherFrente(i) {
  const f = PERS.frente, op = f.opcoes[i];
  if (!op) return;
  // A primeira escolha guarda a foto de antes, para o "Voltar à foto original" e para preparar de novo a partir dela
  if (!f.original) f.original = { pfoto: S.pfoto, recente: $("p-recente").value, nome: $("pfoto-texto").querySelector("strong")?.textContent || "",
                                  url: $("zona-pfoto").querySelector(".midia img")?.src || "" };
  limparZona("pfoto");
  $("pfoto").value = ""; $("p-recente").value = "";
  S.pfoto = { arquivo: op.arquivo };
  f.escolhida = op.arquivo;
  mostrarEscolhido("pfoto", S.pfoto, "Frente preparada", op.url);
  desenharFrente();
  atualizarPersonagemNovo();
}
function voltarFrenteOriginal() {
  const f = PERS.frente, o = f.original;
  if (!o) return;
  limparZona("pfoto");
  S.pfoto = o.pfoto; $("p-recente").value = o.recente;
  if (o.pfoto) mostrarEscolhido("pfoto", o.pfoto, o.nome, o.url);
  f.original = null; f.escolhida = null;
  desenharFrente();
  atualizarPersonagemNovo();
}
$("p-preparar").addEventListener("click", prepararFrente);
$("p-frente-voltar").addEventListener("click", voltarFrenteOriginal);
$("p-frente-opcoes").addEventListener("click", e => {
  const ampliar = e.target.closest("[data-ampliar]"), opcao = e.target.closest("[data-frente]");
  if (ampliar) abrirVisorCom(PERS.frente.opcoes.map((o, i) => ({ src: o.url, nome: "Frente preparada", rotulo: `Opção ${i + 1}`, origem: "" })), Number(ampliar.dataset.ampliar));
  else if (opcao) escolherFrente(Number(opcao.dataset.frente));
});
$("p-frente").querySelectorAll("[data-fundo]").forEach(b => b.addEventListener("click", () => {
  $("p-frente").querySelectorAll("[data-fundo]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  atualizarPersonagemNovo();
}));
// Enter na roupa prepara a frente (sem isto, o Enter enviaria o formulário e criaria o personagem)
$("p-roupa").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); if (!$("p-preparar").disabled) prepararFrente(); } });

/* Escolher um personagem em outra tela: devolve o que /api/personagem-usar respondeu, ou null */
async function escolherPersonagem(opcoes = {}) {
  await carregarPersonagens();
  const d = $("dialogo-personagem"), lista = PERS.lista || [], porId = new Map(lista.map(p => [p.id, p]));
  // Só as pessoas com ao menos um visual pronto entram no seletor
  const pessoas = agruparPessoas(lista).filter(p => visuaisProntos(p).length);
  const cartaPessoa = p => { const r = porId.get(p.id), n = visuaisProntos(p).length; return `<button type="button" class="dp-item" data-pessoa="${esc(p.id)}"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/frente.png?m=${r.marca}" alt=""></span><span><strong>${esc(p.nome)}</strong><small>${PERS.angulos.filter(a => r.angulos[a.id]).length} de ${PERS.angulos.length} vistas${n > 1 ? `. ${n} visuais` : ""}${r.descricao ? `. ${esc(r.descricao)}` : ""}</small></span></button>`; };
  // Miniatura do visual: a frente da ficha quando aprovada, senão a frente
  const cartaVisual = v => { const r = porId.get(v.id), img = r.ficha_aprovada && r.ficha_vistas?.frente ? urlVistaFicha(r, "frente") : `/personagem/${encodeURIComponent(v.id)}/frente.png?m=${r.marca}`; return `<button type="button" class="dp-item" data-id="${esc(v.id)}"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="${img}" alt=""></span><span><strong>${esc(v.rotulo || "Original")}</strong></span></button>`; };
  const desenharPessoas = () => { $("dp-titulo").innerHTML = "<strong>Escolha um personagem</strong>"; $("dp-lista").innerHTML = pessoas.length ? pessoas.map(cartaPessoa).join("") : `<p class="vazio-lista">Nenhum personagem pronto ainda. Crie e aprove a frente em Personagem, no menu.</p>`; };
  const desenharVisuais = p => { $("dp-titulo").innerHTML = `<strong>${esc(p.nome)}: escolha o visual</strong>`; $("dp-lista").innerHTML = `<button type="button" class="botao" data-voltar>← Voltar</button>` + visuaisProntos(p).map(cartaVisual).join(""); };
  desenharPessoas();
  const id = await new Promise(ok => {
    const fim = v => { d.close(); ok(v); };
    $("dp-lista").onclick = e => {
      if (e.target.closest("[data-voltar]")) return desenharPessoas();
      const v = e.target.closest("[data-id]");
      if (v) return fim(v.dataset.id);
      const b = e.target.closest("[data-pessoa]");
      if (!b) return;
      const p = pessoas.find(x => x.id === b.dataset.pessoa);
      if (passosDoSeletor(p) === "direto") fim(visuaisProntos(p)[0].id);
      else desenharVisuais(p);
    };
    $("dp-fechar").onclick = () => fim(null);
    d.oncancel = e => { e.preventDefault(); fim(null); };
    d.showModal();
  });
  if (!id) return null;
  try {
    const r = await postar("/api/personagem-usar", { id, ...opcoes });
    // Com mais de um visual, o nome mostra pessoa · visual
    const pessoa = pessoas.find(p => p.id === porId.get(id)?.pessoa);
    if (pessoa && visuaisProntos(pessoa).length > 1) r.nome = `${pessoa.nome} · ${pessoa.visuais.find(v => v.id === id)?.rotulo || "Original"}`;
    return r;
  } catch (e) { recado(e.message); return null; }
}
/* Trocar personagem (vídeo): a frente vira a foto; os outros ângulos vão como referências extras (opção) */
async function usarPersonagemTroca() {
  // Roupa do vídeo: só a cabeça da foto; roupa da foto: o corpo inteiro (como em lerTroca)
  const r = await escolherPersonagem({ modo: $("t-roupa").value === "video" ? "cabeca" : "corpo" });
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
  const r = await escolherPersonagem({ modo: "corpo" });
  if (!r) return;
  const max = S.dados?.imagem?.max_referencias || 4;
  S.irefs = [r.foto, ...r.angulos].slice(0, max);
  desenharRefs();
  if (!S.ifoto) { preencherArquivo("ifoto", { arquivo: r.foto }); depoisDeEscolher("ifoto", S.ifoto); }
  recado(`${r.nome}: ${S.irefs.length} vistas nos outros ângulos do personagem.`, true);
  atualizarImagem();
}

$("tela-personagens").addEventListener("click", e => { const b = e.target.closest("[data-pers]"); if (b) acaoPersonagem(b); });
/* Navegar na biblioteca: modo lista/galeria, abrir um personagem, trocar de aba de visual, Novo personagem e voltar */
function abrirNovoPersonagem(abrir) {
  PERS.novoAberto = abrir;
  if (PERS.modo === "galeria") PERS.galeriaAberta = abrir;
  desenharPersonagens();
  if (abrir) { atualizarPersonagemNovo(); $("pers-novo").scrollIntoView({ block: "start" }); $("p-nome").focus({ preventScroll: true }); }
}
$("tela-personagens").addEventListener("click", e => {
  const modo = e.target.closest("[data-modo-pers]"), pessoa = e.target.closest("[data-abrir-pessoa]"), visual = e.target.closest("[data-abrir-visual]");
  if (modo) { guardarModo(modo.dataset.modoPers); PERS.galeriaAberta = false; }
  else if (pessoa) {
    // Reabrir o mesmo personagem volta na aba em que estava; outro abre no Original
    const id = pessoa.dataset.abrirPessoa;
    guardarAberto(id, PERS.aberto?.pessoa === id ? PERS.aberto.visual : id);
    PERS.novoAberto = false;
    PERS.galeriaAberta = true;
  } else if (visual) guardarAberto(visual.closest("[data-pessoa]").dataset.pessoa, visual.dataset.abrirVisual);
  else return;
  desenharPersonagens();
});
$("pers-novo-abrir").addEventListener("click", () => abrirNovoPersonagem(true));
$("pers-novo-fechar").addEventListener("click", () => abrirNovoPersonagem(false));
$("pers-voltar").addEventListener("click", () => { PERS.novoAberto = false; PERS.galeriaAberta = false; desenharPersonagens(); });
// Clique fora do menu ⋯ aberto fecha o menu
document.addEventListener("click", e => {
  const aberto = document.querySelector("#pers-detalhe .pers-menu[open]");
  if (aberto && !aberto.contains(e.target)) aberto.removeAttribute("open");
});
// Na galeria, Esc fecha o personagem aberto e volta para a grade, como em Projetos
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || S.aba !== "personagens" || document.querySelector("dialog[open]") || e.target.closest?.("input, textarea, select")) return;
  const menu = document.querySelector("#pers-detalhe .pers-menu[open]");
  if (menu) { menu.removeAttribute("open"); return; }
  if (PERS.modo === "galeria" && PERS.galeriaAberta) { PERS.novoAberto = false; PERS.galeriaAberta = false; desenharPersonagens(); }
});
$("pers-novo").addEventListener("submit", criarPersonagem);
for (const t of ["pfoto", ...Object.keys(ENVIO_ANGULO)]) $(`tirar-${t}`).addEventListener("click", () => { S[t] = null; $(t).value = ""; limparZona(t); atualizarPersonagemNovo(); });

/* Ver as vistas em tamanho grande: clique numa vista da biblioteca; as setas (ou ← e →) passam pelas vistas de todos os
   personagens, na ordem dos cartões; Esc ou um clique fora da foto fecha */
const VISOR = { lista: [], i: 0 };
function abrirVisor(id, angulo) {
  const lista = PERS.lista.flatMap(p => PERS.angulos.filter(a => p.angulos[a.id]).map(a => ({ id: p.id, angulo: a.id, nome: p.nome, rotulo: a.nome,
    origem: (p.enviadas || []).includes(a.id) ? " (foto enviada)" : (p.referencias || []).includes(a.id) ? " (rosto da foto)" : "", src: `/personagem/${encodeURIComponent(p.id)}/${a.id}.png?m=${p.marca}` })));
  abrirVisorCom(lista, Math.max(0, lista.findIndex(v => v.id === id && v.angulo === angulo)));
}
/* O visor com qualquer lista de {src, nome, rotulo, origem}: as vistas da biblioteca ou as opções do Preparar a frente */
function abrirVisorCom(lista, i) {
  VISOR.lista = lista;
  VISOR.i = i;
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
  if (t.modo?.startsWith("ficha")) {
    desenharAndamentoFicha(t, nome, caixa);
    return;
  }
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

function desenharAndamentoFicha(t, nome, caixa) {
  const titulo = `Ficha de ${nome}`;
  const emCurso = (t.registro || "").match(/Gerando vista (\w+)/g)?.at(-1)?.split(" ").at(-1);
  const anuncio = t.rodando ? (t.modo === "ficha-h3" ? "Gerando a ficha de 6 vistas pelo H3 (uns 7 minutos)." :
    emCurso ? `Gerando ${VISTAS_FICHA[emCurso]?.toLowerCase() || "vista"}.` : "Preparando as vistas.") : t.parada ? "Geração da ficha parada." :
    mensagemFim(t).replace(/ As rodadas prontas.*$/, " Você pode tentar de novo na biblioteca.");
  document.title = t.rodando ? `${titulo} – ${TITULO}` : TITULO;
  S.relogio = t.rodando ? { total: t.segundos, etapa: 0, quando: Date.now() } : null;
  const marca = JSON.stringify([t.modo, t.rodando, t.codigo, t.registro]);
  if (marca === S.marcaAndamento) { atualizarPlaca(t); return; }
  S.marcaAndamento = marca;
  const aberto = caixa.querySelector("details")?.open;
  caixa.innerHTML = (t.rodando
    ? `<div class="cabeca"><div><p class="grande">${esc(titulo)}</p><p>${anuncio}</p></div></div>
      <div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div></dl>
      <div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`
    : `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}"><button type="button" data-acao="dispensar">Fechar aviso</button></div>`)
    + blocoRegistro(t, aberto);
  atualizarPlaca(t);
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
