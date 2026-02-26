# LocalSearch

Fully local RAG (Retrieval-Augmented Generation) pipeline for semantic search
across files on NAS / local storage. Everything runs on your own hardware — no
cloud APIs required. **Runs entirely in Docker.**

**Stack:** Docker · NVIDIA CUDA 12.4.1 · Python 3.11 · Qdrant (vector DB) ·
sentence-transformers (CUDA embeddings) · faster-whisper (audio/video) ·
Tesseract OCR (images) · Ollama (LLM for Q&A) · Flask web UI

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Docker Compose Commands](#docker-compose-commands)
5. [Startup Script](#startup-script)
6. [Batch Launchers](#batch-launchers)
7. [Docker Entrypoint Modes](#docker-entrypoint-modes)
8. [Web UI](#web-ui)
9. [Volumes & Mounts](#volumes--mounts)
10. [NTFS USN Journal (Fast Rescan)](#ntfs-usn-journal-fast-rescan)
11. [Project Layout](#project-layout)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Component | Notes |
|-----------|-------|
| **Docker Desktop** | With WSL 2 backend on Windows |
| **NVIDIA GPU + CUDA drivers** | Host drivers only — CUDA toolkit is in the container |
| **NVIDIA Container Toolkit** | `nvidia-ctk` for GPU passthrough to Docker |
| **Ollama** | `ollama serve` on the host (localhost:11434) for RAG Q&A |

No local Python installation is required. Everything runs inside Docker.

---

## Quick Start

```powershell
# Clone the repo
git clone https://github.com/gwdm/LocalSearch.git
cd LocalSearch

# Start Ollama on the host (needed for RAG Q&A)
ollama serve

# Build and start everything (Qdrant + ingest loop + web UI)
docker compose up -d

# Or use the startup script (warms Qdrant page cache first)
.\start.ps1
```

The web UI will be at **http://localhost:8080**. The container runs continuous
ingest (every 60s) plus the web UI by default.

---

## Configuration

All settings live in **`config.docker.yaml`** (loaded automatically inside the
container via the `LOCALSEARCH_CONFIG` environment variable).

### Key settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `scan_paths` | `["/scandata"]` | Directories to scan (host `D:\` mounted) |
| `qdrant.host` | `"qdrant"` | Docker service name |
| `ollama.host` | `"http://host.docker.internal:11434"` | Ollama on the host |
| `ollama.model` | `"qwen3:14b"` | LLM for RAG Q&A |
| `embedding.model` | `mixedbread-ai/mxbai-embed-large-v1` | 1024-dim embedding |
| `embedding.device` | `cuda` | GPU embedding |
| `whisper.model_size` | `large-v3` | Audio/video transcription model |
| `pipeline.cpu_workers` | `8` | Parallel extraction processes |
| `pipeline.embed_batch_size` | `256` | Chunks batched before embedding |
| `query.top_k` | `15` | Number of search results |
| `metadata_db` | `"/data/localsearch_meta.db"` | SQLite tracking DB (bind-mounted) |
| `path_map` | `{"/scandata": "D:\\"}` | Container → host path translation |
| `log_level` | `INFO` | Logging level |

Edit `config.docker.yaml` to change scan paths, file-size limits, GPU settings, etc.

---

## Docker Compose Commands

```powershell
# Start everything (Qdrant + continuous ingest loop + web UI)
docker compose up -d

# Start only Qdrant
docker compose up -d qdrant

# Run a one-shot ingest (Qdrant must be healthy)
docker compose run --rm localsearch ingest

# Start only the web UI
docker compose run --rm -p 8080:8080 localsearch web

# Drop into a shell inside the container
docker compose run --rm localsearch shell

# Rebuild after code changes
docker compose build localsearch

# View logs
docker compose logs -f localsearch

# Stop everything
docker compose down
```

---

## Startup Script

**`start.ps1`** is the recommended way to bring up the full stack:

```powershell
.\start.ps1                     # warm cache → start all (ingest loop + web UI)
.\start.ps1 -Build              # rebuild image then start
.\start.ps1 -SkipWarm           # skip page-cache warming
.\start.ps1 -Mode ingest        # warm → Qdrant → single ingest pass
.\start.ps1 -Mode web           # warm → Qdrant → web UI only
.\start.ps1 -QdrantTimeout 900  # wait longer for Qdrant (default 600s)
```

### What it does (in order)

1. **Wait for Docker daemon** — polls until Docker Desktop is ready
2. **Warm page cache** — `warm-cache.ps1` streams all Qdrant data files through
   RAM at NVMe speed (~30 GB in ~5 s hot / ~15 s cold). Reduces Qdrant startup
   from ~9 min to ~1 min.
3. **Build** (optional) — `docker compose build localsearch` if `-Build` flag set
4. **Start services** — `docker compose up -d` (Qdrant + LocalSearch)
5. **Wait for Qdrant** — polls health endpoint until collection is ready

### Warming the cache manually

```powershell
.\warm-cache.ps1                          # default: D:\qdrant_data, 4 MB buffer
.\warm-cache.ps1 -Path "E:\qdrant_data"   # different path
.\warm-cache.ps1 -BufferMB 8              # larger buffer
```

---

## Batch Launchers

Double-click these from Explorer for one-click operation:

| File | What it does |
|------|-------------|
| **`run.bat`** | Generic Docker launcher: `run.bat [ingest\|web\|shell\|logs\|stop]` |
| **`ingest.bat`** | Start Qdrant, wait for health, run single ingest pass |
| **`dashboard.bat`** | Start all services, open browser to web UI |

---

## Docker Entrypoint Modes

The container entrypoint (`docker-entrypoint.sh`) accepts these modes:

| Mode | Description |
|------|-------------|
| `ingest` | Run one ingestion pass then exit |
| `web` | Start web UI only on port 8080 |
| `both` | *(default)* Continuous ingest loop (every 60s) + web UI |
| `shell` | Drop to bash for debugging |

---

## Web UI

The web UI runs inside the Docker container on port 8080 (mapped to host).
It uses a Catppuccin Mocha dark theme and provides:

- **Dashboard** — live ingestion status, file counts, Qdrant stats
- **Search** — semantic search with file-type filters, score display
- **Chat** — RAG-powered Q&A with source references

Access from another machine via Tailscale: `http://sirius:8080` or
`http://100.126.184.18:8080`.

---

## Volumes & Mounts

| Mount | Purpose |
|-------|---------|
| `D:/qdrant_data:/qdrant/storage` | Qdrant persistent data (~30 GB) |
| `D:/:/scandata:ro` | Host files visible to scanner (read-only) |
| `LocalSearch/data:/data` | Shared SQLite metadata DB |
| `localsearch_model_cache:/root/.cache` | Cached embedding/Whisper models |

### Path mapping

The container sees host files at `/scandata`. The `path_map` config translates
these back to Windows paths (`D:\`) in the metadata DB, so the web UI shows
proper Windows paths to the user.

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
├── config.docker.yaml       # Docker configuration (primary config)
├── docker-compose.yml       # Qdrant + LocalSearch services
├── Dockerfile               # CUDA 12.4 + Python 3.11 container
├── docker-entrypoint.sh     # Container mode selector
├── pyproject.toml           # Package metadata & dependencies
├── start.ps1                # Full Docker startup orchestrator
├── warm-cache.ps1           # Qdrant page cache pre-warmer
├── run.bat                  # Generic Docker CLI launcher
├── ingest.bat               # One-click Docker ingest
├── dashboard.bat            # One-click start + open browser
├── data/
│   ├── localsearch_meta.db  # SQLite metadata DB (bind-mounted into container)
│   └── usn_state.json       # NTFS USN journal position
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
- **Worker process crashes** — the pipeline uses `ProcessPoolExecutor` for
  extraction. A crash in one worker (e.g. corrupt file) is logged as a warning
  and processing continues.

### Search returns nothing

- Check via the web UI dashboard — if vectors = 0, run ingest first
- Lower `query.score_threshold` in `config.docker.yaml` (default 0.3)

### Ollama RAG hangs

- Ensure Ollama is running on the host: `ollama serve`
- Check the model is pulled: `ollama pull qwen3:14b`
- Verify connectivity from container: the container reaches Ollama via
  `http://host.docker.internal:11434`

### Docker ingest can't see host files

- The `D:/` drive is mounted at `/scandata:ro` in `docker-compose.yml`
- Ensure Docker Desktop has file sharing enabled for the D: drive
- `config.docker.yaml` must have `scan_paths: ["/scandata"]`

### Container can't access GPU

- Install NVIDIA Container Toolkit: `nvidia-ctk runtime configure --runtime=docker`
- Restart Docker Desktop after installing
- Verify: `docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi`

### Running tests

```powershell
docker compose run --rm localsearch shell
# Inside container:
pip install -e ".[dev]"
pytest -v
```
