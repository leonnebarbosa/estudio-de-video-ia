/* Testes da capa de cada projeto no modo galeria (projetos.js). Rodado por testar_navegacao.py.
   O projetos.js mexe na página ao carregar, então o teste roda só a função de que precisa, tirada do próprio arquivo. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const fonte = fs.readFileSync(path.join(__dirname, "..", "pagina", "js", "projetos.js"), "utf8");

function pagina() {
  const capa = fonte.match(/^function comCapa\([\s\S]*?^}/m);
  assert.ok(capa, "não achei o comCapa no projetos.js");
  // midiaExplorar (explorar.js) devolve a mídia do projeto, ou "" quando ele não tem nenhuma
  const ctx = { midiaExplorar: p => (p.final ? `<span class="midia"><video src="v.mp4"></video></span>` : "") };
  vm.createContext(ctx);
  vm.runInContext(capa[0], ctx);
  return ctx;
}
const projeto = (resumo = "") => `<details class="projeto" data-projeto="x"><summary><span class="miniatura"></span>${resumo}</summary><div class="corpo"><details><summary>Mais</summary></details></div></details>`;
const testes = {
  a_capa_entra_logo_depois_do_primeiro_resumo(c) {
    const h = c.comCapa({ final: { marca: 1 } }, projeto());
    assert.ok(h.startsWith(`<details class="projeto" data-projeto="x"><summary><span class="capa">`), h.slice(0, 120));
    assert.ok(h.includes("<video"));
    assert.strictEqual((h.match(/class="capa/g) || []).length, 1, "a capa não pode entrar nos detalhes de dentro do projeto");
  },
  sem_midia_a_capa_mostra_um_icone(c) {
    const h = c.comCapa({}, projeto());
    assert.ok(h.includes(`class="capa capa-vazia"`));
    assert.ok(h.includes(`href="#s-filme"`));
  },
  o_resto_do_projeto_fica_igual(c) {
    const original = projeto("<span class=\"nome\">x</span>");
    const h = c.comCapa({ final: { marca: 1 } }, original);
    assert.strictEqual(h.replace(/<span class="capa">[\s\S]*?<\/span><\/span>/, ""), original);
  },
};
let falhas = 0;
for (const [nome, t] of Object.entries(testes)) {
  try { t(pagina()); console.log(`ok ${nome}`); }
  catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
}
process.exit(falhas ? 1 : 0);
