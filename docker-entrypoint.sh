#!/bin/bash
set -e

MODE="${1:-both}"

echo "============================================="
echo " LocalSearch Docker — mode: $MODE"
echo "============================================="

# Extract USN collector script to host (if /data is mounted)
if [ -d "/data" ] && [ -w "/data" ]; then
    echo "Extracting USN collector script to host..."
    cat > /data/extract-and-collect.ps1 << 'EOF'
#!/usr/bin/env pwsh
# Extracted by Docker container - runs USN collector natively
#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$pythonExe = "$env:USERPROFILE\Miniconda3\envs\312\python.exe"
$dataDir = $PSScriptRoot

Write-Host "=== USN Journal Collector ===" -ForegroundColor Cyan
Write-Host "Collecting changes from USN journal..." -ForegroundColor Yellow

Set-Location (Split-Path -Parent $dataDir)
& $pythonExe -m localsearch.usn_collector

if ($LASTEXITCODE -ne 0) {
    Write-Host "USN collection failed!" -ForegroundColor Red
    exit 1
}

Write-Host "USN collection complete" -ForegroundColor Green
EOF
    chmod +x /data/extract-and-collect.ps1
    echo "Script extracted to /data/extract-and-collect.ps1"
    echo "Run on host: powershell -ExecutionPolicy Bypass -File data/extract-and-collect.ps1"
fi

case "$MODE" in
    ingest)
        echo "Starting ingestion pipeline..."
        exec python -m localsearch.cli ingest
        ;;
    web)
        echo "Starting web UI on 0.0.0.0:8080..."
        exec python -m localsearch.cli web --host 0.0.0.0 --port 8080
        ;;
    both)
        echo "Starting ingestion in background + web UI..."
        # Run ingest in background, restart it when it finishes
        (
            while true; do
                echo "[ingest] Starting ingestion pass..."
                python -m localsearch.cli ingest || true
                echo "[ingest] Pass complete. Sleeping 60s before next pass..."
                sleep 60
            done
        ) &
        INGEST_PID=$!

        # Run web UI in foreground
        echo "[web] Starting web UI on 0.0.0.0:8080..."
        python -m localsearch.cli web --host 0.0.0.0 --port 8080 &
        WEB_PID=$!

        # Trap signals for clean shutdown
        trap "echo 'Shutting down...'; kill $INGEST_PID $WEB_PID 2>/dev/null; wait; exit 0" SIGTERM SIGINT

        # Wait for either process to exit
        wait -n $INGEST_PID $WEB_PID
        ;;
    shell)
        echo "Dropping to shell..."
        exec /bin/bash
        ;;
    *)
        echo "Usage: docker run localsearch [ingest|web|both|shell]"
        echo "  ingest  — run one ingestion pass then exit"
        echo "  web     — start web UI only"
        echo "  both    — continuous ingest + web UI (default)"
        echo "  shell   — drop to bash"
        exit 1
        ;;
esac
