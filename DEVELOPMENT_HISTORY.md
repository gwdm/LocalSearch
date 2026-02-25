# LocalSearch — Development History & Recovery Guide

> Written: 2026-02-24  
> Purpose: Record every change so work can be resumed if the system crashes mid-session.

---

## 1. Problem Statement

The original pipeline (`pipeline.py`) used `ThreadPoolExecutor` with 8 threads.  
All threads shared the same process memory and GPU. Running `localsearch ingest`  
on `D:/` caused the system to hang because:

| Root cause | Detail |
|---|---|
| Full D:/ scan | Millions of files, including OneDrive Files-On-Demand stubs |
| 8 threads × 5 GB max file size | Up to 40 GB memory pressure from parallel extractors |
| Tesseract OCR per image | 8 concurrent external processes saturated CPU+RAM |
| Eager Whisper model load | ~3 GB VRAM allocated before any GPU work began |
| Embed model also on CUDA | Two large models competing for GPU |
| No extraction timeout | Hung extractor blocked the thread forever |
| SQLite commit per file | Disk I/O bottleneck under heavy load |

---

## 2. Solution: ProcessPoolExecutor + Safeguards

### Architecture change
- **Before:** `ThreadPoolExecutor(max_workers=8)` — threads share memory/GIL  
- **After:** `ProcessPoolExecutor(max_workers=N)` — isolated OS processes

### Key design decisions
- Worker processes handle CPU-bound extraction only (text/pdf/docx/image/msg)
- GPU extraction (audio/video via Whisper) stays in main process, sequentially
- Each worker has its own extractor instances (no shared state to pickle)
- Per-file timeout via `threading.Event` inside the worker process
- Per-type file size limits prevent resource exhaustion
- SQLite batch operations reduce commit overhead
- Whisper model loaded lazily (only when GPU files actually exist)
- Graceful shutdown via `threading.Event` flag

---

## 3. Files Changed (in order of dependency)

### 3a. `localsearch/config.py` — COMPLETED ✓

**Added** `PipelineConfig` dataclass:
```python
@dataclass
class PipelineConfig:
    cpu_workers: int = 4
    extraction_timeout: int = 300      # seconds, CPU extraction
    gpu_timeout: int = 1800            # seconds, audio/video
    embed_batch_size: int = 512
    type_max_mb: dict = field(default_factory=lambda: {
        "text": 100, "pdf": 500, "docx": 200,
        "image": 50, "msg": 200, "audio": 2000, "video": 5000,
    })
```

**Other changes:**
- `Config` class now includes `pipeline: PipelineConfig` field
- `_merge_dataclass()` now merges dict fields (`.update()`) instead of replacing
- `get_type()` now includes `"msg"` in its search list
- `load_config()` now parses the `"pipeline"` section from YAML

### 3b. `config.yaml` — COMPLETED ✓

**Changed:**
- `max_file_size_mb: 5000` → `500` (global hard cap)
- **Added** full `pipeline:` section with `cpu_workers`, `extraction_timeout`,
  `gpu_timeout`, `embed_batch_size`, and `type_max_mb` per-type limits

### 3c. `localsearch/storage/metadb.py` — COMPLETED ✓

**Added** three batch methods (all use single transactions):
- `upsert_files_batch(records: list[FileRecord])` — bulk insert/update
- `mark_indexed_batch(updates: list[tuple[str, int]])` — bulk mark indexed
- `mark_errors_batch(errors: list[tuple[str, str]])` — bulk mark errors

Original per-file methods (`upsert_file`, `mark_indexed`, `mark_error`) kept
for backward compatibility.

### 3d. `localsearch/worker.py` — NEW FILE ✓

Top-level module functions designed to run in child processes:

- `init_worker(chunk_size, chunk_overlap, timeout)` — called once per worker
  process by `ProcessPoolExecutor(initializer=...)`. Creates extractor and
  chunker instances as process-level globals.
- `extract_and_chunk(file_path, file_type) -> dict` — does extraction + chunking.
  Returns a plain dict `{"error": str|None, "chunks": list[dict]}` (pickle-safe).
  Internal timeout via `threading.Event` kills hung extractors.

### 3e. `localsearch/pipeline.py` — COMPLETED ✓

**Major rewrite.** Key changes:

- **Imports:** Removed all extractor imports, added `ProcessPoolExecutor`,
  `init_worker`, `extract_and_chunk`
- **`__init__`:** Removed `self._extractors` dict and `_build_extractors()`.
  Added lazy GPU extractor properties and `self._shutdown` event.
- **`_get_audio_extractor()` / `_get_video_extractor()`:** Lazy construction —
  Whisper model only loads when GPU files actually exist.
- **`ingest()`:**
  - Per-type file size guard (checks `pipeline.type_max_mb`)
  - Batch metadb writes (`upsert_files_batch`, `mark_indexed_batch`, `mark_errors_batch`)
  - Stats include `skipped_size` count
  - `handle_result()` works with plain dicts (from worker or GPU extraction)
  - Phase 1 uses `ProcessPoolExecutor` via `_process_cpu_batch()`
  - Graceful shutdown checks (`self._shutdown.is_set()`)
- **`_process_cpu_batch()`:** Uses `ProcessPoolExecutor` with `initializer=init_worker`.
  Cancels remaining futures on shutdown. Per-file timeout on `future.result()`.
- **`_extract_gpu()`:** New method for audio/video. Runs extractor in a daemon
  thread with timeout (same pattern as worker.py).
- **`AsyncUpserter.stop()`:** Now has 60s timeout on `thread.join()` to prevent hang.
- **Removed:** `ExtractedFile` dataclass is kept but unused (workers return dicts).
  `_extract_single()` removed. `EXTRACT_WORKERS`/`EMBED_BATCH_FLUSH` constants
  replaced by `PipelineConfig` values.

### 3f. `localsearch/cli.py` — COMPLETED ✓

- Added `"Skipped (size limit)"` row to the ingestion results table.

### 3g. `tests/test_worker.py` — NEW FILE ✓

Five tests:
- `test_extract_text_file` — happy path
- `test_extract_unknown_type` — error for bad file type
- `test_extract_missing_file` — error for non-existent file
- `test_extract_empty_text_file` — empty text returns no chunks
- `test_extract_long_text_multiple_chunks` — verifies multi-chunk output

---

## 4. Test Results

```
19 passed in 0.19s
```

All original tests (chunker, extractors, pipeline/metadb, scanner) still pass.
5 new worker tests pass.

---

## 5. What was NOT changed (intentionally)

| File | Reason |
|---|---|
| `localsearch/extractors/*.py` | No changes needed — workers import and instantiate them independently |
| `localsearch/crawler/scanner.py` | No changes needed — runs in main process |
| `localsearch/embedder.py` | No changes needed — runs in main process |
| `localsearch/storage/vectordb.py` | No changes needed — runs in main process |
| `localsearch/query/search.py` | Unrelated to ingestion |
| `localsearch/query/rag.py` | Unrelated to ingestion |
| `localsearch/dashboard.py` | Unrelated to ingestion |

---

## 6. How to Resume if Interrupted

If another crash occurs mid-session, the remaining potential work items are:

1. **KeyboardInterrupt / Ctrl-C handler in CLI** — `pipeline._shutdown.set()` is
   wired but the CLI doesn't install a signal handler yet. Could add
   `signal.signal(SIGINT, ...)` in `cli.py:ingest()`.

2. **Memory monitoring** — Optional: use `psutil` to check RSS before submitting
   new work to the pool, pause if memory exceeds a threshold.

3. **Scanner filtering** — Config could gain `exclude_paths` patterns (e.g.,
   `"**/OneDrive/**"`) to avoid cloud-backed stubs.

4. **Dashboard integration** — The Textual dashboard could show per-worker
   process status.

5. **Integration test** — End-to-end test that creates temp files, runs
   `Pipeline.ingest()` (with mocked Qdrant/embedder), and verifies the full
   flow through worker processes.

---

## 8. Post-Launch Fixes (same session)

### 8a. Batched Future Submission — `pipeline.py` `_process_cpu_batch()`

**Problem:** The original implementation submitted ALL 551K+ futures at once via
a dict comprehension before calling `as_completed()`. This overwhelmed the
internal `ProcessPoolExecutor` pipe — workers received no work despite being alive.

**Fix:** Replaced with a **sliding-window pattern**: maintains at most
`n_workers * 4` in-flight futures, drains completed results, then refills.
Uses `concurrent.futures.wait(FIRST_COMPLETED)` instead of `as_completed()`.

### 8b. Pending File Resume — `metadb.py` + `pipeline.py`

**Problem:** On restart, `scanner.scan()` only returns new/changed files.
Files recorded in metadb as "pending" from a stalled run were never re-queued.

**Fix:**
- Added `MetadataDB.get_pending_files()` method
- After the scan loop in `ingest()`, loads all pending files from metadb,
  converts them to `ScannedFile` objects, and adds them to CPU/GPU buckets
- Applies per-type size guards to resumed files too
- Logs count of resumed files

### 8c. Results

After these fixes, the pipeline processes files at **~6 files/second** with
4 worker processes, embedding on GPU, and Qdrant upserts flowing steadily.

---

## 7. Git Recovery Checkpoint

To create a safety checkpoint:

```bash
git add -A
git commit -m "refactor: switch pipeline from ThreadPool to ProcessPool

- ProcessPoolExecutor for CPU extraction (process isolation + timeouts)
- Lazy Whisper model loading (GPU only when needed)
- Per-type file size limits (prevent resource exhaustion)
- Batch SQLite operations (reduce commit overhead)
- Graceful shutdown support
- New worker.py module with 5 tests
- Sliding-window future submission (prevents pipe stall on 500K+ files)
- Pending file resume on restart
- All 19 tests passing"
```
