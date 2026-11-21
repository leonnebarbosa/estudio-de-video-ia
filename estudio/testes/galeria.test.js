/* Testes da galeria da tela inicial (explorar.js) no Node. Rodado por testar_navegacao.py. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");

function pagina() {
  const el = () => ({ addEventListener() {}, querySelector: () => null, hidden: true });
  const ctx = { $: el, S: {}, esc: s => String(s), midia: h => h, irPara() {}, desenharProjetos() {},
    localStorage: { getItem: () => null, setItem() {} } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "pagina", "js", "explorar.js"), "utf8"), ctx);
  return ctx;
}
const nomes = lista => lista.map(p => p.nome).join(",");
const testes = {
  cada_tipo_cai_em_um_filtro(c) {
    assert.strictEqual(c.filtroDoProjeto({ tipo: "troca" }), "troca");
    assert.strictEqual(c.filtroDoProjeto({ tipo: "texto", troca_foto: true }), "troca");
    assert.strictEqual(c.filtroDoProjeto({ tipo: "texto" }), "imagem");
    for (const tipo of ["imagem", "wan", "continuar", "editar"]) assert.strictEqual(c.filtroDoProjeto({ tipo }), "video", tipo);
    assert.strictEqual(c.filtroDoProjeto({ tipo: "imagem", sem_imagem: true }), "video");
    assert.strictEqual(c.filtroDoProjeto({ tipo: "novidade" }), null);
    assert.strictEqual(c.filtroDoProjeto({}), null);
  },
  galeria_so_tem_projeto_com_midia_do_mais_novo_ao_mais_antigo(c) {
    const projetos = [
      { nome: "antigo", tipo: "imagem", quando: 10, final: { marca: 1 } },
      { nome: "sem_midia", tipo: "imagem", quando: 50 },
      { nome: "imagens_vazias", tipo: "texto", quando: 40, imagens: [] },
      { nome: "novo", tipo: "texto", quando: 30, imagens: [{ arquivo: "a.png" }] },
      { nome: "meio", tipo: "troca", quando: 20, final: { marca: 2 } },
    ];
    assert.strictEqual(nomes(c.projetosDaGaleria(projetos, "tudo")), "novo,meio,antigo");
    assert.strictEqual(nomes(c.projetosDaGaleria(projetos, "video")), "antigo");
    assert.strictEqual(nomes(c.projetosDaGaleria(projetos, "imagem")), "novo");
    assert.strictEqual(nomes(c.projetosDaGaleria(projetos, "troca")), "meio");
    assert.strictEqual(projetos[0].nome, "antigo", "a lista recebida não pode ser reordenada");
  },
  tipo_desconhecido_so_aparece_em_tudo(c) {
    const projetos = [{ nome: "estranho", tipo: "novidade", quando: 5, final: { marca: 1 } }];
    assert.strictEqual(nomes(c.projetosDaGaleria(projetos, "tudo")), "estranho");
    for (const filtro of ["video", "imagem", "troca"]) assert.strictEqual(c.projetosDaGaleria(projetos, filtro).length, 0, filtro);
  },
  lista_vazia_ou_ausente_nao_quebra(c) {
    assert.strictEqual(c.projetosDaGaleria([], "tudo").length, 0);
    assert.strictEqual(c.projetosDaGaleria(undefined, "video").length, 0);
  },
};
let falhas = 0;
for (const [nome, t] of Object.entries(testes)) {
  try { t(pagina()); console.log(`ok ${nome}`); }
  catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
}
process.exit(falhas ? 1 : 0);
