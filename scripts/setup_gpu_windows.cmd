@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem Keep redirected Python paths in the same encoding as this console.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "ACANE_LOG=%~dp0gpu-setup-log.txt"
set "ACANE_REPORT=%~dp0gpu-check-report.txt"
set "ACANE_ENV=%~dp0.venv-separation"
set "ACANE_BASE_PY="
> "%ACANE_LOG%" echo ACAne Windows GPU setup v2: Python 3.12, torch 2.8.0, torchvision 0.23.0, CUDA 12.8
> "%ACANE_REPORT%" echo GPU validation has not completed in this run. See gpu-setup-log.txt.
echo This installs packages in a local .venv-separation folder.
echo Downloads are large. Allow about 10 GB free space.
echo Your NVIDIA driver and system CUDA installation will not be changed.

>> "%ACANE_LOG%" echo [1] Locating Python 3.12
>> "%ACANE_LOG%" echo Tool directory: "%~dp0"
rem Prefer known executable paths; do not interpret launcher errors as paths.
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "ACANE_BASE_PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if defined ACANE_BASE_PY goto python_found
if exist "%ProgramFiles%\Python312\python.exe" set "ACANE_BASE_PY=%ProgramFiles%\Python312\python.exe"
if defined ACANE_BASE_PY goto python_found
where py >> "%ACANE_LOG%" 2>&1
py -3.12 -c "import sys; print(sys.executable)" > "%~dp0python-path.txt" 2>> "%ACANE_LOG%"
if errorlevel 1 goto python_path_fallback
for /f "usebackq delims=" %%P in ("%~dp0python-path.txt") do if exist "%%P" set "ACANE_BASE_PY=%%P"
if defined ACANE_BASE_PY goto python_found

:python_path_fallback
where python >> "%ACANE_LOG%" 2>&1
python -c "import sys; assert sys.version_info[:2] == (3,12); print(sys.executable)" > "%~dp0python-path.txt" 2>> "%ACANE_LOG%"
if errorlevel 1 goto python_missing
for /f "usebackq delims=" %%P in ("%~dp0python-path.txt") do if exist "%%P" set "ACANE_BASE_PY=%%P"
if defined ACANE_BASE_PY goto python_found

:python_missing
echo Python 3.12 was not found. Install the official 64-bit Python 3.12 first.
echo https://www.python.org/downloads/release/python-31210/
>> "%ACANE_LOG%" echo Python 3.12 was not found. No packages installed.
goto failed

:python_found
>> "%ACANE_LOG%" echo [2] Checking Python: "%ACANE_BASE_PY%"
"%ACANE_BASE_PY%" -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 64-bit required'" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
if exist "%ACANE_ENV%\Scripts\python.exe" goto env_ready
echo Creating isolated Python environment...
>> "%ACANE_LOG%" echo [3] Creating environment: "%ACANE_ENV%"
"%ACANE_BASE_PY%" -m venv "%ACANE_ENV%" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed

:env_ready
set "ACANE_PY=%ACANE_ENV%\Scripts\python.exe"
>> "%ACANE_LOG%" echo [4] Checking environment: "%ACANE_PY%"
if not exist "%ACANE_PY%" goto failed
"%ACANE_PY%" -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Existing environment must use Python 3.12 64-bit'" >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
echo Installing GPU packages. Details are written to gpu-setup-log.txt.
echo This may take a while; please keep this window open.
>> "%ACANE_LOG%" echo [5] Installing GPU packages
"%ACANE_PY%" -m pip install --disable-pip-version-check "torch==2.8.0+cu128" "torchvision==0.23.0+cu128" --index-url https://download.pytorch.org/whl/cu128 >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
"%ACANE_PY%" -m pip check >> "%ACANE_LOG%" 2>&1
if errorlevel 1 goto failed
echo Running GPU matrix and FFT checks...
>> "%ACANE_LOG%" echo [6] GPU validation
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
