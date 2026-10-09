@echo off
rem Dois cliques aqui para ligar o servidor do beta (login com Spotify + vitrines).
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"
python -m uvicorn servidor.app:app --host 127.0.0.1 --port 8000
pause
