<#
.SYNOPSIS
    Full LocalSearch startup via Docker Compose.

.DESCRIPTION
    Orchestrates the complete startup sequence using Docker exclusively:
    1. Pre-warm the OS page cache with Qdrant data (NVMe sequential read)
    2. Build LocalSearch image if needed
    3. Start all services (Qdrant + LocalSearch) via docker compose up
    
    The LocalSearch container runs in "both" mode by default: continuous
    ingest loop (every 60s) + web UI on port 8080.

.PARAMETER SkipWarm
    Skip the page cache warming step (e.g. if already warm from recent use).

.PARAMETER Build
    Force rebuild the LocalSearch Docker image before starting.

.PARAMETER Mode
    Container mode: both (default), ingest, web, shell.

.PARAMETER QdrantTimeout
    Max seconds to wait for Qdrant readiness. Default: 600

.EXAMPLE
    .\start.ps1                    # warm + start all (ingest loop + web UI)
    .\start.ps1 -Build             # rebuild image then start
    .\start.ps1 -SkipWarm          # skip warming, just start services
    .\start.ps1 -Mode ingest       # start Qdrant + run single ingest pass
#>
param(
    [switch]$SkipWarm,
    [switch]$Build,
    [ValidateSet("both", "ingest", "web", "shell")]
    [string]$Mode = "both",
    [int]$QdrantTimeout = 600
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ── Step 0: Wait for Docker daemon ───────────────────────────────────────
Write-Step "Waiting for Docker daemon"
$dockerReady = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Docker ready after $($i * 5)s" -ForegroundColor Green
            $dockerReady = $true
            break
        }
    } catch { }
    if ($i % 6 -eq 0) { Write-Host "  $($i * 5)s ..." -ForegroundColor DarkGray }
    Start-Sleep -Seconds 5
}
if (-not $dockerReady) {
    Write-Host "ERROR: Docker daemon not available after 300s" -ForegroundColor Red
    exit 1
}

# ── Step 1: Warm page cache ──────────────────────────────────────────────
# DISABLED: Skip warmup to avoid preloading database on disk
# if (-not $SkipWarm) {
#     Write-Step "Warming Qdrant page cache"
#     & "$ProjectDir\warm-cache.ps1"
# } else {
#     Write-Host "Skipping cache warm (--SkipWarm)" -ForegroundColor Yellow
# }

# ── Step 2: Build image if requested ─────────────────────────────────────
if ($Build) {
    Write-Step "Building LocalSearch Docker image"
    docker compose build localsearch 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Docker build failed" -ForegroundColor Red
        exit 1
    }
}

# ── Step 3: Start services ───────────────────────────────────────────────
if ($Mode -eq "shell") {
    Write-Step "Dropping into LocalSearch container shell"
    docker compose run --rm localsearch shell
    exit 0
}

if ($Mode -eq "ingest") {
    # Single ingest pass: start Qdrant, run ingest, exit
    Write-Step "Starting Qdrant"
    docker compose up -d qdrant 2>&1 | Write-Host

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
            if ($elapsed % 30 -lt 10) { Write-Host "  ${elapsed}s ..." -ForegroundColor DarkGray }
            Start-Sleep -Seconds 10
        }
    }
    if (-not $ready) {
        Write-Host "ERROR: Qdrant did not become ready within ${QdrantTimeout}s" -ForegroundColor Red
        exit 1
    }

    Write-Step "Running single Docker ingest pass"
    docker compose run --rm localsearch ingest
    exit $LASTEXITCODE
}

# Mode: both (default) or web — use docker compose up for all services
Write-Step "Starting all Docker services (mode: $Mode)"
if ($Mode -eq "web") {
    # Override the default command to web-only
    docker compose up -d qdrant 2>&1 | Write-Host
    Write-Step "Waiting for Qdrant (max ${QdrantTimeout}s)"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $ready = $false
    while ($sw.Elapsed.TotalSeconds -lt $QdrantTimeout) {
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:6333/collections" -TimeoutSec 10 -ErrorAction Stop
            Write-Host "Qdrant ready after $([math]::Round($sw.Elapsed.TotalSeconds))s!" -ForegroundColor Green
            $ready = $true
            break
        } catch {
            Start-Sleep -Seconds 10
        }
    }
    if (-not $ready) {
        Write-Host "ERROR: Qdrant did not become ready within ${QdrantTimeout}s" -ForegroundColor Red
        exit 1
    }
    docker compose run --rm -d -p 8080:8080 localsearch web
} else {
    # Default "both" mode — docker compose up starts everything
    docker compose up -d 2>&1 | Write-Host
}

# ── Step 4: Wait for Qdrant to confirm readiness ─────────────────────────
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
        if ($elapsed % 30 -lt 10) { Write-Host "  ${elapsed}s ..." -ForegroundColor DarkGray }
        Start-Sleep -Seconds 10
    }
}
if (-not $ready) {
    Write-Host "ERROR: Qdrant did not become ready within ${QdrantTimeout}s" -ForegroundColor Red
    exit 1
}

Write-Host "`nAll Docker services started." -ForegroundColor Green
Write-Host "  Web UI:    http://localhost:8080" -ForegroundColor Cyan
Write-Host "  Qdrant:    http://localhost:6333/dashboard" -ForegroundColor Cyan
Write-Host "`nView logs:   docker compose logs -f localsearch" -ForegroundColor DarkGray
Write-Host "Stop all:    docker compose down" -ForegroundColor DarkGray
