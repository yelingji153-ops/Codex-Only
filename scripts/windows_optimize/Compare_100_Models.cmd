@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "OMP_NUM_THREADS=2"
if not exist "%~dp0.venv-training\Scripts\python.exe" goto missing
"%~dp0.venv-training\Scripts\python.exe" "%~dp0optimize-addon\compare_models.py"
pause
exit /b
:missing
echo Extract this package beside Start_ACAne.cmd. Training environment not found.
pause
