/* Ajustes */
function lerAjustes() {
  const loras = [];
  if (valor("lora")) loras.push([valor("lora"), Number($("forca").value)]);
  if (valor("lora2")) loras.push([valor("lora2"), Number($("forca2").value)]);
  return { modelo: valor("modelo"), loras, sampler: valor("sampler"), agendador: valor("agendador"), passos: Number($("passos").value), megapixels: Number($("megapixels").value),
           proporcao: $("proporcao").value, tentativas: Number($("tentativas").value), semente: $("semente").value === "" ? null : Number($("semente").value) };
}
function aplicarAjustes(a) {
  const p = { ...S.dados.padrao, ...a };
  poeValor("modelo", p.modelo); poeValor("sampler", p.sampler); poeValor("agendador", p.agendador);
  $("passos").value = p.passos; $("megapixels").value = p.megapixels; $("proporcao").value = p.proporcao;
  $("tentativas").value = p.tentativas; $("semente").value = p.semente ?? "";
  const [l1, l2] = p.loras;
  poeValor("lora", l1?.[0] ?? ""); $("forca").value = l1?.[1] ?? 1;
  poeValor("lora2", l2?.[0] ?? ""); $("forca2").value = l2?.[1] ?? 1;
  S.passosEditados = false;
}
function preencherOpcoes(d) {
  const marca = JSON.stringify(d.opcoes);
  if (marca === S.marcaOpcoes) return;
  const atual = S.marcaOpcoes && S.dados ? lerAjustes() : null;
  S.marcaOpcoes = marca;
  const o = d.opcoes;
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  const garante = (lista, v) => lista.includes(v) ? lista : [v, ...lista];
  $("modelo").innerHTML = garante(o.modelos, d.padrao.modelo).map(m => opt(m, NOMES_MODELO[m] || semExt(m))).join("");
  const loras = garante(o.loras, d.padrao.loras[0][0]).map(l => opt(l, NOMES_LORA[l] || semExt(l))).join("");
  $("lora").innerHTML = opt("", "Nenhuma") + loras;
  $("lora2").innerHTML = opt("", "Nenhuma") + loras;
  $("sampler").innerHTML = garante(o.samplers, d.padrao.sampler).map(s => opt(s, s === d.padrao.sampler ? `${s} (testado)` : s)).join("");
  $("agendador").innerHTML = garante(o.agendadores, d.padrao.agendador).map(s => opt(s, s === d.padrao.agendador ? `${s} (testado)` : s)).join("");
  $("proporcao").innerHTML = d.proporcoes.map(p => opt(p, nomeProporcao(p))).join("");
  $("megapixels").innerHTML = d.qualidades.map(q => opt(q, `${num(q, q === 0.65 ? 2 : 1)} MP${q === d.padrao.megapixels ? " (testada)" : q > 0.65 ? " (mais lenta, mais memória)" : " (mais lenta)"}`)).join("");
  aplicarAjustes(atual || {});
}
function resolucao(a) {
  const m = a.proporcao.match(/^(\d+):(\d+)/);
  if (!m) return "";
  const r = m[1] / m[2], px = a.megapixels * 1024 * 1024, passo = 32;
  return `${Math.round(Math.sqrt(px * r) / passo) * passo}×${Math.round(Math.sqrt(px / r) / passo) * passo}`;
}
function resumoAjustes(a) {
  const loras = a.loras.length ? a.loras.map(([n, f]) => `${(NOMES_LORA[n] || semExt(n)).replace(" (padrão testado)", "")} ${num(f, 2)}`).join(" e ") : "sem LoRA";
  return `${(NOMES_MODELO[a.modelo] || semExt(a.modelo)).replace(/ \(.*\)$/, "")}, ${loras}, ${a.passos} passos, ${a.sampler} com ${a.agendador}, ${resolucao(a)}`;
}
function ajustesPadrao(a) {
  const p = S.dados.padrao;
  return a.modelo === p.modelo && a.sampler === p.sampler && a.agendador === p.agendador && a.passos === p.passos && a.megapixels === p.megapixels && JSON.stringify(a.loras) === JSON.stringify(p.loras);
}
