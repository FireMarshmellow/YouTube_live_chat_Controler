@echo off
setlocal
title YouTube Live Chat Controller

rem Run from the folder this file lives in so say.exe, sounds and json files are found
cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:5000"

if exist "%PY%" goto :deps

echo First run: setting up the Python environment. This takes a few minutes...
rem pygame 2.6.1 only ships for Python 3.10 - 3.13
set "BASE_PY="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined BASE_PY (
        py -%%V -c "import sys" >nul 2>&1 && set "BASE_PY=py -%%V"
    )
)
if not defined BASE_PY (
    python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1 && set "BASE_PY=python"
)
if not defined BASE_PY (
    echo.
    echo Could not find Python 3.10 - 3.13.
    echo Install Python 3.12 from https://www.python.org/downloads/ and run this file again.
    goto :fail
)
%BASE_PY% -m venv "%VENV%" || goto :fail

:deps
rem Reinstall packages only when requirements.txt has changed since the last install
fc /b requirements.txt "%VENV%\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing requirements...
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
    copy /y requirements.txt "%VENV%\requirements.installed" >nul
)

rem Open the control page once the web server answers
start "" powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 120; $i++) { try { Invoke-WebRequest -UseBasicParsing '%APP_URL%' -TimeoutSec 2 | Out-Null; Start-Process '%APP_URL%'; break } catch { Start-Sleep 1 } }"

echo Starting the application. Close this window to stop it.
echo.
"%PY%" main.py

echo.
echo The application has stopped.
pause
exit /b 0

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
