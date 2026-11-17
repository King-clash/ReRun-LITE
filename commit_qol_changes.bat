@echo off
rem Makes a branch, runs the tests, and commits today's ReRun LITE work (the backups folder is left out).
cd /d "%~dp0"
git rev-parse --is-inside-work-tree >nul 2>&1 || (echo This folder is not a git repository. & pause & exit /b 1)
git checkout -b qol-lite-dev 2>nul || git checkout qol-lite-dev
echo.
echo Running the tests (this takes about a minute)...
python -m pytest tests -q
if errorlevel 1 (
  echo.
  echo Some tests failed. Nothing was committed. Fix or tell Claude, then run this again.
  pause & exit /b 1
)
git add -A -- . ":(exclude)backups"
git commit -m "LITE: run states, session tracking and analytics, activity feed, compact mode, notifications, hotkeys, profiles, stuck watch, health page, diagnostics" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01XnroFo5eiGoMq9DB3AoCjW"
echo.
git log --oneline -1
pause
