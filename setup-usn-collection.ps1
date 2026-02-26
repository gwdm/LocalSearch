# Setup USN Collection from Docker
# Extracts Windows-specific scripts from container and sets up scheduled task

Write-Host "Setting up USN journal collection..." -ForegroundColor Cyan
Write-Host ""

# 1. Extract scripts from Docker to host
Write-Host "[1/3] Extracting scripts from Docker container..." -ForegroundColor Yellow
docker cp localsearch-app:/app/extract-and-collect.ps1 ./extract-and-collect.ps1
docker cp localsearch-app:/app/register-task.ps1 ./register-task.ps1

# 2. Verify Python environment has pywin32
Write-Host "[2/3] Checking Python environment..." -ForegroundColor Yellow
$pythonPath = "$env:USERPROFILE\Miniconda3\envs\312\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Host "ERROR: Python 3.12 not found at $pythonPath" -ForegroundColor Red
    Write-Host "Please install Python 3.12 and pywin32" -ForegroundColor Red
    exit 1
}

# Test pywin32
& $pythonPath -c "import win32file" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: pywin32 not installed in Python 3.12 environment" -ForegroundColor Yellow
    Write-Host "Installing pywin32..." -ForegroundColor Yellow
    & $pythonPath -m pip install pywin32
}

# 3. Register scheduled task
Write-Host "[3/3] Registering Windows Task Scheduler task..." -ForegroundColor Yellow
& .\register-task.ps1

Write-Host ""
Write-Host "✓ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "USN journal collection will run every 5 minutes via Task Scheduler" -ForegroundColor Cyan
Write-Host "View/manage: Task Scheduler → Task Scheduler Library → LocalSearch-USN" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run manually: .\run-usn-collection.ps1" -ForegroundColor Gray
