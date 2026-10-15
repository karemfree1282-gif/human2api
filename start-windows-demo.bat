@echo off
cd /d "%~dp0"
echo Opening a safe demo window for Windows UI Automation...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_demo.ps1"
if errorlevel 1 (
  echo The Windows demo failed to start. PowerShell and .NET Windows Forms are required.
  pause
)
