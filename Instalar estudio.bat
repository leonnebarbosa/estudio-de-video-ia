@echo off
rem Instala o Estudio de video num PC novo, ou baixa mais modelos depois. Abre uma pagina no navegador.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\iniciar.ps1"
if errorlevel 1 pause
