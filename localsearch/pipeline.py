"""Pipeline orchestrator: scan → extract → chunk → embed → store.

CPU-bound extraction (text, pdf, docx, image, msg) runs in separate
worker *processes* via ``ProcessPoolExecutor`` for true parallelism
and process isolation — a crash or hang in one extractor cannot bring
down the pipeline.

GPU-bound extraction (audio/video via Whisper) runs sequentially in
the main process.

Embeddings are batched and Qdrant upserts happen in a background
thread queue.
"""

import logging
import queue
import threading
import time
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from localsearch.chunker import Chunk, TextChunker
from localsearch.config import Config
from localsearch.crawler.scanner import FileScanner, ScannedFile
from localsearch.embedder import Embedder
from localsearch.extractors.base import ExtractionError
from localsearch.storage.metadb import FileRecord, MetadataDB
from localsearch.storage.vectordb import VectorDB
from localsearch.worker import extract_and_chunk, init_worker

logger = logging.getLogger(__name__)

# File types that are CPU-bound (safe for parallel processes)
CPU_FILE_TYPES = {"text", "pdf", "docx", "image", "msg"}
# File types that need the GPU (Whisper) — must be sequential
GPU_FILE_TYPES = {"audio", "video"}

METADB_FLUSH_INTERVAL = 100  # Flush metadb batch every N files


@dataclass
class ExtractedFile:
    """Result of extracting and chunking a single file."""
    scanned: ScannedFile
    chunks: list[Chunk] = field(default_factory=list)
    error: str | None = None


class AsyncUpserter:
    """Background thread that drains a queue of (vectors, payloads) and upserts to Qdrant."""

    def __init__(self, vectordb: VectorDB):
        self._vectordb = vectordb
        self._queue: queue.Queue[tuple[list, list] | None] = queue.Queue(maxsize=32)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._error: Exception | None = None

    def start(self):
        self._thread.start()

    def submit(self, vectors: list[list[float]], payloads: list[dict]):
        """Queue an upsert batch. Blocks if queue is full (back-pressure)."""
        self._queue.put((vectors, payloads))

    def stop(self):
        """Signal shutdown and wait for all queued work to finish."""
        self._queue.put(None)
        self._thread.join(timeout=60)
        if self._thread.is_alive():
            logger.warning("AsyncUpserter did not drain in time")
        if self._error:
            logger.error("AsyncUpserter encountered an error: %s", self._error)

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            vectors, payloads = item
            try:
                self._vectordb.upsert(vectors, payloads)
            except Exception as e:
                logger.error("Qdrant upsert failed: %s", e)
                self._error = e


class AsyncEmbedder:
    """Run GPU embedding in a background thread so the main loop stays
    responsive and workers never starve.

    Accepts batches of (texts, payloads) via ``submit()`` and embeds them
    through the Embedder model, forwarding the resulting vectors+payloads
    to an AsyncUpserter for Qdrant storage.
    """

    def __init__(self, embedder: "Embedder", upserter: AsyncUpserter,
                 batch_size: int = 128):
        self._embedder = embedder
        self._upserter = upserter
        self._batch_size = batch_size
        self._queue: queue.Queue[tuple[list[str], list[dict]] | None] = queue.Queue(maxsize=64)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._error: Exception | None = None
        self._chunks_embedded = 0

    def start(self):
        self._thread.start()

    def submit(self, texts: list[str], payloads: list[dict]):
        """Queue texts + payloads for embedding. Blocks if queue is full."""
        if texts:
            self._queue.put((list(texts), list(payloads)))

    def stop(self):
        """Signal shutdown and wait for all queued work to finish."""
        self._queue.put(None)
        self._thread.join(timeout=300)  # embedding can take a while
        if self._thread.is_alive():
            logger.warning("AsyncEmbedder did not drain in time")
        if self._error:
            logger.error("AsyncEmbedder encountered an error: %s", self._error)

    @property
    def chunks_embedded(self):
        return self._chunks_embedded

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            texts, payloads = item
            try:
                # Embed in sub-batches to keep GPU memory bounded
                for i in range(0, len(texts), self._batch_size):
                    batch_texts = texts[i:i + self._batch_size]
                    batch_payloads = payloads[i:i + self._batch_size]
                    vectors = self._embedder.embed(batch_texts)
                    self._upserter.submit(vectors, batch_payloads)
                    self._chunks_embedded += len(batch_texts)
            except Exception as e:
                logger.error("Embedding failed: %s", e)
                self._error = e


class Pipeline:
    """Orchestrates the full ingestion pipeline."""

    def __init__(self, config: Config):
        self.config = config
        self.metadb = MetadataDB(config.metadata_db)
        self.vectordb = VectorDB(
            host=config.qdrant.host,
            port=config.qdrant.port,
            collection=config.qdrant.collection,
        )
        self.embedder = Embedder(
            model_name=config.embedding.model,
            device=config.embedding.device,
            batch_size=config.embedding.batch_size,
        )
        self.chunker = TextChunker(
            chunk_size=config.chunking.chunk_size,
            chunk_overlap=config.chunking.chunk_overlap,
        )
        self.scanner = FileScanner(config, self.metadb)

        # GPU extractors are lazy-loaded — only initialised when the
        # GPU extraction phase actually begins.
        self._audio_extractor = None
        self._video_extractor = None

        # Set by KeyboardInterrupt handler for graceful shutdown
        self._shutdown = threading.Event()

    # -- Lazy GPU extractor construction --------------------------------

    def _get_audio_extractor(self):
        if self._audio_extractor is None:
            from localsearch.extractors.audio import AudioExtractor

            self._audio_extractor = AudioExtractor(
                model_size=self.config.whisper.model_size,
                device=self.config.whisper.device,
                compute_type=self.config.whisper.compute_type,
                language=self.config.whisper.language,
            )
        return self._audio_extractor

    def _get_video_extractor(self):
        if self._video_extractor is None:
            from localsearch.extractors.video import VideoExtractor

            self._video_extractor = VideoExtractor(self._get_audio_extractor())
        return self._video_extractor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, paths: Optional[list[str]] = None) -> dict:
        """Run the full ingestion pipeline.

        Phase 1 — CPU-bound files extracted in a **ProcessPoolExecutor**
                  (true process isolation, per-file timeout).
        Phase 2 — GPU-bound files (audio/video) processed sequentially
                  in the main process.
        Phase 3 — Deleted-file cleanup.

        Embedding is batched, and Qdrant upserts happen via a
        background thread queue.
        """
        pcfg = self.config.pipeline
        stats = {
            "scanned": 0,
            "processed": 0,
            "chunks_created": 0,
            "errors": 0,
            "skipped_size": 0,
            "deleted": 0,
            "elapsed_seconds": 0,
        }

        start_time = time.time()

        # Ensure Qdrant collection exists
        self.vectordb.ensure_collection(self.embedder.dimension)

        # Start async upserter + async embedder
        upserter = AsyncUpserter(self.vectordb)
        upserter.start()
        async_embedder = AsyncEmbedder(
            self.embedder, upserter,
            batch_size=pcfg.embed_batch_size,
        )
        async_embedder.start()

        # Partition files into CPU and GPU buckets
        logger.info("Scanning for new and changed files...")
        cpu_files: list[ScannedFile] = []
        gpu_files: list[ScannedFile] = []
        pending_records: list[FileRecord] = []

        for scanned_file in self.scanner.scan(paths):
            stats["scanned"] += 1

            # Per-type file size guard
            type_limit_mb = pcfg.type_max_mb.get(
                scanned_file.file_type,
                self.config.scanner.max_file_size_mb,
            )
            if scanned_file.size > type_limit_mb * 1024 * 1024:
                logger.debug(
                    "Skipping %s (%d MB > %d MB limit for %s)",
                    scanned_file.path,
                    scanned_file.size // (1024 * 1024),
                    type_limit_mb,
                    scanned_file.file_type,
                )
                stats["skipped_size"] += 1
                continue

            if scanned_file.file_type in GPU_FILE_TYPES:
                gpu_files.append(scanned_file)
            else:
                cpu_files.append(scanned_file)

            # Stage pending record for batch insert
            pending_records.append(FileRecord(
                file_path=scanned_file.path,
                file_size=scanned_file.size,
                mtime=scanned_file.mtime,
                status="pending",
            ))

            # flush pending records periodically
            if len(pending_records) >= METADB_FLUSH_INTERVAL:
                self.metadb.upsert_files_batch(pending_records)
                pending_records.clear()

        # Flush remaining pending records
        self.metadb.upsert_files_batch(pending_records)
        pending_records.clear()

        # ------------------------------------------------------------
        # Resume pending files from previous interrupted runs
        # ------------------------------------------------------------
        already_queued = {sf.path for sf in cpu_files} | {sf.path for sf in gpu_files}
        resumed = 0
        for rec in self.metadb.get_pending_files():
            if rec.file_path in already_queued:
                continue
            ext = Path(rec.file_path).suffix
            ftype = self.config.extensions.get_type(ext)
            if ftype is None:
                continue
            # Re-apply per-type size guard
            type_limit_mb = pcfg.type_max_mb.get(
                ftype, self.config.scanner.max_file_size_mb,
            )
            if rec.file_size > type_limit_mb * 1024 * 1024:
                stats["skipped_size"] += 1
                continue

            sf = ScannedFile(
                path=rec.file_path,
                size=rec.file_size,
                mtime=rec.mtime,
                file_type=ftype,
                extension=ext,
            )
            if ftype in GPU_FILE_TYPES:
                gpu_files.append(sf)
            else:
                cpu_files.append(sf)
            resumed += 1

        if resumed:
            logger.info("Resumed %d pending files from previous run", resumed)

        logger.info(
            "Scan complete: %d new (%d CPU-bound, %d GPU-bound, %d skipped-size, %d resumed)",
            stats["scanned"], len(cpu_files), len(gpu_files),
            stats["skipped_size"], resumed,
        )

        # Track previously-indexed paths so we only delete old vectors
        # on re-index, not on first-time ingestion (avoids 600K+ useless
        # Qdrant HTTP round-trips).
        _reindex_paths = self.metadb.get_indexed_paths() & {sf.path for sf in cpu_files + gpu_files}
        if _reindex_paths:
            logger.info("%d files queued for re-index (old vectors will be deleted)", len(_reindex_paths))

        # Embedding accumulation buffer
        embed_texts: list[str] = []
        embed_payloads: list[dict] = []

        # Batched metadb updates
        indexed_batch: list[tuple[str, int]] = []
        error_batch: list[tuple[str, str]] = []

        def flush_embeddings():
            """Submit accumulated chunks to the background embedding thread.

            This returns almost immediately — the heavy GPU work happens
            in the AsyncEmbedder's background thread, so the main loop
            stays responsive and workers keep feeding results.
            """
            if not embed_texts:
                return
            async_embedder.submit(embed_texts[:], embed_payloads[:])
            embed_texts.clear()
            embed_payloads.clear()

        def flush_metadb():
            """Write batched metadb updates."""
            self.metadb.mark_indexed_batch(indexed_batch)
            self.metadb.mark_errors_batch(error_batch)
            indexed_batch.clear()
            error_batch.clear()

        def handle_result(sf: ScannedFile, worker_result: dict):
            """Process result from a worker process or GPU extraction.

            Accumulates data into buffers.  Does NOT call flush_embeddings
            or flush_metadb — the caller is responsible for flushing after
            a batch of results so the GPU and DB writes happen once per
            batch rather than once per file.
            """
            error = worker_result.get("error")
            chunks_data = worker_result.get("chunks", [])

            if error:
                logger.warning("Extraction failed for %s: %s", sf.path, error)
                error_batch.append((sf.path, error))
                stats["errors"] += 1
                return

            # Delete old vectors only when re-indexing a previously-indexed file
            if sf.path in _reindex_paths:
                self.vectordb.delete_by_file(sf.path)

            if not chunks_data:
                indexed_batch.append((sf.path, 0))
                stats["processed"] += 1
                return

            for chunk_d in chunks_data:
                embed_texts.append(chunk_d["text"])
                embed_payloads.append({
                    "file_path": chunk_d["source_file"],
                    "chunk_index": chunk_d["chunk_index"],
                    "text": chunk_d["text"][:500],
                    "file_type": chunk_d["metadata"].get("file_type", "unknown"),
                })

            indexed_batch.append((sf.path, len(chunks_data)))
            stats["processed"] += 1
            stats["chunks_created"] += len(chunks_data)

        def maybe_flush():
            """Flush embedding and metadb buffers if thresholds are met."""
            if len(embed_texts) >= pcfg.embed_batch_size:
                flush_embeddings()
            if len(indexed_batch) + len(error_batch) >= METADB_FLUSH_INTERVAL:
                flush_metadb()

        # ------------------------------------------------------------------
        # Phase 1: Parallel CPU extraction (ProcessPoolExecutor)
        # ------------------------------------------------------------------
        if cpu_files:
            n_workers = min(pcfg.cpu_workers, len(cpu_files))
            logger.info(
                "Processing %d CPU-bound files with %d worker processes...",
                len(cpu_files), n_workers,
            )
            self._process_cpu_batch(cpu_files, handle_result, n_workers, flush_callback=maybe_flush)
            flush_embeddings()
            flush_metadb()
            self._log_progress(stats, start_time)

        # ------------------------------------------------------------------
        # Phase 2: Sequential GPU extraction (audio/video)
        # ------------------------------------------------------------------
        if gpu_files:
            logger.info("Processing %d GPU-bound files sequentially...", len(gpu_files))
            for i, sf in enumerate(gpu_files, 1):
                if self._shutdown.is_set():
                    logger.info("Shutdown requested — stopping GPU extraction")
                    break

                result = self._extract_gpu(sf)
                handle_result(sf, result)

                if i % 10 == 0:
                    flush_embeddings()
                    flush_metadb()
                    self._log_progress(stats, start_time)

        # Final flush
        flush_embeddings()
        flush_metadb()

        # Stop async embedder first (waits for all embedding to finish),
        # then stop upserter (waits for all Qdrant upserts to finish).
        async_embedder.stop()
        upserter.stop()

        # ------------------------------------------------------------------
        # Phase 3: Clean up deleted files
        # ------------------------------------------------------------------
        if not self._shutdown.is_set():
            logger.info("Checking for deleted files...")
            deleted = self.scanner.find_deleted(paths)
            if deleted:
                logger.info("Removing %d deleted files from index", len(deleted))
                for file_path in deleted:
                    self.vectordb.delete_by_file(file_path)
                self.metadb.remove_files(deleted)
                stats["deleted"] = len(deleted)

        stats["elapsed_seconds"] = round(time.time() - start_time, 1)
        logger.info(
            "Ingestion complete: %d processed, %d errors, %d chunks, "
            "%d skipped (size), %ss",
            stats["processed"], stats["errors"], stats["chunks_created"],
            stats["skipped_size"], stats["elapsed_seconds"],
        )
        return stats

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _process_cpu_batch(
        self,
        files: list[ScannedFile],
        callback,
        n_workers: int,
        flush_callback=None,
    ) -> None:
        """Extract CPU-bound files in parallel using a **process** pool.

        Uses a sliding-window submit pattern: keeps at most
        ``n_workers * 4`` futures in flight at a time so the OS pipe
        between main and worker processes never stalls on 500K+ tasks.

        Each worker process gets its own extractor instances (initialised
        once via ``init_worker``).  Results are serialised dicts, so the
        main process never unpickles heavy library objects.
        """
        max_inflight = max(n_workers * 64, 128)  # Large window so workers stay busy during embedding
        timeout = self.config.pipeline.extraction_timeout + 30

        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=init_worker,
            initargs=(
                self.config.chunking.chunk_size,
                self.config.chunking.chunk_overlap,
                self.config.pipeline.extraction_timeout,
            ),
        ) as pool:
            pending: dict = {}  # future -> ScannedFile
            file_iter = iter(files)
            done_count = 0
            total = len(files)
            exhausted = False

            # Seed the initial batch of futures
            while len(pending) < max_inflight and not exhausted:
                sf = next(file_iter, None)
                if sf is None:
                    exhausted = True
                    break
                fut = pool.submit(extract_and_chunk, sf.path, sf.file_type)
                pending[fut] = sf

            # Drain completed futures and refill
            while pending:
                if self._shutdown.is_set():
                    logger.info("Shutdown requested — cancelling remaining CPU jobs")
                    for f in pending:
                        f.cancel()
                    break

                # Wait for at least one future to complete
                done_batch = set()
                for fut in list(pending):
                    if fut.done():
                        done_batch.add(fut)
                if not done_batch:
                    # Nothing ready yet — block briefly on any one
                    import concurrent.futures
                    completed_set = concurrent.futures.wait(
                        pending, timeout=5,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    done_batch = completed_set.done
                    if not done_batch:
                        continue  # timeout, loop again

                for fut in done_batch:
                    sf = pending.pop(fut)
                    try:
                        result = fut.result(timeout=timeout)
                    except Exception as e:
                        result = {"error": f"Worker process error: {e}", "chunks": []}

                    callback(sf, result)
                    done_count += 1
                    if done_count % 500 == 0:
                        logger.info("CPU extraction progress: %d / %d", done_count, total)

                # Flush embeddings + metadb ONCE per batch of completed futures
                # (not per-file) so GPU embedding doesn't block workers
                if flush_callback:
                    flush_callback()

                # Refill the window
                while len(pending) < max_inflight and not exhausted:
                    sf = next(file_iter, None)
                    if sf is None:
                        exhausted = True
                        break
                    fut = pool.submit(extract_and_chunk, sf.path, sf.file_type)
                    pending[fut] = sf

    def _extract_gpu(self, sf: ScannedFile) -> dict:
        """Extract a single GPU-bound file (audio/video) in the main process.

        Returns the same dict format as ``extract_and_chunk`` so that
        ``handle_result`` can process both identically.
        """
        timeout = self.config.pipeline.gpu_timeout
        result: dict = {"error": None, "chunks": []}
        completed = threading.Event()

        def _do():
            try:
                if sf.file_type == "audio":
                    extractor = self._get_audio_extractor()
                elif sf.file_type == "video":
                    extractor = self._get_video_extractor()
                else:
                    result["error"] = f"Unknown GPU file type: {sf.file_type}"
                    return

                extraction = extractor.extract(sf.path)
                chunks = self.chunker.chunk(
                    text=extraction.text,
                    source_file=sf.path,
                    metadata={"file_type": sf.file_type, **extraction.metadata},
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

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        if not completed.wait(timeout=timeout):
            result["error"] = f"GPU extraction timed out after {timeout}s: {sf.path}"
            logger.warning("GPU extraction timeout for %s", sf.path)
        return result

    @staticmethod
    def _log_progress(stats: dict, start_time: float) -> None:
        elapsed = round(time.time() - start_time, 1)
        logger.info(
            "Progress: %d scanned, %d processed, %d errors, %d chunks | %ss",
            stats["scanned"], stats["processed"], stats["errors"],
            stats["chunks_created"], elapsed,
        )

    def reset(self) -> None:
        """Clear all indexed data."""
        logger.info("Resetting all indexed data...")
        try:
            self.vectordb.delete_collection()
        except Exception:
            pass
        self.metadb.clear()
        logger.info("Reset complete")

    def get_stats(self) -> dict:
        """Get current indexing statistics."""
        db_stats = self.metadb.get_stats()
        try:
            db_stats["vector_count"] = self.vectordb.count()
        except Exception:
            db_stats["vector_count"] = "unavailable (Qdrant not reachable)"
        return db_stats
