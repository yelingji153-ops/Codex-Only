@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ACANE_REPORT=gpu-check-report.txt"
> "%ACANE_REPORT%" echo ACAne local GPU diagnostic report
>> "%ACANE_REPORT%" echo This check does not install or change system software.
where nvidia-smi >nul 2>&1
if errorlevel 1 goto windows_gpu_info
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader >> "%ACANE_REPORT%" 2>&1
goto select_python

:windows_gpu_info
powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | Format-List" >> "%ACANE_REPORT%" 2>&1

:select_python
if exist "..\.venv-separation\Scripts\python.exe" goto project_python
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python_launcher
python -c "import sys; assert sys.version_info.major == 3" >nul 2>&1
if not errorlevel 1 goto python_path
>> "%ACANE_REPORT%" echo Python 3 was not found. Driver information above can still be reviewed.
goto done

:project_python
"..\.venv-separation\Scripts\python.exe" check_gpu.py >> "%ACANE_REPORT%" 2>&1
goto done

:python_launcher
py -3.12 check_gpu.py >> "%ACANE_REPORT%" 2>&1
goto done

:python_path
python check_gpu.py >> "%ACANE_REPORT%" 2>&1

:done
type "%ACANE_REPORT%"
echo.
echo Send gpu-check-report.txt back to this chat.
echo A missing dependency or CUDA check failure is diagnostic information, not a successful GPU validation.
pause
