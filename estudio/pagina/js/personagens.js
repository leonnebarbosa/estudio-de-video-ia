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
function desenharPersonagens() {
  if (!PERS.lista) return;
  const marca = JSON.stringify([PERS.lista, S.dados?.tarefa?.rodando, S.dados?.tarefa?.projeto, S.dados?.tarefa?.modo, S.dados?.fila?.itens]);
  if (marca === PERS.marca) return;
  PERS.marca = marca;
  $("pers-lista").innerHTML = PERS.lista.length ? PERS.lista.map(desenharPersonagem).join("") : `<p class="vazio-lista">Nenhum personagem ainda. Crie o primeiro acima.</p>`;
}
function desenharPersonagem(p) {
  // Com outra geração rodando, gerar ou refazer vai para a fila; só os ângulos deste personagem em geração travam os botões
  const gerando = gerandoAngulos(p.id), emFila = S.dados?.fila?.itens?.find(i => i.tipo === "personagem" && i.projeto === p.id);
  const modo = gerando ? S.dados?.tarefa?.modo : emFila?.modo, ocupado = gerando || !!emFila;
  const fichaEmCurso = modo?.startsWith("ficha"), faltam = PERS.angulos.filter(a => !p.angulos[a.id]).length;
  const temFrente = !!p.ficha_vistas?.frente;
  const faltaVista = Object.keys(p.ficha_vistas || {}).length < Object.keys(VISTAS_FICHA).length;
  const vistas = PERS.angulos.map(a => p.angulos[a.id]
    ? `<figure class="pers-vista"><button type="button" class="pers-ver" data-pers="ver" data-angulo="${a.id}" aria-label="Ver ${esc(a.nome.toLowerCase())} de ${esc(p.nome)} em tamanho grande"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/${a.id}.png?m=${p.marca}" alt="${esc(p.nome)}, ${esc(a.nome.toLowerCase())}"></span></button>
        <figcaption>${esc(a.nome)}${(p.enviadas || []).includes(a.id) ? " (foto)" : (p.referencias || []).includes(a.id) ? " (rosto da foto)" : ""}${a.id !== "frente" ? ` <button type="button" class="simples" data-pers="refazer" data-angulo="${a.id}"${ocupado ? " disabled" : ""}>Refazer</button>` : ""}</figcaption></figure>`
    : p.folha ? "" : `<figure class="pers-vista falta"><span class="pers-vazio">${gerando && !fichaEmCurso ? "gerando" : "falta"}</span><figcaption>${esc(a.nome)}</figcaption></figure>`).join("");
  const avulsos = `<div class="pers-vistas">${vistas}</div>
    ${faltam ? `<button type="button" class="simples" data-pers="angulos"${ocupado ? " disabled" : ""}>Gerar os ângulos que faltam</button>` : ""}`;
  const ficha = p.folha ? `<button class="pers-ver pers-ficha" type="button" data-pers="ver-ficha" aria-label="Ampliar ficha de ${esc(p.nome)}">
    ${midia(`<img loading="lazy" src="${urlFichaPersonagem(p)}" alt="Ficha de ${esc(p.nome)}">`, "Ficha oculta")}</button>` : "";
  return `<article class="pers" data-pers-id="${esc(p.id)}">
    <div class="modelo-topo"><div class="modelo-nome"><strong>${esc(p.nome)}</strong>${p.descricao ? `<small>${esc(p.descricao)}</small>` : ""}</div>
      <span class="modelo-tamanho">${p.folha ? "Ficha de personagem" : `${PERS.angulos.length - faltam} de ${PERS.angulos.length} vistas`}</span></div>
    ${ficha}
    <div class="botoes">
      ${fichaEmCurso ? `<span role="status">${gerando ? "Gerando vistas da ficha…" : "Ficha na fila"}</span>` : ""}
      ${!temFrente || (p.ficha_aprovada && faltaVista) ? `<button type="button" class="botao" data-pers="ficha" data-vista="${temFrente ? "completar" : "frente"}"${ocupado ? " disabled" : ""}>${temFrente ? "Gerar vistas restantes" : "Preparar frente da ficha"}</button>` : ""}
      ${p.folha ? `<a class="simples pers-baixar" href="${urlFichaPersonagem(p)}" download="${esc(p.id)}_ficha.png">Baixar PNG</a>` : ""}
      <button type="button" class="simples perigo" data-pers="apagar"${ocupado ? " disabled" : ""}>Apagar</button>
    </div>
    ${temFrente || fichaEmCurso ? desenharVistasFicha(p, ocupado) :
      `<details class="pers-avulsos"><summary>Opções da frente da ficha</summary>${desenharVistasFicha(p, ocupado)}</details>`}
    ${p.folha ? `<details class="pers-avulsos"><summary>Imagem-base e ângulos separados</summary>${avulsos}</details>` : avulsos}
  </article>`;
}
async function acaoPersonagem(botao) {
  const caixa = botao.closest("[data-pers-id]"), id = caixa.dataset.persId, p = PERS.lista.find(x => x.id === id);
  if (botao.dataset.pers === "ver") { abrirVisor(id, botao.dataset.angulo); return; }
  if (botao.dataset.pers === "ver-ficha") {
    abrirVisorCom([{ src: urlFichaPersonagem(p), nome: p.nome, rotulo: "Ficha de personagem", origem: "" }], 0);
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
      if (!await perguntar(`Apagar o personagem ${p.nome} e as imagens dele? Os vídeos já feitos com ele continuam.`, "Apagar", "Cancelar")) return;
      await postar("/api/personagem-apagar", { id, confirmar: true });
      recado(`${p.nome} foi apagado.`, true);
    } else if (botao.dataset.pers === "ficha") {
      botao.disabled = true;
      const r = await postar("/api/personagem-ficha", { id, etapa: vista, marca: p.ficha_vistas?.frente });
      recado(vista === "usar-base" ? "Imagem-base pronta para aprovação." : r.fila ? "O pedido entrou na fila." : "Preparando as vistas da ficha.", true);
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
  // Preparar a frente: a foto de frente mudou (outra foto, outra imagem recente, tirada) e não é a original nem a opção escolhida
  const f = PERS.frente, chave = chaveFrente();
  if (f.partida && chave !== f.partida && chave !== f.escolhida) limparFrente();
  $("p-preparar").disabled = !tem || f.preparando || S.enviando > 0 || (!$("p-roupa").value.trim() && fundoFrente() === "manter");
  $("p-preparar").textContent = f.preparando ? "Preparando… (1 a 2 min)" : f.opcoes.length ? "Gerar outras 2" : "Preparar a frente";
  $("p-criar").disabled = !tem || !$("p-nome").value.trim() || !$("p-autorizacao").checked || S.enviando > 0 || f.preparando || PERS.criando;
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
    const r = await postar("/api/personagem-criar", { nome: $("p-nome").value, descricao: $("p-descricao").value, autorizacao: $("p-autorizacao").checked,
      ficha, angulos, usar_base: usarBase, fotos, lados, ...(S.pfoto ? { foto: S.pfoto.arquivo } : { projeto, imagem }) });
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
  const d = $("dialogo-personagem"), lista = PERS.lista || [];
  $("dp-lista").innerHTML = lista.length ? lista.map(p => `<button type="button" class="dp-item" data-id="${esc(p.id)}"><span class="midia" data-rotulo="Foto oculta"><img loading="lazy" src="/personagem/${encodeURIComponent(p.id)}/frente.png?m=${p.marca}" alt=""></span><span><strong>${esc(p.nome)}</strong><small>${PERS.angulos.filter(a => p.angulos[a.id]).length} de ${PERS.angulos.length} vistas${p.descricao ? `. ${esc(p.descricao)}` : ""}</small></span></button>`).join("")
    : `<p class="vazio-lista">Nenhum personagem ainda. Crie em Personagem, no menu.</p>`;
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
  const anuncio = t.rodando ? (emCurso ? `Gerando ${VISTAS_FICHA[emCurso]?.toLowerCase() || "vista"}.` : "Preparando as vistas.") : t.parada ? "Geração da ficha parada." :
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
