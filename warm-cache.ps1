<#
.SYNOPSIS
    Pre-warms the Windows filesystem page cache with Qdrant collection data.

.DESCRIPTION
    Reads every file under the Qdrant storage directory sequentially at full
    NVMe speed (~2-3.5 GB/s), pulling the data into the OS page cache. When
    Qdrant starts and mmap's these files, the pages are already resident in RAM
    — reducing startup from ~9 minutes (cold) to under 1 minute.

    This script is safe to run while Qdrant is stopped OR running. It only reads.
    Uses pure PowerShell — no Python dependency.

.PARAMETER Path
    Root directory of the Qdrant collection data.
    Default: D:\qdrant_data

.PARAMETER BufferMB
    Read buffer size in MB. Larger = fewer syscalls = faster throughput.
    Default: 4

.EXAMPLE
    .\warm-cache.ps1
    .\warm-cache.ps1 -Path "E:\qdrant_data" -BufferMB 8
#>
param(
    [string]$Path = "D:\qdrant_data",
    [int]$BufferMB = 4
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) {
    Write-Host "ERROR: Path not found: $Path" -ForegroundColor Red
    exit 1
}

Write-Host "Warming page cache: $Path (buffer=${BufferMB}MB)" -ForegroundColor Cyan

$bufSize = $BufferMB * 1024 * 1024
$buf = New-Object byte[] $bufSize

# Enumerate files
$files = Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue
$totalSize = ($files | Measure-Object -Property Length -Sum).Sum
$totalGB = [math]::Round($totalSize / 1GB, 2)
Write-Host "  $($files.Count) files, $totalGB GB to warm"

$bytesRead = [long]0
$errors = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$lastReport = $sw.ElapsedMilliseconds

foreach ($file in $files) {
    try {
        $stream = [System.IO.File]::OpenRead($file.FullName)
        try {
            while ($true) {
                $n = $stream.Read($buf, 0, $bufSize)
                if ($n -eq 0) { break }
                $bytesRead += $n
            }
        } finally {
            $stream.Close()
        }
    } catch {
        $errors++
    }

    $now = $sw.ElapsedMilliseconds
    if (($now - $lastReport) -ge 5000) {
        $lastReport = $now
        $elapsed = $now / 1000.0
        $pct = if ($totalSize -gt 0) { [math]::Round($bytesRead / $totalSize * 100, 1) } else { 0 }
        $rateMB = if ($elapsed -gt 0) { [math]::Round($bytesRead / 1MB / $elapsed, 0) } else { 0 }
        Write-Host "  ${pct}% ($([math]::Round($bytesRead / 1GB, 1)) / $totalGB GB) @ $rateMB MB/s" -ForegroundColor DarkGray
    }
}

$elapsed = $sw.Elapsed.TotalSeconds
$rateMB = if ($elapsed -gt 0) { [math]::Round($bytesRead / 1MB / $elapsed, 0) } else { 0 }
Write-Host "  Done: $([math]::Round($bytesRead / 1GB, 1)) GB warmed in $([math]::Round($elapsed, 1))s ($rateMB MB/s avg)" -ForegroundColor Green
if ($errors -gt 0) {
    Write-Host "  $errors files skipped (locked/permission)" -ForegroundColor Yellow
}
