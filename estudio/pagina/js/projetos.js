/* Projetos */
function situacao(p, rodando) {
  if (rodando) return "gerando agora";
  if (p.tipo === "troca" || p.tipo === "editar") return p.final ? "pronto" : "sem vídeo final";
  if (p.tipo === "imagem") return p.completo ? "pronto" : `${p.feitas.length} de ${p.total} tomadas`;
  if (p.tipo === "texto") return p.completo ? `pronto, ${p.total} ${p.total === 1 ? "imagem" : "imagens"}` : `${p.imagens.length} de ${p.total} imagens`;
  if (p.completo && p.final) return `pronto, ${p.total} ${p.total === 1 ? "rodada" : "rodadas"}`;
  if (!p.pagina) return `${p.rodadas.length} ${p.rodadas.length === 1 ? "rodada" : "rodadas"}, ${p.final ? "com vídeo final" : "sem vídeo final"}`;
  if (!p.rodadas.length) return p.passos.length ? "plano pronto para revisar" : "ainda sem plano";
  return `${p.rodadas.length} de ${p.total} rodadas`;
}
function quando(segundos) {
  const d = new Date(segundos * 1000), hoje = new Date();
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === hoje.toDateString() ? `hoje, ${hora}` : `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}, ${hora}`;
}
// Fica por ultimo e com cara de perigo; o servidor confere de novo e recusa o projeto que esta gerando
const botaoApagar = rodando => rodando ? "" : `<button type="button" class="simples perigo" data-acao="apagar">Apagar</button>`;
function desenharTroca(p, rodando, livre) {
  const nome = encodeURIComponent(p.nome);
  const q = p.foto_existe ? midia(`<img loading="lazy" src="/entrada/foto/${encodeURIComponent(p.personagem)}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>Troca de personagem, ${esc(quando(p.quando))}</small></span><span class="situacao">${esc(situacao(p, rodando))}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>Troca de personagem, ${esc(quando(p.quando))} · ${esc(situacao(p, rodando))}</small></h2>`;
  if (p.final) h += midia(`<video controls preload="none" src="/video/${nome}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto");
  const botoes = [];
  if (p.pagina && !p.completo && !rodando) botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>Tentar de novo</button>`);
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`, `<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (p.comparativo) h += `<details><summary><strong>Ver o comparativo lado a lado</strong></summary>${midia(`<video controls preload="none" src="/video/${nome}/comparativo.mp4?m=${p.comparativo.marca}"></video>`, "Vídeo oculto")}</details>`;
  // Troca em janelas: cada janela pode ser refeita com outra semente; as do mesmo plano depois dela vão junto
  if (p.janelas?.length > 1 && p.completo) {
    const linhas = p.janelas.map(j => `<li class="janela-item"><span><strong>Janela ${j.i}</strong> <small>${num(j.de, 1)} a ${num(j.ate, 1)} s${j.corte ? ", depois de um corte de câmera" : ""}</small></span>${rodando ? "" : `<button type="button" class="botao" data-acao="refazer-janela" data-n="${j.i}" ${livre ? "" : "disabled"}>${j.i === 1 ? "Refazer tudo" : "Refazer daqui"}</button>`}</li>`).join("");
    h += `<details class="janelas-troca"><summary><strong>Refazer uma janela</strong> <small>(${p.janelas.length} janelas)</small></summary><p class="legenda">Refaz a janela com outra semente, e as seguintes do mesmo plano, porque emendam nela. As outras ficam como estão. O vídeo de antes fica como antes_de_refazer.mp4 na pasta.</p><ul class="lista-janelas">${linhas}</ul></details>`;
  }
  if (p.config) h += `<p class="legenda">${esc(resumoTroca({ ...S.dados.troca.padrao, ...p.config }))}</p>`;
  if (p.resultado) h += `<p class="legenda">Levou ${tempo(p.resultado.segundos)}, pico de ${num(p.resultado.pico_vram / 1024)} GB de memória e ${p.resultado.temp_max} °C. Semente ${p.resultado.semente}.</p>`;
  if (p.referencia) h += `<details><summary><strong>Ver a referência usada</strong> <small>(a pessoa da foto com a roupa do vídeo)</small></summary>${midia(`<img class="ref-troca" loading="lazy" src="/entrada/foto/${encodeURIComponent(p.referencia)}" alt="Referência montada para a troca">`, "Imagem oculta")}</details>`;
  if (p.prompt) h += `<details><summary><strong>O que a LLM escreveu sobre a personagem</strong></summary><p class="legenda">${esc(p.prompt)}</p></details>`;
  return h + `</div></details>`;
}
/* Editar vídeo (editar_video.py): o cartão da troca, com a pintura usada, o pedido e o roteiro */
function desenharEditar(p, rodando, livre) {
  const nome = encodeURIComponent(p.nome);
  const pintura = p.pintura ? `/editar/${nome}/pintado.png?m=${Math.round(p.quando)}` : "";
  const q = pintura ? midia(`<img loading="lazy" src="${pintura}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  const sub = `Edição de vídeo, ${esc(quando(p.quando))}`;
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>${sub}</small></span><span class="situacao">${esc(situacao(p, rodando))}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>${sub} · ${esc(situacao(p, rodando))}</small></h2>`;
  if (p.ideia) h += `<p class="legenda">Pedido: ${esc(p.ideia)}</p>`;
  if (p.final) h += midia(`<video controls preload="none" src="/video/${nome}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto");
  const botoes = [];
  if (p.pagina && !p.completo && !rodando) botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>Tentar de novo</button>`);
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`, `<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (p.comparativo) h += `<details><summary><strong>Ver o comparativo lado a lado</strong> <small>(original | editado)</small></summary>${midia(`<video controls preload="none" src="/video/${nome}/comparativo.mp4?m=${p.comparativo.marca}"></video>`, "Vídeo oculto")}</details>`;
  if (pintura) h += `<details><summary><strong>Ver a pintura usada</strong></summary>${midia(`<img class="ref-troca" loading="lazy" src="${pintura}" alt="Quadro pintado que o vídeo seguiu">`, "Imagem oculta")}</details>`;
  if (p.config) h += `<p class="legenda">${p.config.qualidade === "melhor" ? "Qualidade melhor (0,5 MP)" : "Qualidade rápida (0,4 MP)"}, ${num(p.config.duracao, p.config.duracao % 1 ? 1 : 0)} s${p.config.inicio ? ` a partir de ${num(p.config.inicio, 1)} s` : ""}${p.config.esrgan ? ", ampliado com ESRGAN" : ""}.</p>`;
  if (p.resultado) h += `<p class="legenda">Levou ${tempo(p.resultado.segundos)}, pico de ${num(p.resultado.pico_vram / 1024)} GB de memória e ${p.resultado.temp_max} °C. Semente ${p.resultado.semente}.</p>`;
  if (p.prompt) h += `<details><summary><strong>O roteiro que o Viggle leu</strong></summary><p class="legenda pre">${esc(p.prompt)}</p></details>`;
  return h + `</div></details>`;
}
function desenharImagem(p, rodando, livre) {
  const nome = encodeURIComponent(p.nome);
  const avancado = !!p.config?.avancado, rotulo = avancado ? "Vídeo avançado" : "Imagem para vídeo";
  const q = p.foto_existe ? midia(`<img loading="lazy" src="/entrada/foto/${encodeURIComponent(p.personagem)}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>${rotulo}, ${esc(quando(p.quando))}</small></span><span class="situacao">${esc(situacao(p, rodando))}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>${rotulo}, ${esc(quando(p.quando))} · ${esc(situacao(p, rodando))}</small></h2>`;
  if (p.final) {
    h += midia(`<video controls preload="none" src="/video/${nome}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto");
    if (!p.completo) h += `<p class="legenda">Este vídeo só tem as tomadas que já estão prontas.</p>`;
  }
  if (p.hd) {
    const como = { esrgan: "ESRGAN", refino: "refino do H3 + ESRGAN" }[p.hd.acabamento?.modo] || "acabamento";
    h += `<details><summary><strong>Ver a versão em Full HD</strong> <small>(${esc(como)})</small></summary>${midia(`<video controls preload="none" src="/video/${nome}/final_hd.mp4?m=${p.hd.marca}"></video>`, "Vídeo oculto")}</details>`;
  }
  const botoes = [];
  if (p.pagina && !p.completo && !rodando) botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>${p.feitas.length ? "Continuar geração" : "Gerar vídeo"}</button>`);
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`, `<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (p.pagina && p.completo && p.final && !rodando) {
    const podeRefino = (p.config?.megapixels || 0) <= S.dados.imagem.max_mp_refino;
    const opcoes = (avancado ? ["esrgan"] : ["esrgan", "refino"]).filter(x => modeloImagem(p.config?.modelo || "h3").acabamentos.includes(x)).map(x => `<option value="${x}" ${x === "refino" && !podeRefino ? "disabled" : ""}>${esc(NOMES_ACABAMENTO[x])}</option>`).join("");
    h += `<div class="botoes" style="margin-top:10px"><label class="campo" style="margin:0"><span class="rotulo">Ampliar este vídeo</span><select data-acabamento>${opcoes}</select></label>`
       + `<button type="button" data-acao="acabar" ${S.dados.tarefa?.rodando ? "disabled" : ""}>${p.hd ? "Ampliar de novo" : "Ampliar"}</button></div>`;
  }
  if (p.feitas.length) {
    const seg = p.feitas.reduce((s, r) => s + (r.segundos || 0), 0), pico = Math.max(...p.feitas.map(r => r.pico_vram || 0)), temp = Math.max(...p.feitas.map(r => r.temp_max || 0));
    h += `<p class="legenda">Levou ${tempo(seg)} de geração, pico de ${num(pico / 1024)} GB de memória e ${temp} °C.</p>`;
  }
  if (p.config) h += `<p class="legenda">${esc(modeloImagem(p.config.modelo || "h3").nome)}${p.config.modelo && p.config.modelo !== "h3" ? `, sem som${p.fps_final === 32 ? ", 32 quadros/s (RIFE)" : ""}` : ""}${p.config.primeira ? `; tomada 1 com o ${esc(nomeRef2va(p.config.primeira))}` : ""}${p.config.seguintes ? `; tomadas 2 em diante com o ${esc(nomeRef2va(p.config.seguintes))}` : ""}${p.config.loras?.length ? `; LoRA ${esc(p.config.loras.map(([n, f]) => `${semExt(n)} ${num(f, 2)}`).join(", "))}` : ""}.</p>`;
  const prompts = p.feitas.filter(r => r.prompt);
  if (prompts.length) h += `<details><summary><strong>Prompt enviado ao modelo</strong></summary>`
    + prompts.map(r => `<p class="legenda"><b>Tomada ${r.n}</b>${r.semente != null ? `, semente ${r.semente}` : ""}</p><pre class="prompt-enviado">${esc(r.prompt)}</pre>`).join("") + `</details>`;
  if (p.config?.referencias?.length) h += `<p class="legenda">Usou ${p.config.referencias.length} ${p.config.referencias.length === 1 ? "imagem extra" : "imagens extras"} do personagem.</p>`;
  if (!avancado && p.config?.tomadas?.length) {
    h += `<details data-editor-caixa><summary><strong>Editar e refazer tomadas</strong></summary><p class="legenda">Refazer uma tomada também refaz as seguintes, porque cada uma parte do fim da anterior. A versão atual fica guardada como final_anterior.mp4.</p><div data-editor>`;
    p.config.tomadas.forEach((t, i) => {
      const feita = i < p.feitas.length;
      const mp = modeloImagem(p.config.modelo || "h3");
      // So as duracoes que valem na resolucao do projeto (no H3, 10 s ate 0,8 MP e so na tomada 1)
      h += htmlTomada(t, i, duracoesTomada(mp, Number(p.config.megapixels) || 0.4746, i), mp.fala).replace(`<button type="button" class="simples" data-tomada-tirar>Remover</button>`, !rodando ? `<button type="button" data-acao="refazer" data-n="${i + 1}" ${livre ? "" : "disabled"}>${feita ? "Refazer daqui em diante" : "Gerar daqui em diante"}</button>` : "");
    });
    h += `</div></details>`;
  }
  return h + `</div></details>`;
}
function desenharTexto(p, rodando, livre) {
  const nome = encodeURIComponent(p.nome), primeira = p.imagens[0];
  const q = primeira ? midia(`<img loading="lazy" src="/imagem/${nome}/${primeira.arquivo}?m=${primeira.marca}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>Texto para imagem, ${esc(quando(p.quando))}</small></span><span class="situacao">${esc(situacao(p, rodando))}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>Texto para imagem, ${esc(quando(p.quando))} · ${esc(situacao(p, rodando))}</small></h2>`;
  if (p.imagens.length) {
    h += `<div class="t2i-galeria" data-n="${p.imagens.length}">` + p.imagens.map(i => {
      const src = `/imagem/${nome}/${i.arquivo}?m=${i.marca}`;
      return `<figure class="t2i-item">${midia(`<img loading="lazy" src="${src}" alt="Imagem ${i.n}">`, "Imagem oculta")}${botoesImagem(p, i, src)}</figure>`;
    }).join("") + `</div>`;
  }
  const botoes = [];
  if (p.pagina && !p.completo && !rodando) botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>${p.imagens.length ? "Gerar as que faltam" : "Gerar imagens"}</button>`);
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`, `<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (p.config?.prompt) h += `<p class="legenda">${esc(p.config.prompt)}</p>`;
  if (p.imagens.length) h += `<p class="legenda">Sementes: ${p.imagens.map(i => i.semente).join(", ")}. ${p.config ? `${resolucao(p.config)}, ${p.config.passos} passos.` : ""}</p>`;
  if (p.config) {
    const mt = (S.dados.texto.modelos || []).find(m => m.id === (p.config.modelo || "chroma_flash"));
    const loras = (p.config.loras || []).map(([n, f]) => `${semExt(n)} ${num(f, 2)}`).join(", ");
    const partida = mt?.edicao ? ` · editando uma imagem${p.config.referencia ? ", com uma segunda de referência" : ""}`
      : p.config.partida ? ` · a partir de uma imagem, força ${num(p.config.forca_partida, 2)}` : "";
    h += `<p class="legenda">${esc(mt?.nome || p.config.modelo || "Chroma1-HD-Flash")}${loras ? ` · LoRA ${esc(loras)}` : ""}${partida}.</p>`;
  }
  return h + `</div></details>`;
}
function desenharProjeto(p, rodando, livre) {
  if (p.tipo === "troca") return desenharTroca(p, rodando, livre);
  if (p.tipo === "editar") return desenharEditar(p, rodando, livre);
  if (p.tipo === "imagem") return desenharImagem(p, rodando, livre);
  if (p.tipo === "texto") return desenharTexto(p, rodando, livre);
  if (p.tipo === "wan") return desenharWan(p, rodando, livre);
  const q = p.tem_quadro ? midia(`<img loading="lazy" src="/quadro/${encodeURIComponent(p.nome)}?r=${p.rodadas.length}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>${esc(quando(p.quando))}</small></span><span class="situacao">${esc(situacao(p, rodando))}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>Continuação de vídeo, ${esc(quando(p.quando))} · ${esc(situacao(p, rodando))}</small></h2>`;
  if (p.final) {
    // So carrega ao tocar, para uma lista grande nao ocupar as conexoes do navegador
    h += midia(`<video controls preload="none" ${p.tem_quadro ? `poster="/quadro/${encodeURIComponent(p.nome)}?r=${p.rodadas.length}"` : ""} src="/video/${encodeURIComponent(p.nome)}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto");
    if (!p.completo) h += `<p class="legenda">Este vídeo só tem as rodadas que estavam prontas quando foi montado.</p>`;
  }
  const botoes = [];
  // Antes da primeira rodada, o botao de gerar fica no fim do plano, depois da revisao
  const revisando = p.pagina && !p.rodadas.length && !rodando && p.passos.length > 0;
  if (p.pagina && !p.completo && !rodando && !revisando) {
    botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>${p.rodadas.length ? "Continuar geração" : "Gerar vídeo"}</button>`);
    if (p.rodadas.length) botoes.push(`<button type="button" data-acao="juntar" ${S.dados.tarefa?.rodando ? "disabled" : ""}>Juntar rodadas prontas</button>`);
  }
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`);
  botoes.push(`<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (!p.pagina && !p.final) h += `<p class="legenda">Feito fora da página. Para continuar este, use o comando do script.</p>`;
  if (p.total) h += `<div class="linha-tempo"><div class="fita">${fita(p.quadros_origem, p.rodadas.length, p.total, false)}</div>${p.config ? `<div class="eixo eixo-real" aria-hidden="true">${eixoReal([[0, p.quadros_origem], [p.quadros_origem / S.dados.constantes.fps, p.total * S.dados.constantes.novos]], p.config.duracao)}</div>` : ""}</div>`;
  if (p.ideia) h += `<p><strong>Ideia:</strong> ${esc(p.ideia)}</p>`;
  if (p.config) h += `<p class="legenda">${esc(resumoAjustes({ ...S.dados.padrao, ...p.config }))}. Duração final: ${num(p.config.duracao)} s.</p>`;
  if (p.passos.length) {
    if (revisando) {
      h += `<div class="editor" data-editor><strong>Plano da LLM</strong><p class="legenda">Corrija o que quiser antes de gerar. Escreva em inglês, uma ação simples por passo.</p>`;
      p.passos.forEach((b, i) => { h += `<label>Passo ${i + 1}<textarea data-passo>${esc(b)}</textarea></label>`; });
      h += `<div class="botoes" style="margin-top:10px"><button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>Gerar vídeo com este plano</button><button type="button" data-acao="salvar-plano">Salvar plano</button></div></div>`;
    } else {
      h += `<div><strong>Plano da LLM</strong><ol class="passos">${p.passos.map(b => `<li>${esc(b)}</li>`).join("")}</ol></div>`;
    }
  }
  if (p.rodadas.length) {
    h += `<details><summary><strong>O que cada rodada pediu e o que a LLM viu</strong></summary>`;
    for (const r of p.rodadas) h += `<div class="rodada"><b>Rodada ${r.n}</b>${r.aprovada === false ? ` <span class="repro">(nenhuma tentativa foi aprovada)</span>` : ""}<br>Pediu: ${esc(r.pediu)}${r.viu ? `<br>Viu: ${esc(r.viu)}` : ""}</div>`;
    h += `</details><p class="legenda">A análise da LLM ainda erra às vezes. Confira no vídeo.</p>`;
  }
  return h + `</div></details>`;
}
/* Galeria (reforma de 20/11/2026): cada projeto ganha uma capa grande, com o vídeo final ou a primeira imagem. Na lista
   ela fica escondida e não carrega nada (observarCapas só busca o vídeo quando a capa aparece). */
function comCapa(p, html) {
  const m = midiaExplorar(p);
  const capa = m ? `<span class="capa">${m}</span>` : `<span class="capa capa-vazia"><svg class="ico" aria-hidden="true"><use href="#s-filme"/></svg></span>`;
  return html.replace("<summary>", `<summary>${capa}`);
}
/* O vídeo do projeto aberto vinha com preload="none": um quadro preto, sem o formato do vídeo, até dar play.
   Abriu, ele busca o começo e mostra o primeiro quadro (o #t=0.1 faz o navegador desenhar esse quadro). */
function carregarVideosAbertos() {
  for (const v of document.querySelectorAll("#projetos .projeto[open] > .corpo > .midia > video")) {
    if (v.preload !== "none") continue;
    v.preload = "metadata";
    const src = v.getAttribute("src") || "";
    if (src && !src.includes("#")) v.src = `${src}#t=0.1`; else v.load();
  }
}
/* Galeria ou lista, como nas outras plataformas; fica guardado */
const MODO_PROJETOS = "estudio_modo_projetos";
S.modoProjetos = (() => { try { return localStorage.getItem(MODO_PROJETOS) === "lista" ? "lista" : "galeria"; } catch { return "galeria"; } })();
function aplicarModoProjetos() {
  const galeria = S.modoProjetos === "galeria";
  $("tela-projetos").querySelector(".biblioteca").classList.toggle("modo-galeria", galeria);
  document.querySelectorAll("[data-modo-projetos]").forEach(b => b.setAttribute("aria-pressed", b.dataset.modoProjetos === S.modoProjetos));
  if (galeria) observarCapas($("projetos"));
}
function fecharProjetoAberto() {
  document.querySelectorAll("#projetos .projeto[open]").forEach(d => { d.open = false; });
}
function desenharProjetos(d) {
  const t = d.tarefa, ocupada = !!t?.rodando;
  const livre = d.comfy.ligado && !d.comfy.ocupado && !ocupada;
  $("projetos-conta").textContent = d.projetos.length || "";
  if (document.activeElement?.closest?.("[data-editor]")) return;
  const marca = JSON.stringify([d.projetos.map(p => [p.nome, p.rodadas.length, p.total, p.passos, p.final?.marca, p.feitas?.length, p.hd?.marca, p.imagens?.length]), ocupada && t.projeto, livre]);
  if (marca !== S.marcaProjetos) {
    S.marcaProjetos = marca;
    // Um projeto aberto por vez (ele vai para o palco): fica o ultimo que foi aberto, como o recem-pronto
    if (S.abertos.size > 1) S.abertos = new Set([[...S.abertos].pop()]);
    $("projetos").innerHTML = d.projetos.length ? d.projetos.map(p => comCapa(p, desenharProjeto(p, ocupada && t.projeto === p.nome, livre))).join("") : `<p class="vazio-lista">Nenhum projeto ainda. Os vídeos que você gerar aparecem aqui.</p>`;
  }
  aplicarModoProjetos();
  carregarVideosAbertos();
  desenharSelecao();
  if (S.recem) {
    document.querySelector(`[data-projeto="${CSS.escape(S.recem)}"] > summary`)?.classList.add("recem");
    S.recem = null;
  }
  if (S.rolar) {
    document.querySelector(`[data-projeto="${CSS.escape(S.rolar)}"]`)?.scrollIntoView({ block: "nearest" });
    S.rolar = null;
  }
}
/* Selecionar varios projetos para apagar de uma vez. Marcar troca o abrir; o que esta gerando nao pode ser marcado. */
S.selecionando = false;
S.marcados = new Set();
const projetoGerando = () => S.dados?.tarefa?.rodando ? S.dados.tarefa.projeto : null;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
function desenharSelecao() {
  const lista = S.dados?.projetos || [], gerando = projetoGerando();
  // Sai da selecao o que foi apagado ou começou a gerar
  for (const n of S.marcados) if (n === gerando || !lista.some(p => p.nome === n)) S.marcados.delete(n);
  if (!lista.length) S.selecionando = false;
  $("projetos-barra").hidden = !lista.length;
  $("tela-projetos").querySelector(".biblioteca").classList.toggle("selecionando", S.selecionando);
  for (const el of document.querySelectorAll("#projetos .projeto")) {
    const n = el.dataset.projeto, marcado = S.selecionando && S.marcados.has(n), s = el.querySelector(":scope > summary");
    el.classList.toggle("marcado", marcado);
    el.classList.toggle("bloqueado", S.selecionando && n === gerando);
    if (S.selecionando) s.setAttribute("aria-pressed", marcado); else s.removeAttribute("aria-pressed");
  }
  const k = S.marcados.size, podem = lista.filter(p => p.nome !== gerando).length;
  $("sel-conta").textContent = !S.selecionando ? plural(lista.length, "projeto", "projetos") : k ? plural(k, "marcado", "marcados") : "Clique nos projetos para marcar";
  $("sel-todos").hidden = !S.selecionando || !podem;
  $("sel-todos").textContent = k && k >= podem ? "Desmarcar todos" : "Marcar todos";
  $("sel-apagar").hidden = !S.selecionando;
  $("sel-apagar").disabled = !k;
  $("sel-apagar").textContent = k ? `Apagar ${k}` : "Apagar";
  $("sel-alternar").textContent = S.selecionando ? "Cancelar" : "Selecionar";
}
function sairSelecao() { S.selecionando = false; S.marcados.clear(); desenharSelecao(); }
$("tela-projetos").addEventListener("click", e => {
  const b = e.target.closest("[data-modo-projetos]");
  if (!b) return;
  S.modoProjetos = b.dataset.modoProjetos;
  try { localStorage.setItem(MODO_PROJETOS, S.modoProjetos); } catch {}
  aplicarModoProjetos();
});
$("fechar-projeto").addEventListener("click", fecharProjetoAberto);
/* Na galeria, a capa toca o vídeo com o mouse em cima, como na tela inicial */
for (const [tipo, tocar] of [["pointerover", true], ["pointerout", false]]) {
  $("projetos").addEventListener(tipo, e => {
    const capa = e.target.closest(".modo-galeria .capa"), v = capa?.querySelector("video");
    if (!v || (e.relatedTarget && capa.contains(e.relatedTarget))) return;
    if (tocar) v.play().catch(() => {}); else v.pause();
  });
}
$("sel-alternar").addEventListener("click", () => { if (S.selecionando) sairSelecao(); else { S.selecionando = true; desenharSelecao(); } });
$("sel-todos").addEventListener("click", () => {
  const gerando = projetoGerando(), podem = S.dados.projetos.filter(p => p.nome !== gerando).map(p => p.nome);
  S.marcados = S.marcados.size >= podem.length ? new Set() : new Set(podem);
  desenharSelecao();
});
$("projetos").addEventListener("click", e => {
  if (!S.selecionando) return;
  const s = e.target.closest(".projeto > summary");
  if (!s) return;
  e.preventDefault();
  const n = s.parentElement.dataset.projeto;
  if (n === projetoGerando()) return;
  S.marcados.has(n) ? S.marcados.delete(n) : S.marcados.add(n);
  desenharSelecao();
});
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || S.aba !== "projetos" || document.querySelector("dialog[open]")) return;
  if (S.selecionando) sairSelecao();
  // Na galeria, Esc fecha o projeto aberto e volta para as capas
  else if (S.modoProjetos === "galeria" && document.querySelector("#projetos .projeto[open]") && !e.target.closest?.("input, textarea, select")) fecharProjetoAberto();
});
$("sel-apagar").addEventListener("click", async () => {
  const nomes = [...S.marcados], k = nomes.length, b = $("sel-apagar");
  if (!k) return;
  try {
    const r = await postar("/api/apagar-varios", { projetos: nomes });
    const quais = k <= 6 ? nomes.join(", ") : `${nomes.slice(0, 5).join(", ")} e mais ${k - 5}`;
    const texto = `Apagar ${plural(k, "projeto", "projetos")} definitivamente (${quais})? Vão sumir ${plural(r.arquivos, "arquivo", "arquivos")} (${num(r.mb)} MB): `
      + `${k === 1 ? "a pasta do projeto, com todas as versões, e o que ele gerou" : "as pastas dos projetos, com todas as versões, e o que eles geraram"} no ComfyUI. `
      + "Não vai para a Lixeira e não dá para desfazer. As imagens e vídeos que você enviou ficam.";
    if (!await perguntar(texto, `Apagar ${k} de vez`, "Cancelar")) return;
    b.disabled = true;
    await postar("/api/apagar-varios", { projetos: nomes, confirmar: true });
    nomes.forEach(n => S.abertos.delete(n));
    S.selecionando = false;
    S.marcados.clear();
    recado(k === 1 ? `${nomes[0]} foi apagado.` : `${k} projetos foram apagados.`, true);
  } catch (err) {
    recado(err.message, false);
  }
  desenharSelecao();
  consultar(true);
});

function desenharSistema(d) {
  const c = d.comfy;
  // Sem o nome "ComfyUI" na frente: para o usuário é o motor que gera (o nome técnico fica na dica ao passar o mouse)
  const textos = { ligando: "Preparando para gerar, leva até um minuto", religando: "Reiniciando o motor de geração", caiu: "O motor de geração parou", desligado: "Motor de geração desligado" };
  $("luz").textContent = c.ligado ? (c.ocupado ? "Gerando" : "Pronto para gerar") : (textos[c.situacao] || "Motor de geração desligado");
  $("luz").title = "Motor de geração: o ComfyUI, que roda neste computador";
  $("luz").classList.toggle("ligado", c.ligado);
  $("luz").dataset.situacao = c.ligado ? (c.ocupado ? "ocupado" : "pronto") : (c.situacao || "desligado");
  $("aviso-comfy").textContent = c.situacao === "caiu" ? c.mensagem : "";
  $("aviso-comfy").hidden = c.situacao !== "caiu";
  $("ligar").hidden = c.situacao !== "caiu";
  desenharRecursos(d.recursos);
}

let primeira = true;
let consultando = false;
async function consultar(forcar) {
  if (S.fechado || (consultando && forcar !== true)) return;
  consultando = true;
  try {
    const d = await (await fetch("/api/estado")).json();
    S.dados = d;
    aplicarExtras(d.extras);
    // Quando as opcoes do ComfyUI chegam, preencherOpcoes/preencherTroca refazem as listas mantendo as escolhas (S.querido)
    S.opcoesProntas = !!d.opcoes.samplers?.length;
    preencherOpcoes(d);
    preencherTroca(d);
    preencherImagem(d);
    preencherAvancado(d);
    preencherTexto(d);
    preencherTrocaFoto(d);
    preencherEditar(d);
    if (primeira) { primeira = false; restaurar(); restaurarTroca(); restaurarTrocaFoto(); restaurarImagem(); restaurarAvancado(); restaurarTexto(); restaurarEditar(); escolherAbaInicial(d); }
    desenharFaltaPacote();
    desenharSistema(d);
    desenharAndamento(d);
    desenharFila(d);
    desenharProjetos(d);
    desenharHistoricos(d);
    desenharExplorar();
    if (!$("tela-personagens").hidden) { desenharPersonagens(); atualizarPersonagemNovo(); }
    // Ângulos acabaram de ficar prontos: a lista muda
    if (S.persRodando && !d.tarefa?.rodando) carregarPersonagens();
    S.persRodando = d.tarefa?.rodando && d.tarefa.tipo === "personagem";
    atualizar();
  } catch {
    if (S.fechado) return;
    $("luz").textContent = "O estúdio foi fechado ou parou. Abra o atalho Estúdio de vídeo de novo.";
    $("luz").classList.remove("ligado");
    $("luz").dataset.situacao = "fora";
    $("ligar").hidden = true;
  } finally {
    consultando = false;
  }
}
function restaurar() {
  const r = lerRascunho();
  if (!r) return;
  $("ideia").value = r.ideia || "";
  if (r.duracao) $("duracao").value = r.duracao;
  if (r.ajustes) aplicarAjustes(r.ajustes);
  if (r.projeto) { $("projeto").value = r.projeto; S.nomeEditado = true; }
  if (r.video) preencherArquivo("video", r.video);
  if (r.foto) preencherArquivo("foto", r.foto);
}
function preencherArquivo(tipo, info) {
  limparZona(tipo);
  S[tipo] = info;
  mostrarEscolhido(tipo, info, info.arquivo, `/entrada/${BASE(tipo)}/${encodeURIComponent(info.arquivo)}`);
  if (tipo === "video") { avisoVideo(info); if (!S.nomeEditado) $("projeto").value = nomeLivre(info.arquivo); }
}
