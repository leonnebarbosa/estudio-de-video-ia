/* Texto para imagem: Z-Image Turbo, Chroma Flash e os modelos do arquivo local, com até 2 LoRAs do modelo escolhido; Editar com Qwen ou FLUX.2 Klein */
const RASCUNHO_TEXTO = "texto_imagem_rascunho";
// Medido em 09/11/2026 na 3080: ~40 s por imagem em 0,9 MP e 12 passos, já com o modelo na placa; a primeira carrega o modelo
const SEGUNDOS_IMAGEM_TEXTO = 35, SEGUNDOS_CARREGAR_TEXTO = 15;
// Modelos que entendem bem um texto em português: o Z-Image (codificador Qwen3) fez certo "cachorro vira-lata caramelo na calçada de
// pedra portuguesa ao pôr do sol" em 13/11/2026. Os outros não foram testados em português e seguem pedindo inglês
const PORTUGUES_TEXTO = new Set(["z_image_turbo"]);
// Segundos por imagem de 0,9 a 1 MP com o modelo já lido, medidos em 09/11/2026. Cada LoRA soma uns 10 s
const SEGUNDOS_MODELO_TEXTO = { chroma_flash: 35, z_image_turbo: 10, qwen_edit: 75, klein_edit: 25 }, SEGUNDOS_POR_LORA = 10;
// O que cada modelo pede de passos, pelo autor, e o que foi testado aqui
const AJUDA_PASSOS_TEXTO = {
  chroma_flash: "12 é o padrão do Chroma Flash (testado). Mais passos, mais tempo.",
  z_image_turbo: "8 é o recomendado (fluxo oficial) e o testado aqui: uns 10 s por imagem.",
  qwen_edit: "4 passos, com a LoRA de aceleração (testado). Mais passos só deixam mais lento.",
  klein_edit: "4 passos, como no fluxo oficial do Klein destilado (testado em 11/11: uns 20 a 30 s em 2 MP).",
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
  opcoesModelo("t2i-modelo", d.texto.modelos || [{ id: "chroma_flash", nome: "Chroma1-HD-Flash", faltam: [] }]);
  $("t2i-megapixels").innerHTML = d.texto.qualidades.map(q => opt(q, NOMES_QUALIDADE_TEXTO[q] || `${num(q, 1)} MP`)).join("");
  $("t2i-proporcao").innerHTML = d.proporcoes.map(x => opt(x, nomeProporcao(x))).join("");
  $("t2i-quantidade").innerHTML = Array.from({ length: d.texto.max_imagens }, (_, i) => opt(i + 1, i ? `${i + 1} imagens` : "1 imagem")).join("");
  aplicarTexto(atual || {});
}
const modeloTexto = id => (S.dados?.texto?.modelos || []).find(m => m.id === (id ?? $("t2i-modelo").value)) || { id: "chroma_flash", passos: 12, loras: [] };
/* As listas de LoRA mostram só as que servem para o modelo; uma escolhida que não serve mais sai */
function desenharLorasTexto(escolhidas = lerLorasTexto()) {
  const m = modeloTexto(), opcoes = m.loras || [];
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
           loras: lerLorasTexto(), partida: S.t2ifoto?.arquivo || null, referencia: S.t2iref?.arquivo || null, forca_partida: Number($("t2i-forca-partida").value) };
}
function aplicarTexto(a) {
  const p = { ...S.dados.texto.padrao, ...a };
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
}
function tirarPartida() {
  S.t2ifoto = null;
  $("t2ifoto").value = "";
  limparZona("t2ifoto");
}
function tirarReferencia() {
  S.t2iref = null;
  $("t2iref").value = "";
  limparZona("t2iref");
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
  const padrao = a.megapixels === p.megapixels && a.passos === mt.passos && a.negativo.trim() === p.negativo;
  const modelos = S.dados.texto.modelos || [];
  $("t2i-passos-ajuda").textContent = AJUDA_PASSOS_TEXTO[a.modelo] || `${mt.passos} é o padrão deste modelo. Mais passos, mais tempo.`;
  $("t2i-loras-ajuda").textContent = !mt.loras?.length ? "Nenhum estilo extra para este modelo. Eles ficam na pasta models/loras do ComfyUI."
    : `${mt.loras.length} ${mt.loras.length === 1 ? "estilo extra serve" : "estilos extras servem"} para este modelo. O número ao lado é a força: 1 é o normal.`;
  $("t2i-modelo-ajuda").textContent = ajudaModelo(modelos.find(m => m.id === a.modelo), modelos.length);
  // Editar: o tamanho segue a imagem de partida (o Qwen leva a ~1 MP, o Klein a 2 MP), não o formato escolhido
  $("t2i-tamanho").textContent = mt.edicao ? `Tamanho: o da imagem de partida, levado a ${a.modelo === "klein_edit" ? "2" : "1"} MP` : `Tamanho: ${resolucao(a)}`;
  $("t2i-ajustes-situacao").textContent = padrao ? "padrão testado" : "alterado";
  if (!S.nomeTextoEditado && !travada) $("t2i-projeto").value = a.prompt.trim() ? nomeDoPrompt(a.prompt) : "";
  // O palco vazio já mostra o formato escolhido
  const m = a.proporcao.match(/^(\d+):(\d+)/);
  if (m) $("t2i-palco-bloco").style.setProperty("--proporcao", `${m[1]} / ${m[2]}`);
  const porImagem = (SEGUNDOS_MODELO_TEXTO[a.modelo] || SEGUNDOS_IMAGEM_TEXTO) * (a.passos / mt.passos) * Math.pow(a.megapixels / p.megapixels, 1.1) + a.loras.length * SEGUNDOS_POR_LORA
    + (mt.edicao && a.referencia ? 18 : 0);  // a segunda imagem no Editar somou 18 s (09/11)
  // Com imagem de partida o modelo só roda a parte final dos passos (a força)
  const segundos = SEGUNDOS_CARREGAR_TEXTO + a.quantidade * porImagem * (a.partida && !mt.edicao ? Math.max(a.forca_partida, 0.2) : 1);
  // Editar: o texto é uma instrução, a imagem é obrigatória e "Quanto muda" não vale (muda só o que foi pedido)
  const editar = !!mt.edicao;
  $("t2i-titulo").textContent = editar ? "O que mudar na imagem" : "O que aparece na imagem";
  $("t2i-prompt-ajuda").textContent = editar && S.t2iref ? "Em inglês, citando as duas: \"Put the jacket from image 2 on the woman in image 1. Keep her face, expression and pose the same.\""
    : editar ? "Em inglês, uma instrução: \"Change her sweater to a red turtleneck. Keep her face, expression and pose the same.\" Citar a expressão (\"same subtle smile\") ajuda a manter o rosto. Para trocar um texto, diga \"replace all the text on the sign with ...\"."
    : PORTUGUES_TEXTO.has(a.modelo) ? "Pode escrever em português. Diga quem ou o que aparece, onde, a luz e o tipo de foto."
    : "Este modelo entende melhor em inglês. Diga quem ou o que aparece, onde, a luz e o tipo de foto.";
  // O exemplo cinza começa com "Ex.:" para não parecer texto já escrito, e vem em português no modelo que entende português
  $("t2i-prompt").placeholder = editar ? "Ex.: Change her sweater to a red turtleneck. Keep her face the same."
    : PORTUGUES_TEXTO.has(a.modelo) ? "Ex.: foto de um cachorro caramelo deitado numa calçada de pedra ao pôr do sol, luz suave"
    : "Ex.: photo of a woman in a yellow raincoat on a rainy street at night, neon reflections";
  if (editar && !S.t2ifoto) falta.push("Escolha a imagem a editar, em Imagem de partida");
  $("t2i-partida-ajustes").hidden = !S.t2ifoto;
  $("t2i-forca-partida").closest(".campo").hidden = editar;
  // Segunda imagem: só no Editar imagem (nos outros modelos o servidor a ignora)
  $("t2i-ref-campo").hidden = !editar;
  $("t2i-tirar-ref").hidden = !S.t2iref;
  // Descrever: só com imagem de partida e com o ComfyUI livre (a LLM roda nele)
  const ocupado = tar?.rodando || !S.dados.comfy.ligado || S.dados.comfy.ocupado;
  $("t2i-descrever").disabled = !S.t2ifoto || S.descrevendo || ocupado || travada;
  $("t2i-descrever").textContent = S.descrevendo ? "Descrevendo…" : "Descrever a imagem de partida";
  $("t2i-descrever-ajuda").textContent = S.descrevendo ? "Uns 15 a 40 s." : !S.t2ifoto ? "Escolha uma imagem de partida e o estúdio escreve a descrição dela por você."
    : ocupado ? "Espere o ComfyUI ficar livre." : "O estúdio descreve a imagem no campo de texto; depois é só ajustar.";
  $("t2i-forca-ajuda").textContent = `${num(a.forca_partida, 2)}. ${ajudaForcaPartida(a.forca_partida)}`;
  mostrarEstimativa("t2i-estimativa", travada ? null : segundos, !padrao);
  if (!a.prompt.trim()) falta.push("Escreva o que deve aparecer na imagem");
  if (!(a.passos >= 4 && a.passos <= 24)) falta.push("Use de 4 a 24 passos");
  if (S.enviando) falta.push("Esperando o envio terminar");
  if (mt.faltam?.length) falta.push("Este modelo não está instalado");
  if (a.loras.length === 2 && a.loras[0][0] === a.loras[1][0]) falta.push("Escolha LoRAs diferentes");
  if (a.loras.some(([, f]) => !(f > 0 && f <= 2))) falta.push("Use força de LoRA entre 0,05 e 2");
  if (a.prompt.trim() && !/^[A-Za-z0-9_-]{1,60}$/.test($("t2i-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(x => x.nome === $("t2i-projeto").value)) falta.push("Já existe um projeto com este nome");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  $("t2i-falta").innerHTML = travada ? notaTravada("texto") : falta.length ? `<ul>${falta.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
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
  tirarReferencia();
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
