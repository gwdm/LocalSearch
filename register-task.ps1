# Register LocalSearch-Startup scheduled task (run this as Administrator)
$taskName = "LocalSearch-Startup"
$scriptPath = "D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch\start.ps1"
$workDir = "D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch"

# Remove old task if it exists
schtasks /Delete /TN $taskName /F 2>$null

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Minimized -File `"$scriptPath`"" `
    -WorkingDirectory $workDir

$trigger = New-ScheduledTaskTrigger -AtLogOn

# No execution time limit, allow on battery, run with highest privileges
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "LocalSearch: warm Qdrant page cache, start Qdrant container, start web UI" `
    -RunLevel Highest | Out-Null

Write-Host "Task '$taskName' registered successfully." -ForegroundColor Green
Write-Host "  Trigger: At logon"
Write-Host "  Action:  powershell.exe -File $scriptPath"
Write-Host "  RunLevel: Highest (admin)"
