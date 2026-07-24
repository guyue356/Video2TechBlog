@echo off
chcp 65001 >nul

REM Self-elevate to admin if not already
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath 'powershell' -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0stop.ps1\"' -Verb RunAs"
    exit /b
)

REM Already admin, run the stop script
powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
pause
