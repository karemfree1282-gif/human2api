@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 is not installed. Install Python 3.10+ and run again.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Preparing isolated Python environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :failed
)
set "APP_PY=.venv\Scripts\python.exe"
echo Installing or updating Human2API dependencies...
"%APP_PY%" -m pip install -e ".[browser]"
if errorlevel 1 goto :failed
echo Checking the Chromium browser runtime...
"%APP_PY%" -m playwright install chromium
if errorlevel 1 echo Chromium download was unavailable. Existing Chrome/Chromium may still work with Selenium.
echo Starting Human2API Studio...
"%APP_PY%" -m human2api start --dir "%USERPROFILE%\Human2API-Workspace"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo Human2API could not start. See the error above.
pause
exit /b 1
