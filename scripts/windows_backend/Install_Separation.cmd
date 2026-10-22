@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%~dp0.venv-separation\Scripts\python.exe" goto missing
"%~dp0.venv-separation\Scripts\python.exe" -u "%~dp0prepare_and_preview.py"
set "ACANE_RESULT=%ERRORLEVEL%"
echo.
echo Send backend-check-report.json back to this chat.
pause
exit /b %ACANE_RESULT%
:missing
echo Existing GPU environment was not found.
echo Extract these files into the SAME folder as Install_GPU.cmd and .venv-separation.
echo Do not move or delete the existing environment.
pause
exit /b 1
