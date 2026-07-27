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

Revise a tabela e clique em **Gerar cortes**.

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

## Seleção da área e saída vertical

Cada corte pode usar uma destas áreas da gravação da tela:

- `Vídeo completo`
- `Flex - Índice`
- `Flex - Dólar`
- `Profit - Índice`
- `Profit - Dólar`

Na interface, abra **Configurar e conferir as quatro áreas**, capture um frame e ajuste X, Y, largura e altura. A seleção e as coordenadas efetivas ficam salvas em cada operação do `cuts.json`.

Para criar vídeos verticais em 1080x1920, informe também o vídeo separado do professor e escolha **Vertical 1080x1920 com professor**. O professor ocupa a metade superior e o gráfico escolhido a metade inferior. Por padrão, o áudio vem do vídeo do professor.

Os vídeos da tela e do professor devem compartilhar a mesma linha do tempo. Se necessário, use o ajuste de sincronização disponível na interface.

No modo vertical, abra **Ajustar enquadramento vertical** para controlar:

- zoom e posição horizontal/vertical do professor;
- zoom e posição horizontal/vertical do gráfico;
- restauração do enquadramento padrão;
- imagem vertical rápida antes de gerar a prévia em vídeo de 10 segundos.

Exemplo pela linha de comando:

```bat
python main.py cut ^
  --video "C:\Videos\gravacao-tela.mp4" ^
  --professor-video "C:\Videos\professor.mp4" ^
  --cuts output\cuts.json ^
  --output output\clips ^
  --format vertical ^
  --audio-source professor
```

- O fluxo antigo continua sendo o padrão com `--format original` e área `full`.
- Recorte de área e composição vertical sempre exigem recodificação.
- O modo `fast` continua sem recodificação apenas para o vídeo completo no formato original.

## Modos de corte

- `exact`: recodifica em H.264/AAC e produz horários mais precisos.
- `fast`: usa `-c copy`, termina rapidamente, mas o início pode acompanhar o keyframe anterior.

## Arquivos produzidos

```text
output/
├── cuts.json
├── report.html
└── clips/
    ├── 01_01-08-01_Venda_no_indice.mp4
    └── ...
```

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
