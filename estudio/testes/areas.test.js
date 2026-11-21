/* Testes do areas.js (menu de quatro áreas) no Node. Rodado por testar_navegacao.py. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const JS = path.join(__dirname, "..", "pagina", "js");

function pagina() {
  const guardado = {};
  const ctx = { localStorage: { getItem: k => (k in guardado ? guardado[k] : null), setItem: (k, v) => { guardado[k] = String(v); } } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(JS, "areas.js"), "utf8"), ctx);
  ctx.valor = codigo => vm.runInContext(codigo, ctx);
  return ctx;
}
const testes = {
  cada_tela_tem_uma_area(c) {
    // As abas que o irPara conhece (base.js): cada uma precisa estar numa área, e não só cair no padrão
    const base = fs.readFileSync(path.join(JS, "base.js"), "utf8");
    const lista = base.match(/for \(const nome of \[([^\]]+)\]\) \$\(`aba-\$\{nome\}`\)/);
    assert.ok(lista, "não achei a lista de abas no irPara");
    const abas = lista[1].match(/"([^"]+)"/g).map(s => s.slice(1, -1));
    assert.strictEqual(abas.length, 11);
    const todas = Object.values(c.valor("AREAS")).flat();
    for (const aba of abas) assert.ok(todas.includes(aba), `a aba ${aba} não está em nenhuma área`);
    assert.strictEqual(c.areaDaAba("tvideo"), "video");
    assert.strictEqual(c.areaDaAba("avancado"), "video");
    assert.strictEqual(c.areaDaAba("novo"), "video");
    // Projetos tem o seu próprio botão no menu (a pasta no canto direito) e é ele que acende
    assert.strictEqual(c.areaDaAba("projetos"), "projetos");
    assert.strictEqual(c.areaDaAba("explorar"), "inicio");
    assert.strictEqual(c.areaDaAba("modelos"), "modelos");
    assert.strictEqual(c.areaDaAba("texto"), "imagem");
    assert.strictEqual(c.areaDaAba("xyz"), "inicio");
  },
  modo_de_video_salvo(c) {
    assert.strictEqual(c.modoVideoSalvo(), "imagem");
    c.guardarModoVideo("novo");
    assert.strictEqual(c.modoVideoSalvo(), "novo");
    c.guardarModoVideo("texto");
    assert.strictEqual(c.modoVideoSalvo(), "novo");
  },
  modo_de_video_invalido_volta_ao_padrao(c) {
    c.localStorage.setItem("estudio_modo_video", "projetos");
    assert.strictEqual(c.modoVideoSalvo(), "imagem");
  },
};
let falhas = 0;
for (const [nome, t] of Object.entries(testes)) {
  try { t(pagina()); console.log(`ok ${nome}`); }
  catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
}
process.exit(falhas ? 1 : 0);
