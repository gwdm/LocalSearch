#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Setup RAM disk for LocalSearch (SQLite + Qdrant)
    
.DESCRIPTION
    Creates a RAM disk, copies existing data, and configures docker-compose
    to use it. After this script, run: docker-compose up localsearch
#>

param(
    [int]$RamDiskSizeGB = 30,
    [string]$RamDiskLetter = "Z"
)

$ErrorActionPreference = "Stop"

$ramdiskMount = "${RamDiskLetter}:"
$ramdiskData = "$ramdiskMount\localsearch_data"
$ramdiskQdrant = "$ramdiskMount\qdrant_storage"

Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  LocalSearch RAM Disk Initialization         ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan

# Check available RAM
Write-Host ""
Write-Host "System RAM Check..." -ForegroundColor Yellow
try {
    $totalRam = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
    $availRam = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB / 1024
    Write-Host "  Total: $([math]::Round($totalRam, 1)) GB" -ForegroundColor White
    Write-Host "  Available: $([math]::Round($availRam, 1)) GB" -ForegroundColor White
    
    if ($totalRam -lt 25) {
        Write-Host "  ⚠ Warning: System has < 25GB RAM. RAM disk may impact system stability." -ForegroundColor Red
        $confirm = Read-Host "Continue anyway? (y/n)"
        if ($confirm -ne "y") { exit 1 }
    }
} catch {
    Write-Host "  Could not detect RAM (continuing anyway)" -ForegroundColor Yellow
}

# Create RAM disk
Write-Host ""
Write-Host "Creating RAM Disk..." -ForegroundColor Yellow
Write-Host "  Size: $RamDiskSizeGB GB" -ForegroundColor White
Write-Host "  Drive: $ramdiskMount" -ForegroundColor White

if (Test-Path $ramdiskMount) {
    Write-Host "  ✓ RAM disk already exists" -ForegroundColor Green
} else {
    try {
        $result = imdisk -a -s "${RamDiskSizeGB}GB" -m $ramdiskMount -p "/fs:ntfs"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ RAM disk created" -ForegroundColor Green
            Start-Sleep -Seconds 2
        } else {
            throw "imdisk failed: $result"
        }
    } catch {
        Write-Host "  ✗ Failed to create RAM disk" -ForegroundColor Red
        Write-Host "    Error: $_" -ForegroundColor Red
        Write-Host "    Install imdisk: https://sourceforge.net/projects/imdisk-toolkit/" -ForegroundColor Yellow
        Write-Host "    Or run as Administrator" -ForegroundColor Yellow
        exit 1
    }
}

# Create directories
Write-Host ""
Write-Host "Setting up directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $ramdiskData -Force | Out-Null
New-Item -ItemType Directory -Path $ramdiskQdrant -Force | Out-Null
Write-Host "  ✓ Directories created" -ForegroundColor Green

# Copy existing data
Write-Host ""
Write-Host "Copying data to RAM disk..." -ForegroundColor Yellow

if (Test-Path "data\localsearch_meta.db") {
    Write-Host "  Copying SQLite database..." -ForegroundColor White
    Copy-Item "data\localsearch_meta.db" "$ramdiskData\" -Force
    Write-Host "  ✓ SQLite copied" -ForegroundColor Green
} else {
    Write-Host "  ℹ No existing SQLite database (will create new)" -ForegroundColor Gray
}

if (Test-Path "qdrant_storage") {
    Write-Host "  Copying Qdrant storage..." -ForegroundColor White
    Copy-Item "qdrant_storage\*" $ramdiskQdrant -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Qdrant storage copied" -ForegroundColor Green
} else {
    Write-Host "  ℹ No existing Qdrant storage (will create new)" -ForegroundColor Gray
}

# Update docker-compose volumes
Write-Host ""
Write-Host "Docker Configuration:" -ForegroundColor Yellow
Write-Host "  Mount points (use in docker-compose.yml):" -ForegroundColor White
Write-Host "    - $ramdiskData`:/app/data" -ForegroundColor Cyan
Write-Host "    - $ramdiskQdrant`:/var/lib/qdrant/storage" -ForegroundColor Cyan

# Save paths to env file for scripts to use
@"
RAMDISK_MOUNT=$ramdiskMount
RAMDISK_DATA=$ramdiskData
RAMDISK_QDRANT=$ramdiskQdrant
RAMDISK_SIZE_GB=$RamDiskSizeGB
"@ | Out-File ".ramdisk_env" -Force

Write-Host ""
Write-Host "✓ Setup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Update docker-compose.yml volumes (or use auto-generated config)" -ForegroundColor White
Write-Host "  2. Run: docker-compose up localsearch" -ForegroundColor White
Write-Host "  3. After use: ./ramdisk-finalize.ps1" -ForegroundColor White
Write-Host ""
Write-Host "⚠️  IMPORTANT: Run finalize script before shutting down!" -ForegroundColor Yellow
