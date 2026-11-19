@echo off
rem Lint + every test + a trial build with its self-test. Leave the mouse and keyboard alone while it runs.
cd /d "%~dp0"
py tools\run_checks.py %*
pause
