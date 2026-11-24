/* Testes do editar.js (aba Editar vídeo) no Node, com o mínimo da página simulado. Rodado por testar_editar_pagina.py.
   Cobre o que a revisão final de 19/11/2026 achou: pintura antiga escolhível depois de mudar o quadro, roteiro e pedido
   do Klein velhos reaproveitados. */
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");

function pagina() {
  const els = {};
  const el = id => els[id] || (els[id] = { id, value: "", textContent: "", innerHTML: "", hidden: false, disabled: false, checked: false, max: "",
    href: "", download: "", querySelector: () => null, querySelectorAll: () => [], classList: { toggle() {}, add() {}, remove() {} }, style: { setProperty() {} } });
  const ctx = {
    console, JSON, Math, Number, String, Object, Array, Promise, setTimeout,
    localStorage: { setItem() {}, getItem() { return null; }, removeItem() {} },
    $: el, esc: s => String(s), num: x => String(x), tempo: s => `${s} s`, midia: h => h, recado() {}, limparZona() {}, preencherArquivo() {},
    nomeLivre: n => n, vaiParaFila: () => false, sincronizarTrava: () => false, mostrarEstimativa() {}, notaTravada: () => "", rotuloFila() {},
    soltarTrava() {}, marcarEnviado() {}, consultar: async () => {}, quadrosDoVideo: v => v.quadros, SEGUNDOS_ESRGAN_POR_SEGUNDO: 10,
    S: { dados: { constantes: { fps: 24 }, editar: { quadros_min: 90, duracao_max: 14, padrao: {} }, comfy: { ligado: true, ocupado: false }, projetos: [] } },
    pedidos: [], respostas: {},
  };
  ctx.postar = async (url, dados) => { ctx.pedidos.push([url, dados]); return ctx.respostas[url]; };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "pagina", "js", "editar.js"), "utf8"), ctx);
  vm.runInContext("atualizarEditar = () => {};", ctx);
  ctx.S.evideo = { arquivo: "v.mp4", quadros: 240, audio: true };
  el("e-duracao").value = "5"; el("e-inicio").value = "0"; el("e-quadro").value = "1"; el("e-pedido").value = "vira tempestade";
  return ctx;
}
const testes = {
  async pintar_de_novo_noutro_quadro_descarta_as_pinturas_antigas(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png", "b.png"], pedido_klein: "x", ia: true, segundos: 60 };
    await c.pintarEditar();
    await c.escolherPintura("a.png");
    c.$("e-quadro").value = "3";
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["c.png", "d.png"], pedido_klein: "x", ia: true, segundos: 60 };
    await c.pintarEditar();
    assert.deepStrictEqual([...c.S.edicao.pinturas], ["c.png", "d.png"]);
    assert.strictEqual(c.S.edicao.escolhida, null);
  },
  async pintar_de_novo_no_mesmo_quadro_guarda_as_antigas(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png", "b.png"], pedido_klein: "x", ia: true, segundos: 60 };
    await c.pintarEditar();
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["c.png", "d.png"], pedido_klein: "x", ia: true, segundos: 60 };
    await c.pintarEditar();
    assert.deepStrictEqual([...c.S.edicao.pinturas], ["c.png", "d.png", "a.png", "b.png"]);
  },
  async roteiro_da_ia_some_quando_o_quadro_ou_a_pintura_muda(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png", "b.png"], pedido_klein: "x", ia: true, segundos: 60 };
    c.respostas["/api/editar-roteiro"] = { roteiro: "ROTEIRO A", ia: true, segundos: 30 };
    await c.pintarEditar();
    await c.escolherPintura("a.png");
    assert.strictEqual(c.$("e-roteiro").value, "ROTEIRO A");
    c.respostas["/api/editar-roteiro"] = { roteiro: "ROTEIRO B", ia: true, segundos: 30 };
    await c.escolherPintura("b.png");
    assert.strictEqual(c.$("e-roteiro").value, "ROTEIRO B");
    c.$("e-duracao").value = "4";
    c.limparRoteiroVelho();
    assert.strictEqual(c.$("e-roteiro").value, "");
  },
  async roteiro_escrito_pelo_usuario_fica(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png"], pedido_klein: "x", ia: true, segundos: 60 };
    await c.pintarEditar();
    c.$("e-roteiro").value = "MEU";
    c.S.roteiroEditado = true;
    await c.escolherPintura("a.png");
    c.$("e-quadro").value = "2";
    c.limparRoteiroVelho();
    assert.strictEqual(c.$("e-roteiro").value, "MEU");
  },
  async pedido_do_klein_da_ia_nao_volta_no_pintar_de_novo(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png"], pedido_klein: "STORM", ia: true, segundos: 60 };
    await c.pintarEditar();
    assert.strictEqual(c.$("e-pedido-klein").value, "STORM");
    c.$("e-pedido").value = "vira neve";
    await c.pintarEditar();
    assert.strictEqual(c.pedidos.filter(p => p[0] === "/api/editar-pintar")[1][1].pedido_klein, null);
  },
  async pedido_do_klein_mudado_pelo_usuario_vai(c) {
    c.respostas["/api/editar-pintar"] = { codigo: "ab12cd34", quadro: "q.png", pinturas: ["a.png"], pedido_klein: "STORM", ia: true, segundos: 60 };
    await c.pintarEditar();
    c.$("e-pedido-klein").value = "MY OWN";
    c.S.kleinEditado = true;
    await c.pintarEditar();
    assert.strictEqual(c.pedidos.filter(p => p[0] === "/api/editar-pintar")[1][1].pedido_klein, "MY OWN");
  },
};
(async () => {
  let falhas = 0;
  for (const [nome, t] of Object.entries(testes)) {
    try { await t(pagina()); console.log(`ok ${nome}`); }
    catch (e) { falhas++; console.log(`FALHOU ${nome}: ${e.message}`); }
  }
  process.exit(falhas ? 1 : 0);
})();
