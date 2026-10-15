@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)
echo Human2API - compiling an actual Android Companion APK...
echo Android SDK Platform 34 and Java 17 must be installed.
%PYTHON_CMD% scripts\build_android.py
if errorlevel 1 (
  echo Build blocked or failed. Read the error above and install the missing SDK.
  pause
  exit /b 1
)
echo APK ready: android-companion\app\build\outputs\apk\debug\app-debug.apk
pause
