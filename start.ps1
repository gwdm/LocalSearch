<#
.SYNOPSIS
    Full LocalSearch startup: warm cache → start Qdrant → wait ready → start web UI.

.DESCRIPTION
    Orchestrates the complete startup sequence:
    1. Pre-warm the OS page cache with Qdrant data (NVMe sequential read)
    2. Start the Qdrant container
    3. Wait for Qdrant to become responsive (API health check)
    4. Start the Flask web UI
    
    Optionally starts a Docker ingest run after Qdrant is ready.

.PARAMETER SkipWarm
    Skip the page cache warming step (e.g. if already warm from recent use).

.PARAMETER Ingest
    Also run a Docker ingest after Qdrant is ready.

.PARAMETER WebPort
    Port for the Flask web UI. Default: 8080

.PARAMETER QdrantTimeout
    Max seconds to wait for Qdrant readiness. Default: 600

.EXAMPLE
    .\start.ps1                    # warm + qdrant + web
    .\start.ps1 -Ingest            # warm + qdrant + web + docker ingest
    .\start.ps1 -SkipWarm          # skip warming, just start services
#>
param(
    [switch]$SkipWarm,
    [switch]$Ingest,
    [int]$WebPort = 8080,
    [int]$QdrantTimeout = 600
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir
$Python = Join-Path $env:USERPROFILE "Miniconda3\envs\312\python.exe"

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ── Step 1: Warm page cache ──────────────────────────────────────────────
if (-not $SkipWarm) {
    Write-Step "Warming Qdrant page cache"
    & "$ProjectDir\warm-cache.ps1"
} else {
    Write-Host "Skipping cache warm (--SkipWarm)" -ForegroundColor Yellow
}

# ── Step 2: Start Qdrant ─────────────────────────────────────────────────
Write-Step "Starting Qdrant container"
docker compose up -d qdrant 2>&1 | Write-Host

# ── Step 3: Wait for Qdrant readiness ────────────────────────────────────
Write-Step "Waiting for Qdrant (max ${QdrantTimeout}s)"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$ready = $false
while ($sw.Elapsed.TotalSeconds -lt $QdrantTimeout) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:6333/collections" -TimeoutSec 10 -ErrorAction Stop
        $collections = $r.result.collections | ForEach-Object { $_.name }
        Write-Host "Qdrant ready after $([math]::Round($sw.Elapsed.TotalSeconds))s! Collections: $($collections -join ', ')" -ForegroundColor Green
        $ready = $true
        break
    } catch {
        $elapsed = [math]::Round($sw.Elapsed.TotalSeconds)
        if ($elapsed % 30 -lt 10) {
            Write-Host "  ${elapsed}s ..." -ForegroundColor DarkGray
        }
        Start-Sleep -Seconds 10
    }
}
if (-not $ready) {
    Write-Host "ERROR: Qdrant did not become ready within ${QdrantTimeout}s" -ForegroundColor Red
    exit 1
}

# ── Step 4: Start Web UI ─────────────────────────────────────────────────
Write-Step "Starting Web UI on port $WebPort"
# Kill any existing web server on the port
$existing = netstat -ano | Select-String ":${WebPort}.*LISTENING"
if ($existing) {
    Write-Host "  Port $WebPort in use — skipping (web UI already running?)" -ForegroundColor Yellow
} else {
    Start-Process -FilePath $Python -ArgumentList "-m", "localsearch.cli", "web", "--port", $WebPort `
        -WindowStyle Minimized -WorkingDirectory $ProjectDir
    Write-Host "  Web UI started: http://localhost:$WebPort" -ForegroundColor Green
}

# ── Step 5 (optional): Docker ingest ─────────────────────────────────────
if ($Ingest) {
    Write-Step "Starting Docker ingest"
    Start-Process -FilePath "docker" -ArgumentList "compose", "run", "--rm", "localsearch", "ingest" `
        -WindowStyle Normal -WorkingDirectory $ProjectDir
    Write-Host "  Ingest container launched (check Docker logs for progress)" -ForegroundColor Green
}

Write-Host "`nAll services started." -ForegroundColor Green
Write-Host "  Dashboard: http://localhost:$WebPort" -ForegroundColor Cyan
Write-Host "  Qdrant:    http://localhost:6333/dashboard" -ForegroundColor Cyan
