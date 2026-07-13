@echo off
chcp 65001 >nul
title Video2TechBlog - Stop Servers

echo.
echo ============================================
echo   Stopping Video2TechBlog Servers
echo ============================================
echo.

REM Kill processes on ports 8000 and 3000
echo Stopping Backend (port 8000)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Stopping Frontend (port 3000)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo [Done] Servers stopped.
echo.
pause
