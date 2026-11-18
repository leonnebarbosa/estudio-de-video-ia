/* Eventos */
// Arquivo solto fora de uma área de envio (ou numa tela travada) não abre no lugar da página
for (const tipo of ["dragover", "drop"]) document.addEventListener(tipo, e => e.preventDefault());
for (const tipo of ["video", "foto", "tvideo", "tfoto", "tfundo", "ifoto", "t2ifoto", "t2iref", "tfbase", "tfrosto", "tfroupa", "pfoto", "ptres", "pperfil", "pcostas", "pvideo"]) {
  $(tipo).addEventListener("change", e => e.target.files[0] && escolher(e.target.files[0], tipo));
  const zona = $(`zona-${tipo}`);
  zona.addEventListener("dragover", e => { e.preventDefault(); zona.classList.add("sobre"); });
  zona.addEventListener("dragleave", () => zona.classList.remove("sobre"));
  zona.addEventListener("drop", e => { e.preventDefault(); zona.classList.remove("sobre"); e.dataTransfer.files[0] && escolher(e.dataTransfer.files[0], tipo); });
}
$("tirar-foto").addEventListener("click", () => { S.foto = null; $("foto").value = ""; limparZona("foto"); atualizar(); });
$("tirar-tfundo").addEventListener("click", () => { S.tfundo = null; $("tfundo").value = ""; limparZona("tfundo"); atualizarTroca(); });
// Escolher na caixa descarta a escolha guardada que esperava as opcoes do ComfyUI
document.addEventListener("change", e => { if (e.target.id) delete S.querido[e.target.id]; }, true);
$("tela-novo").addEventListener("input", atualizar);
$("tela-novo").addEventListener("change", atualizar);
$("projeto").addEventListener("input", () => { S.nomeEditado = true; });
$("passos").addEventListener("input", () => { S.passosEditados = true; });
$("lora").addEventListener("change", () => {
  if (S.passosEditados) return;
  $("passos").value = /8step/i.test($("lora").value) ? 8 : S.dados.padrao.passos;
  atualizar();
});
$("padrao").addEventListener("click", () => { aplicarAjustes({}); if (S.video) aoEscolherVideo(S.video); atualizar(); });
$("tela-novo").addEventListener("submit", e => { e.preventDefault(); iniciar(false); });
$("so-plano").addEventListener("click", () => iniciar(true));
$("ligar").addEventListener("click", async () => {
  try { await postar("/api/ligar-comfy"); } catch (e) { recado(e.message); }
  consultar(true);
});
$("fechar-estudio").addEventListener("click", async () => {
  let confirmar = false;
  for (;;) {
    const r = await fetch("/api/desligar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmar }) });
    if (r.status === 409 && !confirmar) {
      if (!await perguntar("Há uma geração em andamento. Parar e fechar?", "Parar e fechar", "Cancelar")) return;
      confirmar = true;
      continue;
    }
    if (!r.ok) { recado((await r.json().catch(() => ({}))).erro || "Não foi possível fechar."); return; }
    break;
  }
  S.fechado = true;
  document.querySelector(".app").innerHTML = `<div class="fechado"><h1>Estúdio de vídeo</h1><p role="status"><strong>Estúdio fechado.</strong> Pode fechar esta aba.</p></div>`;
});
$("tela-troca").addEventListener("input", atualizarTroca);
$("tela-troca").addEventListener("change", atualizarTroca);
$("tela-troca").addEventListener("submit", e => { e.preventDefault(); iniciarTroca(); });
$("t-projeto").addEventListener("input", () => { S.nomeTrocaEditado = true; });
$("t-passos").addEventListener("input", () => { S.passosTrocaEditados = true; });
$("t-turbo").addEventListener("change", () => {
  if (S.passosTrocaEditados) return;
  $("t-passos").value = /8step/i.test($("t-turbo").value) ? 8 : 6;
  atualizarTroca();
});
$("t-padrao").addEventListener("click", () => { aplicarTroca({}); if (S.tvideo) aoEscolherVideoTroca(S.tvideo); atualizarTroca(); });
// Trocar personagem em foto (trocafoto.js): o seletor Foto/Vídeo aparece nas duas telas da aba
document.addEventListener("click", e => { const b = e.target.closest("[data-modo-troca]"); if (b) trocarModoTroca(b.dataset.modoTroca); });
$("tela-trocafoto").addEventListener("input", atualizarTrocaFoto);
$("tela-trocafoto").addEventListener("change", atualizarTrocaFoto);
$("tela-trocafoto").addEventListener("submit", e => { e.preventDefault(); iniciarTrocaFoto(); });
$("tf-projeto").addEventListener("input", () => { S.nomeTrocaFotoEditado = true; });
$("tf-tirar-rosto").addEventListener("click", () => { tirarFotoTroca("tfrosto"); atualizarTrocaFoto(); });
$("tf-tirar-roupa").addEventListener("click", () => { tirarFotoTroca("tfroupa"); atualizarTrocaFoto(); });
$("tela-imagem").addEventListener("input", atualizarImagem);
$("tela-imagem").addEventListener("change", atualizarImagem);
$("tela-imagem").addEventListener("submit", e => { e.preventDefault(); iniciarImagem(); });
$("tela-texto").addEventListener("input", atualizarTexto);
$("tela-texto").addEventListener("change", atualizarTexto);
$("tela-texto").addEventListener("submit", e => { e.preventDefault(); iniciarTexto(); });
$("t2i-projeto").addEventListener("input", () => { S.nomeTextoEditado = true; });
$("t2i-passos").addEventListener("input", () => { S.passosTextoEditados = true; });
$("t2i-tirar-partida").addEventListener("click", () => { tirarPartida(); atualizarTexto(); });
$("t2i-tirar-ref").addEventListener("click", () => { tirarReferencia(); atualizarTexto(); });
$("t2i-descrever").addEventListener("click", descreverPartida);
// "Usar como partida": uma imagem gerada volta como ponto de partida da próxima
document.addEventListener("click", e => { const b = e.target.closest("[data-usar-partida]"); if (b) usarComoPartida(b.dataset.projetoImagem, b.dataset.usarPartida); });
$("t2i-modelo").addEventListener("change", () => { desenharLorasTexto(); if (!S.passosTextoEditados) $("t2i-passos").value = modeloTexto().passos; });
for (const k of [1, 2]) $(`t2i-lora-${k}`).addEventListener("change", e => {
  const forca = $(`t2i-forca-${k}`);
  forca.disabled = !e.target.value;
  forca.value = e.target.value ? (FORCA_LORA[e.target.value] ?? 1) : "";
});
$("t2i-padrao").addEventListener("click", () => { const t = lerTexto(); S.passosTextoEditados = false; aplicarTexto({ modelo: t.modelo, prompt: t.prompt, proporcao: t.proporcao, quantidade: t.quantidade, passos: modeloTexto(t.modelo).passos, loras: t.loras }); atualizarTexto(); });
// "Usar no Imagem para vídeo" aparece no palco do texto e nos projetos
document.addEventListener("click", e => { const b = e.target.closest("[data-usar-imagem]"); if (b) usarImagem(b.dataset.projetoImagem, b.dataset.usarImagem); });
/* Usar a semente de uma imagem (no palco ou em Projetos): vai para o Texto para imagem com o número no campo Semente */
document.addEventListener("click", e => {
  const b = e.target.closest("[data-usar-semente]");
  if (!b) return;
  e.preventDefault();
  // Numa troca em foto (palco ou prévia do histórico da tela dela), a semente vai para o campo da troca
  if (b.closest("#tela-trocafoto")) {
    const campo = $("tf-semente");
    campo.value = b.dataset.usarSemente;
    $("tf-ajustes").open = true;
    campo.dispatchEvent(new Event("input", { bubbles: true }));
    recado(`Semente ${b.dataset.usarSemente} no campo Semente. Com as mesmas fotos, a troca se repete. Apague o campo para voltar a variar.`, true);
    return;
  }
  if ((S.abaVisivel || S.aba) !== "texto") irPara("texto");
  const campo = $("t2i-semente");
  campo.value = b.dataset.usarSemente;
  $("t2i-ajustes").open = true;
  campo.dispatchEvent(new Event("input", { bubbles: true }));
  recado(`Semente ${b.dataset.usarSemente} no campo Semente. Com o mesmo texto e modelo, a imagem se repete; mudando um pouco o texto, a composição fica parecida. Apague o campo para voltar a variar.`, true);
});
/* Copiar a semente de uma imagem: a API da área de transferência (127.0.0.1 conta como seguro) e, se falhar, o jeito antigo */
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-copiar-semente]");
  if (!b) return;
  e.preventDefault();
  const s = b.dataset.copiarSemente;
  let ok = false;
  try { await navigator.clipboard.writeText(s); ok = true; } catch {
    const t = Object.assign(document.createElement("textarea"), { value: s });
    document.body.append(t); t.select();
    try { ok = document.execCommand("copy"); } catch {}
    t.remove();
  }
  // Volta ao texto que estava (o número sozinho, embaixo da imagem, ou "Semente N", no histórico)
  b.dataset.textoAntes ??= b.textContent;
  b.textContent = ok ? "Copiada" : "Não deu para copiar";
  b.classList.toggle("copiada", ok);
  clearTimeout(b._volta);
  b._volta = setTimeout(() => { b.textContent = b.dataset.textoAntes; b.classList.remove("copiada"); }, 1500);
});
$("i-projeto").addEventListener("input", () => { S.nomeImagemEditado = true; });
$("i-modelo").addEventListener("change", () => aplicarModeloImagem());
$("i-padrao").addEventListener("click", () => { const t = lerImagem(); aplicarImagem({ modelo: t.modelo, quem: t.quem, voz: t.voz, cena: t.cena }); if (S.ifoto?.largura) ajustarProporcao(S.ifoto, "i-proporcao"); atualizarImagem(); });
$("irefs").addEventListener("change", e => { const f = [...e.target.files]; e.target.value = ""; if (f.length) enviarRefs(f); });
// Arrastar imagens vale no cartão (nenhuma escolhida) e na grade (já com algumas)
for (const zona of [$("zona-irefs"), $("irefs-lista")]) {
  zona.addEventListener("dragover", e => { e.preventDefault(); zona.classList.add("sobre"); });
  zona.addEventListener("dragleave", e => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("sobre"); });
  zona.addEventListener("drop", e => { e.preventDefault(); zona.classList.remove("sobre"); if (e.dataTransfer.files.length) enviarRefs(e.dataTransfer.files); });
}
$("irefs-lista").addEventListener("click", e => {
  const tirar = e.target.closest("[data-tirar-ref]");
  if (tirar) tirarRef(Number(tirar.dataset.tirarRef));
  else if (e.target.closest("[data-mais-ref]")) $("irefs").click();
});
$("i-adicionar").addEventListener("click", () => { desenharTomadas([...lerTomadas($("i-tomadas")), { ...TOMADA_VAZIA }]); atualizarImagem(); });
$("i-tomadas").addEventListener("click", e => {
  const b = e.target.closest("[data-tomada-tirar]");
  if (!b) return;
  const lista = lerTomadas($("i-tomadas"));
  lista.splice([...$("i-tomadas").querySelectorAll("[data-tomada]")].indexOf(b.closest("[data-tomada]")), 1);
  desenharTomadas(lista);
  atualizarImagem();
});
$("aba-explorar").addEventListener("click", () => irPara("explorar"));
$("aba-imagem").addEventListener("click", () => irPara("imagem"));
$("aba-tvideo").addEventListener("click", () => irPara("tvideo"));
$("aba-troca").addEventListener("click", () => irPara("troca"));
$("aba-texto").addEventListener("click", () => irPara("texto"));
$("aba-novo").addEventListener("click", () => irPara("novo"));
$("aba-projetos").addEventListener("click", () => irPara("projetos"));
$("aba-modelos").addEventListener("click", () => irPara("modelos"));
$("aba-personagens").addEventListener("click", () => irPara("personagens"));
$("falta-pacote-baixar").addEventListener("click", async () => {
  try {
    await postar("/api/abrir-instalador");
    recado("O instalador abriu no navegador. Escolha o pacote lá; quando terminar, esta aba já funciona.", true);
  } catch (e) { recado(e.message); }
});
$("recado-fechar").addEventListener("click", () => { $("recado").hidden = true; });

/* Limpar tudo: zera a tela atual de uma vez (mídias, textos, tomadas, ângulos e ajustes). Sem pergunta antes:
   o aviso oferece Desfazer, que devolve o rascunho guardado logo antes de limpar. */
const LIMPEZA = {
  novo: { limpar: limparForm, salvar: salvarRascunho, chave: RASCUNHO, restaurar, atualizar, autorizacao: null },
  troca: { limpar: limparTroca, salvar: salvarRascunhoTroca, chave: RASCUNHO_TROCA, restaurar: restaurarTroca, atualizar: atualizarTroca, autorizacao: "t-autorizacao" },
  trocafoto: { limpar: limparTrocaFoto, salvar: salvarRascunhoTrocaFoto, chave: RASCUNHO_TROCA_FOTO, restaurar: restaurarTrocaFoto, atualizar: atualizarTrocaFoto, autorizacao: "tf-autorizacao" },
  // A mesma tela serve o Texto para video: a chave do rascunho segue o modo (imagem ou texto)
  imagem: { limpar: limparImagem, salvar: salvarRascunhoImagem, get chave() { return chaveRascunhoImagem(); }, restaurar: restaurarImagem, atualizar: atualizarImagem, autorizacao: "i-autorizacao" },
  texto: { limpar: limparTexto, salvar: salvarRascunhoTexto, chave: RASCUNHO_TEXTO, restaurar: restaurarTexto, atualizar: atualizarTexto, autorizacao: null },
};
/* Guarda a tela como está (rascunho e autorização) e devolve o botão Desfazer do aviso, que volta a ela.
   Serve ao Limpar tudo e a carregar as configurações de um item do histórico. */
function pontoDesfazer(aba) {
  const m = LIMPEZA[aba];
  if (!m) return null;
  m.salvar();
  let copia = null;
  try { copia = localStorage.getItem(m.chave); } catch {}
  const autorizou = !!m.autorizacao && $(m.autorizacao).checked, visivel = S.abaVisivel || aba;
  return copia && { rotulo: "Desfazer", fazer: () => {
    if ((S.abaVisivel || S.aba) !== visivel) irPara(visivel);
    // Limpa antes de restaurar: o que foi carregado (uma foto, por exemplo) não fica por baixo
    m.limpar();
    try { localStorage.setItem(m.chave, copia); } catch {}
    m.restaurar();
    if (m.autorizacao) $(m.autorizacao).checked = autorizou;
    m.atualizar();
  } };
}
$("limpar-tudo").addEventListener("click", () => {
  const aba = S.aba, m = LIMPEZA[aba], tela = $(`tela-${aba}`);
  if (!m || tela.classList.contains("travada")) return;
  const desfazer = pontoDesfazer(aba);
  m.limpar();
  // O resultado também sai da tela, sem apagar nada: a prévia do histórico e, no Texto para imagem, a galeria
  const previa = S.previa[aba];
  if (previa) fecharPrevia(aba);
  const galeria = aba === "texto" ? tirarGaleria() : aba === "trocafoto" ? tirarGaleriaTF() : null;
  m.atualizar();
  tela.querySelectorAll(".centro, .lado-corpo").forEach(el => { el.scrollTop = 0; });
  const marca = S.marcaLimpeza = Date.now();
  const voltar = (desfazer || previa || galeria) && { rotulo: "Desfazer", fazer: () => {
    desfazer?.fazer();
    galeria?.();
    if (previa && projetoDe(previa)) mostrarPrevia(aba, previa);
  } };
  recado("Tudo limpo.", true, voltar);
  // O Desfazer fica à mão por alguns segundos; depois o aviso some sozinho
  setTimeout(() => { if (S.marcaLimpeza === marca && !$("recado-acao").hidden) $("recado").hidden = true; }, 12000);
});
$("ocultar").checked = document.documentElement.classList.contains("ocultar");
$("ocultar").addEventListener("change", e => {
  document.documentElement.classList.toggle("ocultar", e.target.checked);
  // Um video oculto nao pode continuar tocando o audio
  if (e.target.checked) document.querySelectorAll("video").forEach(v => v.pause());
  try { localStorage.setItem("continuar_video_ocultar", e.target.checked ? "1" : "0"); } catch {}
});

document.addEventListener("toggle", e => {
  const p = e.target.dataset?.projeto;
  if (p) e.target.open ? S.abertos.add(p) : S.abertos.delete(p);
}, true);

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-acao]");
  if (!b) return;
  const acao = b.dataset.acao;
  const caixa = b.closest("[data-projeto]");
  const projeto = caixa?.dataset.projeto || b.closest("[data-projeto-acao]")?.dataset.projetoAcao;
  try {
    if (acao === "parar") {
      const tipoTarefa = S.dados.tarefa?.tipo;
      if (!await perguntar(tipoTarefa === "troca" || tipoTarefa === "wan" ? "Parar a geração? O que foi feito até agora será perdido." : tipoTarefa === "imagem" ? "Parar a geração? A tomada em andamento será perdida; as prontas ficam guardadas." : "Parar a geração? A rodada em andamento será perdida; as prontas ficam guardadas.")) return;
      b.disabled = true;
      b.textContent = "Parando…";
      await pararComConfirmacao();
    } else if (acao === "dispensar") {
      S.dispensada = S.dados.tarefa.projeto + S.dados.tarefa.codigo;
    } else if (acao === "refazer") {
      S.dispensada = null;
      $("recado").hidden = true;
      await postar("/api/refazer-imagem", { projeto, desde: Number(b.dataset.n), tomadas: lerTomadas(caixa.querySelector("[data-editor]")) });
    } else if (acao === "refazer-janela") {
      // Troca em janelas: refaz desta janela até o fim do plano dela, com outra semente (Refazer uma janela, do Henge)
      S.dispensada = null;
      $("recado").hidden = true;
      await postar("/api/refazer-janela", { projeto, janela: Number(b.dataset.n) });
    } else if (acao === "apagar") {
      const r = await postar("/api/apagar", { projeto });
      const alvo = projetoDe(projeto), imagens = alvo?.tipo === "texto";
      const texto = `Apagar ${projeto} definitivamente? Vão sumir ${r.arquivos} ${r.arquivos === 1 ? "arquivo" : "arquivos"} (${num(r.mb)} MB): a pasta do projeto, com ${imagens ? "todas as imagens" : "todas as versões do vídeo"}, e o que ele gerou no ComfyUI. Não vai para a Lixeira e não dá para desfazer. As imagens e vídeos que você enviou ficam.`;
      if (!await perguntar(texto, "Apagar de vez", "Cancelar")) return;
      b.disabled = true;
      await postar("/api/apagar", { projeto, confirmar: true });
      esquecerNaGaleria(alvo);
      S.abertos.delete(projeto);
      recado(`${projeto} foi apagado.`, true);
    } else if (acao === "acabar") {
      S.dispensada = null;
      $("recado").hidden = true;
      await postar("/api/acabar-imagem", { projeto, acabamento: caixa.querySelector("[data-acabamento]").value });
    } else if (acao === "continuar" && S.dados.projetos.find(x => x.nome === projeto)?.tipo === "imagem") {
      S.dispensada = null;
      $("recado").hidden = true;
      await postar("/api/continuar", { projeto, modo: "gerar" });
    } else if (acao === "continuar" || acao === "juntar") {
      const editor = caixa?.querySelector("[data-editor]");
      if (editor) await postar("/api/plano", { projeto, passos: [...editor.querySelectorAll("[data-passo]")].map(t => t.value) });
      S.dispensada = null;
      $("recado").hidden = true;
      await postar("/api/continuar", { projeto, modo: acao === "juntar" ? "juntar" : "gerar" });
    } else if (acao === "salvar-plano") {
      await postar("/api/plano", { projeto, passos: [...caixa.querySelectorAll("[data-passo]")].map(t => t.value) });
      recado(`Plano de ${projeto} salvo.`, true);
      b.blur();
    } else if (acao === "pasta") {
      await postar("/api/abrir-pasta", { projeto });
      return;
    } else if (acao === "reusar") {
      // Do histórico: a prévia fecha e o aviso ganha Desfazer, que devolve a tela como estava antes de carregar
      const doHistorico = b.hasAttribute("data-historico");
      const desfazer = doHistorico ? pontoDesfazer(S.aba) : null;
      if (doHistorico) fecharPrevia(S.aba);
      const r = await postar("/api/reusar", { projeto });
      if (r.tipo === "imagem") {
        // Primeiro a aba: trocar entre Imagem e Texto para vídeo restaura o rascunho daquele modo
        irPara(r.sem_imagem ? "tvideo" : "imagem");
        limparImagem();
        if (r.foto) preencherArquivo("ifoto", r.foto);
        aplicarImagem(r.config);
        desenharTomadas(r.config.tomadas);
        $("i-projeto").value = nomeLivre(`${projeto}.x`);
        atualizarImagem();
        recado(r.sem_imagem ? `Copiado de ${projeto}: cena, tomadas e ajustes. Mude o que quiser e gere.`
          : `Copiado de ${projeto}: ${r.foto ? "imagem, " : ""}tomadas e ajustes. Mude o que quiser, confirme a autorização e gere.`, true, desfazer);
        scrollTo(0, 0);
        S.marcaAndamento = S.marcaProjetos = "";
        consultar(true);
        return;
      }
      if (r.tipo === "wan") {
        // Projeto da aba Wan, que virou o modelo Wan da aba Imagem para vídeo: o texto vira a primeira tomada
        const c = r.config || {};
        irPara("imagem");
        limparImagem();
        if (r.foto) preencherArquivo("ifoto", r.foto);
        aplicarImagem({ modelo: c.modelo, proporcao: c.proporcao, megapixels: c.megapixels, semente: c.semente, negativo: c.negativo });
        desenharTomadas([{ ...TOMADA_VAZIA, acao: c.prompt || "", duracao: c.duracao || 5 }]);
        $("i-projeto").value = nomeLivre(`${projeto}.x`);
        recado(`Copiado de ${projeto}: ${r.foto ? "imagem, " : ""}texto e ajustes, agora na aba Imagem para vídeo. Confirme a autorização e gere.`, true, desfazer);
        scrollTo(0, 0);
        atualizarImagem();
        return;
      }
      if (r.tipo === "texto" && r.config?.troca_foto) {
        limparTrocaFoto();
        aplicarTrocaFoto(r.config);
        $("tf-projeto").value = nomeLivre(`${projeto}.x`);
        S.nomeTrocaFotoEditado = true;
        trocarModoTroca("foto");
        irPara("troca");
        recado(`Copiado de ${projeto}: as fotos e os ajustes. Mude o que quiser, confirme a autorização e troque.`, true, desfazer);
        scrollTo(0, 0);
        atualizarTrocaFoto();
        return;
      }
      if (r.tipo === "texto") {
        limparTexto();
        aplicarTexto(r.config || {});
        irPara("texto");
        recado(`Copiado de ${projeto}: texto e ajustes. Mude o que quiser e gere.`, true, desfazer);
        scrollTo(0, 0);
        atualizarTexto();
        return;
      }
      if (r.tipo === "troca") {
        limparTroca();
        preencherArquivo("tvideo", r.video);
        avisoAudioTroca(r.video);
        if (r.foto) preencherArquivo("tfoto", { arquivo: r.foto });
        if (r.config) { aplicarTroca(r.config); $("t-duracao").value = r.config.duracao; $("t-inicio").value = r.config.inicio || 0; }
        $("t-projeto").value = nomeLivre(`${projeto}.x`);
        irPara("troca");
        recado(`Copiado de ${projeto}: vídeo, ${r.foto ? "foto " : ""}e ajustes. Mude o que quiser, confirme a autorização e gere.`, true, desfazer);
        scrollTo(0, 0);
        S.marcaAndamento = S.marcaProjetos = "";
        consultar(true);
        return;
      }
      limparForm();
      preencherArquivo("video", r.video);
      if (r.foto) preencherArquivo("foto", { arquivo: r.foto });
      $("ideia").value = r.ideia;
      if (r.config) { aplicarAjustes(r.config); $("duracao").value = r.config.duracao; }
      else if (r.video.duracao >= 30) $("duracao").value = Math.ceil(r.video.duracao) + 10;
      $("projeto").value = nomeLivre(`${projeto}.x`);
      irPara("novo");
      recado(`Copiado de ${projeto}: vídeo, ${r.foto ? "foto, " : ""}ideia${r.config ? " e ajustes" : ""}. Mude o que quiser e gere.`, true, desfazer);
      scrollTo(0, 0);
    }
  } catch (err) {
    recado(err.message, false);
    scrollTo(0, 0);
    return;
  }
  S.marcaAndamento = S.marcaProjetos = "";
  consultar(true);
});

consultar();
setInterval(() => { if (!S.fechado) consultar(); }, 3000);
