/* Testes do personagens_visuais.js (agrupar personagens por pessoa e visual) no Node. Rodado por testar_navegacao.py. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const JS = path.join(__dirname, "..", "pagina", "js");

function pagina() {
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(JS, "personagens_visuais.js"), "utf8"), ctx);
  return ctx;
}
const item = (id, pessoa, visual, criado, pronto, nome) => ({ id, nome: nome || id, pessoa, visual, criado, pronto });
const testes = {
  agrupa_tres_itens_em_uma_pessoa(c) {
    const lista = [
      item("mov_b2", "mov", "Casaco", "2026-11-03 10:00:00", false),
      item("mov", "mov", "Original", "2026-11-01 10:00:00", true, "Mov"),
      item("mov_bikini", "mov", "Biquíni", "2026-11-02 10:00:00", true),
    ];
    const pessoas = c.agruparPessoas(lista);
    assert.strictEqual(pessoas.length, 1);
    assert.strictEqual(pessoas[0].id, "mov");
    assert.strictEqual(pessoas[0].nome, "Mov");
    assert.strictEqual(pessoas[0].capa, "mov");
    // raiz primeiro, os demais por data de criação
    // (JSON.stringify: arrays criados dentro do vm têm outro Array e não passam no deepStrictEqual)
    assert.strictEqual(JSON.stringify(pessoas[0].visuais.map(v => v.id)), '["mov","mov_bikini","mov_b2"]');
    assert.strictEqual(pessoas[0].visuais[1].rotulo, "Biquíni");
    assert.strictEqual(c.visuaisProntos(pessoas[0]).length, 2);
  },
  pessoas_na_ordem_da_raiz(c) {
    const lista = [item("b", "b", "", "2026-11-02 00:00:00", true), item("a", "a", "", "2026-11-01 00:00:00", true),
                   item("b2", "b", "X", "2026-11-03 00:00:00", true)];
    assert.strictEqual(JSON.stringify(c.agruparPessoas(lista).map(p => p.id)), '["b","a"]');
  },
  passos_do_seletor(c) {
    const um = c.agruparPessoas([item("a", "a", "", "2026-11-01 00:00:00", true), item("a2", "a", "X", "2026-11-02 00:00:00", false)])[0];
    assert.strictEqual(c.passosDoSeletor(um), "direto");
    const dois = c.agruparPessoas([item("a", "a", "", "2026-11-01 00:00:00", true), item("a2", "a", "X", "2026-11-02 00:00:00", true)])[0];
    assert.strictEqual(c.passosDoSeletor(dois), "visuais");
  },
  lista_vazia(c) {
    assert.strictEqual(c.agruparPessoas([]).length, 0);
  },
};
let falhas = 0;
for (const [nome, t] of Object.entries(testes)) {
  try { t(pagina()); console.log(`ok ${nome}`); }
  catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
}
process.exit(falhas ? 1 : 0);
