#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Configure Windows to auto-create RAM disk and start LocalSearch on boot
    
.DESCRIPTION
    Creates a scheduled task that runs at startup with SYSTEM privileges.
    The task will:
    - Create 25GB RAM disk on Z:
    - Copy databases to RAM disk
    - Start docker-compose with LocalSearch
    
    Run this ONCE to configure auto-startup.
    
.EXAMPLE
    .\setup-startup.ps1
#>

$ErrorActionPreference = "Stop"

# Check if running as admin
$isAdmin = [Security.Principal.WindowsIdentity]::GetCurrent().Owner.IsInBuiltinRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "This script requires Administrator privileges." -ForegroundColor Red
    Write-Host "Please run PowerShell as Administrator and try again." -ForegroundColor Yellow
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptRoot "start-with-ramdisk.ps1"

if (-not (Test-Path $startScript)) {
    Write-Host "ERROR: start-with-ramdisk.ps1 not found in $scriptRoot" -ForegroundColor Red
    exit 1
}

Write-Host "Configuring automatic LocalSearch startup with RAM disk..." -ForegroundColor Cyan

# First register shutdown hook
$shutdownScript = Join-Path $scriptRoot "register-shutdown-hook.ps1"
if (Test-Path $shutdownScript) {
    Write-Host "`nStep 1: Registering data persistence hook..." -ForegroundColor Cyan
    & $shutdownScript
} else {
    Write-Host "WARNING: register-shutdown-hook.ps1 not found - data persistence not configured" -ForegroundColor Yellow
}

Write-Host "`nStep 2: Registering startup task..." -ForegroundColor Cyan

# Create scheduled task action
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""

# Create trigger for startup (Delay 30 seconds to let system stabilize)
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"

# Run with SYSTEM account (highest privilege)
$principal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Create/update the task
try {
    $taskName = "LocalSearchRAMDisk"
    $taskPath = "\"
    
    # Remove existing task if it exists
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } catch { }
    
    # Register new task
    $task = Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Description "Auto-create 25GB RAM disk on Z: and start LocalSearch with databases" `
        -Force
    
    Write-Host "✓ Scheduled task registered: LocalSearchRAMDisk" -ForegroundColor Green
    Write-Host "  Configured to run at startup with 30-second delay" -ForegroundColor Green
    
    Write-Host "`nStartup configuration complete!" -ForegroundColor Green
    Write-Host "`nOn next reboot:" -ForegroundColor Cyan
    Write-Host "  1. System will create 25GB RAM disk on Z:" -ForegroundColor White
    Write-Host "  2. Databases will be copied to RAM disk" -ForegroundColor White
    Write-Host "  3. Docker containers will start with RAM-based mounts" -ForegroundColor White
    Write-Host "  4. Dashboard will be available at http://localhost:8080" -ForegroundColor White
    
} catch {
    Write-Host "ERROR: Failed to register scheduled task" -ForegroundColor Red
    Write-Host "$_" -ForegroundColor Red
    exit 1
}

Write-Host "`nTo manually run before reboot, execute:" -ForegroundColor Yellow
Write-Host "  .\start-with-ramdisk.ps1" -ForegroundColor Cyan
