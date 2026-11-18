/* Controles visuais por cima dos campos de sempre. A caixa original (select ou numero) continua sendo a fonte da verdade:
   os scripts leem e escrevem nela como antes. O controle novo so mostra o valor dela e, quando mexido, muda a caixa e
   dispara os mesmos eventos de quem escolhesse direto nela. Depois de cada atualizacao do formulario, tudo se sincroniza. */
const CONTROLES = {
  faixa: ["megapixels", "t-megapixels", "t-upscale-res", "i-megapixels"],
  formato: ["proporcao", "t-proporcao", "i-proporcao"],
  segmento: ["i-acabamento"],
  forca: ["forca", "forca2", "t-troca-forca", "t-turbo-forca", "t-nitidez-forca"],
  passos: ["passos", "t-passos", "tentativas"],
};
const CURTO_ACABAMENTO = { nenhum: "Nenhum", esrgan: "ESRGAN", refino: "Refino H3" };
const CURTO_OPCAO = { mesma: "Igual à 1ª" };
const montados = new Map();

const ehNumero = v => v !== "" && Number.isFinite(Number(v));
const rotuloDe = el => el.closest(".campo")?.querySelector(".rotulo")?.textContent.trim() || el.getAttribute("aria-label") || "";
// "Média (padrão testado)" -> nome "Média", nota "padrão testado"; a nota diz se foi testado nesta placa
function partes(texto) {
  const m = String(texto).match(/^(.*?)\s*\((.*)\)\s*$/);
  return m ? { nome: m[1], nota: m[2] } : { nome: texto, nota: "" };
}
const tomDaNota = n => /não testad|risco/i.test(n) ? "alerta" : /testad/i.test(n) ? "bom" : n ? "neutro" : "";
function avisar(el, ...tipos) {
  for (const t of tipos) el.dispatchEvent(new Event(t, { bubbles: true }));
}
function escolherOpcao(select, valor) {
  if (select.value === valor) return;
  select.value = valor;
  avisar(select, "change");
}

/* Resolucao: slider com uma marca por opcao, em ordem; uma opcao que nao e numero (ex.: "Mesma da primeira passagem") vira um botao ao lado.
   Com duas opcoes numericas ou menos, um slider nao ajuda: vira um controle segmentado. */
function montarFaixa(select) {
  const caixa = document.createElement("div");
  caixa.className = "faixa-controle";
  caixa.innerHTML = `<div class="faixa-topo"><span class="faixa-nome"></span><span class="selo"></span></div>
    <input type="range" min="0" step="1" aria-label="${esc(rotuloDe(select))}"><div class="faixa-marcas" aria-hidden="true"></div><div class="faixa-extras"></div>`;
  select.after(caixa);
  select.classList.add("substituido");
  const faixa = caixa.querySelector("input");
  let numericas = [];
  faixa.addEventListener("input", () => { const o = numericas[Number(faixa.value)]; if (o) escolherOpcao(select, o.value); sinc(); });
  caixa.querySelector(".faixa-marcas").addEventListener("click", e => { const i = e.target.dataset?.i; if (i !== undefined) { faixa.value = i; avisar(faixa, "input"); } });
  caixa.querySelector(".faixa-extras").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { escolherOpcao(select, b.value); sinc(); } });
  let assinatura = "";
  function sinc() {
    const opcoes = [...select.options];
    const marca = opcoes.map(o => `${o.value}|${o.text}|${o.disabled}`).join(";");
    if (marca !== assinatura) {
      assinatura = marca;
      numericas = opcoes.filter(o => ehNumero(o.value)).sort((a, b) => Number(a.value) - Number(b.value));
      const segmentado = numericas.length <= 2;
      caixa.classList.toggle("como-segmento", segmentado);
      faixa.max = Math.max(0, numericas.length - 1);
      caixa.querySelector(".faixa-marcas").innerHTML = numericas.map((o, i) => `<span data-i="${i}" style="left:${numericas.length > 1 ? i / (numericas.length - 1) * 100 : 0}%" title="${esc(o.text)}"></span>`).join("");
      const extras = segmentado ? opcoes : opcoes.filter(o => !ehNumero(o.value));
      caixa.querySelector(".faixa-extras").innerHTML = extras.map(o => `<button type="button" class="segmento-botao" value="${esc(o.value)}" title="${esc(o.text)}" ${o.disabled ? "disabled" : ""}>${esc(CURTO_OPCAO[o.value] || partes(o.text).nome)}</button>`).join("");
    }
    const atual = select.selectedOptions[0];
    const i = numericas.findIndex(o => o.value === select.value);
    if (i >= 0) faixa.value = i;
    faixa.classList.toggle("fora", i < 0);
    faixa.style.setProperty("--pct", `${i >= 0 && numericas.length > 1 ? i / (numericas.length - 1) * 100 : 0}%`);
    caixa.querySelectorAll(".faixa-marcas span").forEach((s, k) => s.classList.toggle("passou", i >= 0 && k <= i));
    caixa.querySelectorAll(".faixa-extras button").forEach(b => b.setAttribute("aria-pressed", b.value === select.value));
    const { nome, nota } = partes(atual?.text || "");
    caixa.querySelector(".faixa-nome").textContent = nome;
    const selo = caixa.querySelector(".selo");
    selo.textContent = nota;
    selo.dataset.tom = tomDaNota(nota);
  }
  return sinc;
}

/* Formato: cada proporcao desenhada como um retangulo; o escolhido fica em roxo */
function montarFormato(select) {
  const grade = document.createElement("div");
  grade.className = "formatos";
  grade.setAttribute("role", "group");
  grade.setAttribute("aria-label", rotuloDe(select));
  select.after(grade);
  select.classList.add("substituido");
  grade.addEventListener("click", e => { const b = e.target.closest("button"); if (b) { escolherOpcao(select, b.value); sinc(); } });
  let assinatura = "";
  function sinc() {
    const opcoes = [...select.options];
    const marca = opcoes.map(o => o.value).join(";");
    if (marca !== assinatura) {
      assinatura = marca;
      grade.innerHTML = opcoes.map(o => {
        const m = o.value.match(/^(\d+):(\d+)/), w = m ? Number(m[1]) : 1, h = m ? Number(m[2]) : 1;
        const escala = 22 / Math.max(w, h);
        return `<button type="button" class="formato-botao" value="${esc(o.value)}" title="${esc(o.text)}" aria-label="${esc(o.text)}"><i style="width:${(w * escala).toFixed(1)}px;height:${(h * escala).toFixed(1)}px"></i><span>${esc(m ? `${m[1]}:${m[2]}` : o.text)}</span></button>`;
      }).join("");
    }
    grade.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.value === select.value));
  }
  return sinc;
}

/* Acabamento: poucas opcoes lado a lado; a que estiver bloqueada na caixa fica apagada aqui tambem */
function montarSegmento(select) {
  const grupo = document.createElement("div");
  grupo.className = "segmentos";
  grupo.setAttribute("role", "group");
  grupo.setAttribute("aria-label", rotuloDe(select));
  select.after(grupo);
  select.classList.add("substituido");
  grupo.addEventListener("click", e => { const b = e.target.closest("button"); if (b && !b.disabled) { escolherOpcao(select, b.value); sinc(); } });
  let assinatura = "";
  function sinc() {
    const opcoes = [...select.options];
    const marca = opcoes.map(o => `${o.value}|${o.text}`).join(";");
    if (marca !== assinatura) {
      assinatura = marca;
      grupo.innerHTML = opcoes.map(o => `<button type="button" class="segmento-botao" value="${esc(o.value)}" title="${esc(o.text)}">${esc(CURTO_ACABAMENTO[o.value] || partes(o.text).nome)}</button>`).join("");
    }
    grupo.querySelectorAll("button").forEach(b => {
      const o = opcoes.find(x => x.value === b.value);
      b.disabled = !!o?.disabled;
      b.setAttribute("aria-pressed", b.value === select.value);
    });
  }
  return sinc;
}

/* Forca da LoRA: um slider de 0 a 1,5 abaixo da escolha; o numero ao lado continua editavel */
function montarForca(numero) {
  const faixa = document.createElement("input");
  faixa.type = "range";
  faixa.className = "faixa-forca";
  faixa.min = numero.min || 0; faixa.max = numero.max || 1.5; faixa.step = numero.step || 0.05;
  faixa.setAttribute("aria-label", numero.getAttribute("aria-label") || "Força");
  numero.closest(".junto").after(faixa);
  faixa.addEventListener("input", () => { numero.value = faixa.value; avisar(numero, "input", "change"); sinc(); });
  const escolha = numero.closest(".junto").querySelector("select");
  function sinc() {
    // Sem LoRA escolhida a forca nao vale nada: o slider fica apagado (o numero continua como era)
    faixa.disabled = !!escolha && !escolha.value;
    const v = Number(numero.value), min = Number(faixa.min), max = Number(faixa.max);
    if (Number.isFinite(v)) faixa.value = v;
    faixa.style.setProperty("--pct", `${Math.max(0, Math.min(1, ((Number.isFinite(v) ? v : 0) - min) / (max - min))) * 100}%`);
  }
  return sinc;
}

/* Passos e tentativas: o numero entre botoes de menos e mais */
function montarPassos(numero) {
  const grupo = document.createElement("span");
  grupo.className = "passo-a-passo";
  numero.before(grupo);
  const nome = rotuloDe(numero).toLowerCase();
  grupo.innerHTML = `<button type="button" class="passo-botao" data-passo="-1" aria-label="Diminuir ${esc(nome)}">−</button>`;
  grupo.append(numero);
  grupo.insertAdjacentHTML("beforeend", `<button type="button" class="passo-botao" data-passo="1" aria-label="Aumentar ${esc(nome)}">+</button>`);
  grupo.addEventListener("click", e => {
    const b = e.target.closest("[data-passo]");
    if (!b) return;
    const antes = numero.value;
    b.dataset.passo === "1" ? numero.stepUp() : numero.stepDown();
    if (numero.value !== antes) avisar(numero, "input", "change");
    sinc();
  });
  function sinc() {
    const v = Number(numero.value);
    grupo.querySelector('[data-passo="-1"]').disabled = Number.isFinite(v) && numero.min !== "" && v <= Number(numero.min);
    grupo.querySelector('[data-passo="1"]').disabled = Number.isFinite(v) && numero.max !== "" && v >= Number(numero.max);
  }
  return sinc;
}

const MONTAR = { faixa: montarFaixa, formato: montarFormato, segmento: montarSegmento, forca: montarForca, passos: montarPassos };
function sincronizarControles() {
  for (const [tipo, ids] of Object.entries(CONTROLES)) {
    for (const id of ids) {
      const el = $(id);
      if (!el) continue;
      if (!montados.has(id)) montados.set(id, MONTAR[tipo](el));
      montados.get(id)();
    }
  }
}
// Digitar direto no numero (forca, passos) tambem move o controle
document.addEventListener("input", e => { if (montados.has(e.target.id)) montados.get(e.target.id)(); }, true);
// Sincroniza depois de cada atualizacao do formulario (inclui "Voltar ao padrao testado", "Usar de novo" e o rascunho)
for (const nome of ["atualizar", "atualizarTroca", "atualizarImagem"]) {
  const original = window[nome];
  window[nome] = function (...args) { const r = original.apply(this, args); sincronizarControles(); return r; };
}
sincronizarControles();
