/* Andamento */
function nomeEtapa(e) {
  if (!e) return "Preparando";
  if (e === "plano") return "A LLM está escrevendo o plano";
  if (e === "checagem") return "Conferindo o enquadramento";
  if (e === "analise") return "A LLM está analisando o trecho gerado";
  let m = e.match(/^prompt r(\d+)/);
  if (m) return `A LLM está escrevendo o prompt da rodada ${m[1]}`;
  m = e.match(/^video r(\d+)/);
  if (m) return `Gerando o vídeo da rodada ${m[1]}`;
  return e;
}
const ETAPAS_RODADA = ["Escrever o prompt", "Gerar o vídeo", "Conferir o enquadramento", "Analisar o trecho"];
function indiceEtapa(e) {
  return !e ? -1 : e.startsWith("prompt") ? 0 : e.startsWith("video") ? 1 : e === "checagem" ? 2 : e === "analise" ? 3 : -1;
}
/* Quanto da rodada atual ja passou, pelo tempo das rodadas anteriores. O ComfyUI nao informa isso a esta pagina. */
function previsao(t, p) {
  const media = (campo, padrao) => {
    const v = p.rodadas.map(r => r[campo]).filter(Boolean);
    return v.length ? v.reduce((a, b) => a + b) / v.length : padrao;
  };
  const tempos = [media("s_llm", 60), media("s_video", 240), 15, 30];
  const porRodada = tempos.reduce((a, b) => a + b);
  const i = indiceEtapa(t.etapa), feitas = p.rodadas.length;
  let fracao = i < 0 ? 0 : (tempos.slice(0, i).reduce((a, b) => a + b, 0) + Math.min(t.etapa_segundos || 0, tempos[i] * .95)) / porRodada;
  // Uma nova tentativa recomeca as etapas, mas a barra nao anda para tras
  const chave = `${t.projeto}:${feitas}`;
  if (S.pico?.chave === chave) fracao = Math.max(fracao, S.pico.fracao);
  S.pico = { chave, fracao };
  const resta = Math.max(0, (p.total - feitas - fracao) * porRodada);
  return { fracao, resta, pct: Math.min(99, Math.floor((feitas + fracao) / p.total * 100)) };
}
function tentativaAtual(t, n) {
  const feitas = [...(t.registro || "").matchAll(/^rodada (\d+) t(\d+):/gm)].filter(m => Number(m[1]) === n).map(m => Number(m[2]));
  return (feitas.length ? Math.max(...feitas) : 0) + 1;
}
function linhaEtapas(i, segundos, nomes = ETAPAS_RODADA) {
  return `<ol class="etapas">${nomes.map((nome, k) => {
    const estado = k < i ? "feito" : k === i ? "agora" : "";
    return `<li class="${estado}"${k === i ? ' aria-current="step"' : ""}><span class="marca" aria-hidden="true">${k < i ? "✓" : k + 1}</span><span>${esc(nome)}</span>${k === i ? `<small id="na-etapa">${relogio(segundos)}</small>` : ""}</li>`;
  }).join("")}</ol>`;
}
/* O que o ComfyUI está fazendo agora (fase, passo, ritmo), do progresso.json da troca e da imagem para vídeo */
function textoDetalhe(pr) {
  if (!pr?.fase_nome) return "";
  const amostrando = pr.fase === "amostrar" && pr.maximo > 1;
  const partes = [amostrando ? `${pr.fase_nome}: passo ${pr.valor} de ${pr.maximo}` : pr.fase_nome];
  if (amostrando && pr.s_passo > 0) {
    partes.push(`${num(pr.s_passo, 1)} s por passo`);
    const resta = (pr.maximo - pr.valor) * pr.s_passo;
    if (resta >= 1) partes.push(`faltam ~${tempo(resta)} de amostragem`);
  }
  return partes.join(" · ");
}
/* A placa agora (o script lê a cada 2 s): atualiza no lugar, sem redesenhar o andamento */
function atualizarPlaca(t) {
  const el = $("placa-agora"), pl = t?.rodando ? t.placa : null;
  if (!el) return;
  const marca = JSON.stringify(pl);
  if (el.dataset.marca === marca) return;
  el.dataset.marca = marca;
  el.hidden = !pl;
  el.innerHTML = pl ? `<span>Placa</span><b class="${pl.temp >= 80 ? "quente" : ""}">${pl.temp} °C</b><b>${num(pl.vram_mib / 1024, 1)} GB</b>${pl.watts ? `<b>${pl.watts} W</b>` : ""}` : "";
}
const PLACA = `<p class="placa-agora" id="placa-agora" aria-label="Placa de vídeo agora" hidden></p>`;
/* Detalhes técnicos, fechados por padrão: a placa agora (temperatura, memória, consumo) e o registro da geração.
   Antes ficavam à vista e assustavam quem só quer a imagem (análise de UX de 13/11/2026) */
function blocoRegistro(t, aberto, classe = "") {
  if (!t.registro) return "";
  return `<details class="${classe}" ${aberto ? "open" : ""}><summary>Detalhes técnicos</summary>${t.rodando ? PLACA : ""}<pre class="registro">${esc(t.registro)}</pre></details>`;
}
function mensagemFim(t) {
  const continuar = "As rodadas prontas ficaram guardadas. Para seguir, clique em Continuar geração.";
  if (t.parada) return `Geração parada. ${continuar}`;
  if (t.codigo === 3) return "O ComfyUI parou no meio da geração. As rodadas prontas ficaram guardadas: quando o ComfyUI voltar (veja o topo da página), clique em Continuar geração.";
  if (t.codigo === 4) {
    const termo = (t.registro || "").match(/^FALHA[^\n]*termo recusado: ([\w -]+)/m);
    if (termo) return `A LLM usou "${termo[1]}", um termo que o script recusa, em todas as tentativas. Tente de novo ou mude a ideia. ${continuar}`;
    const falha = [...(t.registro || "").matchAll(/^FALHA ([^\n]*)/gm)].pop();
    return `${falha ? `Falha ${falha[1]}.` : "A LLM ou a geração do vídeo falhou. O motivo está no registro técnico."} ${continuar}`;
  }
  if (t.codigo === 5) return `Parou porque a placa chegou a ${t.temp_limite || 90} °C. Espere esfriar. ${continuar}`;
  const ultima = (t.registro || "").trim().split("\n").pop();
  return `O script parou com um erro: ${ultima || "sem mensagem"}`;
}
function desenharAndamento(d) {
  const t = d.tarefa, caixa = $("andamento");
  const p = t && d.projetos.find(x => x.nome === t.projeto);
  // Quando termina bem, leva direto ao resultado
  if (S.estavaRodando && t && !t.rodando && t.codigo === 0) {
    S.abertos.delete(t.projeto); S.abertos.add(t.projeto);
    S.marcaProjetos = "";
    // A troca em foto é um projeto de texto, mas o resultado dela aparece na aba Trocar personagem, modo Foto
    if (t.tipo === "personagem") {
      irPara("personagens");
      const nome = PERS.lista?.find(x => x.id === t.projeto)?.nome || t.projeto;
      recado(t.modo === "ficha-frente" ? `Frente de ${nome} pronta para aprovação.` :
        t.modo === "ficha-h3" ? `Ficha de 6 vistas de ${nome} pronta.` :
        t.modo?.startsWith("ficha") ? `Vistas da ficha de ${nome} atualizadas.` : `Ângulos de ${nome} prontos.`, true);
      S.estavaRodando = false;
      return desenharAndamentoPersonagem(t);
    }
    if (p?.troca_foto) { S.modoTroca = "foto"; irPara("troca"); } else irPara(t.tipo === "texto" ? "texto" : "projetos");
    recado(p?.troca_foto ? `Troca pronta: ${t.projeto}.` : t.tipo === "texto" ? `Imagens prontas: ${t.projeto}.` : t.modo === "plano" ? `Plano de ${t.projeto} pronto. Confira e ajuste os passos antes de gerar.` : t.modo === "juntar" ? `Rodadas de ${t.projeto} juntadas.` : `Vídeo pronto: ${t.projeto}.`, true);
    S.rolar = t.projeto;
    S.recem = t.projeto;
  }
  S.estavaRodando = !!t?.rodando;
  if (t?.tipo === "troca" || t?.tipo === "editar") return desenharAndamentoTroca(t, p);
  if (t?.tipo === "imagem") return desenharAndamentoImagem(t, p);
  if (t?.tipo === "texto") return desenharAndamentoTexto(t, p);
  if (t?.tipo === "wan") return desenharAndamentoWan(t, p);
  if (t?.tipo === "personagem") return desenharAndamentoPersonagem(t);
  const feitas = p ? p.rodadas.length : 0, total = p ? p.total : 0;
  const juntando = t?.modo === "juntar" || (t?.modo === "gerar" && total > 0 && feitas >= total);
  const planejando = t?.modo === "plano" || t?.etapa === "plano";
  const emRodada = !!t?.rodando && t.modo === "gerar" && total > 0 && !juntando && !planejando;
  const prev = emRodada ? previsao(t, p) : null;
  document.title = t?.rodando ? (emRodada ? `${prev.pct}%, rodada ${feitas + 1} de ${total} – ${TITULO}` : `Trabalhando – ${TITULO}`) : TITULO;
  const mostrar = t && (t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo));
  if (!mostrar) { caixa.hidden = true; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  S.relogio = t.rodando ? { total: t.segundos, etapa: t.etapa_segundos || 0, quando: Date.now() } : null;
  const marca = JSON.stringify([t.rodando, t.etapa, t.codigo, t.registro, feitas]);
  if (marca === S.marcaAndamento) {
    // So os numeros mudam: nao redesenha, para nao fechar o registro nem perder a rolagem
    if (prev) {
      if ($("fita-atual")) $("fita-atual").style.width = `${(prev.fracao * 100).toFixed(1)}%`;
      $("pct").textContent = `${prev.pct}%`;
      $("barra").setAttribute("aria-valuenow", prev.pct);
      $("restante").textContent = tempo(prev.resta);
    }
    atualizarPlaca(t);
    return;
  }
  S.marcaAndamento = marca;
  const registroAntes = caixa.querySelector(".registro");
  const noFim = !registroAntes || registroAntes.scrollTop + registroAntes.clientHeight >= registroAntes.scrollHeight - 8;
  const aberto = caixa.querySelector("details.det-registro")?.open, maisAberto = caixa.querySelector("details.det-mais")?.open;
  let h = "", anuncio = "", extras = "";
  if (t.rodando) {
    const n = feitas + 1;
    const titulo = juntando ? "Juntando as rodadas" : planejando ? "Escrevendo o plano" : emRodada ? `Rodada ${n} de ${total}` : "Começando";
    const maxTent = p?.config?.tentativas || 3;
    const tent = emRodada ? tentativaAtual(t, n) : 1;
    const detalhe = juntando ? "Montando o arquivo final" : planejando ? "A LLM está dividindo a ideia em passos" : emRodada && indiceEtapa(t.etapa) >= 0 ? nomeEtapa(t.etapa) : "Preparando";
    const repete = tent > 1 ? ` Tentativa ${tent} de ${maxTent}: a anterior foi reprovada.` : "";
    h += `<div class="cabeca"><div><p class="grande">${esc(titulo)}</p><p>${esc(detalhe)}.${esc(repete)}</p></div>${emRodada ? `<span class="pct" id="pct">${prev.pct}%</span>` : ""}</div>`;
    anuncio = `${titulo}. ${detalhe}.${repete}`;
    if (total) {
      const reprovadas = new Set(p.rodadas.filter(r => r.aprovada === false).map(r => r.n));
      const c = S.dados.constantes, duracao = p.config?.duracao;
      const prontos = (p.quadros_origem + feitas * c.novos) / c.fps;
      const rotulo = emRodada ? `aria-valuenow="${prev.pct}"` : `aria-valuetext="${esc(titulo)}"`;
      h += `<div class="barra" id="barra" role="progressbar" aria-label="Progresso da geração" aria-valuemin="0" aria-valuemax="100" ${rotulo}><div class="fita">${fita(p.quadros_origem, juntando ? total : feitas, total, !juntando && t.modo === "gerar", emRodada ? prev.fracao : null, reprovadas)}</div>`;
      h += `<div class="eixo"><span>0 s</span><span>${num(duracao ? Math.min(prontos, duracao) : prontos)} s prontos</span>${duracao ? `<span>${num(duracao)} s</span>` : "<span></span>"}</div></div>`;
      if (reprovadas.size) extras += `<p class="legenda">Em vermelho: rodadas que seguiram sem aprovação, com a melhor tentativa.</p>`;
    }
    if (emRodada) h += linhaEtapas(indiceEtapa(t.etapa), t.etapa_segundos || 0);
    if (emRodada && p.passos.length) {
      const proximo = Math.max(0, ...p.rodadas.map(r => r.passo || 0));
      if (proximo < p.passos.length) h += `<p><strong>Passo ${proximo + 1} de ${p.passos.length} do plano:</strong> ${esc(p.passos[proximo])}</p>`;
    }
    const ultima = p?.rodadas[feitas - 1];
    if (emRodada && ultima) extras += `<p class="legenda">Rodada ${ultima.n} levou ${tempo(ultima.segundos)} e ${ultima.aprovada === false ? "seguiu sem aprovação" : "foi aprovada"}.</p>`;
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div>${planejando ? `<div><dt>Nesta etapa</dt><dd id="na-etapa">${relogio(t.etapa_segundos || 0)}</dd></div>` : ""}${emRodada ? `<div><dt>Falta cerca de</dt><dd id="restante">${tempo(prev.resta)}</dd></div>` : ""}</dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
    if (emRodada) extras += `<p class="legenda">${feitas ? "A previsão usa o tempo das rodadas anteriores." : "Previsão aproximada até a primeira rodada terminar."}</p>`;
    h += `<p class="legenda">Pode trocar de aba ou fechar o navegador: a geração continua.</p>`;
    if (p?.tem_quadro && feitas) h += midia(`<img class="mosaico" src="/quadro/${encodeURIComponent(t.projeto)}?r=${feitas}" alt="Último quadro da rodada ${feitas} e três quadros anteriores">`, "Imagem oculta", "midia-quadro") + `<p class="legenda com-midia">Fim da rodada ${feitas}: à esquerda o último quadro, à direita os anteriores.</p>`;
  } else {
    const pode = p?.pagina && !p.completo;
    anuncio = mensagemFim(t);
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}">${pode ? `<button class="principal" type="button" data-acao="continuar">Continuar geração</button>` : ""}<button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  // As explicacoes ficam a um clique: o andamento cabe numa faixa e o palco continua a vista
  if (extras) h += `<details class="det-mais" ${maisAberto ? "open" : ""}><summary>Detalhes da geração</summary>${extras}</details>`;
  h += blocoRegistro(t, aberto, "det-registro");
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const registro = caixa.querySelector(".registro");
  if (registro && noFim) registro.scrollTop = registro.scrollHeight;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
/* Duracao de cada etapa, em segundos, medida em 06/11 com 3 s de video: com upscale e sem ele. So pesa a barra; o passo a passo vem do ComfyUI.
   esrgan: a ampliacao fora do ComfyUI, depois de montar (de 8 a 12 s por segundo de video, medido em 11/11/2026). */
const ETAPAS_TROCA = { descrever: ["Descrever a personagem", 85, 85], primeira: ["Primeira passagem", 195, 195], ampliar: ["Upscale", 256, 0], montar: ["Montar o vídeo", 25, 20], esrgan: ["Ampliar com ESRGAN", 0, 35] };
/* Motor Viggle no estúdio (troca_viggle.py), tudo no ComfyUI: ~55 s por quadro pintado (22/11) e 392 s de Viggle para 5 s a 0,5 MP (21/11) */
/* fundo: so com o fundo novo; acabamento: cor dos olhos e pele fosca, na CPU (so com a roupa do video). Medido em 22/11: ~30 s por quadro pintado (Klein), ~360 s por janela */
const ETAPAS_TROCA_VIGGLE = { fundo: ["Trocar o fundo", 0, 250], pintar: ["Pintar os quadros com a pessoa da foto", 0, 70], viggle: ["Viggle Remake", 0, 360], acabamento: ["Acabamento do rosto", 0, 40], montar: ["Montar o vídeo", 0, 10], esrgan: ["Ampliar com ESRGAN", 0, 35] };
/* Motor Wan Animate 2 (troca_wan.py): pinta o primeiro quadro e anima; ~12 min para 5 s (22/11) */
const ETAPAS_TROCA_WAN = { fundo: ["Trocar o fundo", 0, 250], pintar: ["Pintar o primeiro quadro", 0, 45], wan: ["Wan Animate 2", 0, 700], montar: ["Montar o vídeo", 0, 10], esrgan: ["Ampliar com ESRGAN", 0, 35] };
/* Editar vídeo (editar_video.py), medido em 18/11 com 5,2 s a ~0,4 MP: ~30 s para a IA escrever o roteiro (se faltar), ~360 s de Viggle */
const ETAPAS_EDITAR = { roteiro: ["Escrever o roteiro (IA)", 0, 30], viggle: ["Viggle Remake Edit", 0, 380], montar: ["Montar o vídeo", 0, 5], esrgan: ["Ampliar com ESRGAN", 0, 35] };
function mensagemFimTroca(t) {
  if (t.parada) return "Geração parada. Nada ficou pela metade: para gerar de novo, clique em Tentar de novo.";
  if (t.codigo === 3) return "O ComfyUI parou no meio da troca. Quando ele voltar (veja o topo da página), clique em Tentar de novo.";
  if (t.codigo === 5) return `Parou porque a placa chegou a ${t.temp_limite || 90} °C. Espere esfriar e clique em Tentar de novo.`;
  const falha = [...(t.registro || "").matchAll(/^FALHA ([^\n]*)/gm)].pop();
  if (t.codigo === 4) return falha ? `Falha ${falha[1]}` : "A geração falhou. O motivo está no registro técnico.";
  const ultima = (t.registro || "").trim().split("\n").pop();
  return `O script parou com um erro: ${ultima || "sem mensagem"}`;
}
function desenharAndamentoTroca(t, p) {
  const caixa = $("andamento");
  const mostrar = t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo);
  if (!mostrar) { caixa.hidden = true; document.title = TITULO; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  // Projeto antigo, sem as chaves: com a segunda passagem e sem o ESRGAN
  // Editar vídeo usa esta mesma caixa, com as etapas dele
  const ed = t.tipo === "editar";
  const es = p?.config?.esrgan === true, vg = p?.config?.motor === "viggle", wn = p?.config?.motor === "wan", wg = vg || wn || p?.config?.motor === "wangp", up = p?.config?.upscale !== false && !es && !wg && !ed;
  const ET = ed ? ETAPAS_EDITAR : wn ? ETAPAS_TROCA_WAN : wg ? ETAPAS_TROCA_VIGGLE : ETAPAS_TROCA;
  const pr = t.progresso || { etapa: ed ? "roteiro" : wg ? "pintar" : "descrever", valor: 0, maximo: 0, tempos: {} };
  const chaves = Object.keys(ET).filter(k => (up || k !== "ampliar") && (es || k !== "esrgan") && (p?.config?.fundo || k !== "fundo") && (k !== "acabamento" || (p?.config?.acabamento !== false && (p?.config?.roupa || "video") === "video")));
  const peso = k => ET[k][up ? 1 : 2];
  const i = Math.max(0, chaves.indexOf(pr.etapa));
  const naEtapa = Math.max(0, t.segundos - Object.values(pr.tempos || {}).reduce((a, b) => a + b, 0));
  const fracao = pr.maximo ? pr.valor / pr.maximo : Math.min(.95, naEtapa / peso(chaves[i]));
  const soma = chaves.reduce((a, k) => a + peso(k), 0), antes = chaves.slice(0, i).reduce((a, k) => a + peso(k), 0);
  let pct = Math.min(99, Math.floor((antes + fracao * peso(chaves[i])) / soma * 100));
  // Em janelas (trocar_personagem.trocar_em_janelas) as etapas se repetem em cada uma: a barra soma as janelas prontas
  if (pr.janela && pr.etapa !== "esrgan") pct = Math.min(99, Math.floor(((pr.janela[0] - 1) * 100 + pct) / pr.janela[1]));
  // A estimativa de tempo pode passar da conta; a barra nao anda para tras
  if (S.picoTroca?.projeto === t.projeto) pct = Math.max(pct, S.picoTroca.pct);
  S.picoTroca = t.rodando ? { projeto: t.projeto, pct } : null;
  S.relogio =t.rodando ? { total: t.segundos, etapa: naEtapa, quando: Date.now() } : null;
  const nome = ET[chaves[i]][0] + (pr.janela && pr.etapa !== "esrgan" ? ` (janela ${pr.janela[0]} de ${pr.janela[1]})` : ""), passo = pr.maximo ? (pr.etapa === "esrgan" ? `Quadro ${pr.valor} de ${pr.maximo}.` : pr.etapa === "pintar" ? `${pr.valor} de ${pr.maximo} quadros pintados.` : `Passo ${pr.valor} de ${pr.maximo}.`) : "";
  document.title = t.rodando ? `${pct}%, ${nome} – ${TITULO}` : TITULO;
  const marca = JSON.stringify([t.rodando, pr.etapa, pr.valor, pr.maximo, pr.fase, pr.janela, t.codigo, t.registro]);
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
    const titulo = ed ? "Editando o vídeo" : "Trocando personagem";
    anuncio = `${titulo}. ${nome}. ${passo}`;
    const agora = textoDetalhe(pr) || passo;
    h += `<div class="cabeca"><div><p class="grande">${titulo}</p><p>${esc(nome)}.</p>${agora ? `<p class="detalhe-agora">${esc(agora)}</p>` : ""}</div><span class="pct" id="pct">${pct}%</span></div>`;
    h += `<div class="barra" role="progressbar" aria-label="Progresso da geração" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita"><span class="atual vivo" style="flex:1 1 0"><i id="fita-atual" style="width:${pct}%"></i></span></div></div>`;
    h += linhaEtapas(i, naEtapa, chaves.map(k => ET[k][0]));
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div></dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
    h += `<p class="legenda">Pode trocar de aba ou fechar o navegador: a geração continua.</p>`;
  } else {
    anuncio = mensagemFimTroca(t);
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}">${p?.pagina && !p.completo ? `<button class="principal" type="button" data-acao="continuar">Tentar de novo</button>` : ""}<button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const registro = caixa.querySelector(".registro");
  if (registro && noFim) registro.scrollTop = registro.scrollHeight;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
function mensagemFimImagem(t) {
  if (t.parada) return "Geração parada. As tomadas prontas ficam guardadas: clique em Continuar geração para seguir.";
  if (t.codigo === 3) return "O ComfyUI parou no meio da geração. As tomadas prontas ficaram guardadas: quando o ComfyUI voltar (veja o topo da página), clique em Continuar geração.";
  if (t.codigo === 5) return `Parou porque a placa chegou a ${t.temp_limite || 90} °C. As tomadas prontas ficam guardadas. Espere esfriar e clique em Continuar geração.`;
  const falha = [...(t.registro || "").matchAll(/^FALHA ([^\n]*)/gm)].pop();
  if (t.codigo === 4) return falha ? `Falha ${falha[1]}` : "A geração falhou. O motivo está no registro técnico.";
  const ultima = (t.registro || "").trim().split("\n").pop();
  return `O script parou com um erro: ${ultima || "sem mensagem"}`;
}
function desenharAndamentoImagem(t, p) {
  const caixa = $("andamento");
  const mostrar = t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo);
  if (!mostrar) { caixa.hidden = true; document.title = TITULO; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  const lista = p?.config?.tomadas || [], total = lista.length || 1;
  const pr = t.progresso || { tomada: 1, etapa: "preparar", valor: 0, maximo: 0, em: 0 };
  if (t.rodando && (pr.etapa === "refinar" || pr.etapa === "ampliar" || pr.etapa === "suavizar" || t.modo === "acabar")) return desenharAcabamento(t, pr);
  const n = Math.max(1, pr.tomada || 1);
  const naTomada = Math.max(0, t.segundos - (pr.em || 0));
  // O peso de cada tomada na barra: os quadros que ela soma, na conta do modelo do projeto (H3 ou Wan)
  const mod = modeloImagem(p?.config?.modelo || "h3");
  const peso = i => quadrosTomada(mod, lista[i]?.duracao || 3, i === 0);
  const soma = lista.reduce((s, _, i) => s + peso(i), 0) || 1;
  const antes = lista.slice(0, n - 1).reduce((s, _, i) => s + peso(i), 0);
  // Dentro da tomada, a fase do ComfyUI diz onde está: antes da amostragem, nos passos dela ou depois (decodificar, salvar)
  const pele = p?.config?.pele === true;
  const esperado = mod.fala ? segundosTomadaH3(lista[n - 1]?.duracao || 3, Number(p?.config?.megapixels) || 0.4746, n === 1, pele || /turbo/i.test(p?.config?.seguintes || "")) * (pele ? FATOR_PELE : 1) : SEGUNDOS_TOMADA_WAN[mod.id] || 260;
  const porTempo = Math.min(.95, naTomada / esperado);
  let fracao = pr.etapa === "montar" ? .97 : !pr.fase ? porTempo
    : pr.fase === "amostrar" ? .12 + .73 * (pr.maximo > 1 ? pr.valor / pr.maximo : 0)
    : pr.fase === "decodificar" ? .88 : pr.fase === "salvar" ? .94 : Math.min(.12, porTempo);
  // Uma segunda cadeia de amostragem recomeça os passos: a parte feita da tomada não volta
  if (S.picoImagem?.projeto === t.projeto && S.picoImagem.n === n) fracao = Math.max(fracao, S.picoImagem.fracao);
  let pct = Math.min(99, Math.floor((antes + fracao * peso(n - 1)) / soma * 100));
  if (S.picoImagem?.projeto === t.projeto) pct = Math.max(pct, S.picoImagem.pct);
  S.picoImagem = t.rodando ? { projeto: t.projeto, pct, n, fracao } : null;
  S.relogio = t.rodando ? { total: t.segundos, etapa: naTomada, quando: Date.now() } : null;
  const nome = pr.etapa === "montar" ? `Montando a tomada ${n} de ${total}` : `Gerando a tomada ${n} de ${total}`;
  const passo = pr.maximo ? `Passo ${pr.valor} de ${pr.maximo}.` : "";
  document.title = t.rodando ? `${pct}%, ${nome} – ${TITULO}` : TITULO;
  const marca = JSON.stringify([t.rodando, n, pr.etapa, pr.valor, pr.maximo, pr.fase, t.codigo, t.registro]);
  if (marca === S.marcaAndamento) {
    if ($("pct")) $("pct").textContent = `${pct}%`;
    if ($("fita-atual")) $("fita-atual").style.width = `${(fracao * 100).toFixed(1)}%`;
    atualizarPlaca(t);
    return;
  }
  S.marcaAndamento = marca;
  const registroAntes = caixa.querySelector(".registro");
  const noFim = !registroAntes || registroAntes.scrollTop + registroAntes.clientHeight >= registroAntes.scrollHeight - 8;
  const aberto = caixa.querySelector("details")?.open;
  let h = "", anuncio;
  if (t.rodando) {
    anuncio = `${nome}. ${passo}`;
    const faixas = lista.map((_, i) => {
      if (i === n - 1) return `<span class="atual vivo" style="flex:${peso(i)} 1 0"><i id="fita-atual" style="width:${(fracao * 100).toFixed(1)}%"></i></span>`;
      return `<span class="${i < n - 1 ? "feita" : ""}" style="flex:${peso(i)} 1 0"></span>`;
    }).join("");
    const agora = pr.etapa === "montar"
      ? (p?.config?.avancado ? "Salvando o vídeo" : "Juntando a tomada ao vídeo e conferindo a emenda")
      : textoDetalhe(pr) || passo;
    h += `<div class="cabeca"><div><p class="grande">Gerando o vídeo</p><p>${esc(nome)}.</p>${agora ? `<p class="detalhe-agora">${esc(agora)}</p>` : ""}</div><span class="pct" id="pct">${pct}%</span></div>`;
    h += `<div class="barra" role="progressbar" aria-label="Progresso da geração" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita">${faixas}</div></div>`;
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div><div><dt>Nesta tomada</dt><dd id="na-etapa">${relogio(naTomada)}</dd></div></dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
    h += `<p class="legenda">Pode trocar de aba ou fechar o navegador: a geração continua.</p>`;
  } else {
    anuncio = mensagemFimImagem(t);
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}">${p?.pagina && !p.completo ? `<button class="principal" type="button" data-acao="continuar">Continuar geração</button>` : ""}<button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const registro = caixa.querySelector(".registro");
  if (registro && noFim) registro.scrollTop = registro.scrollHeight;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
function mensagemFimTexto(t) {
  if (t.parada) return "Geração parada. As imagens prontas ficam guardadas: clique em Gerar as que faltam para seguir.";
  if (t.codigo === 3) return "O ComfyUI parou no meio. As imagens prontas ficaram guardadas: quando ele voltar, clique em Gerar as que faltam.";
  if (t.codigo === 5) return `Parou porque a placa chegou a ${t.temp_limite || 90} °C. As imagens prontas ficam guardadas. Espere esfriar e continue.`;
  const falha = [...(t.registro || "").matchAll(/^FALHA ([^\n]*)/gm)].pop();
  if (t.codigo === 4) return falha ? `Falha ${falha[1]}` : "A geração falhou. O motivo está no registro técnico.";
  const ultima = (t.registro || "").trim().split("\n").pop();
  return `O script parou com um erro: ${ultima || "sem mensagem"}`;
}
function desenharAndamentoTexto(t, p) {
  const caixa = $("andamento");
  const mostrar = t.rodando || (t.codigo !== 0 && S.dispensada !== t.projeto + t.codigo);
  if (!mostrar) { caixa.hidden = true; document.title = TITULO; S.marcaAndamento = ""; S.relogio = null; $("anuncio").textContent = ""; return; }
  caixa.hidden = false;
  const total = p?.total || p?.config?.quantidade || 1, feitas = p?.imagens?.length || 0;
  const pr = t.progresso || { imagem: feitas + 1, valor: 0, maximo: 0, em: 0 };
  const n = Math.min(total, Math.max(1, pr.imagem || feitas + 1));
  // Na imagem atual: carregar e ler o prompt são rápidos, a amostragem é quase tudo, decodificar e salvar fecham
  const fracao = pr.fase === "amostrar" && pr.maximo > 1 ? .08 + .84 * pr.valor / pr.maximo : pr.fase === "decodificar" || pr.fase === "salvar" ? .96 : .04;
  const pct = Math.min(99, Math.floor((n - 1 + fracao) / total * 100));
  const naImagem = Math.max(0, t.segundos - (pr.em || 0));
  S.relogio = t.rodando ? { total: t.segundos, etapa: naImagem, quando: Date.now() } : null;
  // A troca em foto também é um projeto de texto: o andamento diz o que ela faz
  const troca = !!p?.troca_foto;
  const nome = troca ? (total > 1 ? `Trocando na versão ${n} de ${total}` : "Trocando") : total > 1 ? `Gerando a imagem ${n} de ${total}` : "Gerando a imagem";
  document.title = t.rodando ? `${pct}%, ${nome} – ${TITULO}` : TITULO;
  const marca = JSON.stringify([t.rodando, n, pr.valor, pr.maximo, pr.fase, t.codigo, t.registro]);
  if (marca === S.marcaAndamento) {
    if ($("pct")) $("pct").textContent = `${pct}%`;
    if ($("fita-atual")) $("fita-atual").style.width = `${(fracao * 100).toFixed(1)}%`;
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
    anuncio = `${nome}. ${agora}`;
    const faixas = Array.from({ length: total }, (_, i) => i === n - 1
      ? `<span class="atual vivo" style="flex:1 1 0"><i id="fita-atual" style="width:${(fracao * 100).toFixed(1)}%"></i></span>`
      : `<span class="${i < n - 1 ? "feita" : ""}" style="flex:1 1 0"></span>`).join("");
    h += `<div class="cabeca"><div><p class="grande">${troca ? "Trocar personagem em foto" : "Texto para imagem"}</p><p>${esc(nome)}.</p>${agora ? `<p class="detalhe-agora">${esc(agora)}</p>` : ""}</div><span class="pct" id="pct">${pct}%</span></div>`;
    h += `<div class="barra" role="progressbar" aria-label="Progresso da geração" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita">${faixas}</div></div>`;
    h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div>${total > 1 ? `<div><dt>Nesta imagem</dt><dd id="na-etapa">${relogio(naImagem)}</dd></div>` : ""}</dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
    h += `<p class="legenda">Pode trocar de aba ou fechar o navegador: a geração continua.</p>`;
  } else {
    anuncio = mensagemFimTexto(t);
    h += `<div class="faixa">${esc(anuncio)}</div><div class="botoes" data-projeto-acao="${esc(t.projeto)}">${p?.pagina && !p.completo ? `<button class="principal" type="button" data-acao="continuar">Gerar as que faltam</button>` : ""}<button type="button" data-acao="dispensar">Fechar aviso</button></div>`;
  }
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const registro = caixa.querySelector(".registro");
  if (registro && noFim) registro.scrollTop = registro.scrollHeight;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
function desenharAcabamento(t, pr) {
  const caixa = $("andamento");
  const refino = pr.etapa === "refinar";
  const nome = refino ? (pr.maximo ? `Refinando com o H3: pedaço ${Math.min(pr.valor + 1, pr.maximo)} de ${pr.maximo}` : "Refinando com o H3")
             : pr.etapa === "suavizar" ? "Deixando o movimento mais fluido (RIFE, 32 quadros por segundo)"
             : pr.etapa === "ampliar" ? (pr.maximo ? `Ampliando para Full HD: quadro ${pr.valor} de ${pr.maximo}` : "Ampliando para Full HD") : "Preparando o acabamento";
  const pct = pr.maximo ? Math.min(99, Math.floor(pr.valor / pr.maximo * 100)) : 0;
  const naEtapa = Math.max(0, t.segundos - (pr.em || 0));
  S.relogio = { total: t.segundos, etapa: naEtapa, quando: Date.now() };
  document.title = `${pct}%, ${nome} – ${TITULO}`;
  const marca = JSON.stringify(["acabar", pr.etapa, pr.valor, pr.maximo, t.registro]);
  if (marca === S.marcaAndamento) { atualizarPlaca(t); return; }
  S.marcaAndamento = marca;
  const aberto = caixa.querySelector("details")?.open;
  let h = `<div class="cabeca"><div><p class="grande">Acabamento do vídeo</p><p>${esc(nome)}.</p></div><span class="pct" id="pct">${pct}%</span></div>`;
  h += `<div class="barra" role="progressbar" aria-label="Progresso do acabamento" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="fita"><span class="atual vivo" style="flex:1 1 0"><i style="width:${pct}%"></i></span></div></div>`;
  h += `<div class="rodape"><dl class="tempos"><div><dt>Tempo total</dt><dd id="decorrido">${relogio(t.segundos)}</dd></div><div><dt>Nesta etapa</dt><dd id="na-etapa">${relogio(naEtapa)}</dd></div></dl><div class="botoes"><button type="button" data-acao="parar">Parar geração</button></div></div>`;
  h += pr.etapa === "suavizar" ? `<p class="legenda">${esc(t.projeto)}: as tomadas estão prontas; o vídeo de 16 quadros por segundo fica guardado como final_16qps.mp4.</p>`
    : `<p class="legenda">${esc(t.projeto)}: o vídeo original não é alterado; o resultado sai como final_hd.mp4.</p>`;
  h += blocoRegistro(t, aberto);
  caixa.innerHTML = h;
  atualizarPlaca(t);
  const anuncio = `${nome}.`;
  if ($("anuncio").textContent !== anuncio) $("anuncio").textContent = anuncio;
}
// Os relogios andam a cada segundo; a consulta ao servidor continua a cada 3 s
setInterval(() => {
  if (!S.relogio) return;
  const passou = (Date.now() - S.relogio.quando) / 1000;
  if ($("decorrido")) $("decorrido").textContent = relogio(S.relogio.total + passou);
  if ($("na-etapa")) $("na-etapa").textContent = relogio(S.relogio.etapa + passou);
}, 1000);
