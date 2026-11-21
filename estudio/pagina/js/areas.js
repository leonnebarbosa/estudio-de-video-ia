/* Menu de cima: quatro áreas (Personagem, Trocar, Vídeo, Imagem), a marca como início e, no canto direito, a pasta de
   Projetos (tudo o que já foi gerado) e o botão de modelos.
   Cada área reúne uma ou mais abas de antes; as abas continuam existindo e o irPara (base.js) segue por elas.
   A área Vídeo reúne os modos no seletor da barra da tela; o último usado fica guardado. */
const AREAS = {
  inicio: ["explorar"],
  personagem: ["personagens"],
  troca: ["troca"],
  video: ["imagem", "tvideo", "avancado", "novo", "editar"],
  imagem: ["texto"],
  projetos: ["projetos"],
  modelos: ["modelos"],
};
const MODO_VIDEO = "estudio_modo_video";
function areaDaAba(aba) {
  return Object.keys(AREAS).find(area => AREAS[area].includes(aba)) || "inicio";
}
function modoVideoSalvo() {
  let salvo = null;
  try { salvo = localStorage.getItem(MODO_VIDEO); } catch {}
  return AREAS.video.includes(salvo) ? salvo : "imagem";
}
function guardarModoVideo(aba) {
  if (!AREAS.video.includes(aba)) return;
  try { localStorage.setItem(MODO_VIDEO, aba); } catch {}
}
