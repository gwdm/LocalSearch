#!/usr/bin/env pwsh
# Hybrid ingestion: Native USN journal scan → Docker processing
# This gets the best of both worlds:
# - Fast USN journal change detection (native Windows, requires Admin)
# - Docker GPU/CUDA environment for processing

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

Write-Host "=== Hybrid Ingestion ===" -ForegroundColor Cyan
Write-Host "Phase 1: Native USN scan (fast)" -ForegroundColor Yellow

# Run native scan using USN journal (requires admin for USN access)
& "$env:USERPROFILE\Miniconda3\envs\312\python.exe" -m localsearch.cli scan `
    --output "$PSScriptRoot\data\changed_files.txt"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Scan failed!" -ForegroundColor Red
    exit 1
}

# Check if any files were found
$fileCount = (Get-Content "$PSScriptRoot\data\changed_files.txt" -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
if ($fileCount -eq 0) {
    Write-Host "No changed files found. Nothing to process." -ForegroundColor Green
    exit 0
}

Write-Host "Found $fileCount changed files" -ForegroundColor Green
Write-Host ""
Write-Host "Phase 2: Docker processing (GPU)" -ForegroundColor Yellow

# Start Docker containers if not running
Set-Location $PSScriptRoot
docker compose up -d qdrant

# Wait for Qdrant to be healthy
Write-Host "Waiting for Qdrant..."
$maxWait = 60
$waited = 0
while ($waited -lt $maxWait) {
    $health = docker inspect localsearch-qdrant --format='{{.State.Health.Status}}' 2>$null
    if ($health -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 2
    $waited += 2
}

if ($waited -ge $maxWait) {
    Write-Host "Qdrant failed to start!" -ForegroundColor Red
    exit 1
}

# Run ingestion in Docker with file list
Write-Host "Rebuilding Docker image with latest code..."
docker compose build localsearch

Write-Host "Starting ingestion with file list..."
docker compose run --rm localsearch python -m localsearch.cli ingest --file-list /data/changed_files.txt

Write-Host ""
Write-Host "=== Hybrid Ingestion Complete ===" -ForegroundColor Green
