"""Worker process functions for CPU-bound file extraction.

These functions run in separate processes via ProcessPoolExecutor.
Each worker process initialises its own extractor instances once (via
``init_worker``) and then reuses them for every ``extract_and_chunk``
call routed to that process.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ── Process-level globals (set once per worker via init_worker) ──────
_extractors: dict = {}
_chunker: Any = None
_timeout: int = 300


def init_worker(chunk_size: int, chunk_overlap: int, timeout: int = 300) -> None:
    """Initialise extractors and chunker in the worker process.

    Called automatically by ``ProcessPoolExecutor`` when a new worker
    process starts.  All heavy imports happen here so the main process
    stays lean.
    """
    global _extractors, _chunker, _timeout
    _timeout = timeout

    from localsearch.chunker import TextChunker
    from localsearch.extractors.docx import DocxExtractor
    from localsearch.extractors.image import ImageExtractor
    from localsearch.extractors.msg import MsgExtractor
    from localsearch.extractors.pdf import PDFExtractor
    from localsearch.extractors.text import TextExtractor

    text_ext = TextExtractor()
    pdf_ext = PDFExtractor()
    docx_ext = DocxExtractor()
    image_ext = ImageExtractor()
    msg_ext = MsgExtractor(extractors={
        "text": text_ext,
        "pdf": pdf_ext,
        "docx": docx_ext,
        "image": image_ext,
    })

    _extractors = {
        "text": text_ext,
        "pdf": pdf_ext,
        "docx": docx_ext,
        "image": image_ext,
        "msg": msg_ext,
    }
    _chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def extract_and_chunk(file_path: str, file_type: str) -> dict[str, Any]:
    """Extract text from *file_path* and split it into chunks.

    Runs inside a worker process.  A daemon thread enforces the
    per-file timeout configured in ``init_worker`` — if extraction
    exceeds it, the function returns an error dict immediately.  (The
    orphaned thread is cleaned up when the worker process terminates.)

    Returns
    -------
    dict
        ``{"error": str | None, "chunks": list[dict]}``
        Each chunk dict mirrors the fields of ``localsearch.chunker.Chunk``.
    """
    result: dict[str, Any] = {"error": None, "chunks": []}
    completed = threading.Event()

    def _do_extraction() -> None:
        try:
            extractor = _extractors.get(file_type)
            if extractor is None:
                result["error"] = f"No extractor for '{file_type}'"
                return

            extraction = extractor.extract(file_path)
            chunks = _chunker.chunk(
                text=extraction.text,
                source_file=file_path,
                metadata={"file_type": file_type, **extraction.metadata},
            )

            result["chunks"] = [
                {
                    "text": c.text,
                    "chunk_index": c.chunk_index,
                    "char_offset": c.char_offset,
                    "source_file": c.source_file,
                    "metadata": c.metadata,
                }
                for c in chunks
            ]
        except Exception as e:
            result["error"] = str(e)
        finally:
            completed.set()

    worker_thread = threading.Thread(target=_do_extraction, daemon=True)
    worker_thread.start()

    if not completed.wait(timeout=_timeout):
        result["error"] = f"Extraction timed out after {_timeout}s: {file_path}"
        logger.warning("Extraction timeout for %s", file_path)

    return result
