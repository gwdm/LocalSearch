# LocalSearch Portable Package Design

## Overview

This document describes the design for a portable, self-installing LocalSearch package that can be deployed to any Windows machine with minimal prerequisites. The system uses Docker as both a distribution mechanism and runtime environment while providing a seamless installation experience.

## Core Concept: Bootstrap Container Pattern

```
┌─────────────────────────────────────────────────┐
│  Docker Container (installer image)              │
│  ├── All source code (localsearch/)             │
│  ├── Setup scripts (PowerShell, Python)         │
│  ├── Windows Python embedded distribution       │
│  ├── Config templates                            │
│  ├── Documentation                               │
│  └── Bootstrap orchestrator                      │
└─────────────────────────────────────────────────┘
                    │
                    ▼ (First run: docker run ... /install)
        ┌───────────────────────────────┐
        │   Target Windows Machine       │
        ├────────────────────────────────┤
        │ 1. Extract source → D:/LocalSearch
        │ 2. Setup Python env (embedded)
        │ 3. Deploy docker-compose.yml
        │ 4. Install Qdrant container
        │ 5. Configure Task Scheduler (USN)
        │ 6. Warm cache (download models)
        │ 7. Initial database setup
        │ 8. Initial test run
        └────────────────────────────────┘
```

## Architecture: Dual Python Environments

### Linux Python in Docker (Main Processing)
**Purpose:** All heavy processing workloads  
**Location:** `/usr/bin/python3.11` inside container  
**Executes:**
- File scanning and extraction
- Audio transcription (Whisper + GPU)
- Image OCR (Tesseract)
- Embedding generation (GPU)
- Qdrant vector indexing
- Web UI serving (Flask)
- Search/RAG queries

### Windows Python (USN Collection Only)
**Purpose:** Windows NTFS API access  
**Location:** `D:\LocalSearch\python-env\` (mounted from Docker)  
**Executes:**
- USN journal reading (pywin32)
- Change detection script
- Writes `usn_changes.txt`

**Key Innovation:** Windows Python is stored inside Docker container as static files, then mounted to host filesystem via Docker volume. No Python installation on host system required!

```
Docker Container (Linux):
└── /python-windows/              # Windows binaries (never executed in Linux)
    ├── python.exe
    ├── python312.dll
    └── Lib/site-packages/pywin32/

    ↓ Volume Mount ↓

Windows Host:
└── D:\LocalSearch\python-env\    # Mounted from container
    └── python.exe                # Host Task Scheduler executes this
```

## Installation Options

### Option 1: Assume Docker Pre-Installed (Simplest)
**Prerequisites:** Docker Desktop for Windows  
**Installation:** `docker run localsearch:installer`  
**Result:** Fully working LocalSearch in `D:\LocalSearch\`

**Pros:**
- Simplest implementation
- Small download (just Docker image)
- Fast deployment

**Cons:**
- User must install Docker manually first
- Not truly "one-click"

### Option 2: Bundled Docker Installer (Complete Package)
**Prerequisites:** None (includes everything)  
**Package Size:** ~8.5 GB  
**Contents:**
```
LocalSearch-Installer.exe         (30 MB)
├── Embedded: DockerDesktopInstaller.exe  (~500 MB)
└── Embedded: localsearch-installer.tar    (~8 GB Docker image)
```

**Installation Flow:**
1. Extract embedded Docker Desktop installer
2. Run Docker installation → Wait for completion
3. Reboot if needed
4. Load embedded Docker image
5. Run LocalSearch setup

**Pros:**
- True "one-click" installer
- Works on bare Windows machine
- No internet required after download

**Cons:**
- Very large download (8.5 GB)
- Must re-download for updates
- Static Docker version

### Option 3: Smart Bootstrap (Recommended)
**Prerequisites:** Internet connection  
**Initial Download:** ~5 MB  
**Total Download:** ~3-10 GB (on-demand)

**Package Structure:**
```
LocalSearch-Bootstrap.exe  (5 MB)
├── PowerShell/C# launcher
├── Docker detection logic
├── Guided Docker installation
└── LocalSearch setup orchestration
```

**Installation Flow:**
```
1. Run LocalSearch-Bootstrap.exe
   ↓
2. Check for Docker
   ├─ Found → Skip to step 4
   └─ Not found → Show GUI prompt
      ├─ [Yes, install Docker]
      │   └─ Download Docker Desktop (~500 MB)
      │       └─ Run installer → Reboot prompt
      └─ [Manual installation]
          └─ Open browser to docker.com
              └─ Wait for user → Retry check
   ↓
3. Wait for Docker to be ready
   └─ Check Docker service status
   ↓
4. Pull localsearch:installer image
   └─ docker pull localsearch:installer (~8 GB first time, cached after)
   ↓
5. Run installer container
   └─ docker run -v D:\LocalSearch:/install localsearch:installer
   ↓
6. Automated setup (see Installation Phases below)
   ↓
7. Launch dashboard → http://localhost:8080
```

**Pros:**
- ✅ Small initial download (5 MB)
- ✅ Always pulls latest LocalSearch image
- ✅ Can optionally automate Docker installation
- ✅ Works on fresh Windows machine
- ✅ Cached Docker image for subsequent installs

**Cons:**
- Requires internet connection
- Download time on first install (~10 min)

## Installation Phases

### Phase 1: Extract & Configure
```powershell
# run-installer.ps1 (executed by Docker container)

1. Extract source code to D:\LocalSearch\
   - localsearch/ (Python package)
   - docker-compose.yml
   - config.yaml.template
   - Scripts (start.ps1, stop.ps1, etc.)

2. Copy Windows Python to D:\LocalSearch\python-env\
   - python.exe
   - python312.dll
   - Scripts/
   - Lib/ (including pywin32)

3. Interactive configuration:
   ├── "Which directories to scan?" → config.yaml: scan_paths
   ├── "Where to store database?" → config.yaml: db_path (default: D:\LocalSearch\data)
   ├── "Where to store Qdrant?" → docker-compose.yml volume (default: D:\qdrant_data)
   ├── "Enable audio transcription? (GPU required)" → config.yaml: audio_enabled
   └── "OpenAI API key for RAG?" → config.yaml: openai_api_key (optional)
```

### Phase 2: Database Initialization
```powershell
4. Initialize SQLite metadb:
   python-env\python.exe -c "
   from localsearch.storage.metadb import MetadataDB
   db = MetadataDB('D:/LocalSearch/data/metadata.db')
   db.initialize()  # Creates tables: files, chunks, errors
   "

5. Start Qdrant container:
   docker-compose up -d qdrant
   Wait for healthy status (healthcheck every 15s)...

6. Initialize Qdrant collection:
   docker exec localsearch-app python -c "
   from localsearch.storage.vectordb import VectorDB
   vdb = VectorDB()
   vdb.ensure_collection('localsearch', dimension=1024)
   "
```

### Phase 3: Model Warmup
```powershell
# On first start (and every container start)

7. Download embedding model (if not cached):
   docker exec localsearch-app python -c "
   from sentence_transformers import SentenceTransformer
   print('Downloading embedding model (1.5 GB)...')
   model = SentenceTransformer('mixedbread-ai/mxbai-embed-large-v1')
   # Downloads to /root/.cache (mounted volume for persistence)
   "

8. Download Whisper model (if audio enabled and not cached):
   docker exec localsearch-app python -c "
   from faster_whisper import WhisperModel
   print('Downloading Whisper model (3 GB)...')
   model = WhisperModel('large-v3', device='cuda', download_root='/root/.cache')
   "

   Total warmup download: ~4.5 GB (one-time, cached in model_cache volume)
```

### Phase 4: USN Journal Setup
```powershell
9. Register Task Scheduler:
   $action = New-ScheduledTaskAction `
     -Execute "D:\LocalSearch\python-env\python.exe" `
     -Argument "D:\LocalSearch\scripts\extract-and-collect.ps1" `
     -WorkingDirectory "D:\LocalSearch"
   
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
   
   Register-ScheduledTask `
     -TaskName "LocalSearch-USN" `
     -Action $action `
     -Trigger $trigger `
     -Description "LocalSearch USN journal change detection" `
     -RunLevel Highest

10. Initial USN collection:
    python-env\python.exe scripts\extract-and-collect.ps1
    # Creates data/usn_state.json with initial journal state
    # Creates data/usn_changes.txt (empty on first run)
```

### Phase 5: Initial Scan & Start Services
```powershell
11. First ingestion run:
    Write-Host "Starting initial file scan and indexing..."
    docker exec localsearch-app python -m localsearch.cli ingest --initial
    # Scans all configured paths, processes files
    # May take minutes to hours depending on file count

12. Start web UI:
    docker-compose up -d localsearch
    Start-Sleep -Seconds 5
    
    Write-Host ""
    Write-Host "✅ LocalSearch installation complete!"
    Write-Host ""
    Write-Host "Dashboard: http://localhost:8080"
    Write-Host "Status: .\scripts\status.ps1"
    Write-Host "Logs: docker logs localsearch-app -f"
    Write-Host ""
```

## Docker Container Structure

### Dockerfile.installer
```dockerfile
# Multi-stage build for installer image

# ============= Stage 1: Runtime (Linux) =============
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev python3-pip \
        ffmpeg tesseract-ocr \
        libglib2.0-0 libsm6 libxext6 libxrender-dev \
        curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install Python dependencies
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .
RUN pip install --no-cache-dir -e .

# ============= Stage 2: Windows Python (embedded) =============
FROM runtime AS windows-python

# Download Windows embedded Python (portable, no installer needed)
RUN curl -L https://www.python.org/ftp/python/3.12.0/python-3.12.0-embed-amd64.zip \
    -o /tmp/python-windows.zip && \
    mkdir -p /python-windows && \
    unzip /tmp/python-windows.zip -d /python-windows/ && \
    rm /tmp/python-windows.zip

# Unlock pip in embedded Python (remove import site restriction)
RUN sed -i 's/^#import site/import site/' /python-windows/python312._pth

# Download get-pip.py and install pip
RUN curl -L https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && \
    /python-windows/python.exe /tmp/get-pip.py && \
    rm /tmp/get-pip.py

# Install pywin32 wheel for Windows
RUN curl -L https://github.com/mhammond/pywin32/releases/download/b306/pywin32-306-cp312-cp312-win_amd64.whl \
    -o /tmp/pywin32.whl && \
    /python-windows/python.exe -m pip install /tmp/pywin32.whl && \
    rm /tmp/pywin32.whl

# ============= Stage 3: Installer Bundle =============
FROM runtime AS installer

# Copy Windows Python from previous stage
COPY --from=windows-python /python-windows /python-windows

# Copy installation scripts
COPY install/ /install/
RUN chmod +x /install/*.sh /install/*.ps1

# Default config for installer mode
ENV LOCALSEARCH_INSTALLER_MODE=1

EXPOSE 8080

# Entrypoint detects mode: install vs. runtime
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
```

### docker-entrypoint.sh (Dual Mode)
```bash
#!/bin/bash
set -e

# ============= Installer Mode =============
if [ "$LOCALSEARCH_INSTALLER_MODE" = "1" ]; then
    echo "Running in INSTALLER mode..."
    
    # Check if target directory is mounted
    if [ ! -d /install ]; then
        echo "ERROR: No /install volume mounted!"
        echo "Usage: docker run -v D:/LocalSearch:/install localsearch:installer"
        exit 1
    fi
    
    # Extract source code
    echo "Extracting source code..."
    cp -r /app/* /install/
    
    # Extract Windows Python
    echo "Extracting Windows Python environment..."
    cp -r /python-windows /install/python-env
    
    # Run PowerShell installer script
    echo "Starting installation wizard..."
    cd /install
    exec ./install/run-installer.sh
    
    exit 0
fi

# ============= Runtime Mode =============
echo "Running in RUNTIME mode..."

# Warmup: Ensure models are cached (fast if already downloaded)
echo "Warming up models..."
python -c "
from sentence_transformers import SentenceTransformer
print('Loading embedding model...')
SentenceTransformer('mixedbread-ai/mxbai-embed-large-v1')
print('✓ Embedding model ready')
" &
WARMUP_PID=$!

# Initialize databases if they don't exist
python -c "
from localsearch.storage.metadb import MetadataDB
from localsearch.storage.vectordb import VectorDB
print('Initializing databases...')
MetadataDB().initialize()
VectorDB().ensure_collection()
print('✓ Databases ready')
" || echo "Databases already initialized"

# Wait for warmup to complete
wait $WARMUP_PID

# Start application based on command
case "$1" in
    web)
        echo "Starting web UI only..."
        exec python -m localsearch.web.app
        ;;
    ingest)
        echo "Starting ingestion only..."
        exec python -m localsearch.cli ingest
        ;;
    *)
        # Default: run both (web UI + background ingestion)
        echo "Starting web UI + background ingestion..."
        python -m localsearch.cli ingest &
        exec python -m localsearch.web.app
        ;;
esac
```

### docker-compose.yml (Generated Template)
```yaml
services:
  # ========== Vector Database ==========
  qdrant:
    image: qdrant/qdrant:latest
    container_name: localsearch-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ${QDRANT_DATA_PATH:-D:/qdrant_data}:/qdrant/storage
    restart: unless-stopped
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/localhost/6333; printf \"GET /healthz HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n\" >&3; cat <&3' 2>/dev/null | grep -q '200 OK'"]
      interval: 15s
      timeout: 10s
      retries: 80
      start_period: 60s

  # ========== LocalSearch Application ==========
  localsearch:
    image: localsearch:latest
    container_name: localsearch-app
    depends_on:
      qdrant:
        condition: service_healthy
    ports:
      - "8080:8080"
    volumes:
      # Scan directories (generated from config)
      - ${SCAN_PATH_1}:/scandata:ro
      # Add more scan paths as configured
      
      # Application data
      - ${INSTALL_PATH}/data:/data
      - ${INSTALL_PATH}/python-env:/python-windows  # Windows Python (shared with host)
      
      # Model cache (persistent across rebuilds)
      - model_cache:/root/.cache
      
    environment:
      - LOCALSEARCH_CONFIG=/app/config.docker.yaml
      - NVIDIA_VISIBLE_DEVICES=all
      - LOCALSEARCH_INSTALLER_MODE=0  # Runtime mode
      
    restart: unless-stopped
    
    # GPU access
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  model_cache:
```

## Configuration Files

### config.yaml.template
```yaml
# LocalSearch Configuration Template
# This file is processed during installation

# Directories to scan (absolute Windows paths)
scan_paths:
  - D:/Documents
  - D:/Projects
  # INSTALLER_PROMPT: Add scan paths

# Database locations
db_path: ${INSTALL_PATH}/data/metadata.db
qdrant_host: qdrant
qdrant_port: 6333

# Embedding configuration
embedding_model: mixedbread-ai/mxbai-embed-large-v1
embedding_dimension: 1024
embedding_batch_size: 32
embedding_device: cuda  # or 'cpu' if no GPU

# Audio transcription
audio_enabled: true  # INSTALLER_PROMPT: Enable audio (requires GPU)?
audio_model: large-v3  # Options: tiny, base, small, medium, large-v3
audio_device: cuda
audio_timeout: 300  # seconds per file
audio_batch_size: 1

# Text extraction
max_file_size_mb: 500
text_chunk_size: 1000
text_chunk_overlap: 200

# Processing
workers: 8  # CPU workers for parallel extraction
batch_size: 100  # Files per batch
max_fails: 3  # Max retry attempts per file

# RAG/Chat (optional)
openai_api_key: null  # INSTALLER_PROMPT: OpenAI API key (optional)
openai_model: gpt-4o-mini
rag_top_k: 10

# USN Journal
usn_journal_enabled: true
usn_scan_interval: 300  # seconds (5 minutes)
usn_state_file: ${INSTALL_PATH}/data/usn_state.json
usn_changes_file: ${INSTALL_PATH}/data/usn_changes.txt

# Web UI
web_host: 0.0.0.0
web_port: 8080
web_debug: false
```

## Installation Scripts

### install/run-installer.sh
```bash
#!/bin/bash
# Main installer orchestrator (runs inside container)

echo "================================================"
echo "  LocalSearch Installation Wizard"
echo "================================================"
echo ""

# Check Windows host (PowerShell availability via volume mount indicator)
if [ ! -d "/install" ]; then
    echo "ERROR: Installation directory not mounted!"
    exit 1
fi

# Copy installation scripts to host
cp /install/*.ps1 /install/scripts/
chmod +x /install/scripts/*.ps1

# Generate configuration
echo "Generating configuration files..."
python /install/configure.py

# Hand off to PowerShell for Windows-specific tasks
echo ""
echo "Launching Windows configuration..."
echo "You may be prompted for administrator access (Task Scheduler setup)."
echo ""

# Signal PowerShell to continue
touch /install/.ready

# Wait for PowerShell completion
while [ ! -f /install/.complete ]; do
    sleep 1
done

echo ""
echo "✅ Installation complete!"
exit 0
```

### install/configure.py
```python
#!/usr/bin/env python3
"""
Interactive configuration generator
Prompts user for settings and generates config.yaml
"""
import os
import yaml
from pathlib import Path

def prompt(question, default=None):
    """Prompt user with optional default."""
    if default:
        response = input(f"{question} [{default}]: ").strip()
        return response or default
    return input(f"{question}: ").strip()

def prompt_bool(question, default=True):
    """Prompt for yes/no."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{question} [{default_str}]: ").strip().lower()
    if not response:
        return default
    return response in ('y', 'yes')

def main():
    print("=== LocalSearch Configuration ===")
    print()
    
    config = {}
    
    # Scan paths
    print("Enter directories to scan (one per line, empty line to finish):")
    scan_paths = []
    while True:
        path = input("  Path: ").strip()
        if not path:
            break
        scan_paths.append(path)
    
    config['scan_paths'] = scan_paths or ['D:/Documents']
    
    # Database location
    install_path = os.getenv('INSTALL_PATH', 'D:/LocalSearch')
    config['db_path'] = f"{install_path}/data/metadata.db"
    
    # Audio transcription
    config['audio_enabled'] = prompt_bool("Enable audio transcription? (requires GPU)", True)
    
    if config['audio_enabled']:
        print("\nWhisper model sizes (larger = more accurate but slower):")
        print("  tiny   - Fastest, least accurate (~75 MB)")
        print("  base   - Good balance (~150 MB)")
        print("  small  - Better quality (~500 MB)")
        print("  medium - High quality (~1.5 GB)")
        print("  large-v3 - Best quality (~3 GB, recommended)")
        
        model = prompt("Whisper model", "large-v3")
        config['audio_model'] = model
    
    # OpenAI API key (optional)
    print("\nOpenAI API key (optional, for RAG chat features):")
    print("Leave empty to skip chat features.")
    api_key = prompt("API key", "")
    config['openai_api_key'] = api_key or None
    
    # Write config
    config_path = '/install/config.yaml'
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    print(f"\n✅ Configuration saved to {config_path}")

if __name__ == '__main__':
    main()
```

### scripts/start.ps1
```powershell
# Start LocalSearch services

Write-Host "Starting LocalSearch..." -ForegroundColor Cyan

# Start containers
docker-compose up -d

Write-Host ""
Write-Host "✅ LocalSearch is starting..." -ForegroundColor Green
Write-Host "   Dashboard: http://localhost:8080" -ForegroundColor Yellow
Write-Host "   Logs: docker logs localsearch-app -f"
Write-Host ""
```

### scripts/stop.ps1
```powershell
# Stop LocalSearch services gracefully

Write-Host "Stopping LocalSearch..." -ForegroundColor Cyan

docker-compose down

Write-Host "✅ LocalSearch stopped" -ForegroundColor Green
```

### scripts/status.ps1
```powershell
# Check LocalSearch status

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $scriptDir "..\python-env\python.exe"

& $pythonExe -c @"
import sqlite3
import json
from pathlib import Path

db_path = Path('$scriptDir/../data/metadata.db')

if not db_path.exists():
    print('❌ Database not found. Run initial scan.')
    exit(1)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

# File statistics
cur.execute(\"SELECT status, COUNT(*) FROM files GROUP BY status\")
stats = dict(cur.fetchall())

total = sum(stats.values())
indexed = stats.get('indexed', 0)
pending = stats.get('pending', 0)
errors = stats.get('error', 0)

print(f'Total files: {total:,}')
print(f'  Indexed: {indexed:,} ({indexed/total*100:.1f}%)' if total else 'No files yet')
print(f'  Pending: {pending:,}')
print(f'  Errors: {errors:,}')

# Chunk count
cur.execute(\"SELECT COUNT(*) FROM chunks\")
chunks = cur.fetchone()[0]
print(f'\\nTotal chunks: {chunks:,}')

conn.close()
"@

Write-Host ""
Write-Host "Docker containers:" -ForegroundColor Cyan
docker ps --filter "name=localsearch" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### scripts/uninstall.ps1
```powershell
# Complete LocalSearch removal

Write-Host "⚠️  This will completely remove LocalSearch" -ForegroundColor Yellow
Write-Host "   - Stop and remove Docker containers"
Write-Host "   - Unregister scheduled task"
Write-Host "   - Delete all data (database, vectors, cache)"
Write-Host ""

$confirm = Read-Host "Type 'DELETE' to confirm"
if ($confirm -ne 'DELETE') {
    Write-Host "Cancelled." -ForegroundColor Green
    exit 0
}

$installPath = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "Stopping containers..." -ForegroundColor Cyan
Push-Location $installPath
docker-compose down -v  # Remove volumes too
Pop-Location

Write-Host "Unregistering scheduled task..." -ForegroundColor Cyan
try {
    Unregister-ScheduledTask -TaskName "LocalSearch-USN" -Confirm:$false -ErrorAction Stop
    Write-Host "✅ Task unregistered"
} catch {
    Write-Host "⚠️  Task not found (already removed?)"
}

Write-Host "Deleting installation directory..." -ForegroundColor Cyan
Write-Host "   $installPath"
Remove-Item $installPath -Recurse -Force

Write-Host ""
Write-Host "✅ LocalSearch completely removed" -ForegroundColor Green
```

## Final Directory Structure

After installation, the target machine will have:

```
D:\LocalSearch\
├── config.yaml              # User configuration
├── docker-compose.yml      # Container orchestration
├── INSTALL-LOG.txt         # Installation timestamps, versions
│
├── python-env\             # Windows Python (from Docker)
│   ├── python.exe
│   ├── python312.dll
│   ├── Scripts\
│   │   └── pip.exe
│   └── Lib\
│       └── site-packages\
│           └── pywin32\    # USN journal access
│
├── localsearch\            # Source code
│   ├── __init__.py
│   ├── cli.py
│   ├── pipeline.py
│   ├── worker.py
│   ├── extractors\
│   ├── crawler\
│   ├── storage\
│   ├── query\
│   └── web\
│
├── data\                   # Persistent data
│   ├── metadata.db         # SQLite (initialized)
│   ├── usn_state.json      # USN journal state
│   └── usn_changes.txt     # Incremental changes
│
└── scripts\                # Management scripts
    ├── start.ps1           # Start services
    ├── stop.ps1            # Stop services
    ├── status.ps1          # Check status
    ├── uninstall.ps1       # Complete removal
    ├── extract-and-collect.ps1  # USN collection
    └── register-task.ps1   # Task Scheduler setup

D:\qdrant_data\             # Qdrant vector storage
└── (managed by Qdrant container)

Task Scheduler:
└── LocalSearch-USN         # Runs every 5 minutes
    → D:\LocalSearch\python-env\python.exe
    → D:\LocalSearch\scripts\extract-and-collect.ps1
```

## User Experience Summary

### First-Time Installation (New Machine)
```
1. Download LocalSearch-Bootstrap.exe (5 MB) → 30 seconds
2. Run installer → Detects no Docker
3. "Docker required. Install now? [Yes]"
4. Download Docker Desktop (~500 MB) → 5 minutes
5. Install Docker → Reboot required → 2 minutes
6. Restart installer → Detects Docker
7. Pull localsearch:installer (~8 GB) → 10 minutes
8. Interactive configuration:
   - "Which directories to scan?" → D:/Documents, D:/Projects
   - "Enable audio transcription?" → Yes
   - "OpenAI API key?" → (skip)
9. Extract files → 2 minutes
10. Download models (embedding + Whisper ~4.5 GB) → 5 minutes
11. Initial scan (1000 files) → 5 minutes
12. ✅ Dashboard opens: http://localhost:8080

Total time: ~30 minutes (mostly downloads)
```

### Subsequent Installations (Docker Already Present)
```
1. Run LocalSearch-Bootstrap.exe
2. Docker detected → Skip installation
3. Pull localsearch:installer (cached) → Instant
4. Interactive configuration → 2 minutes
5. Extract files → 2 minutes
6. Models cached → Skip download
7. Initial scan → 5 minutes
8. ✅ Dashboard ready

Total time: ~10 minutes
```

### Developer Workflow (Source Code Changes)
```
1. Edit code in D:\LocalSearch\localsearch\
2. Rebuild container: docker-compose build
3. Restart: docker-compose up -d
4. Test changes

Note: Source code is on host (editable), copied into container at build time
For live development, could mount source code as volume (optional)
```

## Key Benefits

✅ **Zero Python footprint on host** - Everything in D:\LocalSearch\  
✅ **Portable** - Copy folder to another machine, run docker-compose up  
✅ **Reproducible** - Same environment every time  
✅ **Clean uninstall** - Delete folder + unregister task  
✅ **Self-contained** - All dependencies in Docker  
✅ **Versionable** - Tag installer images (v1.0, v1.1, etc.)  
✅ **Hybrid architecture** - Heavy processing in Docker, USN on host  
✅ **Developer-friendly** - Source code on host for editing  

## Implementation Checklist

### Phase 1: Docker Installer Image
- [ ] Create Dockerfile.installer with multi-stage build
- [ ] Download and embed Windows Python (embedded distribution)
- [ ] Install pywin32 wheel in Windows Python
- [ ] Create docker-entrypoint.sh with installer/runtime modes
- [ ] Build and test installer image

### Phase 2: Installation Scripts
- [ ] Create install/run-installer.sh (orchestrator)
- [ ] Create install/configure.py (interactive config)
- [ ] Create scripts/start.ps1, stop.ps1, status.ps1
- [ ] Create scripts/extract-and-collect.ps1 (USN)
- [ ] Create scripts/register-task.ps1 (Task Scheduler)
- [ ] Create scripts/uninstall.ps1
- [ ] Test extraction flow

### Phase 3: Configuration Templates
- [ ] Create config.yaml.template with prompts
- [ ] Create docker-compose.yml.template with variable substitution
- [ ] Implement configuration generation logic
- [ ] Test various configuration scenarios

### Phase 4: Bootstrap Launcher
- [ ] Create LocalSearch-Bootstrap.exe (PowerShell or C#)
- [ ] Implement Docker detection
- [ ] Add Docker installation option
- [ ] Add image pull progress display
- [ ] Test on clean Windows machine

### Phase 5: Database Initialization
- [ ] Add MetadataDB.initialize() to create schema
- [ ] Add VectorDB.ensure_collection() for Qdrant
- [ ] Implement model pre-download (warmup)
- [ ] Test initialization on fresh install

### Phase 6: Documentation
- [ ] User guide (README.md)
- [ ] Troubleshooting guide
- [ ] Developer guide (source code editing)
- [ ] Architecture documentation

### Phase 7: Testing
- [ ] Test on Windows 10 (clean machine)
- [ ] Test on Windows 11 (clean machine)
- [ ] Test with GPU (NVIDIA)
- [ ] Test without GPU (CPU fallback)
- [ ] Test Docker already installed
- [ ] Test uninstall/reinstall
- [ ] Test upgrades (v1.0 → v1.1)

## Future Enhancements

- **Docker Registry**: Publish installer image to Docker Hub or private registry
- **Auto-updates**: Check for new versions, prompt to upgrade
- **GUI installer**: Replace PowerShell prompts with Windows Forms/WPF
- **Linux support**: Create parallel installer for Ubuntu/Debian (no USN, use inotify)
- **macOS support**: Adapt for macOS (FSEvents instead of USN)
- **Cloud deployment**: Azure/AWS version with managed Postgres + Qdrant
- **Multi-machine**: Central Qdrant server, multiple scan agents

## Notes

- Windows Python embedded distribution is ~25 MB compressed
- Total Docker image size: ~17 GB (includes CUDA runtime)
- First-time model download: ~4.5 GB (cached after)
- USN collection overhead: <100 KB/day for typical usage
- Recommended minimum: 16 GB RAM, 50 GB free disk, NVIDIA GPU (optional)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-26  
**Status:** Design Complete, Ready for Implementation
