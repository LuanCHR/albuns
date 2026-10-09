@echo off
rem Dois cliques aqui para atualizar suas playlists.
rem Entra sozinho na pasta certa, instala o que falta, roda o script e oferece abrir o site.
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
python fetch_playlists.py
if errorlevel 1 goto fim
echo.
choice /c SN /n /m "Abrir o site agora para ver o resultado? (S/N) "
if errorlevel 2 goto fim
call "%~dp0ver-site.bat"
:fim
echo.
pause
