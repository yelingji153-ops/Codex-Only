@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ACANE_LOG=%~dp0gpu-setup-log.txt"
set "ACANE_REPORT=%~dp0gpu-check-report.txt"
set "ACANE_ENV=%~dp0.venv-separation"
set "ACANE_BASE_PY="
> "%ACANE_LOG%" echo ACAne Windows GPU setup: Python 3.12, torch 2.8.0, torchvision 0.23.0, CUDA 12.8
> "%ACANE_REPORT%" echo GPU validation has not completed in this run. See gpu-setup-log.txt.
echo This installs packages in a local .venv-separation folder.
echo Downloads are large. Allow about 10 GB free space.
echo Your NVIDIA driver and system CUDA installation will not be changed.

for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "ACANE_BASE_PY=%%P"
if defined ACANE_BASE_PY goto python_found
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "ACANE_BASE_PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if defined ACANE_BASE_PY goto python_found
echo Python 3.12 was not found. Install the official 64-bit Python 3.12 first.
echo https://www.python.org/downloads/release/python-31210/
>> "%ACANE_LOG%" echo Python 3.12 was not found. No packages installed.
goto failed

:python_found
"%ACANE_BASE_PY%" -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 64-bit required'" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
if exist "%ACANE_ENV%\Scripts\python.exe" goto env_ready
echo Creating isolated Python environment...
"%ACANE_BASE_PY%" -m venv "%ACANE_ENV%" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed

:env_ready
set "ACANE_PY=%ACANE_ENV%\Scripts\python.exe"
"%ACANE_PY%" -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Existing environment must use Python 3.12 64-bit'" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
echo Installing GPU packages. Details are written to gpu-setup-log.txt.
echo This may take a while; please keep this window open.
"%ACANE_PY%" -m pip install --disable-pip-version-check "torch==2.8.0+cu128" "torchvision==0.23.0+cu128" --index-url https://download.pytorch.org/whl/cu128 >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
"%ACANE_PY%" -m pip check >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
echo Running GPU matrix and FFT checks...
"%ACANE_PY%" "%~dp0check_gpu.py" > "%ACANE_REPORT%" 2>&1
if errorlevel 1 goto failed
type "%ACANE_REPORT%"
echo.
echo GPU tensor checks passed. Audio model inference is still untested.
echo Send gpu-check-report.txt back to this chat. Keep this folder for the next step.
pause
exit /b 0

:failed
echo.
echo Setup or validation did not complete successfully.
echo Send BOTH gpu-setup-log.txt and gpu-check-report.txt back to this chat.
echo Keep this folder; do not delete your existing files or reinstall the driver.
pause
exit /b 1
