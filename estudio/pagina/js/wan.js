/* Projetos da antiga aba Imagem para vídeo (Wan), de 09/11/2026: o cartão na Biblioteca e o andamento de um "Tentar de novo".
   Os vídeos novos com o Wan saem pela aba Imagem para vídeo, escolhendo o modelo. tamanhoWan também serve a ela. */
const NOMES_MODELO_WAN = { wan22: "Wan 2.2 GGUF + lightx2v" };
const quadrosWan = s => Math.round(s * 16 / 4) * 4 + 1;
function tamanhoWan(a) {
  const m = a.proporcao.match(/^(\d+):(\d+)/);
  if (!m) return "";
  const e = Math.sqrt(a.megapixels * 1024 * 1024 / (m[1] * m[2]));
  return `${Math.round(m[1] * e / 16) * 16}×${Math.round(m[2] * e / 16) * 16}`;
}

/* Andamento: ler os modelos, 4 passos (2 no High, 2 no Low), decodificar e salvar */
function mensagemFimWan(t) {
  if (t.parada) return "Geração parada. Para gerar de novo, clique em Tentar de novo.";
  if (t.codigo === 3) return "O ComfyUI parou no meio da geração. Quando ele voltar (veja o topo da página), clique em Tentar de novo.";
  if (t.codigo === 5) return `Parou porque a placa chegou a ${t.temp_limite || 90} °C. Espere esfriar e clique em Tentar de novo.`;
  const falha = [...(t.registro || "").matchAll(/^FALHA ([^\n]*)/gm)].pop();
  if (t.codigo === 4) return falha ? `Falha ${falha[1]}` : "A geração falhou. O motivo está no registro técnico.";
  const ultima = (t.registro || "").trim().split("\n").pop();
  return `O script parou com um erro: ${ultima || "sem mensagem"}`;
}
function desenharAndamentoWan(t, p) {
  const caixa = $("andamento");
  const mostrar = t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo);
  if (!mostrar) { caixa.hidden = true; document.title = TITULO; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  const pr = t.progresso || { valor: 0, maximo: 4 };
  // Ler os 29 GB do disco pode levar um minuto; a amostragem é quase todo o resto
  const amostrando = pr.fase === "amostrar";
  let fracao = amostrando ? .15 + .75 * (pr.valor || 0) / (pr.maximo || 4) : pr.fase === "decodificar" ? .92 : pr.fase === "salvar" ? .97 : Math.min(.15, t.segundos / 90 * .15);
  if (S.picoWan?.projeto === t.projeto) fracao = Math.max(fracao, S.picoWan.fracao);
  S.picoWan = t.rodando ? { projeto: t.projeto, fracao } : null;
  const pct = Math.min(99, Math.floor(fracao * 100));
  S.relogio = t.rodando ? { total: t.segundos, etapa: t.segundos, quando: Date.now() } : null;
  const nome = amostrando ? `Gerando: passo ${Math.min(4, (pr.valor || 0) + 1)} de 4 (${pr.metade === "baixa" ? "modelo Low, detalhes" : "modelo High, movimento"})`
             : pr.fase === "decodificar" ? "Transformando em imagens" : pr.fase === "salvar" ? "Salvando o vídeo" : pr.fase ? (pr.fase_nome || "Preparando") : "Preparando";
  document.title = t.rodando ? `${pct}%, ${nome} – ${TITULO}` : TITULO;
  const marca = JSON.stringify([t.rodando, pr.valor, pr.fase, pr.metade, t.codigo, t.registro]);
  if (marca === S.marcaAndamento) {
    if ($("pct")) $("pct").textContent = `${pct}%`;
    if ($("fita-atual")) $("fita-atual").style.width = `${pct}%`;
    atualizarPlaca(t);
    return;
  }
  S.marcaAndamento = marca;
  const registroAntes = caixa.querySelector(".registro");
  const noFim = !registroAntes || registroAntes.scrollTop + registroAntes.clientHeight >= registroAntes.scrollHeight - 8;
  const aberto = caixa.querySelector("details")?.open;
  let h = "", anuncio;
  if (t.rodando) {
    const agora = textoDetalhe(pr);
    anuncio = `${nome}.`;
    h += `<div class="cabeca"><div><p class="grande">Imagem para vídeo (Wan)</p><p>${esc(nome)}.</p>${agora && !amostrando ? `<p class="detalhe-agora">${esc(agora)}</p>` : ""}</div><span class="pct" id="pct">${pct}%</span></div>`;
    h += `<div class="barra" role="progressbar" aria-label="Progresso da geração" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita"><span class="atual vivo" style="flex:1 1 0"><i id="fita-atual" style="width:${pct}%"></i></span></div></div>`;
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div></dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
    h += `<p class="legenda">Pode trocar de aba ou fechar o navegador: a geração continua.</p>`;
  } else {
    anuncio = mensagemFimWan(t);
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}">${p?.pagina && !p.completo ? `<button class="principal" type="button" data-acao="continuar">Tentar de novo</button>` : ""}<button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const registro = caixa.querySelector(".registro");
  if (registro && noFim) registro.scrollTop = registro.scrollHeight;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
/* Cartão do projeto na Biblioteca */
function desenharWan(p, rodando, livre) {
  const nome = encodeURIComponent(p.nome), c = p.config, r = p.resultado;
  const q = p.foto_existe ? midia(`<img loading="lazy" src="/entrada/foto/${encodeURIComponent(p.personagem)}" alt="">`, "", "miniatura") : `<span class="miniatura"></span>`;
  const sit = rodando ? "gerando agora" : p.final ? "pronto" : "sem vídeo";
  let h = `<details class="projeto" data-projeto="${esc(p.nome)}" ${S.abertos.has(p.nome) ? "open" : ""}><summary>${q}<span class="nome">${esc(p.nome)}<small>Imagem para vídeo (Wan), ${esc(quando(p.quando))}</small></span><span class="situacao">${esc(sit)}</span></summary><div class="corpo"><h2 class="corpo-titulo">${esc(p.nome)}<small>Imagem para vídeo (Wan), ${esc(quando(p.quando))} · ${esc(sit)}</small></h2>`;
  if (p.final) h += midia(`<video controls preload="none" src="/video/${nome}/final.mp4?m=${p.final.marca}"></video>`, "Vídeo oculto");
  const botoes = [];
  if (p.pagina && !p.completo && !rodando) botoes.push(`<button class="principal" type="button" data-acao="continuar" ${livre ? "" : "disabled"}>Tentar de novo</button>`);
  botoes.push(`<button type="button" data-acao="reusar">Usar de novo</button>`, `<button type="button" data-acao="pasta">Abrir pasta</button>`, botaoApagar(rodando));
  h += `<div class="botoes">${botoes.join("")}</div>`;
  if (c) h += `<p class="legenda">${esc(NOMES_MODELO_WAN[c.modelo]?.replace(" (padrão)", "") || c.modelo)}, ${c.duracao} s, ${r ? `${r.largura}×${r.altura}` : esc(tamanhoWan(c))}.</p>`;
  if (r) h += `<p class="legenda">Levou ${tempo(r.segundos)}, pico de ${num(r.pico_vram / 1024)} GB de memória e ${r.temp_max} °C. Semente ${r.semente}.</p>`;
  if (c?.prompt) h += `<p class="legenda">${esc(c.prompt)}</p>`;
  return h + `</div></details>`;
}
