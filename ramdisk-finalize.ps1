#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Finalize RAM disk: copy data back to disk and cleanup
    
.DESCRIPTION
    After LocalSearch stops, this copies changes from RAM disk
    back to disk and removes the RAM disk.
#>

param(
    [string]$RamDiskLetter = "Z"
)

$ErrorActionPreference = "Stop"

# Load config from env file if it exists
if (Test-Path ".ramdisk_env") {
    Get-Content ".ramdisk_env" | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$ramdiskMount = $env:RAMDISK_MOUNT -or "${RamDiskLetter}:"
$ramdiskData = $env:RAMDISK_DATA -or "$ramdiskMount\localsearch_data"
$ramdiskQdrant = $env:RAMDISK_QDRANT -or "$ramdiskMount\qdrant_storage"

Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  LocalSearch RAM Disk Finalization           ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan

# Stop container first
Write-Host ""
Write-Host "Stopping container..." -ForegroundColor Yellow
try {
    docker-compose down 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "  ✓ Container stopped" -ForegroundColor Green
} catch {
    Write-Host "  ℹ Container already stopped" -ForegroundColor Gray
}

# Copy data back to disk
Write-Host ""
Write-Host "Copying data from RAM to disk..." -ForegroundColor Yellow

if (Test-Path "$ramdiskData\localsearch_meta.db") {
    Write-Host "  Copying SQLite database..." -ForegroundColor White
    New-Item -ItemType Directory -Path "data" -Force | Out-Null
    Copy-Item "$ramdiskData\localsearch_meta.db" "data\" -Force
    $dbSize = (Get-Item "data\localsearch_meta.db").Length / 1MB
    Write-Host "  ✓ SQLite copied ($([math]::Round($dbSize, 1)) MB)" -ForegroundColor Green
} else {
    Write-Host "  ℹ No SQLite database found on RAM disk" -ForegroundColor Gray
}

if (Test-Path $ramdiskQdrant) {
    Write-Host "  Copying Qdrant storage..." -ForegroundColor White
    New-Item -ItemType Directory -Path "qdrant_storage" -Force | Out-Null
    
    # Copy with progress
    $items = Get-ChildItem $ramdiskQdrant -Recurse -ErrorAction SilentlyContinue
    if ($items) {
        Copy-Item "$ramdiskQdrant\*" "qdrant_storage\" -Recurse -Force -ErrorAction SilentlyContinue
        $qdrantSize = (Get-ChildItem "qdrant_storage" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
        Write-Host "  ✓ Qdrant copied ($([math]::Round($qdrantSize, 1)) MB)" -ForegroundColor Green
    } else {
        Write-Host "  ℹ No Qdrant data found on RAM disk" -ForegroundColor Gray
    }
} else {
    Write-Host "  ℹ No Qdrant storage found on RAM disk" -ForegroundColor Gray
}

# Remove RAM disk
Write-Host ""
Write-Host "Removing RAM disk..." -ForegroundColor Yellow

if (-not (Test-Path "$ramdiskMount")) {
    Write-Host "  ℹ RAM disk not active" -ForegroundColor Gray
} else {
    try {
        # Clear anything still in use
        Remove-Item "$ramdiskMount\*" -Recurse -Force -ErrorAction SilentlyContinue
        
        # Unmount
        $result = imdisk -d -m $ramdiskMount 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ RAM disk removed" -ForegroundColor Green
        } else {
            Write-Host "  ⚠ Could not unmount RAM disk automatically" -ForegroundColor Yellow
            Write-Host "    Manual cleanup: imdisk -d -m $ramdiskMount" -ForegroundColor Yellow
            Write-Host "    Or restart your computer" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  ⚠ Error removing RAM disk: $_" -ForegroundColor Yellow
        Write-Host "    Manual cleanup: imdisk -d -m $ramdiskMount" -ForegroundColor Yellow
    }
}

# Clean up env file
Write-Host ""
Remove-Item ".ramdisk_env" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "✓ Finalization Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Data persisted to disk:" -ForegroundColor Cyan
Write-Host "  - data/localsearch_meta.db" -ForegroundColor White
Write-Host "  - qdrant_storage/" -ForegroundColor White
Write-Host ""
Write-Host "Ready for next session. Run ./ramdisk-start.ps1 to reuse." -ForegroundColor Green
