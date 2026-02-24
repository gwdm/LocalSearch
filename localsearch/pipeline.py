"""Pipeline orchestrator: scan → extract → chunk → embed → store."""

import logging
import time
from typing import Optional

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from localsearch.chunker import TextChunker
from localsearch.config import Config
from localsearch.crawler.scanner import FileScanner, ScannedFile
from localsearch.embedder import Embedder
from localsearch.extractors.audio import AudioExtractor
from localsearch.extractors.base import BaseExtractor, ExtractionError
from localsearch.extractors.docx import DocxExtractor
from localsearch.extractors.image import ImageExtractor
from localsearch.extractors.pdf import PDFExtractor
from localsearch.extractors.text import TextExtractor
from localsearch.extractors.video import VideoExtractor
from localsearch.storage.metadb import FileRecord, MetadataDB
from localsearch.storage.vectordb import VectorDB

logger = logging.getLogger(__name__)


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
        self._extractors = self._build_extractors()

    def _build_extractors(self) -> dict[str, BaseExtractor]:
        """Build extractor instances for each file type."""
        audio_ext = AudioExtractor(
            model_size=self.config.whisper.model_size,
            device=self.config.whisper.device,
            compute_type=self.config.whisper.compute_type,
            language=self.config.whisper.language,
        )
        return {
            "text": TextExtractor(),
            "pdf": PDFExtractor(),
            "docx": DocxExtractor(),
            "audio": audio_ext,
            "video": VideoExtractor(audio_ext),
            "image": ImageExtractor(),
        }

    def ingest(self, paths: Optional[list[str]] = None) -> dict:
        """Run the full ingestion pipeline.

        Args:
            paths: Optional list of specific paths to scan. Uses config if None.

        Returns:
            Statistics dict with counts of processed, skipped, errored files.
        """
        stats = {
            "scanned": 0,
            "processed": 0,
            "chunks_created": 0,
            "errors": 0,
            "deleted": 0,
            "elapsed_seconds": 0,
        }

        start_time = time.time()

        # Ensure Qdrant collection exists
        self.vectordb.ensure_collection(self.embedder.dimension)

        # Phase 1: Scan for new/changed files
        logger.info("Scanning for new and changed files...")
        batch: list[ScannedFile] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            scan_task = progress.add_task("Scanning files...", total=None)

            for scanned_file in self.scanner.scan(paths):
                stats["scanned"] += 1
                batch.append(scanned_file)
                progress.update(scan_task, description=f"Found {stats['scanned']} files to process")

                if len(batch) >= self.config.scanner.batch_size:
                    batch_stats = self._process_batch(batch)
                    stats["processed"] += batch_stats["processed"]
                    stats["chunks_created"] += batch_stats["chunks_created"]
                    stats["errors"] += batch_stats["errors"]
                    batch = []

            # Process remaining files
            if batch:
                batch_stats = self._process_batch(batch)
                stats["processed"] += batch_stats["processed"]
                stats["chunks_created"] += batch_stats["chunks_created"]
                stats["errors"] += batch_stats["errors"]

        # Phase 2: Clean up deleted files
        logger.info("Checking for deleted files...")
        deleted = self.scanner.find_deleted(paths)
        if deleted:
            logger.info("Removing %d deleted files from index", len(deleted))
            for file_path in deleted:
                self.vectordb.delete_by_file(file_path)
            self.metadb.remove_files(deleted)
            stats["deleted"] = len(deleted)

        stats["elapsed_seconds"] = round(time.time() - start_time, 1)
        return stats

    def _process_batch(self, files: list[ScannedFile]) -> dict:
        """Process a batch of files: extract → chunk → embed → store."""
        batch_stats = {"processed": 0, "chunks_created": 0, "errors": 0}

        all_chunks = []
        chunk_file_map: list[str] = []  # Track which file each chunk belongs to
        file_chunk_counts: dict[str, int] = {}

        # Extract and chunk
        for scanned_file in files:
            try:
                # Record file in metadb as pending
                self.metadb.upsert_file(FileRecord(
                    file_path=scanned_file.path,
                    file_size=scanned_file.size,
                    mtime=scanned_file.mtime,
                    status="processing",
                ))

                # Delete old vectors for this file (if re-indexing)
                self.vectordb.delete_by_file(scanned_file.path)

                # Extract text
                extractor = self._extractors.get(scanned_file.file_type)
                if extractor is None:
                    logger.warning("No extractor for type '%s': %s",
                                   scanned_file.file_type, scanned_file.path)
                    continue

                result = extractor.extract(scanned_file.path)

                # Chunk text
                chunks = self.chunker.chunk(
                    text=result.text,
                    source_file=scanned_file.path,
                    metadata={
                        "file_type": scanned_file.file_type,
                        **result.metadata,
                    },
                )

                if chunks:
                    all_chunks.extend(chunks)
                    file_chunk_counts[scanned_file.path] = len(chunks)
                    for _ in chunks:
                        chunk_file_map.append(scanned_file.path)

                batch_stats["processed"] += 1

            except ExtractionError as e:
                logger.warning("Extraction failed for %s: %s", scanned_file.path, e)
                self.metadb.mark_error(scanned_file.path, str(e))
                batch_stats["errors"] += 1
            except Exception as e:
                logger.error("Unexpected error processing %s: %s", scanned_file.path, e)
                self.metadb.mark_error(scanned_file.path, str(e))
                batch_stats["errors"] += 1

        # Embed all chunks in batch
        if all_chunks:
            logger.info("Embedding %d chunks...", len(all_chunks))
            texts = [c.text for c in all_chunks]
            vectors = self.embedder.embed(texts)

            # Build payloads
            payloads = []
            for chunk in all_chunks:
                payloads.append({
                    "file_path": chunk.source_file,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text[:500],  # Store preview text in payload
                    "file_type": chunk.metadata.get("file_type", "unknown"),
                })

            # Upsert to Qdrant
            self.vectordb.upsert(vectors, payloads)
            batch_stats["chunks_created"] = len(all_chunks)

            # Mark files as indexed
            for file_path, count in file_chunk_counts.items():
                self.metadb.mark_indexed(file_path, count)

        return batch_stats

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
