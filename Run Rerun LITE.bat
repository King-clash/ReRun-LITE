@echo off
cd /d "%~dp0"
set PY=pythonw
where pythonw >nul 2>nul || set PY="%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
start "" %PY% lite_main.py
