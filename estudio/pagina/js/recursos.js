// Painel de recursos do cabeçalho: CPU, memória, placa e disco, com um traço do histórico (só leitura).
const GB = 2 ** 30;
function traco(valores, maximo) {
  const v = valores.filter((x) => x !== null && x !== undefined);
  if (v.length < 2 || !(maximo > 0)) return "";
  const n = valores.length;
  const pontos = valores.map((x, i) => (x === null || x === undefined) ? null : `${((i / (n - 1)) * 60).toFixed(1)},${(16 - Math.min(x / maximo, 1) * 15 - 0.5).toFixed(1)}`).filter(Boolean);
  return `<svg class="traco" viewBox="0 0 60 16" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pontos.join(" ")}"/></svg>`;
}
function itemRecurso(nome, texto, grafico, quente) {
  return `<span class="recurso${quente ? " quente" : ""}"><span class="rotulo">${nome}</span> <span class="valor">${texto}</span>${grafico || ""}</span>`;
}
function desenharRecursos(r) {
  const alvo = $("recursos"), resumo = $("recursos-resumo"), botao = $("recursos-botao");
  if (!r) { alvo.innerHTML = ""; resumo.textContent = "—"; botao.classList.remove("quente"); return; }
  const gpu = r.gpu;
  resumo.innerHTML = gpu ? `<span class="r-uso">${gpu.uso}% · </span><span class="r-temp">${gpu.temp} °C</span><span class="r-mem"> · ${num(gpu.memoria / 1024)} GB</span>` : esc(r.cpu === null || r.cpu === undefined ? "Uso do computador" : `CPU ${num(r.cpu, 0)}%`);
  botao.classList.toggle("quente", !!gpu && gpu.temp >= 80);
  botao.title = gpu ? `Placa de vídeo: uso, temperatura e memória${gpu.temp >= 80 ? ". A placa está quente" : ""}` : "Uso do computador";
  const h = r.historico || [];
  const g = r.gpu;
  const cpu = r.cpu === null || r.cpu === undefined ? null : r.cpu;
  alvo.innerHTML = [
    itemRecurso("CPU", cpu === null ? "—" : `${num(cpu, 0)}%`, traco(h.map((p) => p.cpu), 100)),
    itemRecurso("RAM", r.ram ? `${num(r.ram.usada / GB)}/${num(r.ram.total / GB, 0)} GB` : "—"),
    itemRecurso("Placa", g ? `${g.uso}% · ${num(g.memoria / 1024)}/${num(g.memoria_total / 1024, 0)} GB · ${g.temp} °C` : "—",
      g ? traco(h.map((p) => p.gpu), 100) + traco(h.map((p) => p.gpu_memoria), g.memoria_total) : "", !!g && g.temp >= 80),
    itemRecurso("Disco", r.disco ? `${num(r.disco.livre / GB, 0)} GB livres` : "—"),
  ].join("");
}
