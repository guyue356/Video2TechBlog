@echo off
chcp 65001 >nul
title Video2TechBlog Launcher

echo.
echo ============================================
echo   Video2TechBlog - Double-click to Start
echo ============================================
echo.
echo Starting Video2TechBlog...
echo A new window will open with the servers.
echo Browser will open automatically in 5 seconds.
echo.

REM Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if errorlevel 1 (
    echo.
    echo [Error] Failed to start. Please run start.ps1 manually in PowerShell.
    echo.
    pause
)
