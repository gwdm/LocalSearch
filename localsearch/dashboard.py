"""Live GUI dashboard for LocalSearch ingestion progress."""

import sqlite3
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pathlib import Path

from localsearch.config import load_config


class DashboardApp:
    """Tkinter dashboard that auto-refreshes every 10 seconds."""

    def __init__(self, config_path=None):
        self.config = load_config(config_path)
        self.root = tk.Tk()
        self.root.title("LocalSearch - Ingestion Dashboard")
        self.root.geometry("750x520")
        self.root.configure(bg="#1e1e2e")
        self.root.resizable(True, True)

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"),
                        foreground="#cdd6f4", background="#1e1e2e")
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"),
                        foreground="#89b4fa", background="#1e1e2e")
        style.configure("Val.TLabel", font=("Segoe UI", 20, "bold"),
                        foreground="#a6e3a1", background="#313244")
        style.configure("Status.TLabel", font=("Segoe UI", 9),
                        foreground="#6c7086", background="#1e1e2e")
        style.configure("Card.TFrame", background="#313244")
        style.configure("Main.TFrame", background="#1e1e2e")
        style.configure("ErrVal.TLabel", font=("Segoe UI", 20, "bold"),
                        foreground="#f38ba8", background="#313244")
        style.configure("PendVal.TLabel", font=("Segoe UI", 20, "bold"),
                        foreground="#fab387", background="#313244")
        style.configure("SmallHeader.TLabel", font=("Segoe UI", 9),
                        foreground="#89b4fa", background="#313244")

        main = ttk.Frame(self.root, style="Main.TFrame", padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main, text="LocalSearch Ingestion Dashboard",
                  style="Title.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(main, text="", style="Status.TLabel")
        self.status_label.pack(anchor="w", pady=(0, 15))

        # --- Chat Window ---
        chat_frame = ttk.Frame(main, style="Card.TFrame", padding=10)
        chat_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 15))
        ttk.Label(chat_frame, text="Chat with Ollama (RAG)", style="SmallHeader.TLabel").pack(anchor="w")
        self.chat_text = tk.Text(chat_frame, height=10, bg="#232634", fg="#cdd6f4", font=("Consolas", 10), relief="flat", wrap="word", borderwidth=0, highlightthickness=0, state="disabled")
        self.chat_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        entry_frame = ttk.Frame(chat_frame, style="Card.TFrame")
        entry_frame.pack(fill=tk.X, pady=(5, 0))
        self.chat_entry = tk.Entry(entry_frame, font=("Segoe UI", 10))
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.chat_entry.bind("<Return>", self._on_chat_enter)
        send_btn = ttk.Button(entry_frame, text="Send", command=self._on_chat_send)
        send_btn.pack(side=tk.RIGHT)

        # Stats cards row
        cards_frame = ttk.Frame(main, style="Main.TFrame")
        cards_frame.pack(fill=tk.X, pady=(0, 15))

        self.cards = {}
        card_defs = [
            ("indexed", "Indexed", "Val.TLabel"),
            ("pending", "Pending", "PendVal.TLabel"),
            ("errors", "Errors", "ErrVal.TLabel"),
            ("total_files", "Total Tracked", "Val.TLabel"),
        ]
        for i, (key, label, val_style) in enumerate(card_defs):
            card = ttk.Frame(cards_frame, style="Card.TFrame", padding=15)
            card.grid(row=0, column=i, padx=5, sticky="nsew")
            cards_frame.columnconfigure(i, weight=1)
            ttk.Label(card, text=label, style="SmallHeader.TLabel").pack(anchor="w")
            val_label = ttk.Label(card, text="--", style=val_style)
            val_label.pack(anchor="w", pady=(5, 0))
            self.cards[key] = val_label

        # Second row: chunks + vectors
        cards_frame2 = ttk.Frame(main, style="Main.TFrame")
        cards_frame2.pack(fill=tk.X, pady=(0, 15))

        card_defs2 = [
            ("total_chunks", "Total Chunks", "Val.TLabel"),
            ("vector_count", "Vectors in Qdrant", "Val.TLabel"),
        ]
        for i, (key, label, val_style) in enumerate(card_defs2):
            card = ttk.Frame(cards_frame2, style="Card.TFrame", padding=15)
            card.grid(row=0, column=i, padx=5, sticky="nsew")
            cards_frame2.columnconfigure(i, weight=1)
            ttk.Label(card, text=label, style="SmallHeader.TLabel").pack(anchor="w")
            val_label = ttk.Label(card, text="--", style=val_style)
            val_label.pack(anchor="w", pady=(5, 0))
            self.cards[key] = val_label

        # Current directory
        dir_frame = ttk.Frame(main, style="Card.TFrame", padding=10)
        dir_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(dir_frame, text="Last Processed File",
                  style="SmallHeader.TLabel").pack(anchor="w")
        self.current_file_label = ttk.Label(
            dir_frame, text="--",
            font=("Consolas", 9), foreground="#cdd6f4", background="#313244",
            wraplength=680)
        self.current_file_label.pack(anchor="w", pady=(5, 0))

        # Recent errors
        err_frame = ttk.Frame(main, style="Card.TFrame", padding=10)
        err_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(err_frame, text="Recent Errors",
                  style="SmallHeader.TLabel").pack(anchor="w")
        self.error_text = tk.Text(
            err_frame, height=6, bg="#313244", fg="#f38ba8",
            font=("Consolas", 8), relief="flat", wrap="word",
            borderwidth=0, highlightthickness=0)
        self.error_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

    def _on_chat_enter(self, event=None):
        self._on_chat_send()


    def _on_chat_send(self):
        import threading
        msg = self.chat_entry.get().strip()
        if not msg:
            return
        self._append_chat("You", msg)
        self.chat_entry.delete(0, tk.END)
        self._append_chat("Ollama", "[Thinking...]")
        def run_rag():
            try:
                from localsearch.query.rag import RAGEngine
                from localsearch.config import load_config
                cfg = load_config()
                engine = RAGEngine(cfg)
                result = engine.ask(msg)
                answer = result.get("answer", "[No answer]")
                sources = result.get("sources", [])
                search_results = result.get("search_results", [])
                src_lines = "\n".join(f"- {src}" for src in sources)
                display = answer
                if src_lines:
                    display += f"\n\nSources:\n{src_lines}"
            except Exception as e:
                display = f"[Error: {e}]"
            def update():
                # Remove last '[Thinking...]' from Ollama
                self.chat_text.config(state="normal")
                self.chat_text.delete("end-2l", "end-1l")
                self.chat_text.config(state="disabled")
                self._append_chat("Ollama", display)
            self.root.after(0, update)
        threading.Thread(target=run_rag, daemon=True).start()

    def _append_chat(self, sender, msg):
        self.chat_text.config(state="normal")
        self.chat_text.insert(tk.END, f"{sender}: {msg}\n")
        self.chat_text.see(tk.END)
        self.chat_text.config(state="disabled")

    def _refresh(self):
        """Fetch stats from SQLite + Qdrant and update the UI."""
        def fetch():
            stats = self._get_stats()
            self.root.after(0, lambda: self._update_ui(stats))

        threading.Thread(target=fetch, daemon=True).start()
        self.root.after(10000, self._refresh)

    def _get_stats(self) -> dict:
        stats = {
            "total_files": 0, "indexed": 0, "pending": 0,
            "errors": 0, "total_chunks": 0, "vector_count": "?",
            "last_file": "--", "recent_errors": [],
        }

        db_path = self.config.metadata_db
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
            stats["recent_errors"] = cur.fetchall()

            conn.close()
        except Exception:
            pass

        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(host=self.config.qdrant.host,
                                  port=self.config.qdrant.port, timeout=3)
            info = client.get_collection(self.config.qdrant.collection)
            stats["vector_count"] = info.points_count
        except Exception:
            stats["vector_count"] = "?"

        return stats

    def _update_ui(self, stats: dict):
        now = datetime.now().strftime("%H:%M:%S")
        self.status_label.config(text=f"Last refresh: {now}  |  Auto-refresh: 10s")

        for key in ["indexed", "pending", "errors", "total_files", "total_chunks"]:
            self.cards[key].config(text=f"{stats[key]:,}")
        self.cards["vector_count"].config(text=f"{stats['vector_count']:,}"
                                          if isinstance(stats["vector_count"], int)
                                          else str(stats["vector_count"]))

        self.current_file_label.config(text=stats["last_file"])

        self.error_text.config(state="normal")
        self.error_text.delete("1.0", tk.END)
        for path, msg in stats.get("recent_errors", []):
            short_msg = (msg or "")[:80]
            self.error_text.insert(tk.END, f"{Path(path).name}: {short_msg}\n")
        self.error_text.config(state="disabled")

    def run(self):
        self.root.mainloop()


def main():
    import sys
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = DashboardApp(config_path)
    app.run()


if __name__ == "__main__":
    main()
