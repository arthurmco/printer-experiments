# printer-experiments

Um conjunto de scripts que eu usei pra gerar a minha talk na GambiConf 2021,
"Seja seu próprio CUPS"

(Quando eu criar a minha conta no speakerdeck eu boto os slides aqui)

## Arquivos:

 - server.py: Escuta na mesma porta da impressora e dumpa as mensagens que
   recebe para um arquivo.
 - epsonserver.py: O servidor que emula a impressora. Ele lê o dump do
   *server.py* e gera uma imagem, o que a impressora geraria. Ele só mostra a
   primeira página, então não se assuste se ele não mostrar tudo.
 - printstatus.py: script que pega informações de status da impressora (o status
   dela e seus erros)
 - printtest.py: imprime uma imagem. Esse script é feito para imprimir imagens
   relativamente pequenas (512x512) em um tamanho grande, então tome cuidado com
   o que você vai imprimir, pode ser que passe da folha
