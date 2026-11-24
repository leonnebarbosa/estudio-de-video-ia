/* Troca de personagem */
const RASCUNHO_TROCA = "trocar_personagem_rascunho";
const NOMES_TROCA = {
  "minimax_h3_character_swap_v1.1_ref2va_fro.safetensors": "Character Swap v1.1 (padrão testado)",
  "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors": "DMD turbo, 8 passos (padrão testado)",
  "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors": "ref2v turbo, 8 passos (não testada aqui)",
  "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors": "DMAD (não testada aqui)",
  "minimax_h3_lms_v1.0_r64.safetensors": "LMS v1.0 (padrão testado)",
  "h3_upscaler_lms_v0.1.safetensors": "LMS v0.1 (mais nítido no teste)",
  "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors": "LBH (mais suave no teste)",
};
/* Ampliação da troca. A segunda passagem do H3 derrubou a placa 3 vezes seguidas em 11/11/2026 (a 0,8 e a 0,5 MP); sem ela,
   ampliando depois com o ESRGAN (fora do ComfyUI, ~1 GB), nunca caiu. Por isso o ESRGAN virou o padrão. */
const AJUDA_AMPLIAR = {
  esrgan: "Depois da troca, amplia o vídeo para Full HD quadro a quadro, fora do ComfyUI: contornos limpos, textura lisa, uns 10 s por segundo de vídeo. Nunca derrubou a placa. O vídeo da primeira passagem fica guardado como primeira_passagem.mp4.",
  h3: "O H3 refaz o vídeo em resolução maior, com mais detalhe, e leva cerca do dobro do tempo; o rosto pode mudar um pouco. Derrubou a placa 3 vezes seguidas em 11/11, a 0,8 e a 0,5 MP.",
  nenhuma: "O vídeo fica no tamanho da primeira passagem. Atenção: se ele for emendado num vídeo de resolução maior (uma base a 0,8 MP ou já ampliada), a troca vai aparecer menos nítida que o resto." };
// Resoluções da primeira passagem: o que já passou nesta placa
const NOTAS_MP_TROCA = { 0.2: "padrão testado", 0.3: "não testada", 0.5: "testada até 5 s", 0.8: "testada até 3,5 s" };
/* O que roda numa passada pela resolução da primeira passagem (validacao.DURACAO_MAX_TROCA_POR_MP; a 0,8 MP, 5 s caiu em
   11/11). Acima disso a troca vai em janelas desse tamanho, até duracao_max; com o upscale não há janelas. */
function duracaoPassadaTroca(mp) {
  const faixas = S.dados.troca.duracao_max_por_mp, geral = S.dados.troca.duracao_max;
  if (!faixas?.length) return geral;
  return Math.min(geral, (faixas.find(([ate]) => mp <= ate + 1e-9) || faixas[faixas.length - 1])[1]);
}
const duracaoMaxTroca = (mp, upscale) => upscale ? duracaoPassadaTroca(mp) : S.dados.troca.duracao_max;
const gradeH3 = n => { n = Math.max(5, n); return n + (((5 - n % 17) % 17) + 17) % 17; };
/* Quantas janelas (trocar_personagem.janelas): a primeira entrega a janela inteira, as seguintes a janela menos 17 */
function janelasTroca(d, mp) {
  const fps = S.dados.constantes.fps, jan = gradeH3(Math.round(duracaoPassadaTroca(mp) * fps)), total = Math.round(d * fps);
  return total <= jan ? 1 : 1 + Math.ceil((total - jan) / (jan - 17));
}
const nomeTroca = n => NOMES_TROCA[n] || NOMES_MODELO[n] || semExt(n);
const curtoTroca = n => nomeTroca(n).replace(/ \(.*\)$/, "");
/* O mesmo arredondamento do fluxo: o modelo so aceita certos numeros de quadros */
// Pelo número de quadros do arquivo: Math.floor(duração × fps) recusava um vídeo de 73 quadros (3,04 s) para 3 s
const quadrosDoVideo = v => v.quadros || Math.floor(v.duracao * S.dados.constantes.fps);
/* Numa passada, arredondado para cima; em janelas, os quadros pedidos (trocar_personagem.quadros_usados) */
function quadrosTroca(d, mp) {
  const n = gradeH3(Math.round(d * S.dados.constantes.fps));
  return mp && janelasTroca(d, mp) > 1 ? Math.round(d * S.dados.constantes.fps) : n;
}
/* Até 2 LoRAs de estilo, da mesma lista do Imagem para vídeo (ambiente.lora_de_estilo). Entram logo depois da
   LoRA de troca e valem nas duas passagens. O número ao lado é a força. */
function lerLorasTroca() {
  return [1, 2].map(k => [$(`t-lora-${k}`).value, Number($(`t-forca-${k}`).value) || 0.8]).filter(([n]) => n);
}
function preencherLorasTroca(lista) {
  for (const k of [1, 2]) $(`t-lora-${k}`).innerHTML = `<option value="">Nenhuma</option>` + lista.map(l => `<option value="${esc(l)}">${esc(semExt(l))}</option>`).join("");
  $("t-loras-ajuda").textContent = lista.length ? "Valem na primeira passagem e no upscale. Com duas, comece com 0,6 a 0,8 em cada. Num vídeo realista, estilo visual pega pouco; as de movimento mudam mais."
    : "Nenhuma LoRA de estilo de H3 na pasta loras (ponha em loras/h3 ou use H3 no nome).";
}
function aplicarLorasTroca(loras) {
  [1, 2].forEach((k, i) => {
    const [nome, forca] = loras[i] || ["", 0.8];
    $(`t-lora-${k}`).value = nome;
    if ($(`t-lora-${k}`).value !== nome) $(`t-lora-${k}`).value = "";
    $(`t-forca-${k}`).value = forca;
  });
}
function lerTroca() {
  const lora = id => valor(`t-${id}`) ? [valor(`t-${id}`), Number($(`t-${id}-forca`).value)] : null;
  const res = $("t-upscale-res").value;
  return { modelo: valor("t-modelo"), troca: lora("troca"), turbo: lora("turbo"), nitidez: lora("nitidez"), upscale: $("t-ampliar").value === "h3", esrgan: $("t-ampliar").value === "esrgan", upscale_mesma: res === "mesma",
           upscale_megapixels: res === "mesma" ? S.dados.troca.padrao.upscale_megapixels : Number(res), upscaler: valor("t-upscaler"), megapixels: Number($("t-megapixels").value), proporcao: $("t-proporcao").value,
           passos: Number($("t-passos").value), sampler: valor("t-sampler"), agendador: valor("t-agendador"), semente: $("t-semente").value === "" ? null : Number($("t-semente").value),
           audio_original: $("t-audio").checked, pouca_vram: $("t-pouca-vram").checked, dividir_blocos: $("t-blocos").checked, roupa: $("t-roupa").value, loras: lerLorasTroca(),
           motor: $("t-motor").value,
           // A fala marcada no pedido do Viggle Remake (troca_wangp.prompt_viggle): so no motor viggle
           fala: $("t-fala").checked && $("t-motor").value !== "estudio",
           // Rosto borrado no guia (source_blur): so na Head Swap do estudio
           borrar_rosto: $("t-borrar").checked && $("t-roupa").value === "video" && $("t-motor").value === "estudio" };
}
/* Motor Viggle (troca_wangp.py e troca_viggle.py): Viggle Remake numa janela só, até 14 s; gera no mínimo 90 quadros e corta no pedido.
   Pinta 2 quadros até 7 s, 3 até 11 s e 4 acima (~50 s cada); o Viggle levou 391 e 370 s para 124 quadros a 0,5 MP. */
const ehWangp = a => a.motor === "wangp" || a.motor === "viggle" || a.motor === "wan";
/* Wan Animate 2 (troca_wan.py): pinta o primeiro quadro e anima; as regras da tela são as do Viggle */
const ehWan = a => a.motor === "wan";
/* "wangp" só aparece em projeto ou rascunho antigo (o WanGP rodava esta receita até 22/11): vale como "viggle" */
const ehViggle = a => a.motor === "viggle";
const SEGUNDOS_BORRAO_BASE = 20, SEGUNDOS_BORRAO_POR_SEGUNDO = 14;
/* Janelas do Viggle (troca_wangp.plano_janelas): até 141 quadros numa só; acima disso, janelas de 124 que repetem 5 da anterior. Cada uma pinta 2 quadros */
const janelasViggle = d => { const n = Math.round(d * S.dados.constantes.fps); return n <= 141 ? 1 : Math.ceil((n - 124) / 119) + 1; };
const pintadosWangp = d => $("t-motor").value === "wan" ? 1 : 2 * janelasViggle(d);
const quadrosGeradosWangp = d => gradeH3(Math.max(S.dados.troca.quadros_min_wangp, Math.round(d * S.dados.constantes.fps)));
/* Medido em 22/11: Viggle, ~35 s por quadro pintado e ~360 s por janela a 0,5 MP, mais o acabamento; Wan Animate 2, ~5 s por quadro a 480p */
const segundosWangp = (d, mp) => $("t-motor").value === "wan" ? 90 + 5 * Math.round(d * S.dados.constantes.fps) : 35 * pintadosWangp(d) + 360 * janelasViggle(d) * mp / 0.5 + 60;
function aplicarTroca(a) {
  const p = { ...S.dados.troca.padrao, ...a };
  const lora = (id, v) => { poeValor(`t-${id}`, v?.[0] ?? ""); $(`t-${id}-forca`).value = v?.[1] ?? 1; };
  lora("troca", p.troca); lora("turbo", p.turbo); lora("nitidez", p.nitidez);
  // O ESRGAN substitui a segunda passagem: um projeto com as duas ligadas volta com o ESRGAN
  poeValor("t-modelo", p.modelo); $("t-ampliar").value = p.esrgan ? "esrgan" : p.upscale ? "h3" : "nenhuma"; $("t-upscale-res").value = p.upscale_mesma ? "mesma" : p.upscale_megapixels;
  poeValor("t-upscaler", p.upscaler); $("t-megapixels").value = p.megapixels; $("t-proporcao").value = p.proporcao; $("t-passos").value = p.passos;
  poeValor("t-sampler", p.sampler); poeValor("t-agendador", p.agendador); $("t-semente").value = p.semente ?? "";
  $("t-roupa").value = p.roupa || "video";
  // Um rascunho de quando havia o motor WanGP (a mesma receita, fora do ComfyUI) vai para o Viggle
  $("t-motor").value = p.motor === "wan" ? "wan" : ehWangp(p) ? "viggle" : "estudio";
  aplicarLorasTroca(p.loras || []);
  $("t-audio").checked = p.audio_original; $("t-pouca-vram").checked = p.pouca_vram; $("t-blocos").checked = p.dividir_blocos;
  $("t-borrar").checked = !!p.borrar_rosto;
  $("t-fala").checked = !!p.fala;
  S.passosTrocaEditados = false;
}
function preencherTroca(d) {
  const marca = JSON.stringify([d.opcoes, d.proporcoes]);
  if (marca === S.marcaOpcoesTroca) return;
  const atual = S.marcaOpcoesTroca ? lerTroca() : null;
  S.marcaOpcoesTroca = marca;
  const o = d.opcoes, p = d.troca.padrao;
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  const garante = (lista, v) => lista.includes(v) ? lista : [v, ...lista];
  const nenhuma = opt("", "Nenhuma");
  $("t-modelo").innerHTML = garante(o.modelos, p.modelo).map(m => opt(m, nomeTroca(m))).join("");
  $("t-troca").innerHTML = garante(o.loras_troca.troca, p.troca[0]).map(l => opt(l, nomeTroca(l))).join("");
  $("t-turbo").innerHTML = nenhuma + garante(o.loras_troca.turbo, p.turbo[0]).map(l => opt(l, nomeTroca(l))).join("");
  $("t-nitidez").innerHTML = nenhuma + garante(o.loras_troca.nitidez, p.nitidez[0]).map(l => opt(l, nomeTroca(l))).join("");
  $("t-upscaler").innerHTML = garante(o.upscalers, p.upscaler).map(u => opt(u, nomeTroca(u))).join("");
  $("t-upscale-res").innerHTML = d.troca.qualidades_upscale.map(q => opt(q, `${num(q)} MP${q === p.upscale_megapixels ? " (padrão testado)" : " (testada)"}`)).join("") + opt("mesma", "Mesma da primeira passagem (não testada)");
  $("t-megapixels").innerHTML = d.troca.qualidades.map(q => opt(q, `${num(q)} MP (${q === p.megapixels ? "padrão testado" : NOTAS_MP_TROCA[q] || "não testada"})`)).join("");
  $("t-sampler").innerHTML = garante(o.samplers, p.sampler).map(s => opt(s, s === p.sampler ? `${s} (testado)` : s)).join("");
  $("t-agendador").innerHTML = garante(o.agendadores, p.agendador).map(s => opt(s, s === p.agendador ? `${s} (testado)` : s)).join("");
  $("t-proporcao").innerHTML = d.proporcoes.map(x => opt(x, nomeProporcao(x))).join("");
  preencherLorasTroca(o.loras_estilo || []);
  aplicarTroca(atual || {});
}
function resumoTroca(a) {
  const base = resolucao(a);
  const final = a.esrgan ? tamanhoHD(a.proporcao) : a.upscale ? (a.upscale_mesma ? base : resolucao({ ...a, megapixels: a.upscale_megapixels })) : base;
  const loras = [a.troca, a.turbo, ...(a.upscale ? [a.nitidez] : [])].filter(Boolean).map(([n, f]) => `${curtoTroca(n)} ${num(f, 2)}`).join(", ");
  const estilo = (a.loras || []).map(([n, f]) => `${semExt(n)} ${num(f, 2)}`).join(", ");
  if (ehWangp(a)) return `Viggle: o Qwen Image 2.1 Viggle Swap pinta os quadros e o Viggle Remake (H3 FL2VA Pruned) gera em 6 passos. Roupa ${a.roupa === "foto" ? "da foto" : "do vídeo"}${a.fala ? ", com a fala marcada" : ""}. Saída ${final}${a.esrgan ? `, gerado em ${base} e ampliado com ESRGAN` : ", sem ampliar"}.`;
  return `Roupa ${a.roupa === "foto" ? "da foto" : "do vídeo"}. Saída ${final}${a.esrgan ? `, primeira passagem ${base}, ampliada com ESRGAN` : a.upscale ? `, primeira passagem ${base}, upscale ${curtoTroca(a.upscaler)}` : ", sem ampliar"}. ${a.passos} passos, ${a.sampler} com ${a.agendador}. ${loras}.${estilo ? ` Estilo: ${estilo}.` : ""}`;
}
function trocaPadrao(a) {
  const p = S.dados.troca.padrao, igual = (x, y) => JSON.stringify(x) === JSON.stringify(y);
  return a.modelo === p.modelo && igual(a.troca, p.troca) && igual(a.turbo, p.turbo) && (!a.upscale || igual(a.nitidez, p.nitidez)) && a.megapixels === p.megapixels && a.passos === p.passos && a.sampler === p.sampler && a.agendador === p.agendador
    && !a.pouca_vram && !a.dividir_blocos && !a.loras.length && (!a.upscale || (!a.upscale_mesma && a.upscaler === p.upscaler && a.upscale_megapixels === p.upscale_megapixels));
}
function salvarRascunhoTroca() {
  try { localStorage.setItem(RASCUNHO_TROCA, JSON.stringify({ video: S.tvideo, foto: S.tfoto, duracao: $("t-duracao").value, inicio: $("t-inicio").value, ajustes: lerTroca(), projeto: S.nomeTrocaEditado ? $("t-projeto").value : null })); } catch {}
}
function restaurarTroca() {
  let r = null;
  try { r = JSON.parse(localStorage.getItem(RASCUNHO_TROCA)); } catch {}
  if (!r) return;
  if (r.duracao) $("t-duracao").value = r.duracao;
  $("t-inicio").value = r.inicio || 0;
  if (r.ajustes) aplicarTroca(r.ajustes);
  if (r.projeto) { $("t-projeto").value = r.projeto; S.nomeTrocaEditado = true; }
  if (r.video) { preencherArquivo("tvideo", r.video); avisoAudioTroca(r.video); carregarTrecho(r.video); if (!S.nomeTrocaEditado) $("t-projeto").value = nomeLivre(`troca_${r.video.arquivo}`); }
  if (r.foto) preencherArquivo("tfoto", r.foto);
}
function avisoAudioTroca(v) {
  $("t-audio").disabled = !v.audio;
  if (!v.audio) $("t-audio").checked = false;
  $("t-audio-aviso").textContent = "Este vídeo não tem áudio, então o resultado sai sem som.";
  $("t-audio-aviso").hidden = v.audio;
}
function aoEscolherVideoTroca(v) {
  ajustarProporcao(v, "t-proporcao");
  $("t-inicio").value = 0;
  S.marcaTroca = null;
  carregarTrecho(v);
  avisoAudioTroca(v);
  const cabe = [3, 2.5, 2, 1.5, 1].find(d => quadrosTroca(d) <= quadrosDoVideo(v));
  if (cabe) $("t-duracao").value = cabe;
  if (!S.nomeTrocaEditado) $("t-projeto").value = nomeLivre(`troca_${v.arquivo}`);
}
function atualizarTroca() {
  if (!S.marcaOpcoesTroca) return;
  const a = lerTroca(), wg = ehWangp(a), v = S.tvideo, d = Number($("t-duracao").value), falta = [], tar = S.dados.tarefa, max = wg ? S.dados.troca.duracao_max_wangp : duracaoMaxTroca(a.megapixels, a.upscale);
  $("t-duracao").max = max;
  const travada = sincronizarTrava("troca");
  const inicio = Math.max(0, Number($("t-inicio").value) || 0), fpsV = S.dados.constantes.fps, padrao = trocaPadrao(a);
  // No Viggle sai exatamente o pedido, mas ele precisa de pelo menos 90 quadros de vídeo a partir do início
  const quadros = wg ? Math.round(d * fpsV) : quadrosTroca(d, a.megapixels), precisa = wg ? Math.max(S.dados.troca.quadros_min_wangp, quadros) : quadros;
  const cabe = !v || precisa <= quadrosDoVideo(v) - Math.round(inicio * fpsV), nj = a.upscale || wg ? 1 : janelasTroca(d, a.megapixels);
  $("t-motor-ajuda").textContent = wg ? (ehWan(a) ? `Pinta o primeiro quadro do trecho com a pessoa da foto e o Wan Animate 2 anima essa imagem com o movimento do vídeo: rosto, corpo e mãos, com o som original. Foi o resultado mais natural nos testes (pele e boca), mas exagera a expressão em alguns trechos; cerca de 2,5 min por segundo de vídeo, a 480p. Aceita o fundo novo e as fotos de expressão do personagem. Ainda sem LoRAs de estilo, marcar pessoa e segunda passagem.` : `Primeiro pinta ${pintadosWangp(d)} quadros do trecho com a pessoa da foto (FLUX.2 Klein, cerca de 30 s cada; com a roupa da foto, Qwen Image 2.1), depois o Viggle Remake espalha a troca pelo vídeo, em janelas de 5 s emendadas, e mantém o som. É o que mais segue o original: gestos, expressão e boca. No fim deixa a pele fosca, com granulação de câmera. Aceita o fundo novo e as fotos de expressão do personagem. Se a pessoa fala, ligue "A pessoa fala no trecho". Ainda sem LoRAs de estilo, marcar pessoa e segunda passagem.`)
    : "A Head Swap (roupa do vídeo) ou a Character Swap (roupa da foto) no ComfyUI, com todas as opções da tela.";
  $("campo-t-loras").hidden = wg;
  avisoGatilhos("t-loras-gatilho", a.loras, "", true);
  $("campo-t-borrar").hidden = wg || a.roupa !== "video";
  $("campo-t-fala").hidden = !wg;
  $("t-ampliar").querySelector('option[value="h3"]').disabled = wg;
  $("t-upscale-opcoes").hidden = !a.upscale;
  $("t-ampliar-ajuda").textContent = AJUDA_AMPLIAR[$("t-ampliar").value] || "";
  $("t-roupa-ajuda").textContent = a.roupa === "foto" ? "A personagem veste o que está na foto do começo ao fim (o modo original da LoRA)."
    : "Da foto vem só a cabeça: rosto, cabelo e barba. A roupa, os acessórios e cada peça que se tira ou põe seguem o vídeo. Use uma foto sem chapéu, boné ou óculos: o que está na cabeça da foto aparece o vídeo todo.";
  const final = a.upscale_mesma ? resolucao(a) : resolucao({ ...a, megapixels: a.upscale_megapixels });
  if (a.esrgan) $("t-ampliar-ajuda").textContent += ` Sai em ${tamanhoHD(a.proporcao)}.`;
  $("t-tamanho-final").textContent = `Tamanho: ${final}`;
  $("t-tamanho").textContent = `Tamanho: ${resolucao(a)}`;
  $("t-ajustes-situacao").textContent = padrao ? "padrão testado" : "alterado";
  $("t-resumo").textContent = resumoTroca(a);
  const avisosTroca = wg ? (a.megapixels === 0.5 && d <= 9 ? [] : ["O Viggle foi testado a 0,5 MP, com até 9 s. O tempo e o uso de memória podem ser maiores."])
    : padrao ? [] : ["Estes ajustes ainda não foram testados nesta placa. O tempo e o uso de memória podem ser maiores."];
  if (a.upscale) avisosTroca.push("A segunda passagem derrubou a placa 3 vezes seguidas em 11/11 (a 0,8 e a 0,5 MP). Ampliar com ESRGAN nunca caiu.");
  $("t-aviso-config").textContent = avisosTroca.join(" ");
  $("t-aviso-config").hidden = !avisosTroca.length;
  const duracaoReal = num(quadros / S.dados.constantes.fps, 2);
  // Medido no padrao: 5 min, e o upscale soma outros 5. 1 s levou quase o mesmo que 3 s, entao o tempo nao acompanha a duracao.
  // Fora do padrao, a conta grosseira escala com passos e tamanho (a parte que pesa na placa).
  const pt = S.dados.troca.padrao;
  // Em janelas, cada uma leva quase o mesmo que uma troca curta (16/11: 293 e 281 s para 2 janelas de 3 s)
  let segundos = 300 * nj * (padrao ? 1 : (a.passos / pt.passos) * (a.megapixels / pt.megapixels));
  if (a.upscale) segundos += 300 * (padrao ? 1 : (a.upscale_mesma ? a.megapixels : a.upscale_megapixels) / pt.upscale_megapixels);
  if (wg) segundos = segundosWangp(d, a.megapixels);
  // Rosto borrado: o SAM segue rosto e boca antes da troca; 84 e 94 s para 5 s de video em 17/11/2026
  if (a.borrar_rosto) segundos += SEGUNDOS_BORRAO_BASE + quadros / S.dados.constantes.fps * SEGUNDOS_BORRAO_POR_SEGUNDO;
  // ESRGAN: de 8 a 12 s por segundo de vídeo (116 s para 14 s em 11/11/2026), mais uns 10 s para ler o modelo
  if (a.esrgan) segundos += 10 + quadros / S.dados.constantes.fps * SEGUNDOS_ESRGAN_POR_SEGUNDO;
  mostrarEstimativa("t-estimativa", travada ? null : segundos, wg ? avisosTroca.length > 0 : !padrao);
  // A fita em tres partes: antes do trecho, o trecho trocado e o resto (editor do trecho, trecho.js)
  const fps = S.dados.constantes.fps, total = v ? quadrosDoVideo(v) : 0, antes = Math.min(total, Math.round(inicio * fps)), usados = Math.min(quadros, total - antes), depois = total - antes - usados;
  $("t-fita").innerHTML = v ? `${antes ? `<span class="resto" style="flex:${antes} 1 0"></span>` : ""}<span class="nova" style="flex:${usados} 1 0"></span>${depois > 0 ? `<span class="resto" style="flex:${depois} 1 0"></span>` : ""}` : "";
  $("t-fita").hidden = !v;
  $("t-fita-eixo").innerHTML = v ? eixoReal([...(antes ? [[0, antes]] : []), [antes / fps, usados], ...(depois > 0 ? [[(antes + usados) / fps, depois]] : [])], v.duracao) : "";
  const cortesNoTrecho = (S.cortesTroca || []).filter(c => c.segundos > inicio + .05 && c.segundos < inicio + quadros / fps - .05);
  $("t-conta").textContent = v && S.tfoto ? `Serão gerados ${duracaoReal} s (${quadros} quadros)${inicio ? ` a partir de ${num(inicio, 1)} s` : ""}${nj > 1 ? `, em ${nj} janelas emendadas` : ""}${cortesNoTrecho.length ? `; recomeça limpa no${cortesNoTrecho.length > 1 ? "s cortes" : " corte"} de câmera` : ""}${S.marcaTroca ? "; só na pessoa marcada" : ""}${S.tfundo ? "; com o fundo novo" : ""}${wg ? `, pelo Viggle (pinta ${pintadosWangp(d)} quadros${precisa > quadros ? ` e gera ${num(quadrosGeradosWangp(d) / fpsV, 2)} s, cortados no pedido` : ""})` : ""}.` : "Escolha a foto e o vídeo.";
  desenharTrecho();
  desenharPersonagemTroca();
  $("tirar-tfundo").hidden = !S.tfundo;

  if (S.enviando) falta.push("Esperando o envio terminar");
  else {
    if (!S.tfoto) falta.push("Escolha a foto");
    if (!v) falta.push("Escolha o vídeo");
  }
  if (!(d >= 1 && d <= max)) falta.push(`Use uma duração de 1 a ${num(max, max % 1 ? 1 : 0)} s${max < S.dados.troca.duracao_max ? ` a ${num(a.megapixels)} MP com o upscale (a segunda passagem não vai em janelas; use o ESRGAN para mais tempo)` : ""}`);
  else if (!cabe && wg) falta.push(`O Viggle Remake precisa de pelo menos ${num(precisa / fpsV, 2)} s de vídeo${inicio ? ` a partir de ${num(inicio, 1)} s` : ""}. Use um vídeo mais longo${inicio ? " ou recue o início" : ""}`);
  else if (!cabe) falta.push(inicio ? `A partir de ${num(inicio, 1)} s o vídeo é curto para ${num(d)} s. Recue o início ou reduza a duração` : `O vídeo é curto para ${num(d)} s (o fluxo usa ${duracaoReal} s). Reduza a duração`);
  if (v && !/^[A-Za-z0-9_-]{1,60}$/.test($("t-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(p => p.nome === $("t-projeto").value)) falta.push("Já existe um projeto com este nome");
  if (a.upscale && !a.upscale_mesma && a.upscale_megapixels <= a.megapixels) falta.push("A resolução final precisa ser maior que a da primeira passagem");
  if (wg) {
    if (a.upscale) falta.push("A segunda passagem do H3 não vai com o Viggle Remake: use o ESRGAN");
    if (a.loras.length) falta.push("Tire as LoRAs de estilo: ainda não vão com o Viggle Remake");
    if (S.marcaTroca) falta.push("Desmarque a pessoa: marcar quem trocar ainda não vai com o Viggle Remake");
  }
  if (!(a.passos >= 2 && a.passos <= 12)) falta.push("Use de 2 a 12 passos");
  if ([a.troca, a.turbo, a.nitidez].some(l => l && !(l[1] >= 0 && l[1] <= 1.5))) falta.push("Use força de LoRA entre 0 e 1,5");
  if (a.loras.length === 2 && a.loras[0][0] === a.loras[1][0]) falta.push("Escolha LoRAs de estilo diferentes");
  if (a.loras.some(([, f]) => !(f > 0 && f <= 1.5))) falta.push("Use força de LoRA de estilo entre 0,05 e 1,5");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  porHtml($("t-falta"), travada ? notaTravada("troca") : htmlFalta(falta));
  $("t-gerar").disabled = falta.length > 0;
  rotuloFila($("t-gerar"));
  salvarRascunhoTroca();
}
async function iniciarTroca() {
  $("t-erro").hidden = true;
  $("t-gerar").disabled = true;
  const nome = $("t-projeto").value;
  try {
    await postar("/api/iniciar-troca", { projeto: nome, video: S.tvideo.arquivo, foto: S.tfoto.arquivo, duracao: Number($("t-duracao").value), inicio: Number($("t-inicio").value) || 0, ...(S.marcaTroca ? { marca: S.marcaTroca } : {}), ...(S.tfundo ? { fundo: S.tfundo.arquivo } : {}), ...personagemDaTroca(), ajustes: lerTroca() });
    S.abertos.add(nome);
    S.dispensada = null;
    marcarEnviado("troca", nome);
  } catch (e) {
    $("t-erro").textContent = e.message;
    $("t-erro").hidden = false;
  }
  await consultar(true);
}
function limparTroca() {
  soltarTrava("troca");
  S.tvideo = S.tfoto = S.tfundo = S.marcaTroca = S.tpersonagem = null;
  S.nomeTrocaEditado = false;
  $("t-duracao").value = 3;
  $("t-inicio").value = 0;
  $("t-projeto").value = "";
  $("t-audio").disabled = false;
  $("t-audio-aviso").hidden = true;
  limparZona("tvideo");
  limparZona("tfoto");
  limparZona("tfundo");
  aplicarTroca({});
  try { localStorage.removeItem(RASCUNHO_TROCA); } catch {}
}
