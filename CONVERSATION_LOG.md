# LocalSearch Development Conversation Log

**Date:** February 24, 2026  
**Session:** Dashboard Chat UI, DB Recovery, and Architecture Discussion

---

## 1. Dashboard Search Box — Missing Feature Discovery

**User:** I don't see a search box or field labeled "Query", "Search", or similar at the top or in the main panel of the dashboard.

**Copilot:** Reviewed `localsearch/dashboard.py` and confirmed that the dashboard UI only contained ingestion stats (indexed, pending, errors, total files, chunks, vectors), a "Last Processed File" display, and a "Recent Errors" panel. **No search/query input field existed in the code.**

The dashboard was purely an ingestion monitoring tool — it had no search or chat capability.

---

## 2. Why Was a Search Box Expected?

**User:** Why did you think a search box existed?

**Copilot:** Acknowledged the error — the earlier suggestion to "look for a search box" was based on standard expectations for RAG dashboard UIs, not on the actual code. The conversation context at that point did not include the dashboard source, so the response was based on assumption rather than fact. Once the code was reviewed, the absence was confirmed.

**Lesson:** Always verify against actual code before describing UI elements.

---

## 3. GUI Chat Window with Ollama RAG Integration

**User:** I want a GUI chat window that allows me to query in a chat style where the query asks Ollama what terms to search for, then given the results feeds whatever info or file contents is required for Ollama to answer the query in the chat window.

**Copilot:** Implemented a full chat-style RAG interface in the dashboard:

### What was built:

1. **Chat panel added to `dashboard.py`** — A dark-themed chat window with:
   - A `tk.Text` widget (read-only) for conversation history
   - A `tk.Entry` input field for typing questions
   - A "Send" button (also responds to Enter key)
   - Styled to match the existing Catppuccin-inspired dark theme

2. **RAG integration** — On each message:
   - User's message is displayed in chat
   - "[Thinking...]" placeholder shown
   - A background thread calls `RAGEngine.ask(msg)` which:
     - Embeds the question using `sentence-transformers`
     - Searches Qdrant for relevant chunks
     - Formats chunks as context
     - Sends context + question to Ollama via `ollama.Client.chat()`
     - Returns answer + sources
   - Answer and source file paths are displayed in the chat window
   - "[Thinking...]" is replaced with the actual response

### Key design decisions:
- **Reused existing `RAGEngine`** from `localsearch/query/rag.py` — no duplicate logic
- **Background threading** — Ollama calls don't freeze the Tkinter UI
- **Config-driven** — Uses the same `config.yaml` for Ollama host, model, Qdrant settings

### Code locations:
- `localsearch/dashboard.py` — Chat UI widgets in `_build_ui()`, handlers in `_on_chat_send()`, `_on_chat_enter()`, `_append_chat()`

### Existing RAG pipeline leveraged:
- `localsearch/query/rag.py` — `RAGEngine.ask()` handles the full flow:
  - `SearchEngine.search()` → Qdrant vector similarity search
  - `_format_context()` → builds context string from results
  - Ollama `client.chat()` with `RAG_PROMPT_TEMPLATE`
- `localsearch/query/search.py` — `SearchEngine` handles embedding + Qdrant query
- Config: `ollama.host = "http://localhost:11434"`, `ollama.model = "llama3"`

---

## 4. Database Integrity Recovery After System Failure

**User:** If there is a system failure, how do I recover DB integrity?

**Copilot:** Analyzed the full storage and pipeline layer:

### Existing protections (already built in):
- **SQLite WAL journal mode** (`PRAGMA journal_mode=WAL`) — crash-safe writes
- **Pipeline resume** — on restart, the pipeline queries `get_pending_files()` and resumes any files left in `pending` state from a previous interrupted run

### Gaps identified:
1. **Files stuck in `processing` state** — if the pipeline crashes mid-extraction, files marked `processing` are never retried (only `pending` files are resumed)
2. **SQLite ↔ Qdrant drift** — metadb could say "indexed" but vectors may be missing (crash between Qdrant upsert and metadb commit) or vice versa
3. **Error files** — files in `error` state are never retried unless manually reset
4. **No integrity check command** — no way to verify SQLite is uncorrupted

### Recovery methods added to `MetadataDB` (`localsearch/storage/metadb.py`):

```python
def check_integrity(self) -> tuple[bool, str]:
    """Run PRAGMA integrity_check. Returns (ok, message)."""

def reset_stuck_processing(self) -> int:
    """Move 'processing' → 'pending' for crash recovery. Returns count."""

def reset_errors(self) -> int:
    """Move 'error' → 'pending' to retry failed files. Returns count."""

def get_indexed_file_paths_with_chunks(self) -> list[tuple[str, int]]:
    """Return (file_path, chunk_count) for all indexed files."""

def vacuum(self) -> None:
    """VACUUM — reclaim space and defragment."""
```

### Recovery procedures (manual):

**Scenario 1: Pipeline crashed mid-run**
```bash
# Files stuck in 'processing' won't be retried automatically
# The new reset_stuck_processing() moves them back to 'pending'
# Then re-run ingest
localsearch ingest
```

**Scenario 2: SQLite corruption**
```bash
# check_integrity() runs PRAGMA integrity_check
# If corrupt, options:
#   1. Delete the .db file and re-ingest (vectors in Qdrant are still valid)
#   2. Use sqlite3 .recover command externally
```

**Scenario 3: Qdrant ↔ SQLite drift**
```bash
# get_indexed_file_paths_with_chunks() lists what metadb thinks is indexed
# Compare against actual Qdrant vector counts per file
# Files with mismatched counts can be reset to 'pending' and re-ingested
```

**Scenario 4: Retry all errors**
```bash
# reset_errors() moves all 'error' files back to 'pending'
# Useful after fixing an extractor bug
```

### Architecture notes:
- The pipeline's `handle_result()` updates metadb AFTER Qdrant upsert completes (via `AsyncUpserter`), but the metadb batch flush is periodic (every 100 files), so a crash can leave up to 100 files in a state where vectors exist in Qdrant but metadb still says `pending`
- This is **safe** — re-ingesting will re-embed and upsert (Qdrant handles duplicates via the same point IDs), so the worst case is redundant work, not data loss
- Qdrant itself has its own WAL and snapshot recovery

---

## Architecture Reference

### Pipeline flow:
```
Scan → Extract (CPU pool) → Chunk → Embed (GPU thread) → Upsert (Qdrant thread) → Update MetaDB
```

### Key files:
| File | Purpose |
|------|---------|
| `localsearch/pipeline.py` | Orchestrator: scan, extract, chunk, embed, store |
| `localsearch/storage/metadb.py` | SQLite metadata tracking (file status, chunk counts) |
| `localsearch/storage/vectordb.py` | Qdrant client wrapper |
| `localsearch/query/rag.py` | RAG engine: search + Ollama LLM |
| `localsearch/query/search.py` | Vector similarity search |
| `localsearch/dashboard.py` | Tkinter GUI: stats + chat |
| `localsearch/cli.py` | CLI: ingest, search, ask, status, dashboard, reset |
| `localsearch/embedder.py` | sentence-transformers embedding |
| `localsearch/chunker.py` | Text chunking with overlap |
| `localsearch/extractors/` | Per-type extractors (pdf, docx, msg, audio, video, image, text) |
| `localsearch/config.py` | Dataclass config from config.yaml |

### Config (`config.yaml`):
- Qdrant: `localhost:6333`, collection `localsearch`
- Ollama: `http://localhost:11434`, model `llama3`
- Embedding: `mixedbread-ai/mxbai-embed-large-v1`, CUDA, batch 64
- Whisper: `large-v3`, CUDA, float16
- Chunking: 1000 chars, 200 overlap
- Pipeline: 8 CPU workers

### Dependencies:
- `qdrant-client`, `sentence-transformers`, `faster-whisper`, `PyMuPDF`
- `python-docx`, `pytesseract`, `Pillow`, `ffmpeg-python`
- `extract-msg`, `ollama`, `click`, `pyyaml`, `rich`

---

## Changes Made This Session

### Files modified:
1. **`localsearch/dashboard.py`** — Added chat window UI (Text + Entry + Send button) and wired it to `RAGEngine.ask()` via background thread
2. **`localsearch/storage/metadb.py`** — Added recovery methods: `check_integrity()`, `reset_stuck_processing()`, `reset_errors()`, `get_indexed_file_paths_with_chunks()`, `vacuum()`

### Files not yet modified (planned):
- `localsearch/cli.py` — A `repair` CLI command was discussed but the consistency check logic (comparing metadb vs Qdrant) was still in progress when this log was written
