@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Execute install_windows.bat primeiro.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python main.py analyze --transcript "examples\GMT20260717-114920_Recording.transcript.vtt" --output output --speaker "RAFAEL FOSSALUSSA"
pause
