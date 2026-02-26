# RAM disk ingest workflow:
# 1. Create RAM disk
# 2. Copy current DB to RAM
# 3. Run ingest (writes to RAM, checkpoints to disk)
# 4. Copy final DB back to disk

param(
    [int]$RamDiskSizeGB = 20,
    [string]$RamDiskLetter = "Z"
)

$ErrorActionPreference = "Stop"

$dataDir = "data"
$dbFile = "localsearch_meta.db"
$dbPath = Join-Path $dataDir $dbFile
$ramPath = "${RamDiskLetter}:\$dbFile"
$ramdiskMount = "${RamDiskLetter}:"

Write-Host "=== RAM Disk Ingest Setup ===" -ForegroundColor Cyan

# 1. Create RAM disk if it doesn't exist
Write-Host "Creating RAM disk ($RamDiskSizeGB GB on $RamDiskLetter)..." -ForegroundColor Yellow
try {
    if (-not (Test-Path $ramdiskMount)) {
        $result = imdisk -a -s "${RamDiskSizeGB}GB" -m $ramdiskMount -p "/fs:ntfs"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create RAM disk"
        }
        Write-Host "✓ RAM disk created" -ForegroundColor Green
    } else {
        Write-Host "✓ RAM disk already exists" -ForegroundColor Green
    }
} catch {
    Write-Error "RAM disk creation failed. You may need admin privileges or imdisk installed."
    exit 1
}

# 2. Copy current DB to RAM (or start fresh)
Write-Host "Copying DB to RAM disk..." -ForegroundColor Yellow
if (Test-Path $dbPath) {
    Copy-Item $dbPath $ramPath -Force
    Write-Host "✓ DB copied to RAM" -ForegroundColor Green
} else {
    Write-Host "✓ Starting fresh (no existing DB)" -ForegroundColor Green
}

# 3. Update config to use RAM disk
$configPath = "config.yaml"
if (Test-Path $configPath) {
    $config = Get-Content $configPath
    if ($config -match "metadata_db:") {
        Write-Host "Note: Update config.yaml to use metadata_db: $ramPath during ingest" -ForegroundColor Yellow
        Write-Host "      OR set LOCALSEARCH_METADATA_DB environment variable" -ForegroundColor Yellow
    }
}

# 4. Environment variable for ingest (easier than editing config)
$env:LOCALSEARCH_METADATA_DB = $ramPath
Write-Host "✓ Environment variable set: LOCALSEARCH_METADATA_DB=$ramPath" -ForegroundColor Green

Write-Host ""
Write-Host "Ready to ingest. Run:" -ForegroundColor Cyan
Write-Host "  docker-compose up localsearch" -ForegroundColor White
Write-Host ""
Write-Host "After ingest completes, run: ./ramdisk-finalize.ps1" -ForegroundColor Cyan
