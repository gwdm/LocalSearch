"""RAG: combine search results with Ollama LLM for natural language answers."""

import logging

from localsearch.config import Config
from localsearch.query.search import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

RAG_PROMPT_TEMPLATE = """You are a helpful assistant that answers questions based on the user's local files.
Use ONLY the context below to answer the question. If the context doesn't contain enough information, say so.
Always cite the source file path for each piece of information you use.

Context:
{context}

Question: {question}

Answer:"""


class RAGEngine:
    """Retrieval Augmented Generation using local search + Ollama."""

    def __init__(self, config: Config, search_engine: SearchEngine | None = None):
        self.config = config
        self.search_engine = search_engine or SearchEngine(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import ollama
            except ImportError:
                raise RuntimeError(
                    "ollama not installed. Install with: pip install ollama"
                )
            self._client = ollama.Client(host=self.config.ollama.host)
        return self._client

    def ask(self, question: str, top_k: int | None = None,
            file_type: str | None = None) -> dict:
        """Ask a question and get an LLM-generated answer with sources.

        Args:
            question: Natural language question.
            top_k: Number of context chunks to retrieve.
            file_type: Optional filter by file type.

        Returns:
            Dict with 'answer', 'sources', and 'search_results'.
        """
        # Retrieve relevant chunks
        results = self.search_engine.search(
            query=question,
            top_k=top_k,
            file_type=file_type,
        )

        if not results:
            return {
                "answer": "No relevant information found in your indexed files.",
                "sources": [],
                "search_results": [],
            }

        # Build context from search results
        context = self._format_context(results)

        # Generate answer with Ollama
        prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        client = self._get_client()
        response = client.chat(
            model=self.config.ollama.model,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response["message"]["content"]

        # Collect unique source files
        sources = list(dict.fromkeys(r.file_path for r in results))

        return {
            "answer": answer,
            "sources": sources,
            "search_results": [
                {
                    "file_path": r.file_path,
                    "score": round(r.score, 4),
                    "text_preview": r.text[:200],
                    "file_type": r.file_type,
                }
                for r in results
            ],
        }

    def _format_context(self, results: list[SearchResult]) -> str:
        """Format search results into context string for the LLM."""
        parts = []
        for i, result in enumerate(results, 1):
            parts.append(
                f"[Source {i}: {result.file_path}]\n{result.text}\n"
            )
        return "\n".join(parts)
