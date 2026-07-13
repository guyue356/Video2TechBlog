@echo off
chcp 65001 >nul
title Video2TechBlog - Stop Servers

echo.
echo ============================================
echo   Stopping Video2TechBlog Servers
echo ============================================
echo.

REM Kill processes on ports 8001 and 3001
echo Stopping Backend (port 8001)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Stopping Frontend (port 3001)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3001 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo [Done] Servers stopped.
echo.
pause
