@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if exist "%~dp0tools\ffmpeg\bin\ffmpeg.exe" set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
set "ACANE_LIBRARY=%~1"
if not defined ACANE_LIBRARY set "ACANE_LIBRARY=%~dp0workspace-data"
echo ACAne vocal separation workbench. Keep this window open while using the app.
if exist "%~dp0.venv-separation\Scripts\python.exe" goto existing_env
py -3.12 -m acane --library "%ACANE_LIBRARY%" serve
if errorlevel 1 pause
exit /b
:existing_env
"%~dp0.venv-separation\Scripts\python.exe" -m acane --library "%ACANE_LIBRARY%" serve
if errorlevel 1 pause
