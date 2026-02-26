#!/usr/bin/env pwsh
# Extracted by Docker container - runs USN collector natively
#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$pythonExe = "$env:USERPROFILE\Miniconda3\envs\312\python.exe"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== USN Journal Collector ===" -ForegroundColor Cyan

# Collect changes from USN journal and append to permanent log
Write-Host "Collecting changes from USN journal..." -ForegroundColor Yellow
& $pythonExe -m localsearch.usn_collector

if ($LASTEXITCODE -ne 0) {
    Write-Host "USN collection failed!" -ForegroundColor Red
    exit 1
}

Write-Host "USN collection complete" -ForegroundColor Green
