# Video2TechBlog - One-Click Start Script
# Usage: .\start.ps1

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$condaEnvName = "video2techblog"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Video2TechBlog - One-Click Launcher" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ---- Prerequisites check ----
$errors = @()
$warnings = @()

# Conda
try { conda --version 2>&1 | Out-Null } catch {
    $errors += "Conda not found. Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
}

# Node.js
try { node --version 2>&1 | Out-Null } catch {
    $errors += "Node.js not found. Install: https://nodejs.org/"
}

# ffmpeg (required for audio extraction)
# Check: 1) system PATH, 2) project-local C:\ffmpeg\bin, 3) project-local D:\tools\ffmpeg\bin
$hasFfmpeg = $false
$ffmpegLocalPaths = @("D:\hsj\Github\ffmpeg\bin", "C:\ffmpeg\bin", "D:\tools\ffmpeg\bin", "$projectRoot\ffmpeg\bin")

# Add local ffmpeg paths to PATH if they exist
foreach ($p in $ffmpegLocalPaths) {
    if ((Test-Path "$p\ffmpeg.exe") -and ($env:PATH -notlike "*$p*")) {
        $env:PATH = "$p;$env:PATH"
        Write-Host "[Info] Added $p to PATH" -ForegroundColor DarkCyan
    }
}

try {
    $ffmpegVer = ffmpeg -version 2>&1 | Select-Object -First 1
    if ($ffmpegVer -match "ffmpeg version") { $hasFfmpeg = $true }
} catch { }
if (-not $hasFfmpeg) {
    $errors += @"
ffmpeg not found. Audio extraction requires ffmpeg.

    Install options (pick one):
    1. winget install ffmpeg
    2. Download from https://github.com/BtbN/FFmpeg-Builds/releases
       Extract to C:\ffmpeg\ so that C:\ffmpeg\bin\ffmpeg.exe exists
    3. Download from https://www.gyan.dev/ffmpeg/builds/
       Extract and place ffmpeg.exe in C:\ffmpeg\bin\
"@
}

if ($errors.Count -gt 0) {
    Write-Host "Prerequisites missing:" -ForegroundColor Red
    $errors | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Please install the missing tools and try again." -ForegroundColor Yellow
    exit 1
}
if ($warnings.Count -gt 0) {
    $warnings | ForEach-Object { Write-Host "[Warn] $_" -ForegroundColor DarkYellow }
}
Write-Host "[Check] Conda, Node.js, ffmpeg found" -ForegroundColor Green

# ---- Conda environment check/create ----
Write-Host "[Conda] Checking environment '$condaEnvName'..." -ForegroundColor Yellow
$envExists = $false
try {
    $envListJson = conda env list --json 2>$null | Out-String
    $envList = $envListJson | ConvertFrom-Json
    $envExists = ($envList.envs | Where-Object { $_ -match "\\$condaEnvName$|/$condaEnvName$" }).Count -gt 0
} catch { }

if (-not $envExists) {
    Write-Host "[Conda] Creating environment '$condaEnvName' (python=3.10)..." -ForegroundColor Yellow
    conda create -n $condaEnvName python=3.10 -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create conda environment. Try manually: conda create -n $condaEnvName python=3.10 -y" -ForegroundColor Red
        exit 1
    }
    Write-Host "[Conda] Environment '$condaEnvName' created" -ForegroundColor Green
} else {
    Write-Host "[Conda] Environment '$condaEnvName' already exists" -ForegroundColor Green
}

# ---- .env file check ----
$envPath = "$projectRoot\backend\.env"
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath -Raw
    if ($envContent -match "DEEPSEEK_API_KEY=sk-") {
        Write-Host "[Check] DEEPSEEK_API_KEY found in backend/.env" -ForegroundColor Green
    } else {
        Write-Host "[Warn] backend/.env exists but DEEPSEEK_API_KEY looks empty. Edit it and restart." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[Warn] backend/.env not found. Copy .env.example to backend/.env and fill in your API key." -ForegroundColor DarkYellow
}

# ---- Install Python dependencies ----
Write-Host ""
Write-Host "[Install] Python dependencies..." -ForegroundColor Yellow
Push-Location "$projectRoot\backend"
$reqTime = (Get-Item requirements.txt).LastWriteTime
$flagFile = ".deps_installed"
$needInstall = $true
if (Test-Path $flagFile) {
    $flagTime = (Get-Item $flagFile).LastWriteTime
    if ($flagTime -ge $reqTime) { $needInstall = $false }
}
if ($needInstall) {
    conda run -n $condaEnvName pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pip install failed. Try manually: conda activate $condaEnvName && cd backend && pip install -r requirements.txt" -ForegroundColor Red
        Pop-Location; exit 1
    }
    New-Item $flagFile -ItemType File -Force | Out-Null
}

# Verify key Python packages are installed
Write-Host "[Verify] Checking Python packages..." -ForegroundColor Yellow
$checkScript = "import importlib.util,sys; pkgs=['fastapi','uvicorn','sqlalchemy','aiosqlite','aiofiles','sse_starlette','pydantic','dotenv','mistune','faster_whisper']; missing=[n for n in pkgs if importlib.util.find_spec(n) is None]; print('MISSING:'+','.join(missing)) if missing else print('ALL_OK'); sys.exit(1 if missing else 0)"
$checkResult = conda run -n $condaEnvName python -c "$checkScript" 2>&1
if ($checkResult -match "MISSING:") {
    $missingPkgs = ($checkResult -replace "MISSING:", "")
    Write-Host "Python packages missing: $missingPkgs" -ForegroundColor Red
    Write-Host "Run: conda activate $condaEnvName && pip install -r requirements.txt" -ForegroundColor Yellow
    Pop-Location; exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Verify] Package check inconclusive, continuing..." -ForegroundColor DarkYellow
} else {
    Write-Host "[Install] Python dependencies ready and verified" -ForegroundColor Green
}
Pop-Location

# ---- Install Node.js dependencies ----
Write-Host "[Install] Node.js dependencies..." -ForegroundColor Yellow
Push-Location "$projectRoot\frontend"
if (-not (Test-Path node_modules)) {
    npm install --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "npm install failed. Try running manually: cd frontend && npm install" -ForegroundColor Red
        Pop-Location; exit 1
    }
}
Write-Host "[Install] Node.js dependencies ready" -ForegroundColor Green
Pop-Location

# ---- Start servers (single window) ----
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Starting servers..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Write a PowerShell runner script to a temp file
# Uses Start-Job for concurrent processes with real-time output
$runnerPath = "$env:TEMP\v2tb_servers.ps1"
$serverScript = @'
$host.UI.RawUI.WindowTitle = "Video2TechBlog Servers"

$backendDir  = '__BACKEND__'
$frontendDir = '__FRONTEND__'
$condaEnv    = '__ENV__'

# Start backend job
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:backendDir
    & conda run -n $using:condaEnv --no-capture-output python -m uvicorn app.main:app --reload --port 8000 2>&1
}

# Start frontend job
$frontendJob = Start-Job -ScriptBlock {
    Set-Location $using:frontendDir
    & npm run dev 2>&1
}

Write-Host "[Backend]  Job $($backendJob.Id) -> http://localhost:8000" -ForegroundColor Green
Write-Host "[Frontend] Job $($frontendJob.Id) -> http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop both servers." -ForegroundColor DarkGray
Write-Host ("=" * 44) -ForegroundColor Cyan
Write-Host ""

# Stream output from both jobs in real-time
try {
    while ($true) {
        # Check if either job failed
        if ($backendJob.State -eq 'Failed') {
            Write-Host "[Backend]  FAILED" -ForegroundColor Red
            Receive-Job $backendJob -ErrorAction SilentlyContinue
            break
        }
        if ($frontendJob.State -eq 'Failed') {
            Write-Host "[Frontend] FAILED" -ForegroundColor Red
            Receive-Job $frontendJob -ErrorAction SilentlyContinue
            break
        }

        # Receive and display new output from backend
        $bOut = Receive-Job $backendJob -ErrorAction SilentlyContinue
        if ($bOut) {
            foreach ($line in $bOut) {
                Write-Host "[Backend]  " -ForegroundColor Cyan -NoNewline
                Write-Host $line
            }
        }

        # Receive and display new output from frontend
        $fOut = Receive-Job $frontendJob -ErrorAction SilentlyContinue
        if ($fOut) {
            foreach ($line in $fOut) {
                Write-Host "[Frontend] " -ForegroundColor Magenta -NoNewline
                Write-Host $line
            }
        }

        Start-Sleep -Milliseconds 500
    }
} finally {
    # Cleanup: stop both jobs
    Stop-Job $backendJob -ErrorAction SilentlyContinue
    Stop-Job $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob -Force -ErrorAction SilentlyContinue
    Remove-Job $frontendJob -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Both servers stopped." -ForegroundColor Yellow
}
'@

$serverScript = $serverScript.
    Replace('__BACKEND__', "$projectRoot\backend").
    Replace('__FRONTEND__', "$projectRoot\frontend").
    Replace('__ENV__', $condaEnvName)

$serverScript | Out-File -FilePath $runnerPath -Encoding UTF8

# Launch everything in a single new window
Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$runnerPath`""
Write-Host "[Servers]  Launched in single window" -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Servers launched!" -ForegroundColor Green
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor White
Write-Host "  Backend API docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close the server window to stop both services."
Write-Host "Press any key to close this launcher..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
