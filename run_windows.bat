@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Execute install_windows.bat primeiro.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
streamlit run app.py
