"""Flask application for LocalSearch web UI.

Provides three views:
  /           — Dashboard with live stats (auto-refresh)
  /search     — Semantic search interface
  /chat       — RAG chat with Ollama
  /api/stats  — JSON stats endpoint (used by dashboard auto-refresh)
  /api/search — JSON search endpoint
  /api/chat   — JSON RAG chat endpoint
"""

import logging
import sqlite3
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from localsearch.config import Config, load_config
from localsearch.storage.progress import read_progress

logger = logging.getLogger(__name__)

# Module-level singletons (lazy-loaded, thread-safe)
_lock = threading.Lock()
_search_engine = None
_rag_engine = None
_config: Config | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_search_engine():
    global _search_engine
    if _search_engine is None:
        with _lock:
            if _search_engine is None:
                from localsearch.query.search import SearchEngine
                _search_engine = SearchEngine(_get_config())
    return _search_engine


def _get_rag_engine():
    global _rag_engine
    if _rag_engine is None:
        with _lock:
            if _rag_engine is None:
                from localsearch.query.rag import RAGEngine
                _rag_engine = RAGEngine(_get_config(), _get_search_engine())
    return _rag_engine


def _get_stats() -> dict:
    """Fetch dashboard stats from SQLite + Qdrant (same logic as dashboard.py)."""
    cfg = _get_config()
    stats = {
        "total_files": 0, "indexed": 0, "pending": 0,
        "errors": 0, "total_chunks": 0, "vector_count": "?",
        "last_file": "--", "recent_errors": [],
        "ingest": {"phase": "idle"},
    }

    db_path = cfg.metadata_db
    if not Path(db_path).exists():
        return stats

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM files")
        stats["total_files"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
        stats["indexed"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM files WHERE status IN ('pending','processing')")
        stats["pending"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM files WHERE status='error'")
        stats["errors"] = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(chunk_count),0) FROM files WHERE status='indexed'")
        stats["total_chunks"] = cur.fetchone()[0]

        cur.execute("SELECT file_path FROM files ORDER BY indexed_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            stats["last_file"] = row[0]

        cur.execute(
            "SELECT file_path, error FROM files WHERE status='error' "
            "ORDER BY indexed_at DESC LIMIT 10"
        )
        stats["recent_errors"] = [
            {"file": Path(fp).name, "path": fp, "error": (err or "")[:120]}
            for fp, err in cur.fetchall()
        ]

        conn.close()
    except Exception as exc:
        logger.warning("Failed to read metadb: %s", exc)

    # Live ingest progress (JSON file — works across Docker bind mounts)
    stats["ingest"] = read_progress(db_path)

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=cfg.qdrant.host, port=cfg.qdrant.port, timeout=3)
        info = client.get_collection(cfg.qdrant.collection)
        stats["vector_count"] = info.points_count
    except Exception:
        stats["vector_count"] = "?"

    return stats


def create_app(config_path: str | None = None) -> Flask:
    """Application factory."""
    global _config
    _config = load_config(config_path)

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # ---- Page routes ----

    @app.route("/")
    def dashboard():
        stats = _get_stats()
        return render_template("dashboard.html", stats=stats)

    @app.route("/search")
    def search_page():
        return render_template("search.html")

    @app.route("/chat")
    def chat_page():
        return render_template("chat.html")

    # ---- API routes ----

    @app.route("/api/stats")
    def api_stats():
        return jsonify(_get_stats())

    @app.route("/api/search", methods=["POST"])
    def api_search():
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Empty query"}), 400

        top_k = data.get("top_k")
        file_type = data.get("file_type")

        try:
            engine = _get_search_engine()
            results = engine.search(query, top_k=top_k, file_type=file_type)
            return jsonify({
                "results": [
                    {
                        "file_path": r.file_path,
                        "file_name": Path(r.file_path).name,
                        "score": round(r.score, 4),
                        "file_type": r.file_type,
                        "chunk_index": r.chunk_index,
                        "text": r.text[:500],
                    }
                    for r in results
                ]
            })
        except Exception as exc:
            logger.exception("Search failed")
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.get_json(silent=True) or {}
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"error": "Empty question"}), 400

        top_k = data.get("top_k")
        file_type = data.get("file_type")

        try:
            engine = _get_rag_engine()
            result = engine.ask(question, top_k=top_k, file_type=file_type)
            return jsonify(result)
        except Exception as exc:
            logger.exception("RAG chat failed")
            return jsonify({"error": str(exc)}), 500

    return app
