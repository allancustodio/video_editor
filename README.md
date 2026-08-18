# Trade Video Cutter

Projeto local para:

1. Ler uma transcrição `.vtt` com timestamps.
2. Detectar entradas, alvos, stops, zeragens e retiradas de risco.
3. Gerar `cuts.json` e um relatório HTML para revisão.
4. Cortar o vídeo local com FFmpeg.
5. Opcionalmente refinar os candidatos com Ollama ou Gemini.

O vídeo nunca é enviado para a IA. No modo Gemini, somente pequenos trechos da transcrição são enviados.

## Forma recomendada: executar com npm

### Pré-requisitos

- Node.js 18 ou superior.
- Python 3.11 ou superior.
- FFmpeg instalado no computador.

Abra o terminal dentro da pasta do projeto e execute:

```bash
npm install
npm run dev
```

O `npm install` cria automaticamente o ambiente Python `.venv` e instala as dependências. Depois, `npm run dev` abre a aplicação em:

```text
http://localhost:8501
```

Nos próximos usos, basta executar:

```bash
npm run dev
```

Outros comandos disponíveis:

```bash
npm run setup             # recria/atualiza as dependências Python
npm run analyze:example   # analisa a transcrição de exemplo
npm start                 # mesmo comportamento de npm run dev
```

Para encerrar o servidor, pressione `Ctrl + C` no terminal.

## Teste rápido no Windows

### 1. Pré-requisitos

- Python 3.11 ou superior.
- FFmpeg disponível no `PATH`, ou o caminho do `ffmpeg.exe` informado na interface.

Para confirmar:

```bat
py --version
ffmpeg -version
```

Caso o FFmpeg não esteja instalado, execute `install_ffmpeg_windows.bat`, feche o terminal e abra novamente.

### 2. Instalar

Clique duas vezes em:

```text
install_windows.bat
```

### 3. Abrir a interface

Clique duas vezes em:

```text
run_windows.bat
```

O navegador abrirá em `http://localhost:8501`.

A transcrição enviada nesta conversa já está em `examples/`. Clique em **Analisar transcrição** para testar imediatamente.

Depois informe o caminho completo do vídeo, por exemplo:

```text
C:\Users\Allan\Videos\GMT20260717-114920_Recording.mp4
```

Revise a tabela, monte as cenas e clique em **Exportar vídeo final**.

As visualizações do vídeo original são carregadas somente ao clicar em
**Carregar prévia leve**. A aplicação gera e reutiliza um arquivo temporário
reduzido, com no máximo dois minutos, para não manter a gravação completa na
memória. Isso não altera a resolução nem a duração dos cortes finais.

## Montagem de cenas e vídeo final

Os trechos selecionados são reunidos, pela coluna **Ordem**, em um único MP4.
Cada trecho possui uma linha do tempo própria: use **Dividir cena** para criar
quantas mudanças forem necessárias, **Começar vídeo aqui** para descartar o
contexto anterior e escolha uma composição para cada cena:

- gráfico em tela inteira;
- professor em tela inteira;
- professor em cima e gráfico embaixo;
- gráfico em cima e professor embaixo;
- professor e gráfico lado a lado.

Todas as composições funcionam em **Vertical 9:16** e **Horizontal 16:9**. Em
cada cena, professor e gráfico têm controles independentes de zoom e posição.
Também é possível restaurar o enquadramento, copiar o da cena anterior ou
aplicá-lo às demais cenas com a mesma composição.

A linha do tempo precisa cobrir o trecho inteiro, sem buracos ou sobreposições.
O áudio permanece contínuo e pode vir do vídeo do professor ou da tela. A ação
**Exportar vídeo final** normaliza as cenas e gera um único arquivo MP4.

### Capa e encerramento

Abra **Capa e encerramento** na montagem final e informe somente a data do
trade e o número de pontos. A aplicação gera automaticamente duas artes
verticais em 1080 × 1920 usando os templates da marca:

- a capa pode ser baixada em PNG para publicação no Instagram;
- o encerramento também pode ser baixado separadamente em PNG;
- **Adicionar ao início do vídeo** inclui a capa por três segundos;
- **Adicionar ao final do vídeo** inclui o encerramento por quatro segundos.

As duas inclusões são independentes e ficam desmarcadas por padrão. Mesmo sem
incluí-las no MP4, os downloads continuam disponíveis. Ao exportar um projeto,
as artes geradas são salvas como `capa.png` e `encerramento.png`. Em projetos
horizontais, as artes verticais são centralizadas com laterais pretas.

### Palavras de 1x e efeitos

Abra **Palavras de 1x e efeitos** para editar a lista usada por **Sugerir cenas
pela transcrição**. Cada palavra ou frase pode ser ativada, mantida em 1x e
associada a um efeito curto: nenhum, tremor, flash dourado ou tremor com texto.
A configuração é salva em `scene_keyword_rules.json` e a busca ignora acentos e
maiúsculas.

O padrão inclui “delícia” com **Tremor + texto**. O instante é estimado pela
mesma divisão por palavra usada na legenda com highlight; portanto o efeito
acompanha a fala, mesmo quando ela está dentro de uma legenda maior. Tudo é
renderizado no próprio FFmpeg, sem uma etapa externa. Ao desmarcar uma ocorrência
na revisão da proposta, tanto a região em 1x quanto seu efeito são removidos.

### Prova social do chat do Zoom

A área **Prova social do chat do Zoom** funciona de forma independente dos
cortes. Ela procura arquivos `*Chat.txt` na pasta do vídeo, interpreta mensagens
multilinha, respostas e reações e faz uma triagem totalmente local, sem IA ou
API.

Em **Professores e palavras**, é possível editar os nomes completos dos autores
internos que devem ser excluídos, seus apelidos, as expressões positivas e
negativas, a pontuação, os limites e o intervalo de agrupamento. A exclusão de
autor usa o nome completo; apelidos servem somente para reconhecer menções nos
textos.

Depois da análise, a tabela informa a pontuação e todas as regras encontradas.
Os candidatos fortes vêm selecionados, mas cada mensagem pode ser conferida com
o contexto, aprovada, descartada e reordenada. A geração produz:

- painéis verticais paginados com até oito comentários no estilo do Zoom;
- uma arte individual opcional para cada depoimento;
- um ZIP com todas as imagens;
- um JSON com a seleção aprovada para reutilização futura;
- uma cena MP4 vertical independente, com os comentários aparecendo em sequência.

As artes exibem somente o primeiro nome. O nome completo permanece nos dados
internos para identidade, exclusão e atribuição consistente de cor. A data e o
horário são reconstruídos a partir do nome GMT do arquivo e podem ser ajustados
na interface.

A paginação pode ser automática ou manual. No modo manual, informe a quantidade
de comentários de cada página, como `6, 4, 5`; os valores consomem a ordem da
tabela de revisão. A interface calcula a ocupação de cada página, bloqueia
combinações que ultrapassem a área segura e pode sobrepor as zonas mortas na
prévia. Esses guias nunca entram nos PNGs baixados.
O mesmo layout protege as duas laterais, o topo e o rodapé para que as artes
possam ser reutilizadas tanto em Stories quanto em Reels e, futuramente, no vídeo.

Ao gerar as imagens, os painéis, as artes individuais, o ZIP e o JSON aprovado
são gravados automaticamente na **Pasta de saída** configurada na interface. Os
botões de download continuam disponíveis como alternativa. Gerar somente o vídeo
também salva nesse local o JSON que descreve a seleção usada.

Em **Vídeo animado da prova social**, o intervalo entre comentários, a pausa na
troca de página, o tempo final de leitura, o som e seu volume são configuráveis.
O pequeno pop é sintetizado pelo FFmpeg, sem arquivo ou serviço externo. O MP4 é
salvo na pasta de saída compartilhada, mas não é inserido automaticamente no
vídeo final.

## Modo sem interface

### Somente analisar

```bat
python main.py analyze ^
  --transcript "C:\Videos\gravacao.transcript.vtt" ^
  --output output ^
  --speaker "RAFAEL FOSSALUSSA"
```

### Cortar usando o `cuts.json`

```bat
python main.py cut ^
  --video "C:\Videos\gravacao.mp4" ^
  --cuts output\cuts.json ^
  --output output\clips ^
  --mode exact
```

### Montar todas as cenas em um único arquivo

```bat
python main.py assemble ^
  --video "C:\Videos\tela.mp4" ^
  --professor-video "C:\Videos\professor.mp4" ^
  --cuts output\cuts.json ^
  --output output\video-final.mp4 ^
  --orientation vertical ^
  --audio-source professor
```

### Analisar e cortar de uma vez

```bat
python main.py all ^
  --transcript "C:\Videos\gravacao.transcript.vtt" ^
  --video "C:\Videos\gravacao.mp4" ^
  --output output ^
  --speaker "RAFAEL FOSSALUSSA" ^
  --mode exact
```

## Modos de análise

### Regras locais

Funciona imediatamente, offline e sem chave. É o modo padrão.

```bat
python main.py analyze --transcript gravacao.vtt --provider rules
```

### Ollama local

Instale o Ollama e baixe um modelo:

```bat
ollama pull qwen3:8b
```

Depois:

```bat
python main.py analyze ^
  --transcript gravacao.vtt ^
  --provider ollama ^
  --model qwen3:8b
```

O detector por regras encontra candidatos e o Ollama confirma/refina cada trecho usando saída JSON estruturada.

### Gemini

Defina a chave no terminal:

```bat
set GEMINI_API_KEY=SUA_CHAVE
```

E execute:

```bat
python main.py analyze ^
  --transcript gravacao.vtt ^
  --provider gemini ^
  --model gemini-2.5-flash
```

## Biblioteca de gravações

Na barra lateral, informe uma pasta padrão para a biblioteca e clique em **Salvar pasta**. O caminho fica apenas no arquivo local user_config.json, que não é enviado ao Git.

A aplicação procura também nas subpastas e agrupa os arquivos pelo timestamp compartilhado:

```text
GMT20260724-114939_Recording_as_3840x1080.mp4   # tela
GMT20260724-114939_Recording.transcript.vtt     # transcrição
GMT20260724-114939_Recording_avo_1280x720.mp4   # professor
```

As resoluções podem mudar; a identificação usa os marcadores _as_ e _avo_. A lista mostra gravações completas e incompletas. Tela e transcrição são necessárias para carregar; o vídeo do professor é necessário para a montagem final.

Escolher uma opção na lista não troca o trabalho atual imediatamente. Clique em **Carregar gravação** para preencher os três caminhos, carregar o VTT e limpar operações e prévias da gravação anterior.

## Busca e corte manual

Com uma transcrição carregada, use **Buscar uma palavra na transcrição**:

1. Digite uma única palavra. A busca ignora acentos e diferença entre maiúsculas e minúsculas.
2. Escolha uma ocorrência para ver a fala ao redor e abrir o vídeo naquele ponto.
3. Ajuste título, início, fim e área.
4. Clique em **Adicionar corte manual**.

O corte começa exatamente na ocorrência e sugere 30 segundos depois para o fim. O contexto anterior aparece somente na prévia. O novo item entra na tabela dos candidatos automáticos com a fonte manual e pode usar todo o fluxo de cenas e enquadramento.

### Corte por horário anotado

Use **Adicionar corte por horário anotado** quando você já tiver marcado um momento da aula:

1. Informe uma posição do vídeo da tela/gráficos e capture a imagem desse instante.
2. Leia o relógio mostrado na captura, informe-o em HH:MM:SS e confirme a sincronização.
3. Digite o horário real da sua anotação, também em HH:MM:SS.
4. Confira a captura calculada: o relógio da imagem deve coincidir com a anotação.
5. Edite título, início, fim e área e clique em **Adicionar corte pelo horário**.

O sistema converte o horário real para a posição relativa do vídeo antes de consultar
a transcrição, gerar a prévia e criar o corte. O intervalo sugerido começa nessa posição
e termina 30 segundos depois. A sincronização usa sempre o vídeo da tela/gráficos, no
qual o relógio está visível, e é salva no projeto exportado.

O horário do relógio e o horário anotado devem ser informados por completo. Por exemplo,
`14:45:20`. Os campos relativos do vídeo continuam aceitando e normalizando valores
incompletos.

## Gerenciamento de regras

Abra **Gerenciar regras automáticas** para visualizar, ativar, desativar, editar, excluir ou adicionar regras das categorias:

- Preparação;
- Entrada;
- Resultado;
- Negação.

Para regras novas, prefira **Texto simples**: ele ignora acentos e procura a palavra ou frase inteira. O modo **Regex** é avançado e recebe o texto da transcrição já convertido para minúsculas e sem acentos.

As ações são separadas para evitar alterações acidentais:

- **Validar** confere campos, pesos e expressões regulares;
- **Salvar** grava em user_rules.json, mas não altera os cortes atuais;
- **Salvar e reanalisar** aplica as regras à transcrição carregada e preserva cortes manuais;
- **Restaurar padrões** recupera as regras originais.

Direção, ativos, associação entre entrada e resultado, duplicidades e limites de tempo continuam protegidos no código nesta versão.

## Seleção da área e enquadramento

Cada corte pode usar uma destas áreas da gravação da tela:

- `Vídeo completo`
- `Flex - Índice`
- `Flex - Dólar`
- `Profit - Índice`
- `Profit - Dólar`

Na interface, abra **Configurar e conferir as quatro áreas**, capture um frame e ajuste X, Y, largura e altura. A seleção e as coordenadas efetivas ficam salvas em cada operação do `cuts.json`.

Os vídeos da tela e do professor devem compartilhar a mesma linha do tempo. Se necessário, use o ajuste de sincronização disponível na interface.

No editor de cenas, cada fonte visível possui controles para:

- zoom e posição horizontal/vertical do professor;
- alinhamento do gráfico à esquerda, ao centro ou à direita;
- zoom e ajuste fino horizontal/vertical do gráfico;
- áudio por cena (professor, tela ou silêncio);
- velocidade por cena em 1×, 2×, 5×, 10×, 15×, 20×, 25×, 50× ou 100×, além do valor calculado pela sugestão;
- legendas normais ou com highlight dourado por palavra, com filtro opcional pelo apresentador;
- preset de gráfico acelerado e cálculo da duração resultante;
- VTT completo, SRT das legendas e mapa edit.json gerados junto do MP4;
- sugestão sob demanda limitada ao corte atual, procurando `stop`, `lote`, `parcial`, `alvo`, `porcento` e `gain`;
- aprovação individual de cada ocorrência, mostrando horário e frase completa do apresentador;
- contexto configurável antes/depois das falas relevantes (3 segundos por padrão);
- aceleração automática dos intervalos sem fala relevante para cerca de 5 segundos;
- aprovação individual de saltos quando o intervalo exigiria mais de 100×;
- cenas sugeridas com professor em cima, Profit mini índice embaixo e gráfico alinhado à direita;
- cenas aceleradas mudas e sem legendas por padrão, sempre editáveis depois;
- restauração do enquadramento padrão;
- cópia do ajuste da cena anterior;
- aplicação do ajuste às cenas com a mesma composição;
- prévia em imagem e em vídeo de até 10 segundos.

## Modos de corte

- `exact`: recodifica em H.264/AAC e produz horários mais precisos.
- `fast`: usa `-c copy`, termina rapidamente, mas o início pode acompanhar o keyframe anterior.

## Arquivos produzidos

```text
output/
├── 2026-08-01_143218_video-final/
│   ├── 2026-08-01_143218_video-final.mp4
│   ├── 2026-08-01_143218_video-final.srt
│   ├── 2026-08-01_143218_video-final.transcript.vtt
│   ├── 2026-08-01_143218_video-final.edit.json
│   ├── source.transcript.vtt
│   ├── capa.png
│   ├── encerramento.png
│   ├── cuts.json
│   ├── report.html
│   └── project.json
└── clips/
    ├── 01_01-08-01_Venda_no_indice.mp4
    └── ...
```

Cada exportação recebe data e horário no nome da pasta. Se o nome já existir,
é acrescentado `-02`, `-03` e assim por diante. Use **Abrir projeto exportado**
na barra lateral para retomar a edição a partir da pasta ou do `project.json`.
Os vídeos originais não são duplicados; o manifesto guarda seus caminhos.

## Ajustes manuais

Abra `output/cuts.json` ou edite os campos diretamente na interface:

```json
{
  "selected": true,
  "cut_start": 3955.0,
  "cut_end": 4435.0
}
```

Os valores estão em segundos. A interface aceita `HH:MM:SS`.

## Limitações da primeira versão

- Frases ambíguas como “acionou” podem representar uma ordem comentada, e não uma entrada do apresentador.
- O detector depende da qualidade da transcrição e do nome do apresentador.
- A revisão humana continua recomendada antes da renderização final.
- Cortes exatos recodificam o vídeo e usam mais CPU.
