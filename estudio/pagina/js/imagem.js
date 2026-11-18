/* Imagem para video: MiniMax H3 (fala, som e voz) ou Wan (sem som), escolhido no campo Modelo */
const RASCUNHO_IMAGEM = "imagem_video_rascunho", RASCUNHO_TVIDEO = "texto_video_rascunho";
/* A aba Texto para vídeo é esta mesma tela em modo texto: sem imagem, com o campo da cena, só no H3 e com rascunho próprio */
const modoTexto = () => $("tela-imagem").dataset.modo === "texto";
const chaveRascunhoImagem = () => modoTexto() ? RASCUNHO_TVIDEO : RASCUNHO_IMAGEM;
const NOMES_CAMERA = { parada: "Parada (testada)", aproximar: "Aproximar devagar (testada uma vez)", afastar: "Afastar devagar (testada uma vez)", acompanhar: "Acompanhar o personagem (testada uma vez)" };
// Medido em 07/11/2026: cerca de 5,3 silabas por segundo; a fala precisa de uma pequena folga na tomada
const SILABAS_POR_SEGUNDO = 5.3;
// Limite de caracteres da ação de cada tomada: vem do servidor (validacao.MAX_ACAO)
const maxAcao = () => S.dados?.imagem?.max_acao || 2000;
/* Tempo de uma tomada do H3, medido na 3080 (tomada 1, fl2va, 8 passos, com os modelos já lidos):
   0,47 MP: 3 s 135 s; 5 s 240 a 290 s (~25 s por passo); 10 s 714 s. 0,8 MP: 5 s ~500 s; 10 s 1.180 s (11/11/2026).
   Cresce com os quadros e com os pixels: 276 s × (quadros / 124)^1,36 × (MP / 0,4746)^1,08 fica a menos de 6% desses pontos.
   A 1 MP, 3 s levaram de 305 a 763 s e 4,25 s de 489 a 979 s em 11/11: o tempo varia muito porque inclui ler os modelos do disco.
   As tomadas seguintes (continuação) geram também os 2 s de contexto da anterior, com 6 passos em vez de 8 (8 num modelo Turbo). */
const SEGUNDOS_H3_BASE = 276, QUADROS_H3_BASE = 124, EXPOENTE_QUADROS_H3 = 1.36, EXPOENTE_MP_H3 = 1.08, QUADROS_CONTEXTO_H3 = 48;
function segundosTomadaH3(s, mp, primeira, turbo = false) {
  const quadros = novosImagem(s, true) + (primeira ? 0 : QUADROS_CONTEXTO_H3);
  return SEGUNDOS_H3_BASE * Math.pow(quadros / QUADROS_H3_BASE, EXPOENTE_QUADROS_H3) * Math.pow(mp / 0.4746, EXPOENTE_MP_H3) * (primeira || turbo ? 1 : 6 / 8);
}
// Combinações de duração e resolução que já foram medidas no H3: fora delas a estimativa aparece como grosseira
const MEDIDOS_H3 = { 0.4746: [3, 5, 10], 0.8: [5, 10] };
// Wan, medido em 09/11/2026 na 3080 (2:3). Por tomada, com os modelos já lidos: GGUF 2 s 164 s, 3 s 194 s, 5 s 290 s.
// Quase todo o tempo é carregar os dois modelos (High e Low) a cada tomada: a duração pesa pouco e 0,6 MP levou o mesmo que 0,475 (160 s em 3 s).
// Ler do disco (primeira geração ou troca de modelo) soma de 35 s a 2 min.
const SEGUNDOS_TOMADA_WAN = { wan22: 290 }, SEGUNDOS_LER_WAN = 60;
const BASE_WAN = { wan22: [100, 38] };  // [fixo, por segundo de vídeo]
const segundosTomadaWan = (id, s, mp) => { const [fixo, porS] = BASE_WAN[id] || [90, 36]; return (fixo + porS * s) * Math.pow(mp / 0.475, 0.3); };
const QUALIDADES_TESTADAS_WAN = [0.475, 0.6], DURACOES_TESTADAS_WAN = [2, 3, 5];
const NOMES_ACABAMENTO = { nenhum: "Nenhum (padrão)", esrgan: "Full HD com ESRGAN (testado)", refino: "Refino do H3 + Full HD (teste curto)" };
const AJUDA_ACABAMENTO = { nenhum: "O vídeo fica no tamanho gerado.",
                           esrgan: "Amplia quadro a quadro para Full HD: contornos limpos, textura lisa. Uns 3 min para 20 s de vídeo. Sai como final_hd.mp4.",
                           refino: "O H3 refaz o vídeo em pedaços de 3 s com mais detalhe e depois amplia para Full HD. Uns 4 min a cada 3 s de vídeo. Sai como final_hd.mp4." };
const NOMES_QUALIDADE_H3 = { 0.3: "Menor e mais rápida (não testada)", 0.4746: "Média (padrão testado)", 0.6: "Maior, mais memória (não testada)", 0.7: "Alta, 0,7 MP (testada em 2 tomadas)",
                             0.8: "Mais alta, 0,8 MP (testada em 5 e 10 s)", 1: "Máxima, 1 MP (só até 5 s; 10 s derrubou a placa)" };
const NOMES_QUALIDADE_WAN = { 0.3: "Menor, 0,3 MP (mais rápida, não testada)", 0.475: "Média, 0,475 MP (testada)", 0.6: "Maior, 0,6 MP (testada em 2 e 3 s, mesmo tempo)" };
// ESRGAN: de 8 a 12 s por segundo de vídeo (116 s para 14 s em 11/11/2026; a conta usa 10); refino: 185 s por pedaço de 73 quadros (65 novos por pedaço)
const SEGUNDOS_ESRGAN_POR_SEGUNDO = 10;
const segundosAcabamento = (modo, quadros) => modo === "nenhum" ? 0 : quadros / 24 * SEGUNDOS_ESRGAN_POR_SEGUNDO + (modo === "refino" ? Math.ceil(Math.max(1, quadros - 8) / 65) * 185 : 0);
function tamanhoHD(proporcao) {
  const m = proporcao.match(/^(\d+):(\d+)/), w = Number(m[1]), h = Number(m[2]);
  return h >= w ? `1080×${Math.round(1080 * h / w / 2) * 2}` : `${Math.round(1080 * w / h / 2) * 2}×1080`;
}
const TOMADA_VAZIA = { acao: "", fala: "", som: "", camera: "parada", olhar: false, duracao: 3 };
const novosImagem = (s, primeira) => Math.round(s * 24 / 17) * 17 + (primeira ? 5 : 0);
const silabas = t => (String(t).match(/[aeiouáéíóúâêôãõà]+/gi) || []).length;

/* O modelo escolhido (ou o de um projeto), com as listas que ele aceita. Antes das opções chegarem, o H3. */
function modeloImagem(id) {
  const lista = S.dados?.imagem?.modelos || [];
  const alvo = id ?? ($("i-modelo")?.value || "h3");
  return lista.find(m => m.id === alvo) || lista[0] || { id: "h3", nome: "MiniMax H3", fala: true, fps: 24, duracoes: S.dados?.imagem?.duracoes || [3], acabamentos: ["nenhum"], qualidades: [0.4746], padrao: { megapixels: 0.4746 }, faltam: [] };
}
/* Quadros novos que a tomada soma ao vídeo: no H3, 17k+5 a 24 por segundo; no Wan, 4k+1 a 16 por segundo, menos o quadro repetido da emenda */
const quadrosTomada = (m, s, primeira) => m.fala ? novosImagem(s, primeira) : Math.round(s * 4) * 4 + (primeira ? 1 : 0);
const nomeQualidade = (q, m) => (m.fala ? NOMES_QUALIDADE_H3 : NOMES_QUALIDADE_WAN)[q] || `${num(q, 2)} MP`;
const maisPerto = (v, lista) => lista.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a, lista[0]);
/* No H3, a duração máxima depende da resolução (validacao.validar_duracoes_h3): 10 s até 0,8 MP; a 1 MP, 5 s, porque 10 s
   derrubou a placa em 11/11/2026. Da tomada 2 em diante, até 5 s: a continuação soma 2 s da anterior e isso não foi medido. */
function duracaoMaximaH3(m, mp, primeira) {
  const faixas = m.duracao_max_por_mp;
  if (!m.fala || !faixas?.length) return Infinity;
  const limite = (faixas.find(([ate]) => mp <= ate + 1e-9) || faixas[faixas.length - 1])[1];
  return primeira ? limite : Math.min(limite, m.duracao_max_seguintes ?? limite);
}
const duracoesTomada = (m, mp, i) => { const max = duracaoMaximaH3(m, mp, i === 0), lista = m.duracoes.filter(d => d <= max); return lista.length ? lista : [m.duracoes[0]]; };
// Curta de propósito: o texto antigo citava MP e os defeitos das emendas e ninguém lia (análise de UX de 13/11/2026)
const AJUDA_DURACAO = "A tomada 1 vai até 10 s e as outras até 5 s. Uma tomada longa com a fala inteira soa mais natural do que várias curtas.";

function htmlTomada(t, i, duracoes, fala = true) {
  const opt = (v, r, sel) => `<option value="${esc(v)}" ${sel ? "selected" : ""}>${esc(r)}</option>`;
  // Uma duração que não vale mais (resolução maior, ou a tomada deixou de ser a 1) vai para a maior permitida abaixo dela
  const pedida = Number(t.duracao) || 3, abaixo = duracoes.filter(d => d <= pedida);
  const duracao = duracoes.includes(pedida) ? pedida : abaixo.length ? abaixo[abaixo.length - 1] : maisPerto(pedida, duracoes);
  const soH3 = fala ? "" : "hidden";
  return `<div class="tomada" data-tomada>
    <div class="tomada-topo"><h3>Tomada ${i + 1}</h3><button type="button" class="simples" data-tomada-tirar>Remover</button></div>
    <label class="campo"><span class="rotulo">O que acontece</span><textarea data-campo="acao" maxlength="${maxAcao()}" placeholder="${fala ? "Ex.: o personagem acena para a câmera e sorri" : "Ex.: the character waves at the camera"}">${esc(t.acao)}</textarea><span class="ajuda conta" data-conta-acao></span></label>
    <label class="campo" ${soH3}><span class="rotulo">Fala (opcional)</span><input type="text" data-campo="fala" maxlength="300" value="${esc(t.fala)}"></label>
    <div class="aviso" data-aviso-fala hidden></div>
    <div class="tres">
      <label class="campo"><span class="rotulo">Câmera</span><select data-campo="camera">${(S.dados?.imagem.cameras || Object.keys(NOMES_CAMERA)).map(c => opt(c, NOMES_CAMERA[c], t.camera === c)).join("")}</select></label>
      <label class="campo"><span class="rotulo">Duração</span><select data-campo="duracao" title="${esc(fala ? AJUDA_DURACAO : "")}">${duracoes.map(d => opt(d, `${num(d, d === 4.25 ? 2 : d % 1 ? 1 : 0)} s`, duracao === d)).join("")}</select></label>
      <label class="chave" style="margin-bottom:8px"><input type="checkbox" role="switch" data-campo="olhar" ${t.olhar ? "checked" : ""}><span class="trilho"></span>Olhar para a câmera</label>
    </div>
    <label class="campo" ${soH3}><span class="rotulo">Sons (opcional)</span><input type="text" data-campo="som" maxlength="300" value="${esc(t.som)}" placeholder="Em inglês. Ex.: birds chirping, distant traffic. Sem isto, o ambiente fica quieto."></label>
  </div>`;
}
function lerTomadas(caixa) {
  return [...caixa.querySelectorAll("[data-tomada]")].map(n => {
    const v = c => n.querySelector(`[data-campo="${c}"]`);
    return { acao: v("acao").value, fala: v("fala").value, som: v("som").value, camera: v("camera").value, olhar: v("olhar").checked, duracao: Number(v("duracao").value) };
  });
}
/* A fala e o som de cada tomada ficam guardados mesmo com o Wan (os campos só somem): voltar ao H3 devolve o texto */
function desenharTomadas(lista) {
  const m = modeloImagem(), mp = Number($("i-megapixels").value) || m.padrao.megapixels;
  const listas = lista.map((_, i) => duracoesTomada(m, mp, i));
  // Guarda quais durações foram reduzidas, para o aviso explicar por quê
  S.duracoesReduzidas = lista.map((t, i) => Number(t.duracao) > Math.max(...listas[i]) ? i + 1 : 0).filter(Boolean);
  S.chaveDuracoes = `${m.id}|${mp}`;
  $("i-tomadas").innerHTML = lista.map((t, i) => htmlTomada(t, i, listas[i], m.fala)).join("");
  $("i-tomadas").querySelectorAll("[data-tomada-tirar]").forEach(b => { b.hidden = lista.length < 2; });
  $("i-adicionar").disabled = lista.length >= S.dados.imagem.max_tomadas;
}
function lerImagem() {
  const texto = modoTexto();
  // Texto para vídeo: só o H3 com o fl2va oficial (o testado sem imagem), sem os outros ângulos
  return { modelo: texto ? "h3" : $("i-modelo").value, quem: $("i-quem").value, voz: $("i-voz").value, megapixels: Number($("i-megapixels").value), proporcao: $("i-proporcao").value,
           semente: $("i-semente").value === "" ? null : Number($("i-semente").value), acabamento: $("i-acabamento").value, negativo: $("i-negativo").value, fluidez: $("i-fluidez").checked,
           referencias: texto ? [] : S.irefs, tomadas: lerTomadas($("i-tomadas")), seguintes: $("i-seguintes").value || null, primeira: texto ? null : $("i-primeira").value || null, loras: lerLorasImagem(),
           cena: texto ? $("i-cena").value : "" };
}
/* H3: o modelo da tomada 1 (o fl2va oficial ou um H3 ref2va da comunidade) e o ref2va das tomadas 2 em diante.
   Um nome com "turbo" já vem acelerado: o servidor tira a LoRA de aceleração e usa 8 passos. */
/* Nome do projeto de video a partir do arquivo da imagem: "texto_imagem_foto_cachorro_imagem_1.png" vira "video_foto_cachorro"
   (antes saia "imagem_texto_imagem_foto_cachorro_imagem", com as palavras repetidas) */
function nomeDoVideo(arquivo) {
  const base = String(arquivo).replace(/\.[a-z0-9]+$/i, "").replace(/^texto_(imagem_)?/i, "").replace(/_imagem_\d+$/i, "");
  return `video_${base || "da_imagem"}`;
}
function nomeRef2va(arquivo) {
  const versao = arquivo.match(/_v(\d+)/i)?.[1], beta = arquivo.match(/beta(\d+)/i)?.[1];
  if (NOMES_MODELO[arquivo]) return NOMES_MODELO[arquivo].replace(/ \(.*\)$/, "");
  const familia = /^minimax_h3/i.test(arquivo) ? "MiniMax H3" : null;
  if (!familia) return semExt(arquivo);
  return `${familia}${versao ? ` v${versao}` : beta ? ` beta${beta}` : ""}${/fix(\d+)/i.test(arquivo) ? ` fix${arquivo.match(/fix(\d+)/i)[1]}` : ""}${/turbo/i.test(arquivo) ? " Turbo" : ""}`;
}
function preencherSeguintes(d) {
  const oficial = d.padrao?.modelo, atual = $("i-seguintes").value;
  const outros = (d.opcoes?.modelos || []).filter(m => m !== oficial);
  $("i-seguintes").innerHTML = `<option value="">MiniMax H3 oficial (padrão)</option>` + outros.map(m => `<option value="${esc(m)}">${esc(nomeRef2va(m))}</option>`).join("");
  $("i-seguintes").value = outros.includes(atual) ? atual : "";
  const atual1 = $("i-primeira").value;
  $("i-primeira").innerHTML = `<option value="">MiniMax H3 oficial (padrão)</option>` + outros.map(m => `<option value="${esc(m)}">${esc(nomeRef2va(m))}</option>`).join("");
  $("i-primeira").value = outros.includes(atual1) ? atual1 : "";
  ajudaSeguintes();
}
function ajudaSeguintes() {
  const v = $("i-seguintes").value;
  $("i-seguintes-ajuda").textContent = (!v ? "O que já foi testado." : /turbo/i.test(v) ? "Já vem acelerado: 8 passos, sem a LoRA de aceleração. Mais rápido; o autor diz que perde um pouco de qualidade."
    : "Variante da comunidade, com a mesma LoRA de aceleração do padrão.");
  const p1 = $("i-primeira").value;
  $("i-primeira-ajuda").textContent = !p1 ? "Parte da sua imagem. O que já foi testado."
    : AJUDA_PRIMEIRA[p1] ? AJUDA_PRIMEIRA[p1]
    : /turbo/i.test(p1) ? "Ainda não testado na tomada 1. Já vem acelerado: 8 passos, sem a LoRA de aceleração."
    : "Também deve partir da sua imagem, com a LoRA de aceleração do padrão. Só a versão Turbo foi testada na tomada 1.";
}
$("i-seguintes").addEventListener("change", () => { ajudaSeguintes(); atualizarImagem(); });
$("i-primeira").addEventListener("change", () => { ajudaSeguintes(); atualizarImagem(); });
/* Até 2 LoRAs de estilo, em todas as tomadas, junto da aceleração. O número ao lado é a força.
   H3: as de H3 da pasta loras menos as técnicas (ambiente.lora_de_estilo).
   Wan: os pares HIGH + LOW (loras.pares_wan); o valor é a metade HIGH e o servidor acha a LOW. */
function lerLorasImagem() {
  return [1, 2].map(k => [$(`i-lora-${k}`).value, Number($(`i-forca-${k}`).value) || 0.8]).filter(([n]) => n);
}
function preencherLorasImagem(d) {
  const h3 = modeloImagem().fala;
  const lista = h3 ? (d.opcoes?.loras_estilo || []).map(l => ({ valor: l, nome: semExt(l) }))
    : (d.opcoes?.loras_wan || []).map(x => ({ valor: x.alta, nome: `${x.nome} (HIGH + LOW)` }));
  for (const k of [1, 2]) {
    const atual = $(`i-lora-${k}`).value;
    $(`i-lora-${k}`).innerHTML = `<option value="">Nenhuma</option>` + lista.map(l => `<option value="${esc(l.valor)}">${esc(l.nome)}</option>`).join("");
    $(`i-lora-${k}`).value = lista.some(l => l.valor === atual) ? atual : "";
  }
  $("i-loras-ajuda").textContent = h3
    ? (lista.length ? "Entram em todas as tomadas, junto da aceleração. Com duas, comece com 0,6 a 0,8 em cada."
      : "Nenhuma LoRA de estilo de H3 na pasta loras (ponha em loras/h3 ou use H3 no nome).")
    : (lista.length ? "Cada par entra nos dois modelos do Wan: a HIGH nos primeiros passos, a LOW nos últimos. Se a LoRA pede palavras-chave, escreva-as na ação."
      : "Nenhum par de LoRAs do Wan na pasta loras. Ponha as duas metades, HIGH e LOW, em loras/wan.");
}
function aplicarLorasImagem(loras) {
  [1, 2].forEach((k, i) => {
    const [nome, forca] = loras[i] || ["", 0.8];
    $(`i-lora-${k}`).value = nome;
    if ($(`i-lora-${k}`).value !== nome) $(`i-lora-${k}`).value = "";
    $(`i-forca-${k}`).value = forca;
  });
}
/* Troca as listas que dependem do modelo (resolução, acabamento, durações) e mostra só os campos que ele usa.
   O que já estava escolhido fica, se o modelo novo aceitar; senão, vai para o padrão dele. */
function aplicarModeloImagem(manter = {}) {
  const m = modeloImagem(), opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  const mp = Number(manter.megapixels ?? $("i-megapixels").value), ac = manter.acabamento ?? $("i-acabamento").value;
  $("i-megapixels").innerHTML = m.qualidades.map(q => opt(q, nomeQualidade(q, m))).join("");
  $("i-megapixels").value = m.qualidades.includes(mp) ? mp : m.padrao.megapixels;
  $("i-acabamento").innerHTML = m.acabamentos.map(x => opt(x, NOMES_ACABAMENTO[x] || x)).join("");
  $("i-acabamento").value = m.acabamentos.includes(ac) ? ac : "nenhum";
  $("i-modelo-ajuda").textContent = m.ajuda || "";
  for (const id of ["campo-i-quem", "campo-i-voz", "campo-irefs", "campo-i-primeira", "campo-i-seguintes"]) $(id).hidden = !m.fala;
  // A lista de LoRAs muda com o modelo: as de H3 ou os pares do Wan
  if (S.dados) preencherLorasImagem(S.dados);
  $("campo-i-negativo").hidden = m.fala;
  $("campo-i-fluidez").hidden = !m.fluidez;
  $("tela-imagem").dataset.modelo = m.id;
  // H3: a ação em português funcionou em 13/11/2026 (o cachorro levantou a cabeça, olhou para a câmera e abanou o rabo). O Wan não foi testado
  $("i-tomadas-ajuda").textContent = m.fala ? `Uma tomada por fala, com uma ação simples em cada. Pode escrever em português; nas falas, números por extenso. ${AJUDA_DURACAO}`
    : "Uma ação simples por tomada, em inglês. Cada tomada parte do último quadro da anterior.";
  if (S.marcaOpcoesImagem) desenharTomadas(lerTomadas($("i-tomadas")));
}
function aplicarImagem(a) {
  const p = { ...S.dados.imagem.padrao, ...a };
  $("i-modelo").value = p.modelo;
  // Um modelo que não está mais instalado volta para o H3
  if (!$("i-modelo").value || $("i-modelo").selectedOptions[0]?.disabled) $("i-modelo").value = "h3";
  aplicarModeloImagem({ megapixels: p.megapixels, acabamento: p.acabamento });
  $("i-cena").value = p.cena ?? "";
  $("i-quem").value = p.quem; $("i-voz").value = p.voz; $("i-proporcao").value = p.proporcao; $("i-semente").value = p.semente ?? ""; $("i-negativo").value = p.negativo ?? ""; $("i-fluidez").checked = p.fluidez !== false;
  // Um modelo que não está mais instalado volta para o oficial
  $("i-seguintes").value = p.seguintes || "";
  if (!$("i-seguintes").value) $("i-seguintes").value = "";
  $("i-primeira").value = p.primeira || "";
  if (!$("i-primeira").value) $("i-primeira").value = "";
  ajudaSeguintes();
  aplicarLorasImagem(p.loras || []);
  if ("referencias" in a) { S.irefs = [...a.referencias]; desenharRefs(); }
}
/* Sem nenhuma imagem: o cartão de escolha com a explicação. Com alguma: uma grade com as imagens (× no canto),
   os envios em andamento e, enquanto houver vaga, um quadrado para adicionar mais. */
function desenharRefs() {
  const max = S.dados?.imagem?.max_referencias || 4, n = S.irefs.length, enviando = S.irefsEnviando || 0, tem = n + enviando > 0;
  const itens = S.irefs.map((nome, i) => `<span class="ref">${midia(`<img loading="lazy" src="/entrada/foto/${encodeURIComponent(nome)}" alt="">`, "Foto oculta")}<button type="button" class="ref-tirar" data-tirar-ref="${i}" title="Tirar" aria-label="Tirar a imagem ${i + 1} (${esc(nome)})"><svg aria-hidden="true"><use href="#s-fechar"/></svg></button></span>`);
  for (let i = 0; i < enviando; i++) itens.push(`<span class="ref enviando" role="status" aria-label="Enviando imagem"></span>`);
  if (tem && n + enviando < max) itens.push(`<button type="button" class="ref ref-mais" data-mais-ref><svg aria-hidden="true"><use href="#s-mais"/></svg>Adicionar</button>`);
  $("irefs-lista").innerHTML = itens.join("");
  $("zona-irefs").hidden = tem;
  $("irefs-conta").textContent = tem ? `${n} de ${max}` : "opcional";
  $("irefs-dica").textContent = tem ? "Frente, três quartos, lado e costas, com fundo liso. Valem da segunda tomada em diante." : "";
}
function tirarRef(i) {
  S.irefs.splice(i, 1);
  desenharRefs();
  // O foco segue para a imagem que tomou o lugar, ou para o próximo jeito de adicionar
  const alvo = $("irefs-lista").querySelector(`[data-tirar-ref="${Math.min(i, S.irefs.length - 1)}"]`) || $("irefs-lista").querySelector("[data-mais-ref]") || $("irefs");
  alvo.focus();
  atualizarImagem();
}
async function enviarRefs(arquivos) {
  const aviso = $("irefs-aviso"), max = S.dados.imagem.max_referencias;
  aviso.hidden = true;
  const lista = [...arquivos];
  if (S.irefs.length + lista.length > max) { aviso.textContent = `Use até ${max} imagens: as demais foram ignoradas.`; aviso.hidden = false; }
  const fila = lista.slice(0, Math.max(0, max - S.irefs.length - (S.irefsEnviando || 0)));
  S.enviando++;
  S.irefsEnviando = (S.irefsEnviando || 0) + fila.length;
  desenharRefs();
  atualizarImagem();
  try {
    for (const f of fila) {
      const r = await enviar(f, "foto", () => {});
      S.irefsEnviando--;
      if (!S.irefs.includes(r.arquivo)) S.irefs.push(r.arquivo);
      desenharRefs();
    }
  } catch (e) {
    aviso.textContent = e.message;
    aviso.hidden = false;
  }
  S.irefsEnviando = 0;
  desenharRefs();
  S.enviando--;
  atualizarImagem();
}
function preencherImagem(d) {
  const marca = JSON.stringify([d.imagem, d.proporcoes, d.opcoes?.modelos, d.opcoes?.loras_estilo, d.opcoes?.loras_wan]);
  if (marca === S.marcaOpcoesImagem) return;
  const atual = S.marcaOpcoesImagem ? lerImagem() : null;
  const opt = (v, t, desligado) => `<option value="${esc(v)}" ${desligado ? "disabled" : ""}>${esc(t)}</option>`;
  // Um servidor de antes do seletor não manda a lista: fica só o H3
  const modelos = d.imagem.modelos || [{ id: "h3", nome: "MiniMax H3", faltam: [] }];
  opcoesModelo("i-modelo", modelos, m => m.nome + (m.id === "h3" ? " (fala e som)" : " (sem som)"));
  $("i-proporcao").innerHTML = d.proporcoes.map(x => opt(x, nomeProporcao(x))).join("");
  preencherSeguintes(d);
  preencherLorasImagem(d);
  const primeira = !S.marcaOpcoesImagem;
  S.marcaOpcoesImagem = marca;
  aplicarImagem(atual || {});
  if (primeira) desenharTomadas([{ ...TOMADA_VAZIA }]);
  else desenharTomadas(atual.tomadas);
}
function salvarRascunhoImagem() {
  try { localStorage.setItem(chaveRascunhoImagem(), JSON.stringify({ foto: modoTexto() ? null : S.ifoto, ajustes: lerImagem(), projeto: S.nomeImagemEditado ? $("i-projeto").value : null })); } catch {}
}
function restaurarImagem() {
  let r = null;
  try { r = JSON.parse(localStorage.getItem(chaveRascunhoImagem())); } catch {}
  if (!r) return;
  if (r.ajustes) { aplicarImagem(r.ajustes); if (r.ajustes.tomadas?.length) desenharTomadas(r.ajustes.tomadas); }
  if (r.projeto) { $("i-projeto").value = r.projeto; S.nomeImagemEditado = true; }
  if (r.foto) { preencherArquivo("ifoto", r.foto); if (!S.nomeImagemEditado) $("i-projeto").value = nomeLivre(nomeDoVideo(r.foto.arquivo)); }
}
function aoEscolherImagem(f) {
  if (f.largura) ajustarProporcao(f, "i-proporcao");
  if (!S.nomeImagemEditado) $("i-projeto").value = nomeLivre(nomeDoVideo(f.arquivo));
}
/* Tempo de uma geração inteira: as tomadas e o acabamento */
function segundosImagem(a, m, quadros) {
  if (m.fala) return a.tomadas.reduce((s, t, i) => s + segundosTomadaH3(t.duracao, a.megapixels, i === 0, /turbo/i.test(a.seguintes || "")), 0) + segundosAcabamento(a.acabamento, quadros);
  // RIFE: 13 s para 6 s de vídeo (09/11/2026); com ele o ESRGAN amplia o dobro de quadros
  const suave = a.fluidez && m.fluidez;
  const rife = suave ? 8 + quadros / m.fps * 1.2 : 0;
  return SEGUNDOS_LER_WAN + a.tomadas.reduce((s, t) => s + segundosTomadaWan(m.id, t.duracao, a.megapixels), 0) + rife + segundosAcabamento(a.acabamento, suave ? quadros * 2 : quadros) * 24 / 16;
}
function atualizarImagem() {
  if (!S.marcaOpcoesImagem) return;
  // A resolução mudou: as durações permitidas em cada tomada podem ter mudado também
  if (S.chaveDuracoes !== `${modeloImagem().id}|${Number($("i-megapixels").value)}`) desenharTomadas(lerTomadas($("i-tomadas")));
  const travada = sincronizarTrava("imagem");
  const texto = modoTexto(), a = lerImagem(), m = modeloImagem(a.modelo), p = S.dados.imagem.padrao, falta = [], tar = S.dados.tarefa, f = texto ? null : S.ifoto;
  if (texto && !S.nomeImagemEditado && !$("i-projeto").value) $("i-projeto").value = nomeLivre("video_do_texto");
  const padrao = a.megapixels === m.padrao.megapixels && a.acabamento === p.acabamento && (m.fala || a.negativo.trim() === p.negativo);
  const quadros = a.tomadas.reduce((s, t, i) => s + quadrosTomada(m, t.duracao, i === 0), 0);
  // O refino quase nao amplia acima de 0,7 MP: a opcao fica bloqueada
  const opRefino = $("i-acabamento").querySelector('[value="refino"]');
  const semRefino = a.megapixels > S.dados.imagem.max_mp_refino;
  if (opRefino) opRefino.disabled = semRefino;
  if (semRefino && a.acabamento === "refino") { $("i-acabamento").value = "esrgan"; a.acabamento = "esrgan"; }
  $("i-tamanho").textContent = `Tamanho: ${m.fala ? resolucao(a) : tamanhoWan(a)}`;
  $("i-acabamento-ajuda").textContent = AJUDA_ACABAMENTO[a.acabamento] + (semRefino && opRefino ? " O refino só vale até 0,7 MP." : "");
  $("i-ajustes-situacao").textContent = padrao ? "padrão testado" : "alterado";
  const segundos = segundosImagem(a, m, quadros);
  const tamanho = m.fala ? resolucao(a) : tamanhoWan(a);
  const saida = a.acabamento === "nenhum" ? tamanho : `${tamanho}, ampliado para ${tamanhoHD(a.proporcao)}`;
  $("i-fita").innerHTML = a.tomadas.map((t, i) => `<span class="nova" style="flex:${quadrosTomada(m, t.duracao, i === 0)} 1 0" title="Tomada ${i + 1}, ${num(t.duracao, t.duracao % 1 ? 2 : 0)} s"><b>${i + 1}</b></span>`).join("");
  $("i-fita-eixo").innerHTML = eixoReal([[0, quadros]], quadros / m.fps);
  $("i-conta").textContent = `${a.tomadas.length} ${a.tomadas.length === 1 ? "tomada" : "tomadas"}, ${num(quadros / m.fps)} s de vídeo em ${saida}${m.fala ? "" : `, sem som, a ${a.fluidez && m.fluidez ? 32 : m.fps} quadros por segundo`}.`;
  // Conta grosseira: fora do que já foi medido (no Wan, 0,475 ou 0,6 MP em 2, 3 ou 5 s)
  const medido = m.fala ? a.acabamento !== "refino" && a.tomadas.every(t => (MEDIDOS_H3[a.megapixels] || []).includes(t.duracao)) : QUALIDADES_TESTADAS_WAN.includes(a.megapixels) && a.tomadas.every(t => DURACOES_TESTADAS_WAN.includes(t.duracao)) && a.acabamento === "nenhum";
  mostrarEstimativa("i-estimativa", travada ? null : segundos, !medido);
  const avisos = [];
  if (m.fala) {
    if (texto) avisos.push("Testado em 10/11: uns 4 min por tomada, com fala. O personagem e o lugar das tomadas seguintes vêm de um quadro da tomada 1.");
    if (a.referencias.length) avisos.push("Imagens extras do personagem só foram testadas uma vez, com 4 vistas.");
    if (a.megapixels === 0.7) avisos.push("0,7 MP foi testada em duas tomadas: imagem mais limpa, cerca de 30% mais lenta.");
    else if (a.megapixels === 0.8) avisos.push("0,8 MP foi testada e aprovada em 11/11, em tomadas de 5 e 10 s: cerca de 1,7 a 1,9 vez o tempo de 0,47 MP.");
    else if (a.megapixels >= 1) avisos.push("1 MP: tomadas de até 5 s. 3 e 4,25 s passaram em 11/11 (de 5 a 16 min cada, o tempo varia muito), mas 10 s derrubou a placa. Se cair, as tomadas prontas ficam guardadas.");
    else if (a.megapixels !== m.padrao.megapixels) avisos.push("Esta resolução ainda não foi testada nesta placa.");
    if (S.duracoesReduzidas?.length) avisos.push(`A duração ${S.duracoesReduzidas.length > 1 ? "das tomadas" : "da tomada"} ${S.duracoesReduzidas.join(", ")} foi reduzida para o limite desta resolução.`);
    if (a.tomadas.some(t => t.duracao > 5)) avisos.push("Tomada longa: 10 s foi medida em 11/11 num take único (12 min a 0,47 MP, 20 min a 0,8 MP, sem queda); 6 a 8 s ficam entre os pontos medidos. Com a fala inteira numa tomada só, não há emenda para repetir frase ou mudar a voz.");
    if (a.loras.length && texto) avisos.push("LoRAs de estilo ainda não foram testadas no Texto para vídeo.");
    else if (a.loras.length) avisos.push("No teste (09/11) a LoRA de stop motion não mudou o visual de uma foto realista, nem com força 1,5: a tomada 1 segue a imagem. Para o estilo pegar, parta de uma imagem que já esteja nele.");
    if (a.acabamento === "refino") avisos.push("O refino do H3 só foi testado em 3 s de vídeo: pode clarear o fundo, mudar pequenas cores e mostrar emendas entre os pedaços.");
  } else {
    if (a.tomadas.some(t => t.fala.trim() || t.som.trim())) avisos.push("O Wan não faz som: as falas e os sons das tomadas ficam guardados, mas não entram neste vídeo.");
    if (!QUALIDADES_TESTADAS_WAN.includes(a.megapixels)) avisos.push("Esta resolução ainda não foi testada no Wan.");
    if (a.tomadas.some(t => !DURACOES_TESTADAS_WAN.includes(t.duracao))) avisos.push("4 s ainda não foi testado no Wan.");
    if (a.tomadas.length > 1) avisos.push("Cada tomada parte do último quadro da anterior: a cor e a nitidez podem mudar um pouco a cada emenda.");
    if (a.acabamento === "esrgan") avisos.push("O ESRGAN ainda não foi testado com o Wan.");
    if (a.loras.length) avisos.push("LoRAs de estilo no Wan ainda não foram testadas no estúdio.");
  }
  // Medido em 07/11/2026: duas tomadas seguidas aproximando deixaram o personagem cortado no quadro
  if (a.tomadas.some((t, i) => t.camera === "aproximar" && a.tomadas[i + 1]?.camera === "aproximar")) avisos.push("Aproximar em tomadas seguidas fecha muito o quadro: no teste, o personagem ficou cortado.");
  else if (a.tomadas.some(t => t.camera !== "parada")) avisos.push("Câmera em movimento só foi testada uma vez. O modelo decide a velocidade, então confira o enquadramento.");
  if (f?.largura) {
    const mm = a.proporcao.match(/^(\d+):(\d+)/), r = mm[1] / mm[2], foto = f.largura / f.altura;
    if (Math.abs(Math.log(r / foto)) > 0.05) avisos.push(`A imagem tem outro formato (${f.largura}×${f.altura}): as bordas serão cortadas.`);
  }
  $("i-aviso-config").textContent = avisos.join(" ");
  $("i-aviso-config").hidden = !avisos.length;
  $("i-tomadas").querySelectorAll("[data-tomada]").forEach((n, i) => {
    const t = a.tomadas[i], aviso = n.querySelector("[data-aviso-fala]"), precisa = silabas(t.fala) / SILABAS_POR_SEGUNDO, cabe = novosImagem(t.duracao, i === 0) / 24 - 0.3;
    const maxAqui = Math.max(...duracoesTomada(m, a.megapixels, i)), cabeMax = novosImagem(maxAqui, i === 0) / 24 - 0.3;
    aviso.textContent = !m.fala || precisa <= cabe ? "" : precisa <= cabeMax ? `Esta fala deve precisar de cerca de ${num(precisa)} s e pode sair cortada. Aumente a duração ou encurte o texto.`
      : `Esta fala deve precisar de cerca de ${num(precisa)} s, mais do que cabe ${i === 0 ? "nesta resolução" : "numa tomada seguinte (até 5 s)"}. Encurte o texto ou divida a fala${i === 0 ? " (ou reduza a resolução para usar até 10 s)" : ""}.`;
    aviso.hidden = !aviso.textContent;
    // O contador so aparece perto do limite, para nao poluir as tomadas curtas
    const conta = n.querySelector("[data-conta-acao]"), usados = t.acao.length;
    conta.textContent = usados > maxAcao() * 0.75 ? `${usados} de ${maxAcao()} caracteres` : "";
    conta.hidden = !conta.textContent;
  });
  if (S.enviando) falta.push("Esperando o envio terminar");
  else if (texto && !a.cena.trim()) falta.push("Descreva a cena");
  else if (!texto && !f) falta.push("Escolha a imagem");
  if (m.faltam?.length) falta.push("Este modelo não está instalado");
  if (a.loras.length === 2 && a.loras[0][0] === a.loras[1][0]) falta.push("Escolha LoRAs de estilo diferentes");
  if (a.loras.some(([, f]) => !(f > 0 && f <= 1.5))) falta.push("Use força de LoRA de estilo entre 0,05 e 1,5");
  if (m.fala && a.tomadas.some(t => !t.acao.trim() && !t.fala.trim())) falta.push("Em cada tomada, escreva o que acontece ou a fala");
  if (!m.fala && a.tomadas.some(t => !t.acao.trim())) falta.push("Em cada tomada, escreva o que acontece");
  if ((f || texto) && !/^[A-Za-z0-9_-]{1,60}$/.test($("i-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(x => x.nome === $("i-projeto").value)) falta.push("Já existe um projeto com este nome");
  if (f && !$("i-autorizacao").checked) falta.push("Confirme a autorização da imagem");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  $("i-falta").innerHTML = travada ? notaTravada("imagem") : falta.length ? `<ul>${falta.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  $("i-gerar").disabled = falta.length > 0;
  rotuloFila($("i-gerar"));
  salvarRascunhoImagem();
}
async function iniciarImagem() {
  $("i-erro").hidden = true;
  $("i-gerar").disabled = true;
  const nome = $("i-projeto").value;
  try {
    await postar("/api/iniciar-imagem", { projeto: nome, foto: modoTexto() ? null : S.ifoto?.arquivo || null, ajustes: lerImagem(), autorizacao: $("i-autorizacao").checked });
    S.abertos.add(nome);
    S.dispensada = null;
    marcarEnviado("imagem", nome);
  } catch (e) {
    $("i-erro").textContent = e.message;
    $("i-erro").hidden = false;
  }
  await consultar(true);
}
function zerarImagem() {
  S.ifoto = null;
  S.nomeImagemEditado = false;
  $("i-projeto").value = "";
  $("i-autorizacao").checked = false;
  $("irefs-aviso").hidden = true;
  limparZona("ifoto");
  aplicarImagem({ referencias: [] });
  desenharTomadas([{ ...TOMADA_VAZIA }]);
}
function limparImagem() {
  soltarTrava("imagem");
  zerarImagem();
  try { localStorage.removeItem(chaveRascunhoImagem()); } catch {}
}
/* Troca entre Imagem para vídeo e Texto para vídeo: guarda o rascunho do modo que sai e traz o do que entra.
   Com a tela travada (gerando), só muda o modo: o que foi enviado continua à vista. */
function trocarModoImagem(texto) {
  const tela = $("tela-imagem"), novo = texto ? "texto" : "imagem";
  if (tela.dataset.modo === novo) return;
  const travada = tela.classList.contains("travada"), pronto = !!S.marcaOpcoesImagem;
  if (pronto && tela.dataset.modo && !travada) salvarRascunhoImagem();
  tela.dataset.modo = novo;
  if (!pronto) return;  // as opções ainda não chegaram: o rascunho é restaurado quando chegarem
  if (!travada) { zerarImagem(); restaurarImagem(); }
  if (texto) { $("i-modelo").value = "h3"; aplicarModeloImagem(); }
  desenharHistorico("imagem");
  atualizarImagem();
}
