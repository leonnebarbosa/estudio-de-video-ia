/* Texto para imagem: Z-Image Turbo, Chroma Flash e os modelos do arquivo local, com até 2 LoRAs do modelo escolhido; Editar com FLUX.2 Klein ou Qwen Image 2.1 (várias referências) */
const RASCUNHO_TEXTO = "texto_imagem_rascunho";
// Medido em 09/11/2026 na 3080: ~40 s por imagem em 0,9 MP e 12 passos, já com o modelo na placa; a primeira carrega o modelo
const SEGUNDOS_IMAGEM_TEXTO = 35, SEGUNDOS_CARREGAR_TEXTO = 15;
// Modelos que entendem bem um texto em português: o Z-Image (codificador Qwen3) fez certo "cachorro vira-lata caramelo na calçada de
// pedra portuguesa ao pôr do sol" em 13/11/2026. Os outros não foram testados em português e seguem pedindo inglês
const PORTUGUES_TEXTO = new Set(["z_image_turbo"]);
// Segundos por imagem de 0,9 a 1 MP com o modelo já lido, medidos em 09/11/2026. Cada LoRA soma uns 10 s
// O Qwen 2.1 levou ~55 s com 3 imagens (21/11/2026), já contando as referências
const SEGUNDOS_MODELO_TEXTO = { chroma_flash: 35, z_image_turbo: 10, klein_edit: 25, klein_t2i: 20, qwen21_edit: 55 }, SEGUNDOS_POR_LORA = 10;
// As imagens depois da de partida, na ordem do pedido: image 2, image 3, image 4
const TIPOS_EXTRAS_TEXTO = ["t2iref", "t2iref3", "t2iref4"];
// O que cada modelo pede de passos, pelo autor, e o que foi testado aqui
const AJUDA_PASSOS_TEXTO = {
  chroma_flash: "12 é o padrão do Chroma Flash (testado). Mais passos, mais tempo.",
  z_image_turbo: "8 é o recomendado (fluxo oficial) e o testado aqui: uns 10 s por imagem.",
  klein_edit: "4 passos, como no fluxo oficial do Klein destilado (testado em 11/11: uns 20 a 30 s em 2 MP).",
  klein_t2i: "4 passos, como no fluxo oficial do Klein destilado.",
  qwen21_edit: "8 passos fixos: a versão Turbo usa uma programação própria (fluxo oficial). Não dá para mudar.",
};
// Força recomendada pelo autor de cada LoRA; as outras começam em 1
// (as das LoRAs da comunidade testadas nesta máquina vêm do arquivo local, extras.py: pagina.forca_lora)
const FORCA_LORA = {};
const NOMES_QUALIDADE_TEXTO = { 0.5: "Rascunho (mais rápida)", 0.9: "Normal (padrão)", 1.3: "Alta (mais lenta)" };

function preencherTexto(d) {
  // Um servidor de antes deste modo não manda o bloco "texto": a tela fica parada até reiniciar o estúdio
  if (!d.texto) return;
  const marca = JSON.stringify([d.texto, d.proporcoes]);
  if (marca === S.marcaOpcoesTexto) return;
  // Uma LoRA nova na pasta muda a lista: o que já estava preenchido fica
  const atual = S.marcaOpcoesTexto ? lerTexto() : null;
  S.marcaOpcoesTexto = marca;
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  // Um servidor de antes do seletor não manda a lista: fica só o Chroma Flash
  desenharModelosDoModo(S.modoImagem || modoSalvoImagem());
  $("t2i-megapixels").innerHTML = d.texto.qualidades.map(q => opt(q, NOMES_QUALIDADE_TEXTO[q] || `${num(q, 1)} MP`)).join("");
  $("t2i-proporcao").innerHTML = d.proporcoes.map(x => opt(x, nomeProporcao(x))).join("");
  $("t2i-quantidade").innerHTML = Array.from({ length: d.texto.max_imagens }, (_, i) => opt(i + 1, i ? `${i + 1} imagens` : "1 imagem")).join("");
  // Um servidor de antes dos estilos não manda a lista: o campo fica escondido
  $("t2i-estilo").innerHTML = opt("", "Nenhum (só o que eu escrever)") + (d.texto.estilos?.lista || []).map(e => opt(e.id, e.nome)).join("");
  // Cada estilo é uma miniatura de exemplo (a personagem Marina, em pagina/estilos); tocar de novo no escolhido tira o estilo
  $("t2i-estilos").innerHTML = (d.texto.estilos?.lista || []).map(e =>
    `<button type="button" class="estilo-botao" data-estilo="${esc(e.id)}" aria-pressed="false" title="${esc(e.nome)}">`
    + `<img src="/pagina/estilos/${esc(e.id)}.webp" alt="" loading="lazy"><span>${esc(NOME_CURTO_ESTILO[e.id] || e.nome)}</span></button>`).join("");
  aplicarTexto(atual || {});
}
const modeloTexto = id => (S.dados?.texto?.modelos || []).find(m => m.id === (id ?? $("t2i-modelo").value)) || { id: "chroma_flash", passos: 12, loras: [] };
/* As listas de LoRA mostram só as que servem para o modelo; uma escolhida que não serve mais sai */
function desenharLorasTexto(escolhidas = lerLorasTexto()) {
  // No Editar com a chave Qualidade alta (Klein 9B) a lista mostra as LoRAs do 9B
  const m = modeloTexto(), alta = !!m.loras_alta && $("t2i-alta").checked && !$("t2i-alta").disabled, opcoes = (alta ? m.loras_alta : m.loras) || [];
  [1, 2].forEach((k, i) => {
    const sel = $(`t2i-lora-${k}`), forca = $(`t2i-forca-${k}`), [nome, f] = escolhidas[i] || [];
    sel.innerHTML = `<option value="">Nenhuma</option>` + opcoes.map(n => `<option value="${esc(n)}">${esc(semExt(n))}</option>`).join("");
    sel.value = opcoes.includes(nome) ? nome : "";
    forca.value = sel.value ? (f ?? FORCA_LORA[nome] ?? 1) : "";
    forca.disabled = !sel.value;
  });
}
function lerLorasTexto() {
  return [1, 2].map(k => [$(`t2i-lora-${k}`).value, Number($(`t2i-forca-${k}`).value) || 1]).filter(([n]) => n);
}
function lerTexto() {
  return { modelo: $("t2i-modelo").value, prompt: $("t2i-prompt").value, negativo: $("t2i-negativo").value, proporcao: $("t2i-proporcao").value, megapixels: Number($("t2i-megapixels").value),
           quantidade: Number($("t2i-quantidade").value), passos: Number($("t2i-passos").value), semente: $("t2i-semente").value === "" ? null : Number($("t2i-semente").value),
           loras: lerLorasTexto(), partida: S.t2ifoto?.arquivo || null,
           // As imagens extras só valem na aba Várias referências; nas outras ficam guardadas, sem ir no pedido
           referencia: S.modoImagem === "referencias" ? S.t2iref?.arquivo || null : null,
           referencias: S.modoImagem === "referencias" ? ["t2iref3", "t2iref4"].map(t => S[t]?.arquivo).filter(Boolean) : [], forca_partida: Number($("t2i-forca-partida").value),
           ...lerEstilo() };
}
/* Abas da área Imagem (Gerar, Editar, Várias referências): cada uma mostra só os modelos dela no seletor, que some quando há um só.
   O último modelo de cada aba é lembrado na troca. */
const MODO_IMAGEM = "estudio_modo_imagem", MODOS_IMAGEM = ["gerar", "editar", "referencias"];
const modelosTexto = () => S.dados?.texto?.modelos || [{ id: "chroma_flash", nome: "Chroma1-HD-Flash", faltam: [], modo: "gerar" }];
const modoDoModelo = m => m?.modo || (m?.edicao ? "editar" : "gerar");
function modoSalvoImagem() {
  let m = null;
  try { m = localStorage.getItem(MODO_IMAGEM); } catch {}
  return MODOS_IMAGEM.includes(m) ? m : "gerar";
}
function desenharModelosDoModo(modo) {
  const todos = modelosTexto(), lista = todos.filter(m => modoDoModelo(m) === modo);
  S.modoImagem = lista.length ? modo : "gerar";
  opcoesModelo("t2i-modelo", lista.length ? lista : todos.filter(m => modoDoModelo(m) === "gerar"));
  document.querySelectorAll("[data-modo-imagem]").forEach(b => {
    b.setAttribute("aria-selected", String(b.dataset.modoImagem === S.modoImagem));
    // Uma aba sem nenhum modelo (pacote não baixado) fica apagada
    b.disabled = !todos.some(m => modoDoModelo(m) === b.dataset.modoImagem);
  });
  $("t2i-modelo").closest(".campo").hidden = lista.length <= 1;
}
function escolherModoImagem(modo) {
  if (modo === S.modoImagem) return;
  S.ultimoModelo = { ...(S.ultimoModelo || {}), [S.modoImagem]: $("t2i-modelo").value };
  desenharModelosDoModo(modo);
  const sel = $("t2i-modelo"), ultimo = S.ultimoModelo[S.modoImagem];
  if (ultimo && [...sel.options].some(o => o.value === ultimo && !o.disabled)) sel.value = ultimo;
  if (!sel.value || sel.selectedOptions[0]?.disabled) sel.selectedIndex = [...sel.options].findIndex(o => !o.disabled);
  desenharLorasTexto();
  if (!S.passosTextoEditados) $("t2i-passos").value = modeloTexto().passos;
  try { localStorage.setItem(MODO_IMAGEM, S.modoImagem); } catch {}
  atualizarTexto();
}
/* Ocultar estilos: a grade some e o botão diz o estilo escolhido; lembrado entre as visitas */
const ESTILOS_OCULTOS = "estudio_estilos_ocultos";
function estilosOcultos() { try { return localStorage.getItem(ESTILOS_OCULTOS) === "1"; } catch { return false; } }
function alternarEstilos() {
  try { localStorage.setItem(ESTILOS_OCULTOS, estilosOcultos() ? "" : "1"); } catch {}
  atualizarTexto();
}
// Na miniatura cabe pouco: o nome inteiro fica no title (ao parar o mouse)
const NOME_CURTO_ESTILO = { oleo: "Óleo", realista: "Realista" };
/* Estilo pronto: só vale no modelo do estilo (Editar imagem com o Klein); fora dele vai vazio */
const estilosTexto = () => S.dados?.texto?.estilos || null;
function lerEstilo() {
  const est = estilosTexto(), noEditar = !!est && $("t2i-modelo").value === est.modelo, estilo = noEditar ? $("t2i-estilo").value || null : null;
  // A chave vale nos modelos que têm a lista do 9B (loras_alta: o Klein do Editar e do Gerar), com ou sem estilo (24/11/2026)
  return { estilo, qualidade_alta: !!est && !!modeloTexto().loras_alta && $("t2i-alta").checked && !$("t2i-alta").disabled };
}
/* Toque numa miniatura: escolhe o estilo; no que já estava escolhido, tira */
function escolherEstilo(id) {
  $("t2i-estilo").value = $("t2i-estilo").value === id ? "" : id;
  trocouEstilo();
}
/* Ao escolher o Realista a chave liga sozinha (o realista no 4B foi o mais fraco dos testes), se o 9B estiver instalado */
function trocouEstilo() {
  const est = estilosTexto();
  if ($("t2i-estilo").value === "realista" && est && !est.faltam_9b?.length) $("t2i-alta").checked = true;
  atualizarTexto();
}
/* Segundos por imagem do estilo (teste de 23/11/2026): 4B ~21 s, 9B ~48 s, realista sem o 9B ~35 s no Qwen (+ ~60 s com a passada
   de realismo do arquivo local); a descrição das cores soma ~15 s uma vez */
function segundosEstilo(a) {
  if (a.qualidade_alta) return 48;
  return a.estilo === "realista" ? 95 : 21;
}
function aplicarTexto(a) {
  const p = { ...S.dados.texto.padrao, ...a };
  // Um pedido com modelo (rascunho, histórico, Usar de novo) abre na aba dele; sem modelo, fica a aba atual
  desenharModelosDoModo("modelo" in a ? modoDoModelo(modelosTexto().find(m => m.id === p.modelo)) : (S.modoImagem || modoSalvoImagem()));
  $("t2i-modelo").value = p.modelo || "z_image_turbo";
  if (!$("t2i-modelo").value || $("t2i-modelo").selectedOptions[0]?.disabled) $("t2i-modelo").selectedIndex = [...$("t2i-modelo").options].findIndex(o => !o.disabled);
  // O modelo pedido pode nao estar instalado (a tela escolhe outro): os passos seguem o modelo que ficou, nao o pedido.
  // Antes, num PC so com o Z-Image, ele gerava com os 12 passos do Chroma e a tela dizia "alterado" (teste de 12/11/2026)
  const trocou = $("t2i-modelo").value !== p.modelo, passos = trocou || !("passos" in a) ? modeloTexto().passos : p.passos;
  $("t2i-prompt").value = p.prompt; $("t2i-negativo").value = p.negativo; $("t2i-proporcao").value = p.proporcao; $("t2i-megapixels").value = p.megapixels;
  $("t2i-quantidade").value = p.quantidade; $("t2i-passos").value = passos; $("t2i-semente").value = p.semente ?? "";
  desenharLorasTexto(p.loras || []);
  $("t2i-forca-partida").value = p.forca_partida ?? 0.6;
  // Só mexe na imagem de partida quando ela vem nos ajustes (rascunho, histórico, Usar de novo)
  if ("partida" in a) { if (a.partida) preencherArquivo("t2ifoto", { arquivo: a.partida }); else tirarPartida(); }
  if ("referencia" in a) { if (a.referencia) preencherArquivo("t2iref", { arquivo: a.referencia }); else tirarReferencia(); }
  if ("referencias" in a) ["t2iref3", "t2iref4"].forEach((t, i) => { const arq = (a.referencias || [])[i]; if (arq) preencherArquivo(t, { arquivo: arq }); else soltarExtra(t); });
  $("t2i-estilo").value = p.estilo || "";
  if ($("t2i-estilo").value !== (p.estilo || "")) $("t2i-estilo").value = "";
  $("t2i-alta").checked = p.qualidade_alta === true;
}
function soltarExtra(tipo) {
  S[tipo] = null;
  $(tipo).value = "";
  limparZona(tipo);
}
/* Tirar uma imagem extra: as seguintes sobem uma posição, para a numeração do pedido (image 2, image 3...) continuar sem buraco */
function tirarReferencia(tipo = "t2iref") {
  const i = TIPOS_EXTRAS_TEXTO.indexOf(tipo), resto = TIPOS_EXTRAS_TEXTO.slice(i + 1).map(t => S[t]).filter(Boolean);
  TIPOS_EXTRAS_TEXTO.slice(i).forEach(soltarExtra);
  resto.forEach((info, k) => preencherArquivo(TIPOS_EXTRAS_TEXTO[i + k], info));
}
/* A frente do personagem (a da ficha, se aprovada) vira a imagem de partida: é a "image 1" do pedido */
async function usarPersonagemTexto() {
  const r = await escolherPersonagem({ modo: "corpo" });
  if (!r) return;
  preencherArquivo("t2ifoto", { arquivo: r.foto });
  atualizarTexto();
  recado(`${r.nome} virou a imagem de partida (image 1). Junte o fundo e a roupa nas outras imagens.`, true);
}
function tirarPartida() {
  S.t2ifoto = null;
  $("t2ifoto").value = "";
  limparZona("t2ifoto");
}
function aoEscolherPartida(f) {
  // O formato acompanha a imagem: assim nada é cortado
  if (f.largura) ajustarProporcao(f, "t2i-proporcao");
}
async function usarComoPartida(projeto, arquivo) {
  try {
    const info = await postar("/api/usar-imagem", { projeto, arquivo });
    irPara("texto");
    preencherArquivo("t2ifoto", info);
    aoEscolherPartida(info);
    atualizarTexto();
    recado("A imagem virou o ponto de partida. Ajuste o texto e quanto ela deve mudar, e gere.", true);
  } catch (e) {
    recado(e.message);
  }
}
/* A LLM de visão escreve o prompt a partir da imagem de partida; o texto anterior volta com Desfazer */
async function descreverPartida() {
  if (!S.t2ifoto || S.descrevendo) return;
  S.descrevendo = true;
  atualizarTexto();
  const antes = $("t2i-prompt").value;
  try {
    const r = await postar("/api/descrever-imagem", { arquivo: S.t2ifoto.arquivo });
    $("t2i-prompt").value = r.prompt;
    recado(`O estúdio descreveu a imagem em ${r.segundos} s. Mude só o trecho que quer diferente e gere.`, true,
           antes.trim() ? { rotulo: "Desfazer", fazer: () => { $("t2i-prompt").value = antes; atualizarTexto(); } } : null);
  } catch (e) {
    recado(e.message);
  }
  S.descrevendo = false;
  atualizarTexto();
}
const ajudaForcaPartida = f => f <= 0.35 ? "Muda pouco: mantém composição, pessoas e cores e melhora detalhe, luz e textura."
  : f <= 0.7 ? "Muda bastante: mantém a ideia e o enquadramento, mas redesenha seguindo o texto."
  : "Muda quase tudo: a imagem vira só uma sugestão de cores e posição.";
function salvarRascunhoTexto() {
  try { localStorage.setItem(RASCUNHO_TEXTO, JSON.stringify({ ajustes: lerTexto(), projeto: S.nomeTextoEditado ? $("t2i-projeto").value : null })); } catch {}
}
function restaurarTexto() {
  let r = null;
  try { r = JSON.parse(localStorage.getItem(RASCUNHO_TEXTO)); } catch {}
  if (!r) return;
  if (r.ajustes) aplicarTexto(r.ajustes);
  if (r.projeto) { $("t2i-projeto").value = r.projeto; S.nomeTextoEditado = true; }
}
/* O nome sai das primeiras palavras do prompt, até alguém editar */
function nomeDoPrompt(prompt) {
  const palavras = prompt.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]+/g, " ").split(" ")
    .filter(w => w.length > 2 && !["photo", "the", "and", "with", "shot", "lens", "50mm", "of"].includes(w)).slice(0, 4);
  return nomeLivre(`imagem_${palavras.join("_") || "texto"}`);
}
function atualizarTexto() {
  if (!S.marcaOpcoesTexto) return;
  const travada = sincronizarTrava("texto");
  const a = lerTexto(), p = S.dados.texto.padrao, falta = [], tar = S.dados.tarefa;
  const mt = modeloTexto(a.modelo);
  // Estilo pronto: o campo aparece no modelo do estilo; a chave Qualidade alta, só com um estilo escolhido
  const est = estilosTexto(), podeEstilo = !!est?.lista?.length && a.modelo === est.modelo, estilo = a.estilo;
  const sem9b = (est?.faltam_9b || []).length > 0;
  $("t2i-estilo-campo").hidden = !podeEstilo;
  const ocultos = estilosOcultos(), nomeEstilo = (est?.lista || []).find(e => e.id === estilo)?.nome;
  $("t2i-estilos").hidden = ocultos;
  // A seta ao lado do "?" dobra a grade; dobrada, o rótulo mostra o estilo escolhido
  const dobrar = $("t2i-estilos-alternar"), acao = ocultos ? "Mostrar os estilos" : "Ocultar os estilos";
  dobrar.setAttribute("aria-expanded", String(!ocultos));
  dobrar.title = acao;
  dobrar.querySelector(".so-leitor").textContent = acao;
  $("t2i-estilo-escolhido").hidden = !(ocultos && nomeEstilo);
  $("t2i-estilo-escolhido").textContent = nomeEstilo ? `· ${nomeEstilo}` : "";
  document.querySelectorAll("#t2i-estilos [data-estilo]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.estilo === estilo)));
  $("t2i-alta-campo").hidden = !(podeEstilo || mt.loras_alta);
  $("t2i-alta").disabled = sem9b;
  if (sem9b) $("t2i-alta").checked = false;
  $("t2i-estilo-ajuda").textContent = !estilo ? "Escolha um estilo e a foto é redesenhada nele, com a mesma pessoa, pose e cena. Não precisa escrever nada. Toque de novo para tirar."
    : estilo === "realista" ? "Transforma um desenho, anime ou cartoon em foto realista, mantendo a cena e as cores."
    : "A mesma pessoa, pose e cena, redesenhada neste estilo. O estúdio descreve as cores da foto antes, para não clarear o cabelo e a pele.";
  $("t2i-alta-ajuda").textContent = sem9b ? `Precisa do Klein 9B, que não está instalado (faltam ${est.faltam_9b.join(", ")}).`
    : estilo === "realista" && !a.qualidade_alta ? "Desligada, o realista usa o Qwen 2.1: natural, mas mais lento e pode mudar a cor dos olhos."
    : estilo ? "Usa o Klein 9B: mais fiel ao rosto e às cores, uns 50 s por imagem em vez de uns 20 s."
    : mt.edicao ? "Edita com o Klein 9B em vez do 4B: mais fiel, uns 50 s por imagem. As LoRAs da lista passam a ser as do 9B."
    : "Gera com o Klein 9B em vez do 4B: mais detalhe e mais fiel ao texto, uns 50 s por imagem. As LoRAs da lista passam a ser as do 9B.";
  const padrao =a.megapixels === p.megapixels && a.passos === mt.passos && a.negativo.trim() === p.negativo;
  const modelos = S.dados.texto.modelos || [];
  $("t2i-passos-ajuda").textContent = AJUDA_PASSOS_TEXTO[a.modelo] || `${mt.passos} é o padrão deste modelo. Mais passos, mais tempo.`;
  const listaLoras = (a.qualidade_alta ? mt.loras_alta : mt.loras) || [];
  $("t2i-loras-ajuda").textContent = !listaLoras.length ? "Nenhum estilo extra para este modelo. Eles ficam na pasta models/loras do ComfyUI."
    : `${listaLoras.length} ${listaLoras.length === 1 ? "estilo extra serve" : "estilos extras servem"} para este modelo. O número ao lado é a força: 1 é o normal.`;
  const avisosGatilho = avisoGatilhos("t2i-loras-gatilho", a.loras, a.prompt);
  $("t2i-aviso-config").textContent = avisosGatilho.join(" ");
  $("t2i-aviso-config").hidden = !avisosGatilho.length;
  $("t2i-modelo-ajuda").textContent = ajudaModelo(modelos.find(m => m.id === a.modelo), modelos.length);
  // Editar: o tamanho segue a imagem de partida (o Qwen 2.1 leva a ~1 MP, o Klein a 2 MP), não o formato escolhido
  const mpEdicao = a.qualidade_alta ? "1,5" : estilo === "realista" ? "1" : a.modelo === "klein_edit" ? "2" : "1";
  $("t2i-tamanho").textContent = mt.edicao ? `Tamanho: o da imagem de partida, levado a ${mpEdicao} MP` : `Tamanho: ${resolucao(a)}`;
  // Passos fixos (Qwen 2.1 Turbo): o campo mostra o número e não deixa mudar
  $("t2i-passos").disabled = !!mt.passos_fixos;
  if (mt.passos_fixos) $("t2i-passos").value = a.passos = mt.passos;
  const extras = (a.referencia ? 1 : 0) + a.referencias.length, maxImagens = mt.edicao ? (mt.max_imagens || 2) : 0;
  $("t2i-ajustes-situacao").textContent = padrao ? "padrão testado" : "alterado";
  if (!S.nomeTextoEditado && !travada) $("t2i-projeto").value = a.prompt.trim() ? nomeDoPrompt(a.prompt) : estilo ? nomeLivre(`estilo_${estilo}`) : "";
  // O palco vazio já mostra o formato escolhido
  const m = a.proporcao.match(/^(\d+):(\d+)/);
  if (m) $("t2i-palco-bloco").style.setProperty("--proporcao", `${m[1]} / ${m[2]}`);
  const porImagem = (a.qualidade_alta ? 48 : SEGUNDOS_MODELO_TEXTO[a.modelo] || SEGUNDOS_IMAGEM_TEXTO) * (a.passos / mt.passos) * Math.pow(a.megapixels / p.megapixels, 1.1) + a.loras.length * SEGUNDOS_POR_LORA
    + (mt.edicao && a.modelo !== "qwen21_edit" ? extras * 18 : 0);  // a segunda imagem no Editar somou 18 s (09/11)
  // Com imagem de partida o modelo só roda a parte final dos passos (a força)
  const segundos = estilo ? SEGUNDOS_CARREGAR_TEXTO + (estilo === "lapis" ? 0 : 15) + a.quantidade * segundosEstilo(a)
    : SEGUNDOS_CARREGAR_TEXTO + a.quantidade * porImagem * (a.partida && !mt.edicao ? Math.max(a.forca_partida, 0.2) : 1);
  // Editar: o texto é uma instrução, a imagem é obrigatória e "Quanto muda" não vale (muda só o que foi pedido)
  const editar = !!mt.edicao;
  $("t2i-titulo").textContent = estilo ? "Algo a acrescentar? (opcional)" : editar ? "O que mudar na imagem" : "O que aparece na imagem";
  $("t2i-prompt-ajuda").textContent = estilo ? "O estilo já vem pronto. Se quiser, escreva em inglês um detalhe a mais, como \"golden hour light\"."
    : editar && extras > 1 ? "Em inglês, citando cada imagem pelo número: \"The woman from image 1 in the café from image 2, wearing the dress from image 3. Keep her exact face and hair. She leans on the table, smiling.\" Diga também a pose: sem ela a pessoa tende a ficar parada, de frente."
    : editar && S.t2iref ? "Em inglês, citando as duas: \"Put the jacket from image 2 on the woman in image 1. Keep her face, expression and pose the same.\""
    : editar ? "Em inglês, uma instrução: \"Change her sweater to a red turtleneck. Keep her face, expression and pose the same.\" Citar a expressão (\"same subtle smile\") ajuda a manter o rosto. Para trocar um texto, diga \"replace all the text on the sign with ...\"."
    : PORTUGUES_TEXTO.has(a.modelo) ? "Pode escrever em português. Diga quem ou o que aparece, onde, a luz e o tipo de foto."
    : "Este modelo entende melhor em inglês. Diga quem ou o que aparece, onde, a luz e o tipo de foto.";
  // O exemplo cinza começa com "Ex.:" para não parecer texto já escrito, e vem em português no modelo que entende português
  $("t2i-prompt").placeholder = estilo ? "Ex.: golden hour light (pode deixar vazio)" : editar ? "Ex.: Change her sweater to a red turtleneck. Keep her face the same."
    : PORTUGUES_TEXTO.has(a.modelo) ? "Ex.: foto de um cachorro caramelo deitado numa calçada de pedra ao pôr do sol, luz suave"
    : "Ex.: photo of a woman in a yellow raincoat on a rainy street at night, neon reflections";
  if (editar && !S.t2ifoto) falta.push("Escolha a imagem a editar, em Imagem de partida");
  // "Quanto muda" só fora do Editar; o X de tirar fica na caixa da imagem
  $("t2i-partida-ajustes").hidden = !S.t2ifoto || editar;
  $("t2i-tirar-partida").hidden = !S.t2ifoto;
  // No Editar a saída segue o formato da imagem de partida: o Formato só ocuparia espaço
  $("t2i-proporcao").closest(".campo").hidden = editar;
  $("t2i-forca-partida").closest(".campo").hidden = editar;
  // Imagens extras: só no Editar imagem (nos outros modelos o servidor as ignora); cada uma aparece depois da anterior, até o máximo do modelo
  $("t2i-ref-campo").hidden = S.modoImagem !== "referencias";
  if (estilo && extras) falta.push("Com um estilo, tire as imagens extras: ele usa só a imagem de partida");
  $("t2i-ref3-campo").hidden = !(maxImagens >= 3 && (S.t2iref || S.t2iref3));
  $("t2i-ref4-campo").hidden = !(maxImagens >= 4 && (S.t2iref3 || S.t2iref4));
  TIPOS_EXTRAS_TEXTO.forEach(t => { $(`t2i-tirar-${t.replace("t2i", "")}`).hidden = !S[t]; });
  if (editar && 1 + extras > maxImagens) falta.push(`Este modelo junta até ${maxImagens} imagens: tire ${1 + extras - maxImagens} ou escolha o Qwen Image 2.1`);
  $("t2i-personagem").hidden = travada;
  // Descrever: só com imagem de partida e com o ComfyUI livre (a LLM roda nele)
  const ocupado = tar?.rodando || !S.dados.comfy.ligado || S.dados.comfy.ocupado;
  $("t2i-descrever").disabled = !S.t2ifoto || S.descrevendo || ocupado || travada;
  $("t2i-descrever").textContent = S.descrevendo ? "Descrevendo…" : "Descrever a imagem de partida";
  $("t2i-descrever-ajuda").textContent = S.descrevendo ? "Uns 15 a 40 s." : !S.t2ifoto ? "Escolha uma imagem de partida e o estúdio escreve a descrição dela por você."
    : ocupado ? "Espere o ComfyUI ficar livre." : "O estúdio descreve a imagem no campo de texto; depois é só ajustar.";
  $("t2i-forca-ajuda").textContent = `${num(a.forca_partida, 2)}. ${ajudaForcaPartida(a.forca_partida)}`;
  mostrarEstimativa("t2i-estimativa", travada ? null : segundos, !padrao);
  if (!a.prompt.trim() && !estilo) falta.push("Escreva o que deve aparecer na imagem");
  if (estilo === "realista" && !a.qualidade_alta && (est?.faltam_realista || []).length) falta.push("Ligue a Qualidade alta: o realista sem ela precisa do Qwen 2.1, que não está instalado");
  if (!(a.passos >= 4 && a.passos <= 24)) falta.push("Use de 4 a 24 passos");
  if (S.enviando) falta.push("Esperando o envio terminar");
  if (mt.faltam?.length) falta.push("Este modelo não está instalado");
  if (a.loras.length === 2 && a.loras[0][0] === a.loras[1][0]) falta.push("Escolha LoRAs diferentes");
  if (a.loras.some(([, f]) => !(f > 0 && f <= 2))) falta.push("Use força de LoRA entre 0,05 e 2");
  if ((a.prompt.trim() || estilo) && !/^[A-Za-z0-9_-]{1,60}$/.test($("t2i-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(x => x.nome === $("t2i-projeto").value)) falta.push("Já existe um projeto com este nome");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  porHtml($("t2i-falta"), travada ? notaTravada("texto") : htmlFalta(falta));
  $("t2i-gerar").disabled = $("t2i-gerar-centro").disabled = falta.length > 0;
  $("t2i-gerar").textContent = $("t2i-gerar-centro").textContent = a.quantidade > 1 ? `Gerar ${a.quantidade} imagens` : "Gerar imagem";
  rotuloFila($("t2i-gerar"), $("t2i-gerar-centro"));
  // Descrever a imagem só faz sentido com uma imagem de partida: sem ela o botão some (antes ficava apagado, sempre à vista)
  $("t2i-descrever-linha").hidden = !S.t2ifoto;
  salvarRascunhoTexto();
  desenharGaleria();
}
/* O resultado some do palco de dois jeitos: Limpar tudo só o tira da tela (com Desfazer); Descartar apaga do disco, com
   pergunta antes. O palco mostra o projeto de texto mais recente desde que ele seja mais novo que o limite guardado aqui:
   uma geração nova sempre aparece, e o que foi tirado não volta num F5 nem quando o mais recente é apagado. */
const CHAVE_GALERIA = "estudio_galeria_limite";
S.galeriaLimite = (() => { try { return Number(localStorage.getItem(CHAVE_GALERIA)) || 0; } catch { return 0; } })();
function limiteGaleria(v) {
  S.galeriaLimite = v;
  try { localStorage.setItem(CHAVE_GALERIA, String(v)); } catch {}
  S.marcaGaleria = null;
  if (S.dados) desenharGaleria();
}
function projetoDaGaleria() {
  // As trocas em foto também são projetos de texto, mas aparecem na aba Trocar personagem (trocafoto.js)
  const ultimo = S.dados?.projetos.find(x => x.tipo === "texto" && !x.troca_foto && x.imagens?.length);
  return ultimo && ultimo.quando > S.galeriaLimite ? ultimo : null;
}
/* Limpar tudo: tira o resultado da tela sem apagar nada; devolve como trazê-lo de volta (o Desfazer do aviso) */
function tirarGaleria() {
  const p = projetoDaGaleria(), antes = S.galeriaLimite;
  if (!p) return null;
  limiteGaleria(p.quando);
  return () => limiteGaleria(antes);
}
/* Um projeto de texto apagado (Descartar no palco, no histórico ou Apagar em Projetos) não deixa o anterior subir ao palco */
function esquecerNaGaleria(p) {
  if (p?.tipo === "texto") limiteGaleria(Math.max(S.galeriaLimite, p.quando));
}
/* Uma imagem só, numa geração com várias: apaga do disco depois de perguntar (o servidor conta antes e só apaga com confirmar) */
async function descartarImagem(projeto, arquivo, botao) {
  try {
    const r = await postar("/api/apagar-imagem", { projeto, arquivo });
    const copia = r.arquivos > 1 ? " e a cópia que o ComfyUI guardou" : "";
    if (!await perguntar(`Descartar esta imagem de ${projeto}? Vão sumir a imagem${copia} (${num(r.mb, 1)} MB). Não vai para a Lixeira e não dá para desfazer. As outras imagens ficam.`, "Descartar de vez", "Cancelar")) return;
    botao.disabled = true;
    await postar("/api/apagar-imagem", { projeto, arquivo, confirmar: true });
    recado(`Imagem descartada de ${projeto}.`, true);
  } catch (e) {
    botao.disabled = false;
    recado(e.message);
  }
  await consultar(true);
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-descartar-imagem]");
  if (b) descartarImagem(b.dataset.projetoImagem, b.dataset.descartarImagem, b);
});
/* Os botões de cada imagem, no palco e em Projetos, sempre à vista embaixo dela: antes só apareciam com o mouse em cima e
   quem queria o vídeo não achava o caminho (análise de UX de 13/11/2026). Transformar em vídeo é o principal.
   Descartar uma só aparece quando há mais de uma e nada está gerando este projeto; com uma só, vale o Descartar do projeto */
function botoesImagem(p, i, src) {
  const sozinha = p.imagens.length < 2 || S.dados.tarefa?.rodando && S.dados.tarefa.projeto === p.nome;
  const baixar = `${p.nome}${p.imagens.length > 1 ? `_${i.n}` : ""}.png`;
  return `<figcaption class="acoes-imagem"><button type="button" class="principal" data-usar-imagem="${esc(i.arquivo)}" data-projeto-imagem="${esc(p.nome)}">Transformar em vídeo</button>`
    + `<a class="botao" href="${src}" download="${esc(baixar)}">Baixar</a>`
    + `<button type="button" class="botao" data-usar-partida="${esc(i.arquivo)}" data-projeto-imagem="${esc(p.nome)}" title="Gera outra imagem partindo desta, seguindo o texto">Usar como base</button>`
    + `<a class="botao" href="${src}" target="_blank" rel="noopener" title="Abre a imagem em tamanho real numa nova aba">Ampliar</a>`
    + (sozinha ? "" : `<button type="button" class="botao botao-perigo" data-descartar-imagem="${esc(i.arquivo)}" data-projeto-imagem="${esc(p.nome)}" title="Apaga só esta imagem do disco (pergunta antes)">Descartar</button>`)
    + linhaSemente(p, i)
    + `</figcaption>`;
}
/* A semente de cada imagem, embaixo dela: com 2 a 4 imagens dá para saber qual é qual (numeradas) e usar a de uma só.
   "Usar esta semente" põe o número no campo Semente; com o mesmo texto e modelo, a imagem se repete */
function linhaSemente(p, i) {
  if (i.semente == null) return "";
  const num = p.imagens.length > 1 ? `Imagem ${i.n}: semente` : "Semente";
  return `<span class="semente-linha">${num} <button type="button" class="simples semente-texto" data-copiar-semente="${esc(i.semente)}" title="Copiar o número">${esc(i.semente)}</button>`
    + `<button type="button" class="simples semente-texto" data-usar-semente="${esc(i.semente)}" title="Põe esta semente no campo Semente, nos Ajustes avançados">Usar esta semente</button></span>`;
}
/* Legenda do resultado: sem nome de pasta nem semente na frente (a semente fica embaixo de cada imagem) */
function legendaImagens(p) {
  const n = p.imagens.length, seg = p.imagens.map(i => i.segundos).filter(Boolean);
  const pronto = n === 1 ? "Imagem pronta" : `${n} imagens prontas`;
  const tempo = seg.length ? ` em ${tempo_curto(seg.reduce((a, b) => a + b, 0))}` : "";
  const descartadas = p.descartadas ? ` (${p.descartadas} ${p.descartadas === 1 ? "descartada" : "descartadas"})` : "";
  return `${esc(pronto + tempo + descartadas)}.`;
}
const tempo_curto = s => s < 60 ? `${Math.round(s)} s` : tempo(s);
/* O palco mostra as imagens do projeto de texto mais recente; cada uma pode virar o primeiro quadro de um vídeo */
function desenharGaleria() {
  const ultimo = projetoDaGaleria(), tar = S.dados.tarefa;
  const gerando = !!(ultimo && tar?.rodando && tar.projeto === ultimo.nome);
  const marca = JSON.stringify([ultimo?.nome, ultimo?.imagens.map(i => i.marca), gerando, tar?.rodando && tar.tipo === "texto" ? tar.projeto : null]);
  if (marca === S.marcaGaleria) return;
  S.marcaGaleria = marca;
  // Gerando um projeto novo: o palco diz que a imagem está a caminho, em vez de "As imagens aparecem aqui" ou do resultado anterior
  const novo = !!(tar?.rodando && tar.tipo === "texto" && !tarefaTrocaFoto(tar) && (!ultimo || tar.projeto !== ultimo.nome));
  $("t2i-vazio").classList.toggle("gerando", novo);
  $("t2i-vazio-texto").innerHTML = novo ? "<strong>Gerando a imagem…</strong><small>Ela aparece aqui em alguns segundos.</small>"
    : "<strong>As imagens aparecem aqui</strong><small>Descreva a cena abaixo e clique em Gerar.</small>";
  $("t2i-vazio").hidden = !!ultimo && !novo;
  $("t2i-galeria").hidden = !ultimo || novo;
  $("t2i-rodape").hidden = !ultimo || novo;
  if (!ultimo || novo) { $("t2i-conta").textContent = ""; return; }
  const nome = encodeURIComponent(ultimo.nome), n = ultimo.imagens.length;
  $("t2i-galeria").dataset.n = n;
  $("t2i-galeria").innerHTML = ultimo.imagens.map(i => {
    const src = `/imagem/${nome}/${i.arquivo}?m=${i.marca}`;
    return `<figure class="t2i-item">${midia(`<img src="${src}" alt="Imagem ${i.n} de ${esc(ultimo.nome)}">`, "Imagem oculta")}${botoesImagem(ultimo, i, src)}</figure>`;
  }).join("");
  $("t2i-conta").innerHTML = gerando ? esc(`Gerando ${n} de ${ultimo.total}…`) : legendaImagens(ultimo);
  // Descartar o resultado inteiro = apagar o projeto (a pergunta e o apagar são os mesmos de Projetos)
  $("t2i-rodape").dataset.projetoAcao = ultimo.nome;
  $("t2i-descartar").hidden = gerando;
  $("t2i-descartar").textContent = n > 1 ? `Descartar as ${n}` : "Descartar";
}
async function iniciarTexto() {
  $("t2i-erro").hidden = true;
  $("t2i-gerar").disabled = $("t2i-gerar-centro").disabled = true;
  const nome = $("t2i-projeto").value;
  try {
    await postar("/api/iniciar-texto", { projeto: nome, ajustes: lerTexto() });
    S.dispensada = null;
    marcarEnviado("texto", nome);
  } catch (e) {
    $("t2i-erro").textContent = e.message;
    $("t2i-erro").hidden = false;
  }
  await consultar(true);
}
function limparTexto() {
  soltarTrava("texto");
  tirarPartida();
  TIPOS_EXTRAS_TEXTO.forEach(soltarExtra);
  S.nomeTextoEditado = false;
  $("t2i-projeto").value = "";
  aplicarTexto({});
  try { localStorage.removeItem(RASCUNHO_TEXTO); } catch {}
}
/* Leva a imagem para o Imagem para vídeo, já como o primeiro quadro */
async function usarImagem(projeto, arquivo) {
  try {
    const info = await postar("/api/usar-imagem", { projeto, arquivo });
    irPara("imagem");
    preencherArquivo("ifoto", info);
    aoEscolherImagem(info);
    atualizarImagem();
    scrollTo(0, 0);
    recado("A imagem virou o primeiro quadro do vídeo. Escreva as tomadas e gere.", true);
  } catch (e) {
    recado(e.message);
  }
}
