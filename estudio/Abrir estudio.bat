@echo off
rem Abre o estudio com console (alternativa ao atalho): mostra mensagens e erros nesta janela.
rem O ComfyUI portatil fica dentro da pasta do repositorio (instalador) ou ao lado dela.
set "PY=%~dp0..\ComfyUI_windows_portable\python_embeded\python.exe"
if not exist "%PY%" set "PY=%~dp0..\..\ComfyUI_windows_portable\python_embeded\python.exe"
if not exist "%PY%" (
  echo Nao achei o ComfyUI portatil. Rode "Instalar estudio.bat", na pasta de cima.
  pause
  exit /b 1
)
"%PY%" -I "%~dp0estudio.pyw"
pause
