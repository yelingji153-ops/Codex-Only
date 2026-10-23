@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
echo ACAne training - all saved segments. Keep this window open.
if exist ".venv-separation\Scripts\python.exe" goto existing
py -3.12 training-addon\start_training.py
 goto done
:existing
".venv-separation\Scripts\python.exe" training-addon\start_training.py
:done
pause
