const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (x, d = 1) => Number(x).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const tempo = s => { const m = Math.round(s / 60); return m < 1 ? `${Math.round(s)} s` : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`; };
const semExt = n => String(n).replace(/\.safetensors$/, "");
const relogio = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, r = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`; };
/* Semente de uma imagem gerada, num botão no canto dela: um clique copia (ver eventos.js) */
const botaoSemente = s => s == null ? "" : `<button type="button" class="semente-copiar" data-copiar-semente="${esc(s)}" title="Copiar a semente" aria-label="Copiar a semente ${esc(s)}">Semente ${esc(s)}</button>`;
const midia = (html, rotulo = "", classe = "") => `<span class="midia ${classe}"${rotulo ? ` data-rotulo="${esc(rotulo)}"` : ""}>${html}</span>`;
const MIN_POR_RODADA = { comFoto: 5, semFoto: 4 };
const VIDEO_TESTADO = 6;
const RASCUNHO = "continuar_video_rascunho";
const NOMES_MODELO = { "minimax_h3_ref2va_pruned_int8_convrot.safetensors": "ref2va (padrão testado)" };
const NOMES_LORA = { "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors": "DMAD (padrão testado)" };
const AJUDA = { video: ["Escolher vídeo", "MP4 com áudio. Também pode arrastar para cá."], foto: ["Escolher foto", "Ajuda a manter o rosto e a roupa até o fim."],
                tvideo: ["Escolher vídeo", "MP4 de onde vêm o cenário e os movimentos."], tfoto: ["Escolher foto", "Quem vai aparecer no vídeo. Mostre bem o rosto e o cabelo."],
                ifoto: ["Escolher imagem", "É o primeiro quadro do vídeo."],
                t2ifoto: ["Escolher imagem", "Sem imagem, gera do zero. Com ela, o modelo refaz a imagem seguindo o texto."],
                t2iref: ["Escolher imagem", "De onde tirar algo para a primeira: roupa, objeto, fundo. Na instrução, chame de image 2."],
                tfbase: ["Escolher foto", "A foto que vai mudar. A pose, a luz e o cenário ficam."],
                tfrosto: ["Escolher foto do rosto", "De quem vem o rosto. O cabelo vem junto."],
                tfroupa: ["Escolher foto da roupa", "Uma pessoa vestindo a roupa ou a foto da peça."],
                pfoto: ["Escolher foto", "De frente, de corpo inteiro e com fundo liso."],
                ptres: ["Três quartos", "Escolher foto"], pperfil: ["Perfil", "Escolher foto"], pcostas: ["Costas", "Escolher foto"],
                pvideo: ["Escolher vídeo", "MP4 com a pessoa de vários ângulos"] };
const BASE = tipo => tipo.endsWith("video") ? "video" : "foto";
/* Nome do formato na tela, em português e pelo uso; o valor enviado ao servidor continua o mesmo ("2:3 (Portrait Photo)") */
const NOMES_PROPORCAO = { "1:1": "Quadrado", "2:3": "Retrato (foto em pé)", "3:2": "Paisagem (foto deitada)", "3:4": "Retrato", "4:3": "Paisagem",
                          "9:16": "Vertical (Stories, Reels, TikTok)", "16:9": "Horizontal (YouTube, TV)", "21:9": "Cinema (bem largo)" };
const nomeProporcao = p => { const r = String(p).split(" ")[0]; return NOMES_PROPORCAO[r] ? `${NOMES_PROPORCAO[r]}, ${r}` : p; };
const TITULO = "Estúdio de vídeo";

const S = { video: null, foto: null, tvideo: null, tfoto: null, pfoto: null, pvideo: null, tpersonagem: null, ifoto: null, t2ifoto: null, t2iref: null, irefs: [], nomeImagemEditado: false, marcaOpcoesImagem: "", nomeTrocaEditado: false, passosTrocaEditados: false, marcaOpcoesTroca: "", enviando: 0, dados: null, abertos: new Set(), aba: "texto", marcaProjetos: "", marcaAndamento: "", marcaOpcoes: "", nomeEditado: false, estavaRodando: false, dispensada: null, passosEditados: false, querido: {}, opcoesProntas: false };

/* A pagina abre antes do ComfyUI ficar pronto: ate la as listas so tem o padrao. Uma escolha (do rascunho, de "Usar de novo")
   que ainda nao esta na lista fica guardada em S.querido e volta sozinha quando as opcoes chegarem. Mexer na caixa descarta. */
function poeValor(id, v) {
  const el = $(id), s = String(v ?? "");
  el.value = s;
  if (el.value === s || S.opcoesProntas) delete S.querido[id];
  else S.querido[id] = s;
}
const valor = id => S.querido[id] ?? $(id).value;

/* Campo Modelo, o mesmo em toda aba: o servidor manda [{id, nome, ajuda, faltam}] e um modelo sem os arquivos fica desativado.
   Para uma aba ganhar um modelo novo basta ele entrar na lista do servidor. */
function opcoesModelo(id, modelos, rotulo = m => m.nome) {
  $(id).innerHTML = modelos.map(m => `<option value="${esc(m.id)}" ${m.faltam?.length ? "disabled" : ""}>${esc(rotulo(m) + (m.faltam?.length ? ", não instalado" : ""))}</option>`).join("");
}
function ajudaModelo(m, total) {
  return (m?.ajuda || "") + (total === 1 ? " É o único instalado por enquanto; um modelo novo aparece aqui depois de baixado e testado." : "");
}

/* Rascunho: guarda o que foi preenchido se a pagina recarregar */
function salvarRascunho() {
  try { localStorage.setItem(RASCUNHO, JSON.stringify({ video: S.video, foto: S.foto, ideia: $("ideia").value, duracao: $("duracao").value, ajustes: lerAjustes(), projeto: S.nomeEditado ? $("projeto").value : null })); } catch {}
}
function lerRascunho() {
  try { return JSON.parse(localStorage.getItem(RASCUNHO)); } catch { return null; }
}
function apagarRascunho() {
  try { localStorage.removeItem(RASCUNHO); } catch {}
}

/* Pedidos */
async function postar(caminho, dados) {
  const r = await fetch(caminho, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dados || {}) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.erro || "O pedido falhou.");
  return j;
}
async function pararComConfirmacao() {
  // Parar precisa funcionar mesmo se um pedido falhar; pedir de novo nao tem efeito colateral
  let ultimo = null;
  for (let i = 0; i < 3; i++) {
    try {
      await postar("/api/parar");
      for (let j = 0; j < 10; j++) {
        const t = (await (await fetch("/api/estado")).json()).tarefa;
        if (!t?.rodando) return;
        await new Promise(r => setTimeout(r, 500));
      }
    } catch (e) { ultimo = e; }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`A geração não parou${ultimo ? ` (${ultimo.message})` : ""}. Clique em Parar geração de novo ou feche o estúdio pelo botão Fechar o estúdio.`);
}
// acao opcional: { rotulo, fazer } vira um botão no aviso (ex.: Desfazer)
function recado(texto, bom, acao = null) {
  $("recado-texto").textContent = texto;
  $("recado").classList.toggle("boa", !!bom);
  const b = $("recado-acao");
  b.hidden = !acao;
  b.textContent = acao?.rotulo || "";
  b.onclick = acao ? () => { $("recado").hidden = true; acao.fazer(); } : null;
  $("recado").hidden = false;
}
async function iniciar(soPlano) {
  $("erro-form").hidden = true;
  $("gerar").disabled = $("so-plano").disabled = true;
  const nome = $("projeto").value;
  try {
    await postar("/api/iniciar", { projeto: nome, video: S.video.arquivo, foto: S.foto?.arquivo || null, ideia: $("ideia").value, duracao: Number($("duracao").value), ajustes: lerAjustes(), so_plano: soPlano });
    S.abertos.add(nome);
    S.dispensada = null;
    marcarEnviado("novo", nome);
  } catch (e) {
    $("erro-form").textContent = e.message;
    $("erro-form").hidden = false;
  }
  await consultar(true);
}
function limparForm() {
  soltarTrava("novo");
  S.video = S.foto = null;
  S.nomeEditado = false;
  $("ideia").value = "";
  $("duracao").value = 30;
  $("projeto").value = "";
  limparZona("video");
  limparZona("foto");
  aplicarAjustes({});
  apagarRascunho();
}
/* Texto para video usa a tela do Imagem para video em modo texto (sem imagem), com rascunho próprio.
   S.aba guarda a tela (o resto do código, como Limpar tudo, trava e histórico, segue por ela); S.abaVisivel, o botão do menu. */
const TELA_DA_ABA = { tvideo: "imagem" };
/* Modelos da comunidade testados so nesta maquina: o servidor manda nomes, tempos e ajudas do arquivo local (extras.py),
   que entram nas tabelas da pagina. Fora desta maquina nao vem nada e as tabelas ficam so com os oficiais. */
const AJUDA_PRIMEIRA = {};
function aplicarExtras(x) {
  if (!x || aplicarExtras.feito) return;
  aplicarExtras.feito = true;
  Object.assign(NOMES_MODELO, x.nomes_modelo || {});
  Object.assign(SEGUNDOS_MODELO_TEXTO, x.segundos_texto || {});
  Object.assign(AJUDA_PASSOS_TEXTO, x.ajuda_passos_texto || {});
  Object.assign(SEGUNDOS_TOMADA_WAN, x.segundos_wan || {});
  Object.assign(BASE_WAN, x.base_wan || {});
  Object.assign(NOMES_MODELO_WAN, x.nomes_modelo_wan || {});
  Object.assign(AJUDA_PRIMEIRA, x.ajuda_primeira || {});
  Object.assign(FORCA_LORA, x.forca_lora || {});
}
const ABA_SALVA = "estudio_aba", ABAS_DE_CRIAR = ["texto", "imagem", "tvideo", "novo", "troca"];
/* Ao abrir: a ultima aba usada; na primeira vez, a primeira aba com o pacote de modelos baixado.
   Antes abria sempre em Continuar video, que num PC novo nao tem os modelos (teste de 12/11/2026). */
function escolherAbaInicial(d) {
  let salva = null;
  try { salva = localStorage.getItem(ABA_SALVA); } catch {}
  if (salva && $(`aba-${salva}`)) return irPara(salva);
  // Interface nova: na primeira vez abre no Explorar, que mostra o que dá para fazer
  irPara("explorar");
}
/* Aviso no topo de uma aba cujo pacote de modelos ainda nao foi baixado, com o botao que abre o instalador */
function desenharFaltaPacote() {
  // A troca em foto usa outro pacote (Editar imagem) que a troca em vídeo
  const a = S.dados?.abas?.[S.aba === "trocafoto" ? "trocafoto" : S.abaVisivel || S.aba], el = $("falta-pacote");
  el.hidden = !a || a.pronto;
  if (el.hidden) return;
  const tam = a.falta ? ` (${num(a.falta / 2 ** 30, 1)} GB)` : "";
  $("falta-pacote-texto").textContent = `Esta aba precisa do pacote de modelos ${a.pacote}${tam}, que ainda não foi baixado.`;
}
function irPara(aba) {
  // A aba Trocar personagem tem duas telas, uma por modo (Foto ou Vídeo, trocafoto.js)
  const nomeTela = aba === "troca" && S.modoTroca === "foto" ? "trocafoto" : TELA_DA_ABA[aba] || aba;
  S.aba = nomeTela;
  S.abaVisivel = aba;
  for (const nome of ["explorar", "novo", "troca", "personagens", "imagem", "tvideo", "texto", "projetos", "modelos"]) $(`aba-${nome}`).setAttribute("aria-selected", aba === nome);
  for (const nome of ["explorar", "novo", "troca", "trocafoto", "personagens", "imagem", "texto", "projetos", "modelos"]) $(`tela-${nome}`).hidden = nomeTela !== nome;
  if (nomeTela === "imagem") trocarModoImagem(aba === "tvideo");
  // O CSS (Limpar tudo, posição do aviso) segue a tela, que no Texto para vídeo é a do Imagem para vídeo
  document.documentElement.dataset.aba = nomeTela;
  $("titulo-tela").textContent = $(`aba-${aba}`).querySelector(".rotulo-aba").textContent;
  const tela = $(`tela-${nomeTela}`);
  (tela.querySelector(".centro") || tela).prepend($("falta-pacote"));
  (tela.querySelector(".centro") || tela).prepend($("andamento"));
  $("andamento").after($("fila-painel"));
  try { localStorage.setItem(ABA_SALVA, aba); } catch {}
  desenharFaltaPacote();
  $("limpar-tudo").disabled = tela.classList.contains("travada");
  if (aba === "modelos") carregarModelos();
  if (aba === "personagens") { carregarPersonagens(); atualizarPersonagemNovo(); }
  if (aba === "explorar") desenharExplorar();
}
function perguntar(texto, sim = "Parar geração", nao = "Continuar gerando") {
  return new Promise(ok => {
    const d = $("dialogo");
    $("dialogo-texto").textContent = texto;
    d.querySelector('[value="sim"]').textContent = sim;
    d.querySelector('[value="nao"]').textContent = nao;
    // Apagar e parar perdem trabalho: o botao fica vermelho, como nos alertas do macOS
    d.querySelector('[value="sim"]').classList.toggle("perigo", /^(Apagar|Parar)/.test(sim));
    // A resposta vem do clique: o evento close pode atrasar com a aba em segundo plano
    const responder = valor => { d.close(); ok(valor); };
    d.querySelector('[value="sim"]').onclick = () => responder(true);
    d.querySelector('[value="nao"]').onclick = () => responder(false);
    d.oncancel = e => { e.preventDefault(); responder(false); };
    d.showModal();
    d.querySelector('[value="nao"]').focus();
  });
}

/* Tempo estimado ao lado do Gerar: recalcula a cada ajuste e, quando a mudança veio da pessoa, mostra por um instante
   quanto ela somou ou tirou. A consulta a cada 3 s também redesenha, sem animar (não foi um gesto). */
const ESTIMATIVAS = {};
let ultimoGesto = 0;
for (const tipo of ["input", "change", "click"]) document.addEventListener(tipo, () => { ultimoGesto = Date.now(); }, true);
function trocarTexto(el, texto) { if (el.textContent !== texto) el.textContent = texto; }
function mostrarEstimativa(id, segundos, grosseira = false) {
  const caixa = $(id);
  if (segundos == null || !isFinite(segundos)) { caixa.hidden = true; delete ESTIMATIVAS[id]; return; }
  const antes = ESTIMATIVAS[id], minutos = Math.max(1, Math.round(segundos / 60));
  ESTIMATIVAS[id] = { minutos, grosseira };
  caixa.hidden = false;
  caixa.classList.toggle("grosseira", grosseira);
  // Abaixo de 1 minuto (uma imagem do Z-Image leva uns 25 s), segundos de 5 em 5: "1 min" assustava (teste de 12/11/2026)
  const mostrado = segundos < 55 ? Math.max(5, Math.round(segundos / 5) * 5) : minutos * 60;
  trocarTexto(caixa.querySelector(".est-valor"), `${grosseira ? "≈ " : ""}${tempo(mostrado)}`);
  const fim = new Date(Date.now() + mostrado * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  // Com outra geração rodando, esta só começa depois: a hora de término não vale
  const quando = S.dados?.tarefa?.rodando ? "Começa quando a geração atual terminar." : grosseira ? `Pronto lá pelas ${fim}.` : `Pronto por volta das ${fim}.`;
  trocarTexto(caixa.querySelector(".est-detalhe"), grosseira ? `${quando} Conta grosseira: ajustes fora do padrão testado.` : quando);
  if (antes && antes.minutos !== minutos && Date.now() - ultimoGesto < 1500) {
    const d = minutos - antes.minutos, chip = caixa.querySelector(".est-delta");
    chip.textContent = `${d > 0 ? "+" : "−"}${tempo(Math.abs(d) * 60)}`;
    chip.classList.toggle("menos", d < 0);
    caixa.classList.remove("mudou");
    void caixa.offsetWidth;  // reinicia a animação quando duas mudanças vêm em seguida
    caixa.classList.add("mudou");
  }
}
