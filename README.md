# LocalSearch

Fully local RAG (Retrieval-Augmented Generation) pipeline for semantic search
across files on NAS / local storage. Everything runs on your own hardware — no
cloud APIs required.

**Stack:** Python 3.12 · Qdrant (vector DB) · sentence-transformers (CUDA
embeddings) · faster-whisper (audio/video) · Tesseract OCR (images) · Ollama
(LLM for Q&A) · Flask web UI

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running — Quick Start](#running--quick-start)
5. [CLI Reference](#cli-reference)
6. [Batch Launchers](#batch-launchers)
7. [PowerShell Startup Script](#powershell-startup-script)
8. [Docker](#docker)
9. [Web UI](#web-ui)
10. [NTFS USN Journal (Fast Rescan)](#ntfs-usn-journal-fast-rescan)
11. [Project Layout](#project-layout)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Component | Notes |
|-----------|-------|
| **Python 3.11+** | Developed on 3.12.8 via Miniconda (`312` env) |
| **NVIDIA GPU + CUDA 12.x** | For embedding & Whisper; CPU-only works but is slow |
| **Docker Desktop** | For Qdrant (and optional containerised ingest) |
| **Tesseract OCR** | `choco install tesseract` or install manually for image text extraction |
| **Ollama** | `ollama serve` on localhost:11434 for the `ask` (RAG) command |
| **ffmpeg** | Required by faster-whisper for audio/video transcription |

## Installation

```powershell
# Clone / enter project
cd D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch

# Create & activate conda env (or venv)
conda create -n 312 python=3.12 -y
conda activate 312

# Install in editable mode
pip install -e .

# (Optional) dev / test dependencies
pip install -e ".[dev]"
```

After install the `localsearch` CLI is available globally in the env, and you
can also invoke via `python -m localsearch.cli`.

---

## Configuration

All settings live in **`config.yaml`** (native / local runs) or
**`config.docker.yaml`** (Docker runs).

### Key settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `scan_paths` | `["D:/"]` | Directories to recursively scan |
| `qdrant.host` / `port` | `localhost:6333` | Qdrant connection |
| `embedding.model` | `mixedbread-ai/mxbai-embed-large-v1` | 1024-dim model |
| `embedding.device` | `cuda` | `cuda` or `cpu` |
| `whisper.model_size` | `large-v3` | faster-whisper model for audio/video |
| `scanner.use_usn_journal` | `true` | NTFS change journal for fast rescans |
| `pipeline.cpu_workers` | `8` | Parallel extraction processes |
| `pipeline.embed_batch_size` | `256` | Chunks batched before embedding |
| `metadata_db` | `data/localsearch_meta.db` | SQLite tracking DB |
| `ollama.model` | `llama3` | LLM used by `ask` command |
| `log_level` | `INFO` | Python logging level |

Edit `config.yaml` to change scan paths, file-size limits, GPU settings, etc.

---

## Running — Quick Start

> **Important:** Qdrant must be running before ingest / search / web commands.

### 1. Start Qdrant

```powershell
docker compose up -d qdrant
```

Wait for it to load the collection (~30 GB, takes ~9 min cold, ~1 min warm):

```powershell
# Quick readiness check
Invoke-RestMethod http://localhost:6333/collections
```

### 2. Run Ingestion

```powershell
# Using the installed CLI entry point
localsearch ingest

# Or via python -m
& "$env:USERPROFILE\Miniconda3\envs\312\python.exe" -m localsearch.cli ingest
```

Scan specific paths instead of what's in config:

```powershell
localsearch ingest -p "D:\OneDrive\Documents" -p "D:\Projects"
```

### 3. Search

```powershell
localsearch search "quarterly budget report"
localsearch search "kubernetes deployment" -k 20 -t pdf
```

Options:
- `-k` / `--top-k` — Number of results (default: 10)
- `-t` / `--file-type` — Filter: `text`, `pdf`, `docx`, `audio`, `video`, `image`, `msg`

### 4. Ask a Question (RAG)

Requires Ollama running (`ollama serve`):

```powershell
localsearch ask "What were the key decisions in the Q3 board meeting?"
localsearch ask "Summarise the audio transcript from the interview" -t audio
```

### 5. Check Status

```powershell
localsearch status
```

Shows total files tracked, indexed, pending, errors, chunk count, and vector
count in Qdrant.

### 6. Reset (Delete All Data)

```powershell
localsearch reset
```

Prompts for confirmation, then clears the metadata DB and Qdrant collection.

---

## CLI Reference

All commands accept `--config / -c` to specify an alternative config file.

```
localsearch [--config PATH] <command>
```

| Command | Description |
|---------|-------------|
| `ingest` | Scan files → extract text → chunk → embed → store in Qdrant |
| `search QUERY` | Semantic search across indexed files |
| `ask QUESTION` | RAG: search + LLM-generated answer with sources |
| `status` | Show indexing statistics |
| `dashboard` | Open live TUI dashboard (Rich-based, shows ingest progress) |
| `web` | Start Flask web UI (dashboard + search + chat) |
| `reset` | Delete all indexed data (with confirmation) |

### `ingest` options

| Flag | Description |
|------|-------------|
| `-p PATH` | One or more specific paths to scan (overrides `config.yaml`) |

### `search` options

| Flag | Description |
|------|-------------|
| `-k N` | Number of results (default: from config, usually 10) |
| `-t TYPE` | Filter by file type |

### `ask` options

| Flag | Description |
|------|-------------|
| `-k N` | Number of context chunks to use |
| `-t TYPE` | Filter by file type |

### `web` options

| Flag | Description |
|------|-------------|
| `-h HOST` | Bind address (default: `0.0.0.0`) |
| `-p PORT` | Port number (default: `8080`) |
| `--debug` | Enable Flask debug mode (dev only) |

---

## Batch Launchers

Double-click these from Explorer for one-click operation:

| File | What it does |
|------|-------------|
| **`run.bat`** | Generic launcher: `run.bat <command> [options]` — routes to CLI |
| **`ingest.bat`** | Shortcut: runs `localsearch ingest` then pauses |
| **`dashboard.bat`** | Shortcut: runs `localsearch dashboard` (TUI) |

All `.bat` files auto-detect the Python environment at
`%USERPROFILE%\Miniconda3\envs\312\python.exe`.

---

## PowerShell Startup Script

**`start.ps1`** is the recommended way to bring up the full stack:

```powershell
.\start.ps1                     # warm cache → Qdrant → web UI
.\start.ps1 -Ingest             # also run Docker ingest after startup
.\start.ps1 -SkipWarm           # skip page-cache warming
.\start.ps1 -WebPort 9090       # web UI on a different port
.\start.ps1 -QdrantTimeout 900  # wait longer for Qdrant (default 600s)
```

### What it does (in order)

1. **Warm page cache** — `warm-cache.ps1` streams all Qdrant data files through
   RAM at NVMe speed (~30 GB in ~5 s hot / ~15 s cold). When Qdrant mmap's the
   files they're already resident → startup drops from ~9 min to ~1 min.
2. **Start Qdrant** — `docker compose up -d qdrant`
3. **Wait for readiness** — polls `http://localhost:6333/collections` every 10 s
4. **Start web UI** — launches `localsearch web --port 8080` in a minimised window
5. *(Optional)* **Docker ingest** — `docker compose run --rm localsearch ingest`

### Warming the cache manually

```powershell
.\warm-cache.ps1                          # default: D:\qdrant_data, 4 MB buffer
.\warm-cache.ps1 -Path "E:\qdrant_data"   # different path
.\warm-cache.ps1 -BufferMB 8              # larger buffer
```

---

## Docker

The project is fully containerised. `docker-compose.yml` defines two services:

### Services

| Service | Image | Purpose |
|---------|-------|---------|
| `qdrant` | `qdrant/qdrant:latest` | Vector database, ports 6333/6334 |
| `localsearch` | Built from `Dockerfile` | Ingest + web UI, CUDA GPU enabled |

### Docker Compose Commands

```powershell
# Start everything (Qdrant + continuous ingest loop + web UI)
docker compose up -d

# Start only Qdrant
docker compose up -d qdrant

# Run a one-shot ingest (Qdrant must be healthy)
docker compose run --rm localsearch ingest

# Start only the web UI in Docker
docker compose run --rm -p 8080:8080 localsearch web

# Drop into a shell inside the container
docker compose run --rm localsearch shell

# Rebuild after code changes
docker compose build localsearch
```

### Docker Entrypoint Modes

The container entrypoint (`docker-entrypoint.sh`) accepts these modes:

| Mode | Description |
|------|-------------|
| `ingest` | Run one ingestion pass then exit |
| `web` | Start web UI only on port 8080 |
| `both` | *(default)* Continuous ingest loop + web UI |
| `shell` | Drop to bash for debugging |

### Docker Config

Docker runs use `config.docker.yaml`, which differs from the local config:
- `scan_paths: ["/scandata"]` — host `D:\` is mounted at `/scandata`
- `qdrant.host: "qdrant"` — Docker service name instead of `localhost`
- `ollama.host: "http://host.docker.internal:11434"` — reaches host Ollama
- `metadata_db: "/data/localsearch_meta.db"` — bind-mounted to `LocalSearch/data/`
- `path_map: {"/scandata": "D:\\"}` — translates container paths to Windows paths
  in the shared metadata DB

### Volumes

| Mount | Purpose |
|-------|---------|
| `D:/qdrant_data:/qdrant/storage` | Qdrant persistent data (~30 GB) |
| `D:/:/scandata:ro` | Host files visible to scanner (read-only) |
| `LocalSearch/data:/data` | Shared SQLite metadata DB |
| `localsearch_model_cache:/root/.cache` | Cached embedding/Whisper models |

---

## Web UI

```powershell
localsearch web                  # http://0.0.0.0:8080
localsearch web --port 9090      # custom port
localsearch web --debug          # Flask debug mode
```

The web UI uses a Catppuccin Mocha dark theme and provides:

- **Dashboard** — live ingestion status, file counts, Qdrant stats
- **Search** — semantic search with file-type filters, score display
- **Chat** — RAG-powered Q&A with source references

Access from another machine via Tailscale: `http://sirius:8080` or
`http://100.126.184.18:8080`.

---

## NTFS USN Journal (Fast Rescan)

On Windows, LocalSearch can read the NTFS USN (Update Sequence Number) Change
Journal to detect file changes without doing a full directory walk. This makes
repeat ingests dramatically faster.

### Requirements

- **Windows only** — Linux/macOS fall back to full directory walk automatically
- **Administrator** — reading the USN journal requires `GENERIC_READ` on the
  volume handle, which needs elevated privileges
- Config: `scanner.use_usn_journal: true` (default)

### How it works

1. First ingest does a full directory walk and saves the journal position to
   `data/usn_state.json`
2. Subsequent ingests read only the changes since the last saved position
3. If the journal has wrapped (entries deleted) it auto-clamps and does a full
   walk as fallback
4. If not running as admin, the volume handle open fails → automatic fallback
   to full walk (no crash, just slower)

### Increasing journal size

The default Windows USN journal is small (~32 MB) and can wrap quickly on busy
volumes. To increase it to 1 GB:

```powershell
# Run as Administrator
fsutil usn createJournal m=1073741824 a=134217728 D:

# Verify
fsutil usn queryJournal D:
# → Maximum Size: 0x40000000 (1.0 GB)
# → Allocation Delta: 0x8000000 (128 MB)
```

---

## Project Layout

```
LocalSearch/
├── config.yaml              # Local configuration
├── config.docker.yaml       # Docker configuration
├── docker-compose.yml       # Qdrant + LocalSearch services
├── Dockerfile               # CUDA 12.4 + Python 3.11 container
├── docker-entrypoint.sh     # Container mode selector
├── pyproject.toml           # Package metadata & dependencies
├── start.ps1                # Full startup orchestrator
├── warm-cache.ps1           # Qdrant page cache pre-warmer
├── run.bat                  # Generic CLI launcher
├── ingest.bat               # One-click ingest
├── dashboard.bat            # One-click TUI dashboard
├── data/
│   ├── localsearch_meta.db  # SQLite metadata DB
│   ├── usn_state.json       # NTFS USN journal position
│   └── qdrant_storage/      # (legacy, now at D:\qdrant_data)
├── localsearch/
│   ├── __init__.py
│   ├── cli.py               # Click CLI (all commands)
│   ├── config.py            # Configuration dataclasses + YAML loader
│   ├── pipeline.py          # Orchestrator: scan → extract → chunk → embed → store
│   ├── chunker.py           # Text chunking (size + overlap)
│   ├── embedder.py          # sentence-transformers CUDA embeddings
│   ├── worker.py            # Multiprocess extraction worker
│   ├── dashboard.py         # Rich TUI dashboard
│   ├── crawler/
│   │   ├── scanner.py       # File scanner (USN + full walk)
│   │   └── usn.py           # NTFS USN Change Journal reader (ctypes)
│   ├── extractors/
│   │   ├── base.py          # Base extractor interface
│   │   ├── text.py          # Plain text / code files
│   │   ├── pdf.py           # PDF via PyMuPDF
│   │   ├── docx.py          # Word documents
│   │   ├── image.py         # OCR via Tesseract
│   │   ├── audio.py         # Audio transcription via faster-whisper
│   │   ├── video.py         # Video transcription via faster-whisper
│   │   └── msg.py           # Outlook .msg files
│   ├── query/
│   │   ├── search.py        # Semantic search engine
│   │   └── rag.py           # RAG engine (search + Ollama)
│   ├── storage/
│   │   ├── metadb.py        # SQLite metadata tracking
│   │   ├── vectordb.py      # Qdrant client wrapper
│   │   └── progress.py      # JSON progress files for dashboard
│   └── web/
│       └── app.py           # Flask web application
└── tests/
    ├── test_chunker.py
    ├── test_extractors.py
    ├── test_pipeline.py
    ├── test_scanner.py
    └── test_worker.py
```

---

## Troubleshooting

### Qdrant takes forever to start

The collection is ~30 GB. On cold start Qdrant must mmap-fault every page. Run
`.\warm-cache.ps1` first, or use `.\start.ps1` which does it automatically.

### Ingest exits with code 1

Common causes:
- **Qdrant not running** — start it first: `docker compose up -d qdrant`
- **USN journal without admin** — if not running as administrator, USN will
  fail to open the volume handle. The scanner falls back to full directory walk
  automatically (no crash). Run as admin for USN speed benefit.
- **Worker process crashes** — the pipeline uses `ProcessPoolExecutor` for
  extraction. A crash in one worker (e.g. corrupt file) is logged as a warning
  and processing continues.

### Search returns nothing

- Check `localsearch status` — if vectors = 0, run ingest first
- Lower `query.score_threshold` in config (default 0.3)

### Ollama `ask` command hangs

- Ensure Ollama is running: `ollama serve`
- Check the model is pulled: `ollama pull llama3`
- Verify connectivity: `curl http://localhost:11434/api/tags`

### Docker ingest can't see host files

- The `D:/` drive is mounted at `/scandata:ro` in `docker-compose.yml`
- Ensure Docker Desktop has file sharing enabled for the D: drive
- `config.docker.yaml` must have `scan_paths: ["/scandata"]`

### Running tests

```powershell
pip install -e ".[dev]"
pytest -v
```
