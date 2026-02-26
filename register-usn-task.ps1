#!/usr/bin/env pwsh
# Register a scheduled task to run USN collector daily
# Must run as Administrator

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$pythonExe = "$env:USERPROFILE\Miniconda3\envs\312\python.exe"
$repoRoot = $PSScriptRoot

Write-Host "=== Register USN Collector Task ===" -ForegroundColor Cyan

# Task configuration
$taskName = "LocalSearch-USN-Collector"
$taskDescription = "Collects NTFS USN journal changes for LocalSearch daily and at startup"

# Action: Run the USN collector
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\extract-and-collect.ps1`""

# Triggers: Daily at 2 AM + at system startup
$triggerDaily = New-ScheduledTaskTrigger -Daily -At 2:00AM
$triggerStartup = New-ScheduledTaskTrigger -AtStartup

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

# Principal (run as SYSTEM with highest privileges for USN access)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Register the task
try {
    # Remove existing task if present
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    
    Register-ScheduledTask `
        -TaskName $taskName `
        -Description $taskDescription `
        -Action $action `
        -Trigger @($triggerDaily, $triggerStartup) `
        -Settings $settings `
        -Principal $principal
    
    Write-Host "Task registered successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task will run:" -ForegroundColor Cyan
    Write-Host "  - Daily at 2:00 AM"
    Write-Host "  - At system startup"
    Write-Host ""
    Write-Host "To view: Get-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
    Write-Host "To run now: Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
    Write-Host "To unregister: Unregister-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
    
} catch {
    Write-Host "Failed to register task: $_" -ForegroundColor Red
    exit 1
}
