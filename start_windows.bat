@echo off
cd /d "%~dp0"
title SCIA Magna 200 - Process Viewer
echo ===================================================
echo   SCIA Magna 200 - Process Viewer (Starting...)
echo ===================================================
echo.

python -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto :run_native
)

py -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py
    goto :run_native
)

wsl python3 -c "import sys" >nul 2>&1
if %errorlevel% equ 0 goto :run_wsl

echo [ERROR] Python 3 was not found on this Windows system.
echo Please install Python 3 from: https://www.python.org/downloads/
echo IMPORTANT: Check the box Add python.exe to PATH during installation.
pause
exit /b 1

:run_native
if not exist ".venv\Scripts\activate.bat" (
    echo [1/2] Creating Windows virtual environment for the first time...
    %PY_CMD% -m venv .venv
    call .venv\Scripts\activate.bat
    echo [2/2] Installing required libraries ^(takes some minutes on first run^)...
    pip install --disable-pip-version-check -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
echo.
echo Starting web server... Your browser will open automatically as soon as it is ready!
start /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){ try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8050' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; Start-Process 'http://127.0.0.1:8050'; break } catch { Start-Sleep -Milliseconds 500 } }"
python app_scia.py
pause
exit /b 0

:run_wsl
echo Python detected inside WSL Ubuntu. Starting server...
echo Your browser will open automatically as soon as it is ready!
start /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){ try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8050' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; Start-Process 'http://127.0.0.1:8050'; break } catch { Start-Sleep -Milliseconds 500 } }"
wsl bash ./start_mac_linux.sh
pause
exit /b 0
