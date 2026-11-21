/* Conta e validacao */
function rodadasPara(f0, duracao) {
  const c = S.dados.constantes;
  return Math.max(1, Math.ceil((Math.round(duracao * c.fps) - (f0 - c.sobreposicao + c.quadros)) / c.novos) + 1);
}
/* Escala de tempo sob uma fita: cada rotulo fica onde o seu trecho comeca */
function eixoReal(marcas, total) {
  return marcas.map(([s, peso]) => `<span style="flex:${peso} 1 0">${num(s, s % 1 ? 1 : 0)} s</span>`).join("") + `<span class="fim">${num(total, total % 1 ? 1 : 0)} s</span>`;
}
function fita(f0, feitas, total, ativa, fracao = null, reprovadas = new Set()) {
  const novos = S.dados?.constantes.novos || 85;
  let h = `<span class="orig" style="flex:${f0} 1 0"></span>`;
  for (let i = 1; i <= total; i++) {
    const agora = ativa && i === feitas + 1;
    const c = i <= feitas ? (reprovadas.has(i) ? "feita repro" : "feita") : (agora ? (fracao === null ? "atual pulsa" : "atual") : "");
    h += `<span class="${c}" style="flex:${novos} 1 0">${agora && fracao !== null ? `<i id="fita-atual" style="width:${(fracao * 100).toFixed(1)}%"></i>` : ""}</span>`;
  }
  return h;
}
function atualizar() {
  if (!S.dados) return;
  const v = S.video, d = Number($("duracao").value), falta = [], a = lerAjustes(), tar = S.dados.tarefa;
  const padrao = ajustesPadrao(a), travada = sincronizarTrava("novo");
  if (v && d > v.duracao) {
    const total = rodadasPara(v.quadros, d);
    const min = total * (S.foto ? MIN_POR_RODADA.comFoto : MIN_POR_RODADA.semFoto) * (a.passos / S.dados.padrao.passos) * (a.megapixels / S.dados.padrao.megapixels);
    $("fita").innerHTML = fita(v.quadros, 0, total, false);
    $("fita").hidden = false;
    $("fita-eixo").innerHTML = eixoReal([[0, v.quadros], [v.duracao, Math.max(0, total * S.dados.constantes.novos)]], d);
    $("conta").textContent = `Seu vídeo tem ${num(v.duracao)} s. Serão gerados ${num(d - v.duracao)} s em ${total} ${total === 1 ? "rodada" : "rodadas"}.`;
    mostrarEstimativa("estimativa", travada ? null : min * 60, !padrao);
  } else {
    mostrarEstimativa("estimativa", null);
    $("fita").hidden = true;
    $("conta").textContent = v ? `A duração final precisa ser maior que o seu vídeo (${num(v.duracao)} s).` : "Escolha um vídeo para ver quantas rodadas serão feitas e quanto tempo leva.";
  }
  $("tamanho").textContent = `Resolução: ${resolucao(a)}`;
  $("resumo-config").textContent = resumoAjustes(a);
  $("ajustes-situacao").textContent = padrao ? "padrão testado" : "alterado";
  $("aviso-config").textContent = "Estes ajustes ainda não foram testados nesta placa. Comece com um vídeo curto.";
  $("aviso-config").hidden = padrao;
  const l = $("lora").value;
  $("dica-lora").textContent = !l ? "Sem LoRA de aceleração, poucos passos tendem a dar um resultado ruim." : /8step/i.test(l) ? "Feita para 8 passos." : /character_swap/i.test(l) ? "Feita para troca de personagem, não para acelerar." : l === S.dados.padrao.loras[0][0] ? "Feita para 4 passos; o padrão testado usa 6." : "";

  if (S.enviando) falta.push("Esperando o envio terminar");
  else if (!v) falta.push("Escolha o vídeo");
  else if (!v.audio) falta.push("O vídeo precisa ter áudio");
  if (!$("ideia").value.trim()) falta.push("Escreva o que acontece");
  if (v && !(d > v.duracao)) falta.push("Aumente a duração final");
  if (v && !/^[A-Za-z0-9_-]{1,60}$/.test($("projeto").value)) falta.push("Corrija o nome do projeto, em Modelo e ajustes");
  if (S.dados.projetos.some(p => p.nome === $("projeto").value)) falta.push("Já existe um projeto com este nome");
  if ($("lora").value && $("lora").value === $("lora2").value) falta.push("Escolha LoRAs diferentes");
  if (!(a.passos >= 2 && a.passos <= 12)) falta.push("Use de 2 a 12 passos");
  if (!(a.tentativas >= 1 && a.tentativas <= 5)) falta.push("Use de 1 a 5 tentativas");
  if (a.loras.some(([, f]) => !(f >= 0 && f <= 1.5))) falta.push("Use força de LoRA entre 0 e 1,5");
  // Com uma geração rodando o pedido vai para a fila (fila.js), que espera o ComfyUI
  if (!vaiParaFila()) { if (!S.dados.comfy.ligado) falta.push("Esperando o ComfyUI ficar pronto"); else if (S.dados.comfy.ocupado) falta.push("O ComfyUI está ocupado"); }
  porHtml($("falta"), travada ? notaTravada("novo") : htmlFalta(falta));
  $("gerar").disabled = $("so-plano").disabled = falta.length > 0;
  rotuloFila($("gerar"));
  salvarRascunho();
  atualizarTroca();
  atualizarTrocaFoto();
  atualizarEditar();
  atualizarImagem();
  atualizarAvancado();
  atualizarTexto();
  atualizarRecentes();
}
