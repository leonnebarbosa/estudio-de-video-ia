/* Editar vídeo (editar_video.py): o Klein pinta um quadro do trecho com a mudança pedida (2 opções), o usuário escolhe e o
   Viggle Remake Edit do WanGP espalha a mudança pelo trecho, mantendo as pessoas, o movimento, a câmera e o som.
   Testado em 18/11/2026: 5,2 s viraram tempestade em 413 s a ~0,4 MP, pico de 8,3 GB. O vídeo copia a pintura, defeitos
   inclusive: por isso a pintura é escolhida antes de gerar. */
const RASCUNHO_EDITAR = "editar_video_rascunho";
// ~70 s por segundo de vídeo a 0,4 MP (358 s de Viggle para 5,2 s em 18/11), mais a carga do modelo; a 0,5 MP, uns 15% a mais
const SEGUNDOS_EDITAR = { rapido: 70, melhor: 80 };
S.edicao = { codigo: null, quadro_png: null, pinturas: [], escolhida: null, pintadoEm: null, pintando: false, escrevendo: false };
S.nomeEditarEditado = false;
S.roteiroEditado = false;
// O pedido do Klein que a IA escreveu só volta a ser mandado se o usuário mexeu nele: com o pedido em português mudado,
// "Pintar de novo" deixa a IA escrever outro (revisão de 19/11/2026)
S.kleinEditado = false;

const fpsEditar = () => S.dados?.constantes?.fps || 24;
const quadroEditar = () => Math.max(0, Math.round((Number($("e-quadro").value) || 0) * fpsEditar()));
const chaveTrecho = () => JSON.stringify([S.evideo?.arquivo, Number($("e-inicio").value) || 0, quadroEditar()]);
// O roteiro da IA vale para uma pintura, um trecho e uma duração: mudou algum, ele cita o momento e a pintura errados
const chaveRoteiro = () => JSON.stringify([S.edicao.escolhida, chaveTrecho(), Number($("e-duracao").value) || 0]);
function limparRoteiroVelho() {
  const e = S.edicao;
  if (!S.roteiroEditado && e.roteiroDe && e.roteiroDe !== chaveRoteiro()) {
    $("e-roteiro").value = "";
    e.roteiroDe = null;
    $("e-roteiro-nota").textContent = "A pintura, o trecho ou o quadro mudou: o roteiro da IA saiu. Escolha a pintura de novo ou deixe a geração escrever.";
  }
}

function lerEditar() {
  return { qualidade: $("e-qualidade").value, semente: $("e-semente").value === "" ? null : Number($("e-semente").value), esrgan: $("e-esrgan").checked,
           pedido_klein: $("e-pedido-klein").value.trim(), roteiro: $("e-roteiro").value.trim() };
}
function aplicarEditar(a) {
  const p = { ...(S.dados?.editar?.padrao || {}), ...a };
  $("e-qualidade").value = p.qualidade || "rapido";
  $("e-semente").value = p.semente ?? "";
  $("e-esrgan").checked = p.esrgan !== false;
  $("e-pedido-klein").value = p.pedido_klein || "";
  $("e-roteiro").value = p.roteiro || "";
  S.roteiroEditado = !!p.roteiro;
  S.kleinEditado = !!p.pedido_klein;
}
function preencherEditar(d) {
  if (S.marcaOpcoesEditar) return;
  S.marcaOpcoesEditar = true;
  aplicarEditar({});
}
function salvarRascunhoEditar() {
  try {
    localStorage.setItem(RASCUNHO_EDITAR, JSON.stringify({ video: S.evideo, pedido: $("e-pedido").value, duracao: $("e-duracao").value, inicio: $("e-inicio").value, quadro: $("e-quadro").value,
      ajustes: lerEditar(), projeto: S.nomeEditarEditado ? $("e-projeto").value : null, edicao: { ...S.edicao, pintando: false, escrevendo: false } }));
  } catch {}
}
function restaurarEditar() {
  let r = null;
  try { r = JSON.parse(localStorage.getItem(RASCUNHO_EDITAR)); } catch {}
  if (!r) return;
  $("e-pedido").value = r.pedido || "";
  if (r.duracao) $("e-duracao").value = r.duracao;
  $("e-inicio").value = r.inicio || 0;
  if (r.quadro != null) $("e-quadro").value = r.quadro;
  if (r.ajustes) aplicarEditar(r.ajustes);
  if (r.projeto) { $("e-projeto").value = r.projeto; S.nomeEditarEditado = true; }
  if (r.edicao) S.edicao = { ...S.edicao, ...r.edicao, pintando: false, escrevendo: false };
  if (r.video) { preencherArquivo("evideo", r.video); if (!S.nomeEditarEditado) $("e-projeto").value = nomeLivre(`editar_${r.video.arquivo}`); }
}
function aoEscolherVideoEditar(v) {
  $("e-inicio").value = 0;
  const cabe = [5, 4, 3, 2, 1].find(d => Math.max(S.dados.editar.quadros_min, Math.round(d * fpsEditar())) <= quadrosDoVideo(v));
  if (cabe) $("e-duracao").value = cabe;
  $("e-quadro").value = 1;
  esquecerPinturas();
  if (!S.nomeEditarEditado) $("e-projeto").value = nomeLivre(`editar_${v.arquivo}`);
}
function esquecerPinturas() {
  S.edicao = { codigo: S.edicao.codigo, quadro_png: null, pinturas: [], escolhida: null, pintadoEm: null, pintando: false, escrevendo: false };
  if (!S.roteiroEditado) $("e-roteiro").value = "";
}
function usarQuadroDaPrevia() {
  const v = $("zona-evideo").querySelector(".midia video");
  if (!v) return;
  const d = Number($("e-duracao").value) || 1, ini = Number($("e-inicio").value) || 0;
  const t = Math.min(Math.max(0, v.currentTime - ini), Math.max(0, d - 1 / fpsEditar()));
  $("e-quadro").value = Math.round(t * 10) / 10;
  atualizarEditar();
}
function desenharPinturas() {
  const e = S.edicao, bloco = $("e-pinturas-bloco");
  bloco.hidden = !S.evideo || (!e.pinturas.length && !e.quadro_png);
  const marca = JSON.stringify([e.pinturas, e.escolhida, e.pintando]);
  if (marca !== S.marcaPinturas) {
    S.marcaPinturas = marca;
    $("e-pinturas").innerHTML = e.pinturas.map((n, i) => `<button type="button" class="pintura-opcao" data-pintura="${esc(n)}" aria-pressed="${n === e.escolhida}">
      ${midia(`<img src="/entrada/foto/${encodeURIComponent(n)}" alt="Opção ${i + 1}">`, "Imagem oculta")}<span>${n.endsWith("_minha.png") ? "Imagem sua" : n.includes("_reuso") ? "A usada antes" : `Opção ${i + 1}`}${n === e.escolhida ? " · escolhida" : ""}</span></button>`).join("");
  }
  $("e-pinturas-nota").textContent = e.pintando ? "pintando…" : e.escolhida ? "escolhida; o vídeo vai passar por ela" : e.pinturas.length ? "clique na melhor" : "";
  const baixar = $("e-baixar-quadro");
  baixar.hidden = !e.quadro_png;
  if (e.quadro_png) { baixar.href = `/entrada/foto/${encodeURIComponent(e.quadro_png)}`; baixar.download = e.quadro_png; }
}
async function pintarEditar() {
  const e = S.edicao, chave = chaveTrecho(), mesmoQuadro = e.pintadoEm === chave;
  $("e-erro").hidden = true;
  e.pintando = true;
  atualizarEditar();
  try {
    const r = await postar("/api/editar-pintar", { video: S.evideo.arquivo, inicio: Number($("e-inicio").value) || 0, quadro: quadroEditar(), pedido: $("e-pedido").value,
                                                   pedido_klein: S.kleinEditado ? $("e-pedido-klein").value.trim() || null : null, codigo: e.codigo || null });
    // As pinturas de antes ficam na lista só se forem do mesmo quadro: de outro quadro, o vídeo seria forçado a passar
    // por uma pose de outro momento (revisão de 19/11/2026)
    Object.assign(e, { codigo: r.codigo, quadro_png: r.quadro, pinturas: [...r.pinturas, ...(mesmoQuadro ? e.pinturas.filter(n => !r.pinturas.includes(n)) : [])].slice(0, 6), pintadoEm: chave });
    if (e.escolhida && !e.pinturas.includes(e.escolhida)) e.escolhida = null;
    $("e-pedido-klein").value = r.pedido_klein;
    recado(r.ia ? `Pintado em ${tempo(r.segundos)}. Escolha a melhor opção.` : `Pintado em ${tempo(r.segundos)}, com o seu pedido em português (a IA não respondeu). Escolha a melhor opção.`, true);
  } catch (err) {
    $("e-erro").textContent = err.message;
    $("e-erro").hidden = false;
  }
  e.pintando = false;
  atualizarEditar();
}
async function escolherPintura(nome) {
  const e = S.edicao;
  e.escolhida = nome;
  limparRoteiroVelho();
  atualizarEditar();
  if (S.roteiroEditado || $("e-roteiro").value.trim() || e.escrevendo) return;
  e.escrevendo = true;
  atualizarEditar();
  try {
    const r = await postar("/api/editar-roteiro", { codigo: e.codigo, quadro_png: e.quadro_png, pintura: nome, pedido: $("e-pedido").value, pedido_klein: $("e-pedido-klein").value,
                                                    quadro: quadroEditar(), duracao: Number($("e-duracao").value) });
    // Só preenche se ninguém escreveu no campo enquanto a IA pensava
    if (!S.roteiroEditado && !$("e-roteiro").value.trim() && e.escolhida === nome) { $("e-roteiro").value = r.roteiro; e.roteiroDe = chaveRoteiro(); }
    $("e-roteiro-nota").textContent = r.ia ? "Escrito pela IA olhando o quadro e a pintura. Confira ou mude." : "A IA não escreveu um roteiro válido: este é o roteiro fixo. Pode mudar.";
  } catch (err) {
    $("e-roteiro-nota").textContent = `${err.message} Sem roteiro aqui, a geração escreve antes de começar.`;
  }
  e.escrevendo = false;
  atualizarEditar();
}
async function usarImagemMinha(r) {
  const e = S.edicao;
  try {
    const x = await postar("/api/editar-imagem-minha", { arquivo: r.arquivo, video: S.evideo?.arquivo, codigo: e.codigo || null });
    e.codigo = x.codigo;
    // Pinturas de outro quadro saem, como no Pintar de novo
    const antigas = e.pintadoEm && e.pintadoEm !== chaveTrecho() ? [] : e.pinturas;
    e.pinturas = [x.pintura, ...antigas.filter(n => n !== x.pintura)].slice(0, 6);
    e.pintadoEm = chaveTrecho();
    limparZona("epintura");
    S.epintura = null;
    escolherPintura(x.pintura);
  } catch (err) {
    limparZona("epintura");
    S.epintura = null;
    $("epintura-aviso").textContent = err.message;
    $("epintura-aviso").hidden = false;
  }
  atualizarEditar();
}
function atualizarEditar() {
  if (!S.dados?.editar) return;
  limparRoteiroVelho();
  const cfg = S.dados.editar, a = lerEditar(), v = S.evideo, e = S.edicao, fps = fpsEditar(), falta = [];
  const travada = sincronizarTrava("editar");
  const d = Number($("e-duracao").value), inicio = Math.max(0, Number($("e-inicio").value) || 0), quadro = quadroEditar();
  const quadros = Math.round(d * fps), precisa = Math.max(cfg.quadros_min, quadros);
  const cabe = !v || precisa <= quadrosDoVideo(v) - Math.round(inicio * fps);
  const placaOcupada = vaiParaFila() || !S.dados.comfy.ligado || S.dados.comfy.ocupado;
  const pedido = $("e-pedido").value.trim();
  $("e-quadro").max = Math.max(0, d - 1 / fps);
  // Pintar
  const motivoPintar = !v ? "Escolha o vídeo" : !pedido ? "Escreva o que mudar" : e.pintando ? "" : vaiParaFila() ? "Pintar só com a placa livre: espere a geração atual terminar" : !S.dados.comfy.ligado ? "Esperando o ComfyUI ficar pronto" : S.dados.comfy.ocupado ? "O ComfyUI está ocupado" : quadro >= quadros ? "O quadro a pintar fica fora do trecho" : "";
  $("e-pintar").disabled = travada || e.pintando || !!motivoPintar || e.escrevendo;
  $("e-pintar").textContent = e.pintando ? "Pintando… (1 a 2 min)" : e.pinturas.length ? "Pintar de novo" : "Pintar o quadro";
  $("e-pintar-nota").textContent = motivoPintar && !e.pintando ? motivoPintar + "." : "O Klein pinta 2 opções (uns 1 a 2 min). Escolha uma antes de gerar: o vídeo copia a pintura, defeitos inclusive.";
  const mudou = e.pintadoEm && e.pintadoEm !== chaveTrecho();
  desenharPinturas();
  $("e-ajustes-situacao").textContent = a.roteiro ? (S.roteiroEditado ? "roteiro seu" : "roteiro pronto") : e.escrevendo ? "escrevendo o roteiro…" : "escritos pela IA";
  if (e.escrevendo) $("e-roteiro-nota").textContent = "A IA está escrevendo o roteiro (uns 30 s)…";
  // Fita: antes do trecho, o trecho editado (com o quadro pintado marcado) e o resto
  const total = v ? quadrosDoVideo(v) : 0, antes = Math.min(total, Math.round(inicio * fps)), usados = Math.max(0, Math.min(quadros, total - antes)), depois = total - antes - usados;
  $("e-fita").innerHTML = v ? `${antes ? `<span class="resto" style="flex:${antes} 1 0"></span>` : ""}<span class="nova" style="flex:${usados} 1 0"></span>${depois > 0 ? `<span class="resto" style="flex:${depois} 1 0"></span>` : ""}` : "";
  $("e-fita").hidden = !v;
  $("e-conta").textContent = v ? `Serão gerados ${num(quadros / fps, 2)} s (${quadros} quadros)${inicio ? ` a partir de ${num(inicio, 1)} s` : ""}, com o quadro pintado em ${num(quadro / fps, 1)} s do trecho${precisa > quadros ? `; o WanGP lê ${num(precisa / fps, 2)} s e corta no pedido` : ""}.` : "Escolha o vídeo e escreva o que mudar.";
  const avisos = [];
  if (v && !v.audio) avisos.push("Este vídeo não tem áudio, então o resultado sai sem som.");
  if (a.qualidade === "melhor" || d > 6) avisos.push("Testado a 0,4 MP com 5 s. O tempo e a carga na placa podem ser maiores.");
  $("e-aviso-config").textContent = avisos.join(" ");
  $("e-aviso-config").hidden = !avisos.length;
  let segundos = d * (SEGUNDOS_EDITAR[a.qualidade] || 70) + 30 + (a.roteiro ? 0 : 30);
  if (a.esrgan) segundos += 10 + d * SEGUNDOS_ESRGAN_POR_SEGUNDO;
  mostrarEstimativa("e-estimativa", travada || !v ? null : segundos, avisos.length > 0);

  if (S.enviando) falta.push("Esperando o envio terminar");
  else if (!v) falta.push("Escolha o vídeo");
  if (!pedido) falta.push("Escreva o que mudar");
  if (!(d >= 1 && d <= cfg.duracao_max)) falta.push(`Use uma duração de 1 a ${cfg.duracao_max} s`);
  else if (!cabe) falta.push(`O WanGP precisa de pelo menos ${num(precisa / fps, 2)} s de vídeo${inicio ? ` a partir de ${num(inicio, 1)} s` : ""}. ${inicio ? "Recue o início ou reduza a duração" : "Use um vídeo mais longo"}`);
  if (quadro >= quadros) falta.push("O quadro a pintar fica fora do trecho");
  if (v && !e.escolhida) falta.push(e.pinturas.length ? "Escolha uma das pinturas" : "Pinte o quadro e escolha uma pintura");
  else if (mudou) falta.push("O vídeo, o trecho ou o quadro mudou depois de pintar: pinte de novo");
  if (!cfg.wangp) falta.push("O WanGP não está instalado");
  if (v && !/^[A-Za-z0-9_-]{1,60}$/.test($("e-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(p => p.nome === $("e-projeto").value)) falta.push("Já existe um projeto com este nome");
  if (!$("e-autorizacao").checked) falta.push("Confirme que você tem direito de editar o vídeo");
  if (e.pintando || e.escrevendo) falta.push("Espere a pintura ou o roteiro terminar");
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado && !e.pintando && !e.escrevendo) falta.push("O ComfyUI está ocupado"); }
  porHtml($("e-falta"), travada ? notaTravada("editar") : htmlFalta(falta));
  $("e-gerar").disabled = falta.length > 0;
  rotuloFila($("e-gerar"));
  salvarRascunhoEditar();
}
async function iniciarEditar() {
  $("e-erro").hidden = true;
  $("e-gerar").disabled = true;
  const nome = $("e-projeto").value;
  try {
    await postar("/api/iniciar-editar", { projeto: nome, video: S.evideo.arquivo, inicio: Number($("e-inicio").value) || 0, duracao: Number($("e-duracao").value), quadro: quadroEditar(),
                                          pintura: S.edicao.escolhida, pedido: $("e-pedido").value, ajustes: lerEditar(), autorizacao: $("e-autorizacao").checked });
    S.abertos.add(nome);
    S.dispensada = null;
    marcarEnviado("editar", nome);
  } catch (err) {
    $("e-erro").textContent = err.message;
    $("e-erro").hidden = false;
  }
  await consultar(true);
}
function limparEditar() {
  soltarTrava("editar");
  S.evideo = S.epintura = null;
  S.nomeEditarEditado = false;
  S.edicao = { codigo: null, quadro_png: null, pinturas: [], escolhida: null, pintadoEm: null, pintando: false, escrevendo: false };
  S.marcaPinturas = "";
  $("e-pedido").value = "";
  $("e-duracao").value = 5;
  $("e-inicio").value = 0;
  $("e-quadro").value = 1;
  $("e-projeto").value = "";
  $("e-autorizacao").checked = false;
  $("e-roteiro-nota").textContent = "As 6 partes que o Viggle Remake Edit lê. Vazio, a geração escreve antes de começar.";
  limparZona("evideo");
  limparZona("epintura");
  aplicarEditar({});
  try { localStorage.removeItem(RASCUNHO_EDITAR); } catch {}
}
/* Usar de novo um projeto do Editar vídeo: o vídeo, o trecho, o pedido, os ajustes e a pintura usada (já escolhida) */
function reusarEditar(r, projeto) {
  limparEditar();
  preencherArquivo("evideo", r.video);
  const c = r.config || {};
  $("e-pedido").value = c.pedido || "";
  $("e-duracao").value = c.duracao || 5;
  $("e-inicio").value = c.inicio || 0;
  $("e-quadro").value = Math.round((c.quadro ?? 24) / fpsEditar() * 10) / 10;
  aplicarEditar(c);
  if (r.pintura) S.edicao = { ...S.edicao, pinturas: [r.pintura], escolhida: r.pintura, pintadoEm: chaveTrecho() };
  $("e-projeto").value = nomeLivre(`${projeto}.x`);
  S.nomeEditarEditado = true;
}
