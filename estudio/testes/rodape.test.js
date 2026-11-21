/* Testes do htmlFalta (base.js): o que falta para gerar aparece em uma linha no rodapé da barra lateral.
   Rodado por testar_barra_lateral.py. O base.js mexe na página ao carregar, então o teste roda só as duas definições
   de que precisa, tiradas do próprio arquivo. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const base = fs.readFileSync(path.join(__dirname, "..", "pagina", "js", "base.js"), "utf8");

function pagina() {
  const esc = base.match(/^const esc = .*$/m), falta = base.match(/^function htmlFalta\([\s\S]*?^}/m);
  assert.ok(esc, "não achei o esc no base.js");
  assert.ok(falta, "não achei o htmlFalta no base.js");
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(`${esc[0]}\n${falta[0]}`, ctx);
  return ctx;
}
const visivel = html => html.replace(/<span class="falta-lista"[\s\S]*?<\/ul><\/span>/, "").replace(/<[^>]+>/g, "");
const testes = {
  nada_faltando_nao_desenha_nada(c) {
    assert.strictEqual(c.htmlFalta([]), "");
  },
  um_item_aparece_inteiro_sem_contador(c) {
    const h = c.htmlFalta(["Escolha a imagem"]);
    assert.ok(h.includes("Escolha a imagem"));
    assert.ok(!h.includes("falta-mais"));
  },
  varios_itens_mostram_o_primeiro_e_quantos_mais(c) {
    const h = c.htmlFalta(["Escolha a imagem", "Escreva a tomada 1", "Confirme a autorização"]);
    assert.ok(visivel(h).includes("Escolha a imagem"));
    assert.ok(visivel(h).includes("e mais 2"));
    assert.ok(!visivel(h).includes("Escreva a tomada 1"));
    const lista = h.match(/<span class="falta-lista"[\s\S]*<\/ul><\/span>/)[0];
    for (const item of ["Escolha a imagem", "Escreva a tomada 1", "Confirme a autorização"]) assert.ok(lista.includes(`<li>${item}</li>`), item);
  },
  o_texto_sai_escapado(c) {
    assert.ok(!c.htmlFalta(["<b>x</b>"]).includes("<b>"));
    assert.ok(!c.htmlFalta(["a", "<b>x</b>"]).includes("<b>"));
  },
};
let falhas = 0;
for (const [nome, t] of Object.entries(testes)) {
  try { t(pagina()); console.log(`ok ${nome}`); }
  catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
}
process.exit(falhas ? 1 : 0);
