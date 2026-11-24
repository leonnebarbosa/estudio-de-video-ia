/* Trocar personagem em foto: o rosto, a roupa ou os dois, com o FLUX.2 Klein (troca_foto.py). A aba Trocar personagem tem dois
   modos, Foto e Vídeo, cada um com a sua tela (tela-trocafoto e tela-troca). O resultado é um projeto de imagem: a galeria, a semente
   e o Transformar em vídeo são os mesmos do Texto para imagem. Teste de 14/11/2026: 27 a 37 s por troca; os dois fazem duas passadas. */
const RASCUNHO_TROCA_FOTO = "trocar_foto_rascunho", MODO_TROCA = "estudio_modo_troca";
S.modoTroca = (() => { try { return localStorage.getItem(MODO_TROCA) || "foto"; } catch { return "foto"; } })();
S.tfbase = S.tfrosto = S.tfroupa = null;

function trocarModoTroca(modo) {
  S.modoTroca = modo === "video" ? "video" : "foto";
  try { localStorage.setItem(MODO_TROCA, S.modoTroca); } catch {}
  for (const b of document.querySelectorAll("[data-modo-troca]")) b.setAttribute("aria-pressed", String(b.dataset.modoTroca === S.modoTroca));
  if (S.abaVisivel === "troca") irPara("troca");
}
function preencherTrocaFoto(d) {
  if (S.marcaOpcoesTrocaFoto || !d.texto) return;
  S.marcaOpcoesTrocaFoto = true;
  $("tf-quantidade").innerHTML = Array.from({ length: d.texto.max_imagens }, (_, i) => `<option value="${i + 1}">${i ? `${i + 1} versões` : "1 versão"}</option>`).join("");
}
function lerTrocaFoto() {
  return { partida: S.tfbase?.arquivo || null, rosto: S.tfrosto?.arquivo || null, roupa: S.tfroupa?.arquivo || null,
           quantidade: Number($("tf-quantidade").value) || 1, semente: $("tf-semente").value === "" ? null : Number($("tf-semente").value) };
}
/* Vem do rascunho (os campos de lerTrocaFoto) ou de Carregar configurações (os parâmetros do projeto, com troca_foto) */
function aplicarTrocaFoto(a) {
  const t = a.troca_foto || a, foto = (tipo, nome) => { if (nome) preencherArquivo(tipo, { arquivo: nome }); else tirarFotoTroca(tipo); };
  foto("tfbase", a.partida);
  foto("tfrosto", t.rosto);
  foto("tfroupa", t.roupa);
  if (a.quantidade) $("tf-quantidade").value = a.quantidade;
  $("tf-semente").value = a.semente ?? "";
}
function tirarFotoTroca(tipo) {
  S[tipo] = null;
  $(tipo).value = "";
  limparZona(tipo);
}
function aoEscolherBaseTroca(f) {
  if (!S.nomeTrocaFotoEditado) $("tf-projeto").value = nomeLivre(`troca_foto_${f.arquivo}`);
}
function salvarRascunhoTrocaFoto() {
  try { localStorage.setItem(RASCUNHO_TROCA_FOTO, JSON.stringify({ ajustes: lerTrocaFoto(), projeto: S.nomeTrocaFotoEditado ? $("tf-projeto").value : null })); } catch {}
}
function restaurarTrocaFoto() {
  for (const b of document.querySelectorAll("[data-modo-troca]")) b.setAttribute("aria-pressed", String(b.dataset.modoTroca === S.modoTroca));
  let r = null;
  try { r = JSON.parse(localStorage.getItem(RASCUNHO_TROCA_FOTO)); } catch {}
  if (!r) return;
  if (r.ajustes) aplicarTrocaFoto(r.ajustes);
  if (r.projeto) { $("tf-projeto").value = r.projeto; S.nomeTrocaFotoEditado = true; }
}
function limparTrocaFoto() {
  soltarTrava("trocafoto");
  for (const tipo of ["tfbase", "tfrosto", "tfroupa"]) tirarFotoTroca(tipo);
  S.nomeTrocaFotoEditado = false;
  $("tf-projeto").value = "";
  $("tf-semente").value = "";
  $("tf-quantidade").value = 1;
  try { localStorage.removeItem(RASCUNHO_TROCA_FOTO); } catch {}
}
/* O que cada escolha faz, embaixo das fotos: o cabelo vem com o rosto e os dois fazem duas passadas */
function ajudaTrocaFoto(a) {
  if (a.rosto && a.roupa) return "Troca o rosto e depois a roupa, em duas passadas. O cabelo vem com o rosto; a pose, a luz e o cenário ficam os da foto da pessoa.";
  if (a.rosto) return "Troca a cabeça: rosto e cabelo vêm da foto do rosto. A expressão, a roupa, a pose e o cenário ficam os da foto da pessoa.";
  if (a.roupa) return "Troca só a roupa: o rosto, o cabelo, a pose e o cenário ficam os da foto da pessoa. O estúdio usa a foto da roupa do pescoço para baixo.";
  return "Escolha o rosto novo, a roupa nova ou os dois. O estúdio recorta sozinho o que importa de cada foto.";
}
function atualizarTrocaFoto() {
  if (!S.marcaOpcoesTrocaFoto) return;
  const travada = sincronizarTrava("trocafoto");
  const a = lerTrocaFoto(), s = S.dados.troca_foto || { faltam: [], falta_lora_rosto: false, segundos_passada: 30 }, falta = [], tar = S.dados.tarefa;
  const passadas = (a.rosto ? 1 : 0) + (a.roupa ? 1 : 0);
  // O nome sai da foto da pessoa até alguém editar (também depois de um F5, que restaura as fotos sem passar pelo envio)
  if (!S.nomeTrocaFotoEditado && !travada) $("tf-projeto").value = S.tfbase ? nomeLivre(`troca_foto_${S.tfbase.arquivo}`) : "";
  $("tf-ajuda").textContent = ajudaTrocaFoto(a);
  $("tf-tirar-rosto").hidden = !S.tfrosto;
  $("tf-tirar-roupa").hidden = !S.tfroupa;
  // Uns 15 s para ler o modelo na primeira e ~30 s por passada (medido em 14/11/2026)
  mostrarEstimativa("tf-estimativa", travada || !passadas ? null : 15 + a.quantidade * passadas * s.segundos_passada, false);
  $("tf-gerar").textContent = a.quantidade > 1 ? `Trocar (${a.quantidade} versões)` : "Trocar";
  if (S.enviando) falta.push("Esperando o envio terminar");
  if (!S.tfbase) falta.push("Escolha a foto da pessoa");
  if (!passadas) falta.push("Escolha o rosto novo, a roupa nova ou os dois");
  if (s.faltam?.length) falta.push("Falta o pacote de modelos Editar imagem");
  else if (a.rosto && s.falta_lora_rosto) falta.push("Falta a LoRA de troca de rosto: baixe o pacote Editar imagem de novo");
  if (S.tfbase && !/^[A-Za-z0-9_-]{1,60}$/.test($("tf-projeto").value)) falta.push("Corrija o nome do projeto, em Ajustes avançados");
  if (S.dados.projetos.some(x => x.nome === $("tf-projeto").value)) falta.push("Já existe um projeto com este nome");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  porHtml($("tf-falta"), travada ? notaTravada("trocafoto") : htmlFalta(falta));
  $("tf-gerar").disabled = falta.length > 0;
  rotuloFila($("tf-gerar"));
  salvarRascunhoTrocaFoto();
  desenharGaleriaTrocaFoto();
}
/* O palco mostra a troca em foto mais recente, como a galeria do Texto para imagem (que deixa estas de fora) */
const CHAVE_GALERIA_TF = "estudio_galeria_troca_foto_limite";
S.galeriaLimiteTF = (() => { try { return Number(localStorage.getItem(CHAVE_GALERIA_TF)) || 0; } catch { return 0; } })();
function limiteGaleriaTF(v) {
  S.galeriaLimiteTF = v;
  try { localStorage.setItem(CHAVE_GALERIA_TF, String(v)); } catch {}
  S.marcaGaleriaTF = null;
  if (S.dados) desenharGaleriaTrocaFoto();
}
function projetoDaGaleriaTF() {
  const ultimo = S.dados?.projetos.find(x => x.tipo === "texto" && x.troca_foto && x.imagens?.length);
  return ultimo && ultimo.quando > S.galeriaLimiteTF ? ultimo : null;
}
function tirarGaleriaTF() {
  const p = projetoDaGaleriaTF(), antes = S.galeriaLimiteTF;
  if (!p) return null;
  limiteGaleriaTF(p.quando);
  return () => limiteGaleriaTF(antes);
}
/* As fotos que entraram na troca, lado a lado embaixo do resultado, para comparar o antes e o depois (palco e histórico) */
function entradasTrocaFoto(p) {
  const c = p?.config || {}, t = c.troca_foto || {};
  const itens = [["Foto da pessoa", c.partida], ["Rosto", t.rosto], ["Roupa", t.roupa]].filter(([, a]) => a);
  if (!itens.length) return "";
  return `<div class="tf-entradas"><span class="tf-entradas-rotulo">Feita com</span>${itens.map(([rotulo, a]) => {
    const src = `/entrada/foto/${encodeURIComponent(a)}`;
    return `<figure><a href="${src}" target="_blank" rel="noopener" title="Abre a ${esc(rotulo.toLowerCase())} em tamanho real">${midia(`<img src="${src}" alt="${esc(rotulo)}" loading="lazy">`, "Foto oculta")}</a><figcaption>${esc(rotulo)}</figcaption></figure>`;
  }).join("")}</div>`;
}
/* Uma foto de entrada que sumiu da pasta do ComfyUI sai da comparação, em vez de aparecer quebrada */
function tirarEntradasQuebradas(el) {
  for (const img of el.querySelectorAll(".tf-entradas img")) img.addEventListener("error", () => img.closest("figure")?.remove(), { once: true });
}
/* A geração em andamento é uma troca em foto? (a tarefa só diz "texto"; o projeto diz o resto) */
const tarefaTrocaFoto = tar => !!(tar?.rodando && tar.tipo === "texto" && S.dados?.projetos.find(p => p.nome === tar.projeto)?.troca_foto);
function desenharGaleriaTrocaFoto() {
  const ultimo = projetoDaGaleriaTF(), tar = S.dados.tarefa;
  const gerando = !!(ultimo && tar?.rodando && tar.projeto === ultimo.nome);
  const novo = tarefaTrocaFoto(tar) && (!ultimo || tar.projeto !== ultimo.nome);
  const marca = JSON.stringify([ultimo?.nome, ultimo?.imagens.map(i => i.marca), gerando, novo, ultimo?.avisos]);
  if (marca === S.marcaGaleriaTF) return;
  S.marcaGaleriaTF = marca;
  $("tf-vazio").classList.toggle("gerando", novo);
  $("tf-vazio-texto").innerHTML = novo ? "<strong>Trocando…</strong><small>A foto aparece aqui em uns 30 segundos por troca.</small>"
    : "<strong>A foto trocada aparece aqui</strong><small>Escolha a foto da pessoa e o rosto ou a roupa nova, ao lado.</small>";
  $("tf-vazio").hidden = !!ultimo && !novo;
  $("tf-galeria").hidden = $("tf-entradas").hidden = !ultimo || novo;
  $("tf-rodape").hidden = !ultimo || novo;
  if (!ultimo || novo) { $("tf-conta").textContent = ""; return; }
  $("tf-entradas").innerHTML = entradasTrocaFoto(ultimo);
  tirarEntradasQuebradas($("tf-entradas"));
  const nome = encodeURIComponent(ultimo.nome), n = ultimo.imagens.length;
  $("tf-galeria").dataset.n = n;
  $("tf-galeria").innerHTML = ultimo.imagens.map(i => {
    const src = `/imagem/${nome}/${i.arquivo}?m=${i.marca}`;
    return `<figure class="t2i-item">${midia(`<img src="${src}" alt="Versão ${i.n} de ${esc(ultimo.nome)}">`, "Imagem oculta")}${botoesImagem(ultimo, i, src)}</figure>`;
  }).join("");
  const avisos = (ultimo.avisos || []).map(x => ` ${esc(x)}`).join("");
  $("tf-conta").innerHTML = (gerando ? esc(`Gerando ${n} de ${ultimo.total}…`) : legendaImagens(ultimo)) + avisos;
  $("tf-rodape").dataset.projetoAcao = ultimo.nome;
  $("tf-descartar").hidden = gerando;
  $("tf-descartar").textContent = n > 1 ? `Descartar as ${n}` : "Descartar";
}
async function iniciarTrocaFoto() {
  $("tf-erro").hidden = true;
  $("tf-gerar").disabled = true;
  const nome = $("tf-projeto").value;
  try {
    await postar("/api/iniciar-troca-foto", { projeto: nome, ajustes: lerTrocaFoto() });
    S.dispensada = null;
    marcarEnviado("trocafoto", nome);
  } catch (e) {
    $("tf-erro").textContent = e.message;
    $("tf-erro").hidden = false;
  }
  await consultar(true);
}
