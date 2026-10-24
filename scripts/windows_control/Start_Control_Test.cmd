@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
if not exist "%~dp0.venv-training\Scripts\python.exe" goto missing
"%~dp0.venv-training\Scripts\python.exe" "%~dp0control-addon\control_test.py"
pause
exit /b
:missing
echo Training environment not found. Extract beside Start_ACAne.cmd.
pause
