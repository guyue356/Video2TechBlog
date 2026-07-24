# Video2TechBlog - Stop Script
# Stops backend (port 8001) and frontend (port 3002)

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Stopping Video2TechBlog Servers" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Kill all python processes running uvicorn (backend)
Write-Host "Stopping backend processes..." -ForegroundColor Yellow
$backendProcs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe" -or $_.Name -eq "python3.exe") -and
    $_.CommandLine -match "uvicorn"
}
foreach ($proc in $backendProcs) {
    Write-Host "  Killing PID $($proc.ProcessId) ($($proc.Name))" -ForegroundColor Yellow
    & taskkill /F /T /PID $proc.ProcessId 2>$null
}

# Kill all node processes running next dev (frontend)
Write-Host "Stopping frontend processes..." -ForegroundColor Yellow
$frontendProcs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "node.exe" -or $_.Name -eq "node") -and
    $_.CommandLine -match "next"
}
foreach ($proc in $frontendProcs) {
    Write-Host "  Killing PID $($proc.ProcessId) ($($proc.Name))" -ForegroundColor Yellow
    & taskkill /F /T /PID $proc.ProcessId 2>$null
}

# Also kill by port as fallback
Write-Host ""
Write-Host "Checking ports..." -ForegroundColor Yellow
$ports = @(8001, 3002)
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "  Killing orphan PID $procId ($($proc.ProcessName)) on port $port..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

# Wait and verify
Write-Host ""
Write-Host "Verifying..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

$allClear = $true
foreach ($port in $ports) {
    $stillBusy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($stillBusy) {
        Write-Host "[Warn] Port $port still in use!" -ForegroundColor Red
        $allClear = $false
    } else {
        Write-Host "[OK] Port $port freed" -ForegroundColor Green
    }
}

Write-Host ""
if ($allClear) {
    Write-Host "[Done] All servers stopped." -ForegroundColor Green
} else {
    Write-Host "[Done] Some ports still occupied. Wait a moment or restart computer." -ForegroundColor Yellow
}
Write-Host ""
