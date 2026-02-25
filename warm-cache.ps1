<#
.SYNOPSIS
    Pre-warms the Windows filesystem page cache with Qdrant collection data.

.DESCRIPTION
    Reads every file under the Qdrant storage directory sequentially at full
    NVMe speed (~2-3.5 GB/s), pulling the data into the OS page cache. When
    Qdrant starts and mmap's these files, the pages are already resident in RAM
    — reducing startup from ~9 minutes (cold) to under 1 minute.

    This script is safe to run while Qdrant is stopped OR running. It only reads.

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

# Use the project's Python env for reliable streaming read
$Python = Join-Path $env:USERPROFILE "Miniconda3\envs\312\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "ERROR: Python not found at $Python" -ForegroundColor Red
    exit 1
}

Write-Host "Warming page cache: $Path (buffer=${BufferMB}MB)" -ForegroundColor Cyan

& $Python -u -c @"
import os, sys, time

root = sys.argv[1]
buf_size = int(sys.argv[2]) * 1024 * 1024

# Enumerate files
files = []
total_size = 0
for dirpath, dirs, fnames in os.walk(root):
    for f in fnames:
        fp = os.path.join(dirpath, f)
        try:
            sz = os.path.getsize(fp)
            files.append((fp, sz))
            total_size += sz
        except OSError:
            pass

total_gb = total_size / (1 << 30)
print(f'  {len(files)} files, {total_gb:.2f} GB to warm')

buf = bytearray(buf_size)
bytes_read = 0
errors = 0
start = time.monotonic()
last_report = start

for fp, sz in files:
    try:
        with open(fp, 'rb') as fh:
            while True:
                n = fh.readinto(buf)
                if not n:
                    break
                bytes_read += n
    except OSError:
        errors += 1

    now = time.monotonic()
    if now - last_report >= 5:
        last_report = now
        elapsed = now - start
        pct = bytes_read / total_size * 100 if total_size else 0
        rate = bytes_read / (1 << 20) / elapsed if elapsed else 0
        print(f'  {pct:.1f}% ({bytes_read/(1<<30):.1f} / {total_gb:.1f} GB) @ {rate:.0f} MB/s')

elapsed = time.monotonic() - start
rate = bytes_read / (1 << 20) / elapsed if elapsed else 0
print(f'  Done: {bytes_read/(1<<30):.1f} GB warmed in {elapsed:.1f}s ({rate:.0f} MB/s avg)')
if errors:
    print(f'  {errors} files skipped (locked/permission)')
"@ $Path $BufferMB

if ($LASTEXITCODE -ne 0) {
    Write-Host "Cache warming failed" -ForegroundColor Red
    exit 1
}
