# LocalSearch - Session Notes

## Python Environment

- **Conda distribution**: Miniconda3
- **Environment name**: `312`
- **Python version**: 3.12.8
- **Executable path**: `%USERPROFILE%\Miniconda3\envs\312\python.exe`

### Running commands

Since `python` is not on the system PATH, always invoke using the full path:

```powershell
& "$env:USERPROFILE\Miniconda3\envs\312\python.exe" -m localsearch.cli <command>
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `ingest` | Scan files and build the search index |
| `dashboard` | Open live GUI dashboard showing ingestion progress |
| `search "query"` | Semantic search across indexed files |

### Start ingestion

```powershell
& "$env:USERPROFILE\Miniconda3\envs\312\python.exe" -m localsearch.cli ingest
```

### Start dashboard

```powershell
& "$env:USERPROFILE\Miniconda3\envs\312\python.exe" -m localsearch.cli dashboard
```

## Bug Fixes Applied

### Dashboard `AttributeError: 'DashboardApp' object has no attribute 'cards'` (2026-02-24)

The stats cards UI code in `localsearch/dashboard.py` was incorrectly indented inside `_append_chat()` instead of `_build_ui()`. This meant `self.cards` was never initialized before `_refresh()` tried to use it. Fixed by moving the cards/stats/errors UI code back into `_build_ui()` after the chat widget section.

## Configuration

- **Config file**: `config.yaml`
- **Scan paths**: `D:/`
- **Qdrant**: localhost:6333, collection `localsearch`
- **Ollama**: localhost:11434, model `llama3`
- **Embedding**: `mixedbread-ai/mxbai-embed-large-v1` (1024-dim, CUDA)
- **Whisper**: `large-v3` (CUDA, float16)
- **Metadata DB**: `data/localsearch_meta.db`
