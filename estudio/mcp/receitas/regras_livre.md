O prompt do modo livre descreve UMA tomada contínua e tem seis partes, nesta ordem. Cada parte começa uma linha com o nome e dois-pontos. O estúdio recusa o prompt que não tiver as seis.
O prompt é escrito em inglês. A fala fica no idioma em que deve ser dita, dentro de <d>[Portuguese (Brazil)] ...</d>. Cada referência é citada como @nome, o mesmo nome que você manda em referencias.

As seis partes:
subject_definitions: quem é cada <Subject N> e de qual @nome vem; o que se usa de cada referência e o que não se usa. <Subject N> é para pessoas, objetos, roupas ou lugares que vêm de fotos ou vídeos; a referência de voz (áudio) não é um <Subject>: ela é citada na frase da fala ("Speaking in the exact same voice as @voz ...").
summary: uma frase com a duração, o formato e o que acontece.
retention_analysis: o que fica igual à referência do começo ao fim (rosto, roupa, lugar, voz).
detailed_description: a tomada passo a passo: enquadramento, movimento da câmera, ação e a fala em <d>. Conte uns 2,5 palavras por segundo.
overall_soundscape: a voz e o som ambiente.
non_diegetic_music: a trilha; escreva N/A quando não houver.

Modelo preenchido (uma foto @ana e um áudio @voz). Copie e adapte:
```
subject_definitions:
<Subject 1> is the young woman from @ana, preserving her exact face, hair, skin texture and outfit.
summary:
[reference generation] A 5-second vertical video of <Subject 1> standing in a bright kitchen and telling the camera, in Brazilian Portuguese, that the coffee is ready.
retention_analysis:
<Subject 1>: fully_preserved - face, hair, skin and outfit stay identical to @ana in every frame.
detailed_description:
A realistic handheld vertical smartphone-style clip with natural daylight and true-to-life skin, no beauty filter. [Shot 1] <Subject 1> stands in a bright kitchen with a window behind her. The shot opens as a medium shot from the waist up. She smiles and lifts a white cup toward the camera. The handheld camera slowly pushes in during the whole shot. She faces the lens. Speaking in the exact same voice as @voz, with the same pitch and energy, <Subject 1> (S1) says: <d>[Portuguese (Brazil)] O café já está pronto, vem comigo.</d> Her lips and jaw move in clear sync with every word, in a warm, relaxed tone. She ends with a small nod, looking into the lens. Her face and outfit stay consistent in every frame.
overall_soundscape:
<Subject 1>'s voice, the same as @voz, clear and close, speaking Brazilian Portuguese, with a quiet kitchen room tone and a soft clink of the cup.
non_diegetic_music:
N/A
```

Erros comuns:
- Citar @nome que não está em referencias: o estúdio recusa. Mandar uma referência e não citá-la no prompt: o estúdio também recusa.
- Escrever a fala fora do <d>...</d>, ou sem o [Portuguese (Brazil)] no começo.
- Pôr duas tomadas ou cortes no mesmo prompt: um prompt é um [Shot 1] só. Para vários cortes, faça outro vídeo.
- Chamar a referência de outro jeito ("a foto", "Picture 1", "<Audio 1>"): use sempre @nome.
- Pôr mais fala do que cabe na duração: o final fica cortado.
