#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Save RAM disk contents back to disk before shutdown
    
.DESCRIPTION
    Called automatically on system shutdown to ensure data persistence.
    - Stops docker containers gracefully
    - Copies updated databases from Z: RAM disk back to disk
    - Dismounts RAM disk
    - Signals reboot/shutdown to proceed
    
    Registered automatically by setup-startup.ps1
    
.NOTES
    Runs with system shutdown event
#>

$ErrorActionPreference = "Stop"
$logFile = "C:\Windows\Temp\localsearch-shutdown.log"

function Log {
    param([string]$message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] $message"
    Add-Content -Path $logFile -Value $logEntry
    Write-Host $logEntry
}

Log "=== LocalSearch Shutdown/Persistence Started ==="

try {
    # Check if Z: drive exists (RAM disk)
    if (Test-Path "Z:\") {
        Log "Detected Z: RAM disk - saving data to disk..."
        
        # Stop containers gracefully (give 10 seconds timeout)
        Log "Stopping docker containers..."
        try {
            $dockerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
            if (Test-Path (Join-Path $dockerDir "docker-compose.yml")) {
                cd $dockerDir
                docker-compose down --timeout 10
                Log "Containers stopped"
            }
        } catch {
            Log "WARNING: Failed to stop containers: $_"
        }
        
        # Wait for I/O to settle
        Start-Sleep -Seconds 2
        
        # Copy Qdrant from RAM to disk
        if (Test-Path "Z:\qdrant_storage") {
            Log "Saving Qdrant vector database from RAM to disk..."
            $dest = Join-Path $PSScriptRoot "qdrant_storage"
            Copy-Item -Path "Z:\qdrant_storage\*" -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
            Log "Qdrant data synced"
        }
        
        # Copy SQLite database from RAM to disk
        if (Test-Path "Z:\localsearch_data") {
            Log "Saving Local Search data from RAM to disk..."
            $dest = Join-Path $PSScriptRoot "data"
            Copy-Item -Path "Z:\localsearch_data\*" -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
            Log "LocalSearch data synced"
        }
        
        # Dismount RAM disk
        Log "Removing RAM disk..."
        try {
            imdisk -d -m Z: -ErrorAction SilentlyContinue
            Log "RAM disk removed"
        } catch {
            Log "WARNING: Failed to remove RAM disk: $_"
        }
    } else {
        Log "Z: drive not found - nothing to save"
    }
    
    Log "=== Shutdown/Persistence Complete - Safe to reboot ==="
    
} catch {
    Log "ERROR: $_ - Proceeding with shutdown anyway"
}
