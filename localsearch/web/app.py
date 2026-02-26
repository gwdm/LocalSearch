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
import os
import sqlite3
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from localsearch.config import Config, load_config
from localsearch.storage.progress import read_progress

logger = logging.getLogger(__name__)

# Module-level singletons (lazy-loaded, thread-safe)
# NOTE: Must use RLock (reentrant) because _get_rag_engine -> _get_search_engine
#       both acquire the same lock, and threading.Lock would deadlock.
_lock = threading.RLock()
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
                logger.info("Initializing SearchEngine (embedding model load)...")
                _search_engine = SearchEngine(_get_config())
                logger.info("SearchEngine ready")
    return _search_engine


def _get_rag_engine():
    global _rag_engine
    if _rag_engine is None:
        with _lock:
            if _rag_engine is None:
                from localsearch.query.rag import RAGEngine
                logger.info("Initializing RAGEngine...")
                _rag_engine = RAGEngine(_get_config(), _get_search_engine())
                logger.info("RAGEngine ready")
    return _rag_engine


def _get_stats() -> dict:
    """Fetch dashboard stats from JSON progress file (no SQLite locks)."""
    cfg = _get_config()
    
    # Read cached stats from JSON file (updated by pipeline after each batch)
    progress = read_progress(cfg.metadata_db)
    
    stats = {
        "total_files": progress.get("db_total", 0),
        "indexed": progress.get("db_indexed", 0),
        "pending": progress.get("db_pending", 0),
        "errors": progress.get("db_errors", 0),
        "total_chunks": progress.get("db_chunks", 0),
        "vector_count": "?",
        "last_file": "--",
        "recent_errors": [],
        "ingest": {
            "phase": progress.get("phase", "idle"),
            "files_queued": progress.get("files_queued", 0),
            "files_processed": progress.get("files_processed", 0),
            "files_errors": progress.get("files_errors", 0),
            "dirs_visited": progress.get("dirs_visited", 0),
            "files_checked": progress.get("files_checked", 0),
            "files_new": progress.get("files_new", 0),
        },
    }
    
    # Get last file and recent errors from SQLite (low priority, can fail gracefully)
    db_path = cfg.metadata_db
    if Path(db_path).exists():
        try:
            conn = sqlite3.connect(db_path, timeout=1)
            cur = conn.cursor()
            
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
        except Exception:
            # Non-critical, stats already populated from JSON
            pass

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

    # Pre-warm the search and RAG engines (loads embedding model to GPU)
    # so the first request doesn't have a long cold-start delay.
    logger.info("Pre-warming search engine (loading embedding model)...")
    _get_search_engine()
    logger.info("Pre-warming RAG engine...")
    _get_rag_engine()
    logger.info("Engines ready")

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # Register RAM disk cleanup on app shutdown
    @app.teardown_appcontext
    def teardown_ramdisk(*args):
        """Cleanup RAM disk when app shuts down."""
        if os.name == "nt":
            try:
                from localsearch.storage.ramdisk import RAMDiskManager
                ramdisk = RAMDiskManager(_config.metadata_db)
                if ramdisk.is_active:
                    logger.info("Cleaning up RAM disk...")
                    ramdisk.destroy()
            except Exception as e:
                logger.debug("RAM disk cleanup: %s", e)

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
