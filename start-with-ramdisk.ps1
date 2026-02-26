#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Auto-setup RAMdisk and start LocalSearch with one command
    
.DESCRIPTION
    Checks for Z: RAM disk. If missing, auto-elevates to admin and creates it.
    Then copies databases and starts docker-compose.
    
.EXAMPLE
    .\start-with-ramdisk.ps1
#>

$ErrorActionPreference = "Stop"

# Check if running as admin
$isAdmin = [Security.Principal.WindowsIdentity]::GetCurrent().Owner.IsInBuiltinRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# If not admin and Z: doesn't exist, self-elevate
if (-not $isAdmin -and -not (Test-Path Z:\)) {
    Write-Host "RAMdisk not found. Elevating to Administrator..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    Start-Process -FilePath powershell -ArgumentList $arguments -Verb RunAs -Wait
    exit 0
}

# =============================================================================
# Create RAM disk if it doesn't exist
# =============================================================================
if (-not (Test-Path Z:\)) {
    Write-Host "Creating 25GB RAM disk on Z:..." -ForegroundColor Cyan
    
    # Create the device (25GB: 20GB Qdrant + 500MB SQLite + headroom)
    $output = imdisk -a -s 25GB -m Z: -p "/fs:ntfs /q /y" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create RAM disk: $output" -ForegroundColor Red
        exit 1
    }
    
    Start-Sleep -Seconds 3
    
    # Create directories
    New-Item -ItemType Directory -Path Z:\localsearch_data -Force -ErrorAction SilentlyContinue | Out-Null
    New-Item -ItemType Directory -Path Z:\qdrant_storage -Force -ErrorAction SilentlyContinue | Out-Null
    
    Write-Host "Copying databases to RAM disk..." -ForegroundColor Cyan
    
    # Copy SQLite database
    if (Test-Path "data\localsearch_meta.db") {
        Copy-Item "data\localsearch_meta.db" "Z:\localsearch_data\" -Force -ErrorAction SilentlyContinue
        Write-Host "  ✓ SQLite copied" -ForegroundColor Green
    }
    
    # Copy Qdrant storage
    if (Test-Path "qdrant_storage") {
        Copy-Item "qdrant_storage\*" "Z:\qdrant_storage\" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  ✓ Qdrant copied" -ForegroundColor Green
    }
    
    Write-Host "RAM disk ready!" -ForegroundColor Green
} else {
    Write-Host "RAM disk Z: already exists" -ForegroundColor Green
}

# =============================================================================
# Start containers
# =============================================================================
Write-Host "`nStarting LocalSearch on RAM disk..." -ForegroundColor Cyan

cd $PSScriptRoot
docker-compose up localsearch
