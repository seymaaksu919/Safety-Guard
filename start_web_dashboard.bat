@echo off
cd /d "%~dp0"
echo Safety Guard Web Dashboard baslatiliyor...
echo Tarayici: http://127.0.0.1:5003/
echo.
".venv\Scripts\python.exe" dashboard_api.py
pause
