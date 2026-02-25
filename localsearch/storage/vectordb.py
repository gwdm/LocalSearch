"""Qdrant vector database client."""

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class VectorDB:
    """Wrapper around Qdrant client for vector storage and search."""

    def __init__(self, host: str = "localhost", port: int = 6333,
                 collection: str = "localsearch"):
        self.host = host
        self.port = port
        self.collection = collection
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError:
                raise RuntimeError(
                    "qdrant-client not installed. Install with: pip install qdrant-client"
                )
            self._client = QdrantClient(
                host=self.host, port=self.port, timeout=120,
            )
        return self._client

    def ensure_collection(self, vector_size: int) -> None:
        """Create the collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

        client = self._get_client()
        collections = [c.name for c in client.get_collections().collections]

        if self.collection not in collections:
            logger.info("Creating Qdrant collection '%s' (dim=%d)", self.collection, vector_size)
            client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )

        # Ensure payload index on file_path for fast filtered deletes
        info = client.get_collection(self.collection)
        if not info.payload_schema or "file_path" not in info.payload_schema:
            logger.info("Creating payload index on 'file_path'")
            client.create_payload_index(
                collection_name=self.collection,
                field_name="file_path",
                field_schema=PayloadSchemaType.KEYWORD,
                wait=False,
            )

    def upsert(self, vectors: list[list[float]], payloads: list[dict],
               ids: Optional[list[str]] = None) -> None:
        """Insert or update vectors with payloads.

        Args:
            vectors: List of embedding vectors.
            payloads: List of metadata dicts (one per vector).
            ids: Optional list of point IDs. Auto-generated if not provided.
        """
        from qdrant_client.models import PointStruct

        client = self._get_client()

        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]

        points = [
            PointStruct(id=id_, vector=vec, payload=payload)
            for id_, vec, payload in zip(ids, vectors, payloads)
        ]

        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            client.upsert(collection_name=self.collection, points=batch)

    def search(self, query_vector: list[float], top_k: int = 10,
               score_threshold: float = 0.0,
               filters: Optional[dict] = None,
               exclude_file_types: Optional[list[str]] = None) -> list[dict]:
        """Search for similar vectors.

        Args:
            query_vector: The query embedding.
            top_k: Number of results to return.
            score_threshold: Minimum similarity score.
            filters: Optional Qdrant filter conditions.
            exclude_file_types: Optional list of file_type values to exclude.

        Returns:
            List of dicts with 'score', 'payload', and 'id' keys.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        client = self._get_client()

        must_conditions = []
        must_not_conditions = []

        if filters:
            for key, value in filters.items():
                must_conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

        if exclude_file_types:
            must_not_conditions.append(
                FieldCondition(key="file_type", match=MatchAny(any=exclude_file_types))
            )

        qdrant_filter = None
        if must_conditions or must_not_conditions:
            qdrant_filter = Filter(
                must=must_conditions or None,
                must_not=must_not_conditions or None,
            )

        results = client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
        )

        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results.points
        ]

    def get_chunks_by_files(self, file_paths: list[str], limit: int = 100) -> list[dict]:
        """Retrieve all chunks for the given file paths.

        Args:
            file_paths: List of file paths to retrieve chunks for.
            limit: Maximum chunks to return per file.

        Returns:
            List of dicts with 'payload' keys, sorted by file_path and chunk_index.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = self._get_client()
        conditions = [
            FieldCondition(key="file_path", match=MatchValue(value=fp))
            for fp in file_paths
        ]
        results, _ = client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(should=conditions),
            limit=limit * len(file_paths),
            with_payload=True,
            with_vectors=False,
        )
        return [
            {"payload": point.payload}
            for point in sorted(
                results,
                key=lambda p: (p.payload.get("file_path", ""), p.payload.get("chunk_index", 0)),
            )
        ]

    def delete_by_file(self, file_path: str) -> None:
        """Delete all vectors associated with a file."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = self._get_client()
        client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))]
            ),
        )

    def delete_collection(self) -> None:
        """Delete the entire collection."""
        client = self._get_client()
        client.delete_collection(self.collection)
        logger.info("Deleted collection '%s'", self.collection)

    def count(self) -> int:
        """Get total number of vectors in the collection."""
        client = self._get_client()
        info = client.get_collection(self.collection)
        return info.points_count
