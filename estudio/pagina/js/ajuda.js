/* Ajuda atrás de um "?" (reforma de 20/11/2026): na barra lateral, o texto que explica um campo deixa de ocupar espaço e
   abre num balão, ao passar o mouse, ao focar ou ao clicar (o clique fixa). O texto continua no mesmo elemento .ajuda,
   escrito pelo código de sempre: este arquivo só muda onde ele aparece.
   Fica à vista, sem "?": a .ajuda com data-estado (valor calculado, contagem, resultado de uma escolha) e a que não tem
   um rótulo ou uma chave no mesmo campo para ancorar o botão. */
{
  let fixado = null;
  const balaoDe = botao => botao._balao;
  function posicionar(botao) {
    // O balão nasce embaixo do nome do campo (o "?" ficou invisível em 23/11/2026; só o teclado chega nele)
    const balao = balaoDe(botao), r = (botao._alvo || botao).getBoundingClientRect(), margem = 8;
    const largura = balao.offsetWidth, altura = balao.offsetHeight;
    const esquerda = Math.max(margem, Math.min(r.left, innerWidth - largura - margem));
    const abaixo = r.bottom + 6, cabeAbaixo = abaixo + altura + margem <= innerHeight;
    balao.style.left = `${Math.round(esquerda)}px`;
    balao.style.top = `${Math.round(cabeAbaixo ? abaixo : Math.max(margem, r.top - altura - 6))}px`;
  }
  function abrir(botao) {
    const balao = balaoDe(botao);
    if (!balao.isConnected || !balao.textContent.trim()) return;
    document.querySelectorAll(".dica[aria-expanded='true']").forEach(b => { if (b !== botao) fechar(b); });
    if (!balao.matches(":popover-open")) balao.showPopover();
    botao.setAttribute("aria-expanded", "true");
    posicionar(botao);
  }
  function fechar(botao) {
    const balao = balaoDe(botao);
    if (balao.matches(":popover-open")) balao.hidePopover();
    botao.setAttribute("aria-expanded", "false");
    if (fixado === botao) fixado = null;
  }
  function nomeDe(el) {
    const texto = [...el.childNodes].find(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
    if (!texto) return el;
    const nome = document.createElement("span");
    nome.className = "nome-campo";
    texto.replaceWith(nome);
    nome.append(texto);
    return nome;
  }
  function criarDica(ancora, balao, rotulo, alvo) {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "dica";
    botao.textContent = "?";
    botao.setAttribute("aria-label", `Ajuda: ${rotulo}`);
    botao.setAttribute("aria-expanded", "false");
    botao._balao = balao;
    balao.popover = "manual";
    balao.classList.add("balao");
    balao.setAttribute("role", "tooltip");
    // Um botão dentro de um <label> sem "for" viraria o controle dele: clicar no nome do campo abriria a ajuda em vez de
    // focar o campo, e o campo perderia o nome. O label passa a apontar para o campo de verdade.
    const rotulado = balao.closest("label.campo");
    if (rotulado && !rotulado.htmlFor) {
      const controle = rotulado.querySelector("input, select, textarea");
      if (controle) { controle.id ||= `campo-${++criarDica.n}`; rotulado.htmlFor = controle.id; }
    }
    // Clicar no texto do balão não mexe no campo nem fecha a ajuda (os links dentro dele continuam valendo)
    balao.addEventListener("click", e => { if (!e.target.closest("a")) e.preventDefault(); });
    ancora(botao);
    // Sem texto não há o que mostrar: o código de cada tela esvazia e preenche a ajuda conforme a escolha
    const conferir = () => { botao.hidden = !balao.textContent.trim(); if (botao.hidden) fechar(botao); else if (botao.getAttribute("aria-expanded") === "true") posicionar(botao); };
    new MutationObserver(conferir).observe(balao, { childList: true, characterData: true, subtree: true });
    conferir();
    botao.addEventListener("pointerenter", e => { if (e.pointerType === "mouse") abrir(botao); });
    botao.addEventListener("pointerleave", e => { if (e.pointerType === "mouse" && fixado !== botao) fechar(botao); });
    // Passar o mouse no nome do campo abre a explicação; sem o "?" à vista, o cursor de ajuda avisa que há o que ler.
    // Só as palavras do nome contam, não o resto da linha: o primeiro texto do rótulo ou da chave ganha um <span> próprio
    alvo = alvo && nomeDe(alvo);
    if (alvo) {
      botao._alvo = alvo;
      alvo.classList.add("tem-ajuda");
      alvo.addEventListener("pointerenter", e => { if (e.pointerType === "mouse" && !botao.hidden) abrir(botao); });
      alvo.addEventListener("pointerleave", e => { if (e.pointerType === "mouse" && fixado !== botao) fechar(botao); });
    }
    botao.addEventListener("focus", () => abrir(botao));
    botao.addEventListener("blur", () => { if (fixado !== botao) fechar(botao); });
    botao.addEventListener("click", e => {
      e.preventDefault();
      if (fixado === botao) return fechar(botao);
      abrir(botao);
      fixado = botao;
    });
  }
  criarDica.n = 0;
  const textoDoRotulo = el => (el?.childNodes[0]?.textContent || el?.textContent || "").trim();
  for (const ajuda of document.querySelectorAll(".lado .ajuda:not([data-estado])")) {
    const campo = ajuda.closest(".campo") || ajuda.parentElement;
    const rotulo = [...campo.children].find(f => f.classList.contains("rotulo")), chave = [...campo.children].find(f => f.classList.contains("chave"));
    if (rotulo) criarDica(b => rotulo.append(b), ajuda, textoDoRotulo(rotulo), rotulo);
    else if (chave && ajuda.previousElementSibling === chave) { campo.classList.add("campo-chave"); criarDica(b => chave.after(b), ajuda, chave.textContent.trim(), chave); }
  }
  // Áreas de envio: a explicação da zona vazia vai para o "?" do rótulo; o texto da zona passa a ser só o nome
  for (const zona of document.querySelectorAll(".lado .escolha")) {
    const campo = zona.closest(".campo"), rotulo = campo && [...campo.children].find(f => f.classList.contains("rotulo")), explicacao = zona.querySelector("small")?.textContent.trim();
    if (!rotulo || !explicacao || rotulo.querySelector(".dica")) continue;
    const balao = document.createElement("span");
    balao.className = "ajuda";
    balao.textContent = explicacao;
    campo.append(balao);
    criarDica(b => rotulo.append(b), balao, textoDoRotulo(rotulo), rotulo);
  }
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".dica[aria-expanded='true']").forEach(fechar); });
  document.addEventListener("pointerdown", e => { if (fixado && !e.target.closest(".dica, .balao, .tem-ajuda")) fechar(fixado); });
  // A barra rola e a janela muda de tamanho: o balão ficaria longe do botão
  document.addEventListener("scroll", () => document.querySelectorAll(".dica[aria-expanded='true']").forEach(fechar), true);
  addEventListener("resize", () => document.querySelectorAll(".dica[aria-expanded='true']").forEach(fechar));
}
