/* Aviso de prompt comprido (24/11/2026): Klein, Z-Image, Chroma, Krea 2 e Wan foram feitos para até 512 tokens de texto. Quem conta é
   o servidor (tokens.py, /api/contar-tokens), com o tokenizador do modelo. Só avisa: o texto vai inteiro e a geração não é travada. */
const CAMPOS_TOKENS = [
  { alvo: "imagem", campo: "t2i-prompt", ler: () => lerTexto(), textos: a => [a.prompt] },
  { alvo: "wan", campo: "i-tomadas", ler: () => lerImagem(), textos: a => a.modelo === "h3" ? [] : a.tomadas.map(t => t.acao) },
  { alvo: "pintura", campo: "e-pedido-klein", ler: () => ({ prompt: $("e-pedido-klein").value }), textos: a => [a.prompt] },
];
/* Um token tem pelo menos 1 byte: com menos bytes que isto nenhum texto passa de 512, nem com a frase da câmera, a palavra da LoRA
   e o molde do modelo, e o servidor nem é chamado. O estilo pronto soma o texto dele, então com detalhe conta sempre. */
const BYTES_SEM_CONTAR = 250;
const bytesTexto = s => new TextEncoder().encode(s || "").length;
function precisaContar(textos, estilo) {
  return textos.some(s => bytesTexto(s) > (estilo ? 0 : BYTES_SEM_CONTAR));
}
function caixaTokens(campo) {
  const id = `${campo}-tokens`;
  if (!$(id)) {
    const p = document.createElement("p");
    p.id = id; p.className = "aviso"; p.setAttribute("role", "status"); p.style.whiteSpace = "pre-line";
    $(campo).insertAdjacentElement("afterend", p);
  }
  return $(id);
}
/* Os campos também mudam pelo código (Usar de novo, Descrever, a IA que escreve o pedido): em vez de ligar em cada lugar, confere
   de segundo em segundo se o que seria contado mudou. Só chama o servidor depois que o texto ficou igual por um ciclo. */
async function conferirTokens(c) {
  if (!$(c.campo) || !S.dados) return;
  let ajustes, textos;
  try { ajustes = c.ler(); textos = c.textos(ajustes); } catch { return; }
  const chave = JSON.stringify([textos, ajustes.modelo, ajustes.estilo, ajustes.loras, ajustes.qualidade_alta, (ajustes.tomadas || []).map(t => [t.camera, t.olhar])]);
  if (chave === c.contada) return;
  if (chave !== c.vista) { c.vista = chave; return; }
  c.contada = chave;
  if (!precisaContar(textos, ajustes.estilo)) { caixaTokens(c.campo).textContent = ""; return; }
  try {
    const r = await postar("/api/contar-tokens", { alvo: c.alvo, ajustes });
    if (c.contada === chave) caixaTokens(c.campo).textContent = (r.avisos || []).join("\n");
  } catch { if (c.contada === chave) caixaTokens(c.campo).textContent = ""; }
}
setInterval(() => { if (!document.hidden) CAMPOS_TOKENS.forEach(conferirTokens); }, 1000);
