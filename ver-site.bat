@echo off
rem Dois cliques aqui para ver o site no seu computador.
rem Abre no navegador padrao do Windows. Feche esta janela quando terminar.
cd /d "%~dp0docs"
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"
python -m http.server 8000 --bind 127.0.0.1
