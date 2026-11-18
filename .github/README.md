# Estúdio de vídeo com IA

Um estúdio de imagem e vídeo com IA que roda **no seu computador**, pelo navegador, em português. Por baixo é o [ComfyUI](https://github.com/comfyanonymous/ComfyUI), mas você não precisa abrir nó nenhum: cada coisa que dá para fazer tem a sua aba, com os ajustes já testados.

- **Texto para imagem**: descreva e gere uma foto (entende português). Também edita uma imagem pronta: trocar roupa, fundo, cor.
- **Imagem para vídeo**: dá movimento, fala e som a uma imagem, em tomadas, com a mesma voz do começo ao fim.
- **Texto para vídeo**: um vídeo com som só a partir do texto.
- **Trocar personagem**: em **foto** (o rosto, a roupa ou os dois, vindos de outras fotos) ou em **vídeo** (outra pessoa no lugar, mantendo os movimentos e a fala, em trechos de até 15 s).
- **Personagens**: guarde um personagem com a foto de frente e os ângulos, para reaproveitar nas trocas e nos vídeos.
- **Continuar vídeo**: estende um vídeo que você já tem, com uma IA local escrevendo cada trecho.
- **Projetos** e **Explorar**: tudo o que foi gerado, para assistir, refazer, ampliar para Full HD e usar de novo.
- **Fila**: deixe várias gerações na fila; elas rodam uma depois da outra.

Nada vai para a nuvem: os modelos rodam na sua placa de vídeo e os arquivos ficam na sua pasta.

## Do que precisa

- Windows 10 ou 11.
- Placa de vídeo **NVIDIA**: 8 GB para as imagens; **10 GB** para os vídeos. Testado numa RTX 3080 de 10 GB.
- **16 GB de RAM** para as imagens; **32 GB** para os vídeos.
- Espaço no disco: uns 25 GB para começar (o primeiro pacote); cada pacote de vídeo pede mais 27 a 51 GB.

## Instalar

1. Baixe o estúdio (no GitHub: **Code > Download ZIP**) e extraia numa pasta curta, como `C:\Estudio`. Evite pastas sincronizadas (OneDrive): os modelos são arquivos muito grandes.
2. Clique duas vezes em **`Instalar estudio.bat`**. Em segundos abre uma página no navegador.
3. Deixe marcado o pacote **Imagens rápidas** e clique em **Instalar e baixar**. A página baixa o ComfyUI, os complementos e os modelos, mostrando o progresso de cada um. Leva de 10 a 40 minutos, conforme a internet.
4. Clique em **Abrir o estúdio** e gere a primeira imagem na aba **Texto para imagem**.

Depois, o estúdio abre pelo atalho **Estúdio de vídeo** na área de trabalho. Os outros pacotes se baixam quando você quiser, pelo atalho **Estúdio de vídeo - baixar modelos** ou pelo botão que aparece na aba que precisa deles. Rodar o instalador de novo pula o que já está feito.

| Pacote | Modelo | Tamanho | Libera |
|---|---|---|---|
| Imagens rápidas | Z-Image Turbo | 11 GB | Texto para imagem |
| Editar imagem | FLUX.2 Klein 4B | 10 GB | Editar imagem, Trocar personagem em foto |
| Vídeo com som | MiniMax H3 | 39 GB | Imagem para vídeo, Texto para vídeo |
| Continuar e trocar personagem | MiniMax H3 ref2va | 51 GB | Continuar vídeo, Trocar personagem em vídeo, Ampliar para Full HD, Descrever imagem |
| Vídeo com Wan 2.2 | Wan 2.2 I2V (GGUF) | 27 GB | Imagem para vídeo com o Wan |

Cada arquivo é baixado do endereço oficial, com retomada se a internet cair e conferência do conteúdo (sha256) no fim.

## Usar com responsabilidade

As abas de troca de personagem põem o rosto de uma pessoa em outra imagem ou vídeo. Use só fotos de pessoas que autorizaram o uso da imagem delas, ou de personagens fictícios. O estúdio pede essa confirmação antes de cada troca. Não use para enganar, difamar ou criar conteúdo íntimo de alguém sem consentimento: além de errado, é crime em muitos países, inclusive no Brasil.

## Licenças

O código do estúdio é livre, sob a licença [MIT](../LICENSE). Os modelos de IA **não** fazem parte deste repositório: o instalador baixa cada um do repositório oficial do autor, e cada um tem a sua licença (alguns só permitem uso não comercial). Confira a licença de cada modelo antes de usar o resultado comercialmente.

Também vêm junto: o detector de rosto YuNet ([OpenCV Zoo](https://github.com/opencv/opencv_zoo), MIT) e as fontes Inter e Archivo (SIL Open Font License, em `estudio/pagina/fontes/OFL.txt`).

## Opcional

- **WanGP**: um segundo motor para a troca de personagem em vídeo. Se a pasta `WanGP` com o [WanGP](https://github.com/deepbeepmeep/Wan2GP) instalado estiver ao lado da pasta do estúdio, ele aparece como opção na aba Trocar personagem.
- **LM Studio**: se você conversa com uma IA no [LM Studio](https://lmstudio.ai), o estúdio descarrega o modelo dele antes de gerar, para liberar a placa.

## Se algo der errado

- Se o atalho não abrir, use `estudio\Abrir estudio.bat`: ele abre com uma janela que mostra mensagens e erros.
- Se o ComfyUI cair, o estúdio o religa (até 2 tentativas) e avisa na página. O botão **Fechar o estúdio** fecha o ComfyUI junto e libera a placa.
- O registro técnico de cada geração fica na pasta do projeto, em `projetos\<nome>\execucao.log`.

## Para quem quer mexer no código

O estúdio é Python (só a biblioteca padrão, no Python que vem com o ComfyUI portátil) e uma página em HTML, CSS e JavaScript puros, sem etapa de compilação.

O ComfyUI fica dentro da pasta, em `ComfyUI_windows_portable`. Um ComfyUI portátil que já esteja na pasta de cima é usado no lugar. Um `local.json` na pasta muda o lugar e as portas: `{"comfy": "E:\\ComfyUI_windows_portable", "porta": 8190, "porta_comfy": 8188}`.

O instalador fixa as versões para sair igual ao testado: `instalador/nos.json` (cada nó extra num commit), `instalador/requisitos_estudio.txt` (os pacotes Python) e `estudio/pacotes.json` (cada modelo com endereço, tamanho e sha256).

Modelos e LoRAs da comunidade testados numa máquina entram por dois arquivos dela, fora do git: `modelos_locais.json` (as opções extras das telas, lido por `estudio/extras.py`) e `catalogo_local.json` (as anotações da aba Modelos). Sem eles, o estúdio funciona só com os oficiais.

**Testes**: um comando roda todos (de qualquer pasta) e sai com código 1 se algum falhar. Eles usam processo, relógio e pastas falsos: não ligam o ComfyUI nem usam a placa.

```
ComfyUI_windows_portable\python_embeded\python.exe -I estudio\rodar_testes.py
```

| Arquivo | Para que serve |
|---|---|
| `estudio/estudio.pyw` | Ponto de entrada: liga o servidor e abre o navegador |
| `estudio/config.py` | Caminhos e constantes |
| `estudio/servidor.py`, `acoes.py` | Servidor local, rotas da página e o que cada botão faz |
| `estudio/tarefa.py`, `fila.py`, `retomada.py` | A geração em andamento, a fila e a retomada depois de uma queda |
| `estudio/vigia.py`, `recursos.py` | Liga, vigia e religa o ComfyUI; CPU, RAM, placa e disco do topo |
| `estudio/texto_para_imagem.py`, `troca_foto.py` | Imagens, edição e troca de personagem em foto |
| `estudio/imagem_para_video.py`, `wan_para_video.py` | Vídeo por tomadas no H3 e no Wan |
| `estudio/trocar_personagem.py`, `cortes.py`, `fundo.py`, `troca_wangp.py` | Troca de personagem em vídeo (janelas, cortes de câmera, fundo novo, motor WanGP) |
| `estudio/personagens.py`, `rostos_video.py` | Biblioteca de personagens e rostos tirados de um vídeo |
| `estudio/continuar_video.py`, `acabamento.py` | Continuar vídeo e ampliar para Full HD |
| `estudio/projetos.py`, `modelos.py`, `pacotes.py` | Projetos, aba Modelos e os pacotes do instalador |
| `estudio/validacao.py`, `envio.py` | Conferência do que a página envia |
| `estudio/grafos/` | Os grafos do ComfyUI usados pelos scripts |
| `estudio/pagina/` | HTML, CSS e JS da página |
| `estudio/testes/` | Os testes (`rodar_testes.py` roda todos) |
| `Instalar estudio.bat`, `instalador/` | Instalador: Python mínimo e página de boas-vindas |
| `rodar_comfy_lowvram.ps1` | Referência das opções de pouca VRAM com que o estúdio liga o ComfyUI |
