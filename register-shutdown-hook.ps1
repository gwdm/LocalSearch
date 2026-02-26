#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Register shutdown hook to save RAM disk data before reboot
    
.DESCRIPTION
    Creates a scheduled task that triggers on system shutdown.
    This ensures RAM disk data is persisted to disk before reboot.
    
    Called automatically by setup-startup.ps1
    
.EXAMPLE
    .\register-shutdown-hook.ps1
#>

$ErrorActionPreference = "Stop"

# Check if running as admin
$isAdmin = [Security.Principal.WindowsIdentity]::GetCurrent().Owner.IsInBuiltinRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "This script requires Administrator privileges." -ForegroundColor Red
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$shutdownScript = Join-Path $scriptRoot "ramdisk-shutdown.ps1"

if (-not (Test-Path $shutdownScript)) {
    Write-Host "ERROR: ramdisk-shutdown.ps1 not found in $scriptRoot" -ForegroundColor Red
    exit 1
}

Write-Host "Registering shutdown hook for RAM disk persistence..." -ForegroundColor Cyan

try {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$shutdownScript`""

    # Trigger on system shutdown event (Event ID 1074 = shutdown)
    # Using Event Log trigger from System event log
    $trigger = New-ScheduledTaskTrigger `
        -CimTriggerType OnEvent `
        -TriggerValue @(
            @{
                Path = "System"
                XPath = @"
                    *[System[
                        Provider[@Name='User32']
                        and 
                        (EventID=1074)
                    ]]
"@
            }
        )

    $principal = New-ScheduledTaskPrincipal `
        -UserId "NT AUTHORITY\SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest

    # Remove existing task if it exists
    try {
        Unregister-ScheduledTask -TaskName "LocalSearchShutdown" -Confirm:$false -ErrorAction SilentlyContinue
    } catch { }

    # Register new task
    $task = Register-ScheduledTask `
        -TaskName "LocalSearchShutdown" `
        -Action $action `
        -Principal $principal `
        -Description "Save LocalSearch RAM disk data to disk on system shutdown" `
        -ErrorAction SilentlyContinue

    # Use alternative approach via XML if event trigger didn't work
    if (-not $task) {
        Write-Host "Using XML-based task registration..." -ForegroundColor Yellow
        
        $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>$(Get-Date -Format 'o')</Date>
    <Author>LocalSearch</Author>
    <Description>Save LocalSearch RAM disk data to disk on shutdown</Description>
  </RegistrationInfo>
  <Triggers>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='User32'] and EventID=1074]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="author">
      <UserId>NT AUTHORITY\SYSTEM</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File "$shutdownScript"</Arguments>
    </Exec>
  </Actions>
</Task>
"@
        $tempXml = [System.IO.Path]::GetTempFileName() + ".xml"
        Set-Content -Path $tempXml -Value $taskXml -Encoding Unicode
        
        schtasks /create /tn "LocalSearchShutdown" /xml "$tempXml" /f /ru "SYSTEM"
        Remove-Item -Path $tempXml -Force
    }

    Write-Host "✓ Shutdown hook registered: LocalSearchShutdown" -ForegroundColor Green
    Write-Host "  Will save RAM disk data on system shutdown" -ForegroundColor Green
    
} catch {
    Write-Host "ERROR: Failed to register shutdown hook" -ForegroundColor Red
    Write-Host "$_" -ForegroundColor Red
    Write-Host "`nFallback: Shutdown tasks are optional but recommended for data persistence" -ForegroundColor Yellow
}

Write-Host "`nShutdown hook configuration complete!" -ForegroundColor Green
