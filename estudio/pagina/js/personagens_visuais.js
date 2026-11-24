/* Agrupa a lista de /api/personagens em pessoas, cada uma com seus visuais (roupas).
   Função pura, sem DOM: carregada antes do personagens.js e testada no Node. */

// Uma entrada por `pessoa`, na ordem em que a raiz aparece na lista. Nome e capa vêm da raiz.
function agruparPessoas(lista) {
  const grupos = new Map();
  for (const p of lista || []) {
    if (!grupos.has(p.pessoa)) grupos.set(p.pessoa, []);
    grupos.get(p.pessoa).push(p);
  }
  const pessoas = [];
  for (const p of lista || []) {
    if (p.id !== p.pessoa) continue;   // só a raiz abre uma pessoa
    const outros = grupos.get(p.pessoa).filter(v => v.id !== p.id)
      .sort((a, b) => String(a.criado).localeCompare(String(b.criado)));
    pessoas.push({
      id: p.id, nome: p.nome, capa: p.id,
      visuais: [p, ...outros].map(v => ({ id: v.id, rotulo: v.visual, pronto: !!v.pronto })),
    });
  }
  return pessoas;
}

// Só os visuais prontos para uso (os demais aparecem na tela, mas não entram nos seletores).
function visuaisProntos(pessoa) {
  return pessoa.visuais.filter(v => v.pronto);
}

// Seletor do Trocar/Vídeo: um visual pronto segue direto; dois ou mais pedem a escolha do visual.
function passosDoSeletor(pessoa) {
  return visuaisProntos(pessoa).length > 1 ? "visuais" : "direto";
}
