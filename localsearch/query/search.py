"""Semantic search against the vector database."""

import logging
from dataclasses import dataclass

from localsearch.config import Config
from localsearch.embedder import Embedder
from localsearch.storage.vectordb import VectorDB

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    file_path: str
    chunk_index: int
    text: str
    score: float
    file_type: str


class SearchEngine:
    """Embeds queries and searches the vector database."""

    def __init__(self, config: Config):
        self.config = config
        self.embedder = Embedder(
            model_name=config.embedding.model,
            device=config.embedding.device,
            batch_size=config.embedding.batch_size,
        )
        self.vectordb = VectorDB(
            host=config.qdrant.host,
            port=config.qdrant.port,
            collection=config.qdrant.collection,
        )

    def search(self, query: str, top_k: int | None = None,
               file_type: str | None = None,
               exclude_file_types: list[str] | None = None) -> list[SearchResult]:
        """Search for relevant chunks matching the query.

        Args:
            query: Natural language search query.
            top_k: Number of results (defaults to config value).
            file_type: Optional filter by file type.
            exclude_file_types: Optional list of file types to exclude.

        Returns:
            List of SearchResult objects, ranked by relevance.
        """
        top_k = top_k or self.config.query.top_k

        query_vector = self.embedder.embed_query(query)

        filters = {}
        if file_type:
            filters["file_type"] = file_type

        raw_results = self.vectordb.search(
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=self.config.query.score_threshold,
            filters=filters if filters else None,
            exclude_file_types=exclude_file_types,
        )

        results = []
        for hit in raw_results:
            payload = hit["payload"]
            results.append(SearchResult(
                file_path=payload.get("file_path", ""),
                chunk_index=payload.get("chunk_index", 0),
                text=payload.get("text", ""),
                score=hit["score"],
                file_type=payload.get("file_type", "unknown"),
            ))

        return results

    def get_file_chunks(self, file_paths: list[str]) -> list[SearchResult]:
        """Retrieve all indexed chunks for the given file paths."""
        raw = self.vectordb.get_chunks_by_files(file_paths)
        results = []
        for hit in raw:
            payload = hit["payload"]
            results.append(SearchResult(
                file_path=payload.get("file_path", ""),
                chunk_index=payload.get("chunk_index", 0),
                text=payload.get("text", ""),
                score=1.0,  # file-level retrieval, no score
                file_type=payload.get("file_type", "unknown"),
            ))
        return results
