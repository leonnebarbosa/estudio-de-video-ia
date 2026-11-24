"""Catalogo das ferramentas do MCP do estudio (registradas em mcp_servidor ao importar este arquivo).
Aqui ficam so os textos e os esquemas, na ordem do tools/list; as funcoes moram em quatro modulos:
mcp_consultas (estado, projetos, andamento, resultado), mcp_midias (envio, midias, personagem),
mcp_planejar (receitas, planos e confirmar_plano) e mcp_completo (chamar_api, enviar_arquivo, ver_log).
Quem usa o nivel operador e o agente que conversa com o usuario (cliente MCP), as vezes um LLM pequeno: cada descricao diz
quando usar, quando nao usar e traz um exemplo, e cada resultado e um texto curto, nunca o JSON bruto. O agente escreve as
tomadas seguindo regras_das_tomadas; o estudio so confere. As ferramentas do nivel operador nao apagam nada; o chamar_api
do nivel completo pode apagar, com confirmar: true, como a pagina."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estilos, planos, validacao, video_avancado
from imagem_para_video import CAMERAS, DURACOES
from mcp_servidor import registrar
from mcp_consultas import (MAX_PROJETOS, listar_personagens, listar_projetos, parar_geracao, retomar_fila, ver_andamento,
                           ver_estado, ver_resultado)
from mcp_midias import criar_personagem, importar_url, listar_midias, pedir_envio, usar_resultado
from mcp_planejar import (confirmar_plano, listar_modelos_video, listar_receitas, planejar_imagem, planejar_video, planejar_video_livre,
                          regras_das_tomadas, regras_do_modo_livre)
import mcp_completo
from mcp_completo import chamar_api, enviar_arquivo, ver_log

AMBOS = {"operador", "completo"}
SEM_ARGUMENTOS = {"type": "object", "properties": {}}


registrar("ver_estado",
          "Mostra como está o estúdio em poucas linhas: se o ComfyUI está ligado, o que está sendo gerado, a fila e o uso da placa. "
          "Quando usar: sempre no começo da conversa e antes de planejar um vídeo. "
          "Quando não usar: para saber a tomada e o passo da geração atual (use ver_andamento). "
          "Exemplo: ver_estado {}.", SEM_ARGUMENTOS, AMBOS, ver_estado)

registrar("listar_personagens",
          "Lista os personagens da biblioteca, um por linha, no formato id: nome. "
          "Quando usar: antes de planejar_video com as receitas fala_camera, podcast ou anuncio_vertical, para achar o id do personagem. "
          "Quando não usar: na receita cena_texto, que não usa personagem. Nunca invente um personagem que não está na lista. "
          "Exemplo: listar_personagens {}.", SEM_ARGUMENTOS, AMBOS, listar_personagens)

registrar("criar_personagem",
          "Cria um personagem na biblioteca a partir de uma foto que já foi enviada. Devolve o id, que serve no campo personagem do planejar_video. "
          "Quando usar: quando o usuário pedir para criar, salvar ou guardar um personagem com uma foto dele. A foto tem de ser uma mídia (pedir_envio, depois listar_midias). "
          "Quando não usar: para usar a foto uma vez só (basta o campo foto no planejar_video), para apagar um personagem ou para fazer a ficha e os ângulos (só pela página). "
          "Chame uma vez só. "
          "Exemplo: {\"nome\": \"Ana\", \"foto\": \"ana.png\"}.",
          {"type": "object", "properties": {
              "nome": {"type": "string", "maxLength": 60},
              "foto": {"type": "string", "description": "Nome de uma foto que já é mídia do estúdio (listar_midias)."},
              "descricao": {"type": "string", "maxLength": 600, "description": "Só se o usuário descreveu."}},
           "required": ["nome", "foto"]}, AMBOS, criar_personagem)

registrar("listar_projetos",
          f"Lista os {MAX_PROJETOS} projetos de vídeo e de imagem mais recentes com nome, tipo, data e se está pronto ou incompleto. "
          "Quando usar: quando o usuário perguntar pelos vídeos feitos ou quiser ver um vídeo antigo (depois use ver_resultado com o nome). "
          "Quando não usar: para saber o que está gerando agora (use ver_andamento). "
          "Exemplo: listar_projetos {}.", SEM_ARGUMENTOS, AMBOS, listar_projetos)

registrar("ver_andamento",
          "Diz o que a geração atual está fazendo: o projeto, a etapa, a tomada, o passo e há quantos segundos começou. "
          "Quando usar: quando o usuário perguntar \"já terminou?\" ou \"como está o vídeo?\" depois de confirmar_plano. "
          "Quando não usar: para ver o vídeo pronto (use ver_resultado); nem várias vezes seguidas: uma consulta por pergunta do usuário. "
          "Exemplo: ver_andamento {}.", SEM_ARGUMENTOS, AMBOS, ver_andamento)

registrar("parar_geracao",
          "Para a geração que está rodando e pausa a fila, para nada novo começar sozinho. "
          "Quando usar: quando o usuário pedir para parar, cancelar ou \"para tudo\". "
          "Quando não usar: para apagar um projeto (não é possível por aqui) ou só para ver o estado (use ver_estado). "
          "Exemplo: parar_geracao {}.", SEM_ARGUMENTOS, AMBOS, parar_geracao)

registrar("retomar_fila",
          "Tira a pausa da fila: o próximo pedido começa sozinho quando a placa estiver livre. "
          "Quando usar: só quando o usuário pedir para continuar a fila (por exemplo, depois de parar_geracao). "
          "Quando não usar: para começar um vídeo novo (use planejar_video e confirmar_plano). "
          "Exemplo: retomar_fila {}.", SEM_ARGUMENTOS, AMBOS, retomar_fila)

registrar("ver_resultado",
          "Mostra o resultado de um projeto: se terminou, a duração, o link para baixar o vídeo e o último quadro como imagem; "
          "num projeto de imagem, um link para baixar cada imagem e a primeira como imagem. "
          "Quando usar: depois que ver_andamento disser \"Nada gerando agora.\", com o nome do projeto que confirmar_plano devolveu, "
          "ou com um nome de listar_projetos. "
          "Quando não usar: para saber o passo de uma geração em andamento (use ver_andamento). "
          "Exemplo: {\"projeto\": \"mcp_podcast_20261121_153000\"}.",
          {"type": "object", "properties": {"projeto": {"type": "string", "description": "Nome do projeto (de confirmar_plano ou listar_projetos)."}},
           "required": ["projeto"]}, AMBOS, ver_resultado)


registrar("listar_receitas",
          "Lista as receitas de vídeo: id, nome e para que serve. "
          "Quando usar: antes de planejar_video, para escolher a receita que combina com o pedido do usuário. "
          "Quando não usar: para saber o que está gerando (use ver_estado ou ver_andamento). "
          "Exemplo: listar_receitas {}.", SEM_ARGUMENTOS, AMBOS, listar_receitas)

QUALIDADE = {"type": "string", "enum": list(planos.QUALIDADES), "default": "ugc",
             "description": "\"ugc\" (padrão, 1,1 MP) ou \"rapido\" (teste a 0,47 MP, sem pele natural)."}
RESOLUCAO = {"type": "string", "enum": list(planos.RESOLUCOES),
             "description": "Opcional: só se o usuário pedir uma resolução (\"em 720p\"). Troca a resolução da qualidade; a pele natural segue a qualidade."}

RESOLUCAO_LIVRE = {"type": "string", "enum": list(planos.RESOLUCOES), "default": "540p",
                   "description": "Opcional, padrão 540p: \"480p\", \"540p\", \"720p\" ou \"maxima\"."}
# Semente: so com pedido do usuario (repetir uma geracao); o teto e o do mcp_planejar.MAX_SEMENTE
SEMENTE = {"type": "integer", "minimum": 0, "description": "Só se o usuário pedir uma."}
AUDIO_FALA = {"type": "string", "description": "Opcional: nome de um áudio de fala que já é mídia do estúdio (listar_midias). O vídeo sai sincronizado "
                                                "com ele, sempre com a pele natural; o estúdio divide o áudio nas pausas e o número de tomadas vem dessa divisão."}

registrar("regras_das_tomadas",
          "Devolve as regras para você escrever as tomadas de um vídeo: limites, durações e câmeras aceitas nesta qualidade, "
          "o padrão do texto em inglês, a regra da cena e um exemplo pronto. Qualidade: \"ugc\" é o padrão (1,1 MP, pele natural nas receitas com personagem; demora mais e fica mais bonito); "
          "\"rapido\" é um teste a 0,47 MP sem pele natural, só quando o usuário pedir algo rápido, um teste ou um rascunho "
          "(\"faz um rápido só pra ver\" → \"rapido\"). Resolução (opcional): \"480p\", \"540p\", \"720p\" ou \"maxima\", só se o usuário pedir "
          "(\"em 720p\"); os limites das tomadas seguem a resolução. "
          "Com audio_fala (nome de um áudio de listar_midias, só nas receitas com imagem), a fala é o áudio: devolve em quantas tomadas ele se "
          "divide e o que cada uma leva. "
          "Quando usar: depois de escolher a receita e antes de planejar_video, sempre que for escrever ou corrigir tomadas. "
          "Quando não usar: para gerar (planejar_video). "
          "Exemplo: {\"receita\": \"fala_camera\", \"qualidade\": \"ugc\"}.",
          {"type": "object", "properties": {
              "receita": {"type": "string", "enum": list(planos.receitas()), "description": "Id da receita (listar_receitas)."},
              "qualidade": QUALIDADE, "resolucao": RESOLUCAO, "audio_fala": AUDIO_FALA},
           "required": ["receita"]}, AMBOS, regras_das_tomadas)

registrar("planejar_video",
          "Planeja um vídeo sem gerar nada: você manda as tomadas que escreveu seguindo regras_das_tomadas e o estúdio confere com a mesma "
          "validação da página. Devolve um código de plano e um resumo, que você mostra ao usuário antes de confirmar. Nas receitas com "
          "imagem, informe o personagem (id de listar_personagens) ou uma foto já enviada; a cena, opcional, diz onde acontece (em "
          "inglês: lugar e luz) e, sem ela, vale o lugar da receita ou o padrão do estúdio. Na cena_texto, a cena é obrigatória. "
          "A duração do vídeo é a soma das tomadas. Use a mesma qualidade (e a mesma resolução, se pediu) que usou em regras_das_tomadas; "
          "o resumo pode trazer linhas \"Aviso:\", que você repassa ao usuário. Com audio_fala (áudio de listar_midias; só nas receitas com imagem) "
          "o vídeo sai sincronizado com o áudio: mande uma tomada por corte (regras_das_tomadas diz quantas), sem duracao; cenario é uma foto do lugar, só junto com audio_fala. "
          "Se recusar, corrija as tomadas pela mensagem e chame de novo. "
          "Quando usar: quando o usuário pedir um vídeo, depois de regras_das_tomadas. "
          "Quando não usar: antes de regras_das_tomadas ou para começar a geração (confirmar_plano). "
          "Exemplo: {\"receita\": \"anuncio_vertical\", \"personagem\": \"ana\", \"formato\": \"9:16\", \"qualidade\": \"ugc\", "
          "\"tomadas\": [{\"acao\": \"The character smiles and waves at the camera while talking.\", \"fala\": \"A internet chegou!\", "
          "\"som\": \"soft room tone\", \"camera\": \"aproximar\", \"duracao\": 3.5}, {\"acao\": \"The character points to the side and nods.\", "
          "\"fala\": \"Agora é só aproveitar.\", \"som\": \"\", \"camera\": \"acompanhar\", \"duracao\": 3}]}.",
          {"type": "object", "properties": {
              "receita": {"type": "string", "enum": list(planos.receitas()), "description": "Id da receita (listar_receitas)."},
              "personagem": {"type": "string", "description": "Id ou nome do personagem da biblioteca (listar_personagens). Não vale em cena_texto."},
              "foto": {"type": "string", "description": "Nome de uma foto que já é mídia do estúdio (listar_midias), no lugar do personagem."},
              "formato": {"type": "string", "enum": list(planos.FORMATOS)},
              "qualidade": QUALIDADE, "resolucao": RESOLUCAO,
              "audio_fala": AUDIO_FALA,
              "cenario": {"type": "string", "description": "Só com audio_fala: nome de uma foto do lugar que já é mídia do estúdio (listar_midias). Sem áudio, use o campo cena."},
              "tomadas": {"type": "array", "minItems": 1, "maxItems": validacao.MAX_TOMADAS,
                          "description": "As tomadas, na ordem, escritas seguindo regras_das_tomadas.",
                          "items": {"type": "object", "properties": {
                              "acao": {"type": "string", "maxLength": validacao.MAX_ACAO, "description": "O que acontece, em inglês, com \"the character\" como sujeito."},
                              "fala": {"type": "string", "maxLength": validacao.MAX_FALA, "description": "O que a pessoa fala, em português, ou \"\" sem fala. Com audio_fala é opcional e só guia a boca."},
                              "som": {"type": "string", "maxLength": validacao.MAX_SOM, "description": "O som ambiente, em inglês e curto, ou \"\"."},
                              "camera": {"type": "string", "enum": list(CAMERAS)},
                              "duracao": {"type": "number", "enum": list(DURACOES), "description": "Segundos; respeite o limite de regras_das_tomadas. Obrigatória sem audio_fala; com audio_fala não mande: vem do corte do áudio."}},
                                    "required": ["acao", "camera"]}},
              "cena": {"type": "string", "maxLength": validacao.MAX_CENA, "description": "Em inglês. Com imagem (opcional): onde acontece, o lugar e a luz atrás da pessoa; "
                                                        "sem ela, o lugar da receita ou o padrão do estúdio. Na cena_texto (obrigatória): o estilo, "
                                                        "o lugar, a luz e quem aparece."},
              "modelo_tomada1": {"type": "string", "description": "De listar_modelos_video."}, "modelo_seguintes": {"type": "string"},
              "semente": {**SEMENTE, "description": "Só com pedido. No ver_log, \"semente 2126\" na tomada 1 = 2026 (+100 por tomada)."},
              "loras": {"type": "array", "maxItems": validacao.MAX_LORAS_VIDEO,
                        "items": {"type": "object", "properties": {"nome": {"type": "string"}, "forca": {"type": "number", "minimum": 0.05, "maximum": 1.5}},
                                  "required": ["nome"]}}},
           "required": ["receita", "formato", "tomadas"]}, AMBOS, planejar_video)

registrar("listar_modelos_video",
          "Modelos e LoRAs de estilo para o planejar_video, com as regras. "
          "Quando usar: o usuário pediu um visual, estilo ou LoRA (\"cara de cinema\", \"stop motion\"). "
          "Quando não usar: sem esse pedido (vale o padrão); no modo livre. Exemplo: {}.",
          SEM_ARGUMENTOS, AMBOS, listar_modelos_video)

registrar("regras_do_modo_livre",
          "Devolve as regras do modo livre: um vídeo de UMA tomada no MiniMax H3 com um prompt escrito por você e de 1 a 15 referências "
          "do usuário (fotos, vídeos, áudios), citadas no prompt como @nome. Traz os limites, as durações aceitas na resolução, o papel de "
          "cada tipo de referência, o formato de seis partes do prompt com um modelo preenchido e os erros comuns. "
          "Só mande resolucao se o usuário pedir uma com essas palavras (\"em 720p\"): \"480p\", \"540p\", \"720p\" ou \"maxima\". Sem ela vale 540p, a mais rápida já testada. O tamanho da foto (720x1280, por exemplo) não é a resolução do vídeo. "
          "Quando usar: quando o usuário quiser usar fotos, vídeos ou áudios dele como referência num vídeo e escrever o prompt livre, "
          "antes de planejar_video_livre. "
          "Quando não usar: para vídeos de receita (fala_camera, podcast, anuncio_vertical, cena_texto), que usam regras_das_tomadas. "
          "Exemplo: {} (sem argumentos).",
          {"type": "object", "properties": {"resolucao": RESOLUCAO_LIVRE}}, AMBOS, regras_do_modo_livre)

registrar("planejar_video_livre",
          "Planeja um vídeo do modo livre sem gerar nada: você manda o prompt que escreveu seguindo regras_do_modo_livre e as referências "
          "(nome e mídia de listar_midias); o estúdio confere com a mesma validação da página. Devolve um código de plano e um resumo com "
          "o prompt inteiro, que você mostra ao usuário antes de confirmar. O resumo pode trazer linhas \"Aviso:\", que você repassa. "
          "O estúdio recusa o prompt que não tiver as seis partes e a referência enviada que o prompt não cita. "
          "Se recusar, corrija pela mensagem e chame de novo. "
          "Quando usar: depois de regras_do_modo_livre, quando o usuário quiser um vídeo com as próprias fotos, vídeos ou áudios de referência. "
          "Quando não usar: vídeos de receita (planejar_video) ou começar a geração (confirmar_plano). "
          "Exemplo: {\"prompt\": \"subject_definitions:\\n<Subject 1> is the young woman from @ana...\", "
          "\"referencias\": [{\"nome\": \"ana\", \"midia\": \"ana.png\"}, {\"nome\": \"voz\", \"midia\": \"voz.wav\"}], "
          "\"formato\": \"9:16\", \"duracao\": 5}. Só mande resolucao se o usuário pediu uma.",
          {"type": "object", "properties": {
              "prompt": {"type": "string", "maxLength": video_avancado.MAX_PROMPT,
                         "description": "O prompt de uma tomada, em inglês, nas seis partes de regras_do_modo_livre; cada referência citada como @nome."},
              "referencias": {"type": "array", "minItems": 1, "maxItems": sum(video_avancado.LIMITES.values()),
                              "description": "De 1 a 15 referências: até 9 fotos, 3 vídeos e 3 áudios.",
                              "items": {"type": "object", "properties": {
                                  "nome": {"type": "string", "description": "O nome para citar no prompt como @nome: começa com letra; letras sem acento, números, _ ou -."},
                                  "midia": {"type": "string", "description": "Nome da mídia do estúdio (listar_midias)."}},
                                        "required": ["nome", "midia"]}},
              "formato": {"type": "string", "enum": list(planos.FORMATOS)},
              "resolucao": RESOLUCAO_LIVRE, "semente": SEMENTE,
              "duracao": {"type": "number", "enum": list(DURACOES), "description": "Segundos de uma tomada só; só valem as durações que regras_do_modo_livre mostra para a resolução."}},
           "required": ["prompt", "referencias", "formato", "duracao"]}, AMBOS, planejar_video_livre)

registrar("planejar_imagem",
          "Planeja uma imagem sem gerar; devolve código e resumo para mostrar ao usuário. "
          "Sem imagens: gera do texto (pode ser em português). "
          "Com 1 imagem: edita (instrução em inglês, como \"change the shirt to red, keep the same face\"), "
          "ou muda o estilo dela com estilo, sem prompt. "
          "Com 2 a 4: junta as fotos (cite \"image 1\", \"image 2\" na ordem). "
          "Quando usar: o usuário pede uma imagem nova ou mudar ou juntar fotos dele. "
          "Quando não usar: vídeo (planejar_video) ou começar a geração (confirmar_plano). "
          "Exemplo: {\"prompt\": \"um gato astronauta, foto realista\"}. Só mande formato ou quantidade se o usuário pediu.",
          {"type": "object", "properties": {
              "prompt": {"type": "string", "maxLength": 2000, "description": "O que deve aparecer."},
              "estilo": {"type": "string", "enum": list(estilos.ESTILOS), "description": "realista: desenho vira foto"},
              "qualidade_alta": {"type": "boolean"},
              "formato": {"type": "string", "enum": list(planos.FORMATOS_IMAGEM), "default": "2:3",
                          "description": "Só ao gerar do texto."},
              "quantidade": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1}, "semente": SEMENTE,
              "imagens": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                          "description": "Opcional: nomes de fotos de listar_midias, na ordem de \"image 1\", \"image 2\"."}},
           "required": []}, AMBOS, planejar_imagem)

registrar("usar_resultado",
          "Transforma o resultado pronto de um projeto numa mídia do estúdio. A imagem vira foto (serve em planejar_imagem e planejar_video); "
          "o vídeo vira vídeo (serve só em planejar_video_livre, como referência). "
          "Quando usar: quando o usuário quiser continuar a partir de uma imagem ou de um vídeo que o estúdio gerou (editar a imagem, "
          "usar de referência). "
          "Quando não usar: para baixar ou ver o resultado (use ver_resultado), com projeto ainda gerando, ou para uma mídia que o usuário enviou (ela já aparece em listar_midias). "
          "Exemplo: {\"projeto\": \"mcp_imagem_20261122_153000_a1b2\"}.",
          {"type": "object", "properties": {
              "projeto": {"type": "string", "description": "Nome do projeto (de confirmar_plano ou listar_projetos)."},
              "imagem": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1, "description": "Só se o projeto tem várias imagens e o usuário escolheu uma."}},
           "required": ["projeto"]}, AMBOS, usar_resultado)

registrar("confirmar_plano",
          "Começa a geração de um plano de planejar_video, planejar_video_livre ou planejar_imagem, ou põe na fila se já houver uma geração. Um plano vale 30 min e só pode ser "
          "confirmado uma vez. "
          "Quando usar: só depois que o usuário viu o resumo do plano e respondeu que aprova (\"ok\", \"pode gerar\"). "
          "Quando não usar: sem a resposta do usuário, nunca; nem para mudar o plano (planeje de novo). "
          "Exemplo: {\"codigo_plano\": \"a1b2c3\"}.",
          {"type": "object", "properties": {"codigo_plano": {"type": "string"}}, "required": ["codigo_plano"]}, AMBOS, confirmar_plano)


registrar("pedir_envio",
          "Cria o link para o usuário (ou o agente) mandar uma foto, um áudio ou um vídeo ao estúdio. O link de envio só existe na "
          "resposta desta ferramenta: nunca escreva um link por conta própria. "
          "Devolve o link, o comando curl e o limite de tamanho. O link vale 1 hora e para um envio só. "
          "Quando usar: sempre que o usuário disser que quer mandar, enviar ou subir um arquivo dele (a foto do rosto, a voz, um vídeo) que ainda não aparece em listar_midias. "
          "Quando não usar: se a mídia já aparece em listar_midias. "
          "Exemplo: {\"tipo\": \"foto\"}.",
          {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["foto", "audio", "video"], "description": "O que será enviado."}},
           "required": ["tipo"]}, AMBOS, pedir_envio)

registrar("listar_midias",
          "Lista as fotos, áudios e vídeos enviados ao estúdio que ainda existem, uma por linha: o nome, o tipo, as medidas e há quanto tempo chegou. "
          "Quando usar: depois de um envio (para ver o nome com que a mídia ficou) e antes de planejar um vídeo que usa uma mídia enviada. "
          "Quando não usar: para ver os vídeos prontos (use listar_projetos) ou os personagens (use listar_personagens). "
          "Exemplo: {\"tipo\": \"foto\"}.",
          {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["foto", "audio", "video"], "description": "Só deste tipo; sem ele, todos."}}},
          AMBOS, listar_midias)


registrar("importar_url",
          "Baixa uma foto, um áudio ou um vídeo de um endereço público da internet para o estúdio. Só aceita http:// ou https:// de sites públicos "
          "(nunca endereços da rede interna) e para no limite de tamanho: 50 MB para foto e áudio, 200 MB para vídeo. "
          "Quando usar: quando o usuário dá o endereço de um arquivo na internet (um link direto para a foto, o áudio ou o MP4). "
          "Quando não usar: se o arquivo está no computador do usuário (use pedir_envio), se é uma página que só mostra o arquivo (peça o link direto dele) "
          "ou se a mídia já aparece em listar_midias. "
          "Exemplo: {\"url\": \"https://exemplo.test/foto.png\", \"tipo\": \"foto\"}.",
          {"type": "object", "properties": {"url": {"type": "string", "description": "Endereço direto do arquivo, http:// ou https://."},
                                            "tipo": {"type": "string", "enum": ["foto", "audio", "video"], "description": "O que o arquivo é."}},
           "required": ["url", "tipo"]}, AMBOS, importar_url)


# --- Nivel completo (o Claude Code): so aparecem para a chave completa ---
COMPLETO = {"completo"}

registrar("chamar_api",
          "Chama uma rota POST /api/ do estúdio, a mesma que a página usa, com a mesma validação e as mesmas confirmações "
          "(para apagar de verdade, mande confirmar: true nos dados). Devolve o JSON da resposta; o erro do estúdio vira erro da ferramenta. "
          "Não liga nem desliga o estúdio (/api/desligar) e não envia arquivos (use enviar_arquivo). "
          "Exemplo: {\"rota\": \"/api/apagar\", \"dados\": {\"projeto\": \"mcp_podcast_20261121_153000\"}}.",
          {"type": "object", "properties": {
              "rota": {"type": "string", "enum": mcp_completo._rotas(), "description": "Rota POST da API do estúdio."},
              "dados": {"type": "object", "description": "Corpo JSON da chamada, como a página manda."}},
           "required": ["rota"]}, COMPLETO, chamar_api)

registrar("enviar_arquivo",
          "Envia uma foto, um vídeo MP4 ou um áudio para o estúdio (mesma validação do envio pela página). Até 20 MB depois de decodificar; "
          "acima disso, use pedir_envio ou importar_url (a página também serve). "
          "Exemplo: {\"tipo\": \"foto\", \"nome\": \"rosto.png\", \"conteudo_base64\": \"iVBORw0KGgo...\"}.",
          {"type": "object", "properties": {
              "tipo": {"type": "string", "enum": ["foto", "video", "audio"]},
              "nome": {"type": "string", "description": "Nome do arquivo, com a extensão."},
              "conteudo_base64": {"type": "string", "description": "Conteúdo do arquivo em base64."}},
           "required": ["tipo", "nome", "conteudo_base64"]}, COMPLETO, enviar_arquivo)

registrar("ver_log",
          "Mostra o fim do log do estúdio (logs/estudio.log), para achar o motivo de uma falha. "
          "Exemplo: {\"linhas\": 50}.",
          {"type": "object", "properties": {"linhas": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Quantas linhas do fim."}},
           "required": ["linhas"]}, COMPLETO, ver_log)
