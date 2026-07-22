@echo off
setlocal
where winget >nul 2>nul
if errorlevel 1 (
  echo WinGet nao encontrado. Instale o FFmpeg manualmente e informe o caminho do ffmpeg.exe na interface.
  pause
  exit /b 1
)
echo Instalando FFmpeg pelo WinGet...
winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
echo.
echo Feche e abra novamente o terminal antes de testar ffmpeg -version.
pause
