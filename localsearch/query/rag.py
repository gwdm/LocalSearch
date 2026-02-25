"""RAG: combine search results with Ollama LLM for natural language answers."""

import logging

from localsearch.config import Config
from localsearch.query.search import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

QUERY_EXPANSION_PROMPT = """You are rewriting a question into a search query for a personal file archive (emails, documents, receipts, notes, certificates).
Your job is to figure out what INFORMATION the user wants, then produce search terms that would appear in a file containing that information.
IGNORE formatting instructions (like "in a table", "as a list", "summarize"). Focus ONLY on the information need.
For ambiguous terms, prefer the interpretation most relevant to personal records:
- "keys" / "windows keys" -> Windows product key serial number license key activation code
- "passwords" / "logins" -> account credentials login password username
- "receipts" / "orders" -> purchase confirmation order invoice payment receipt
- "serial numbers" -> product key serial number registration code license
- "qualifications" / "grades" / "education" -> GCE O level A level GCSE degree certificate university exam results grade pass merit distinction BSc MSc diploma
- "O levels" / "A levels" -> GCE ordinary level advanced level Cambridge London examination certificate subject grade
Always include 5-10 specific search terms with synonyms. Return ONLY the search query, no explanation.

User question: {question}

Search query:"""

RAG_PROMPT_TEMPLATE = """You are a helpful assistant that answers questions based on the user's personal files.
These are the user's OWN files — when they ask "what do I have" or "my grades", they are asking about THEMSELVES.
Use ONLY the context below to answer. If the context doesn't contain enough information, say so.

CRITICAL RULES:
- ALWAYS extract and list EVERY specific detail: grades, subjects, dates, names, numbers, codes, keys.
- NEVER give a vague summary when specific data exists. List each item individually.
- For qualifications/grades: list EVERY subject and grade found, organized by certificate/exam.
- For product keys/serial numbers: show the EXACT values.
- Cite the source file path for each piece of information.
- Do NOT add generic advice, tips, or "next steps" — only report what the files contain.

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

    def _expand_query(self, question: str) -> str:
        """Use the LLM to rewrite a vague question into better search terms."""
        client = self._get_client()
        try:
            response = client.chat(
                model=self.config.ollama.model,
                messages=[{"role": "user", "content": QUERY_EXPANSION_PROMPT.format(question=question)}],
                options={"num_ctx": 512, "num_predict": 100},
                think=False,
            )
            expanded = response["message"]["content"].strip()
            # Sanity check: if the LLM returned something too long or weird, fall back
            if expanded and len(expanded) < 500:
                logger.info("Query expanded: %r -> %r", question, expanded)
                return expanded
        except Exception as e:
            logger.warning("Query expansion failed: %s", e)
        return question

    def _multi_search(self, question: str, expanded_query: str,
                      top_k: int, file_type: str | None) -> list[SearchResult]:
        """Search with both original and expanded queries, merge results.

        Includes file-type diversity: if results are dominated by a single file
        type (e.g. all .msg emails), a supplementary search excluding that type
        is performed so that documents, PDFs, etc. are also surfaced.
        """
        expanded_k = top_k
        original_k = max(top_k // 2, 5)

        # Primary search with expanded query
        results = self.search_engine.search(
            query=expanded_query, top_k=expanded_k, file_type=file_type,
        )
        seen = {(r.file_path, r.chunk_index) for r in results}

        # Secondary search with original question (catches things expansion missed)
        if expanded_query != question:
            extra = self.search_engine.search(
                query=question, top_k=original_k, file_type=file_type,
            )
            for r in extra:
                key = (r.file_path, r.chunk_index)
                if key not in seen:
                    results.append(r)
                    seen.add(key)

        # --- File-type diversity ---
        # The collection is heavily dominated by .msg emails.  ALWAYS run a
        # supplementary search excluding msg so that rarer document types
        # (PDFs, DOCX, text, images) get a chance to appear.
        if results and not file_type:
            diversity_k = max(top_k, 15)
            logger.info("File-type diversity: supplementary non-msg search (k=%d)", diversity_k)
            for q in [expanded_query, question]:
                diverse = self.search_engine.search(
                    query=q, top_k=diversity_k, file_type=file_type,
                    exclude_file_types=["msg"],
                )
                for r in diverse:
                    key = (r.file_path, r.chunk_index)
                    if key not in seen:
                        results.append(r)
                        seen.add(key)

        # Re-sort by score descending.
        # Do NOT trim here — let _expand_with_file_chunks see all candidates
        # (including lower-scored diverse results) so it can pick the right files.
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _expand_with_file_chunks(self, results: list) -> list:
        """For the top-scoring unique files, fetch ALL their chunks.

        This ensures the LLM sees complete documents (e.g. all pages of a
        certificate) instead of just the chunk that matched the query
        vocabulary.

        File-type diversity: if multiple file types appear in the results,
        at least one slot is reserved for each non-dominant type so that
        rare documents (PDFs among millions of emails) get expanded.
        """
        if not results:
            return results

        MAX_EXPAND_FILES = 5
        MAX_EXPAND_CHUNKS = 40

        # Build per-file best score and file type
        file_info: dict[str, dict] = {}  # fp -> {score, file_type}
        for r in results:
            if r.file_path not in file_info or r.score > file_info[r.file_path]["score"]:
                file_info[r.file_path] = {"score": r.score, "file_type": r.file_type}

        # Count file types
        type_counts: dict[str, int] = {}
        for info in file_info.values():
            type_counts[info["file_type"]] = type_counts.get(info["file_type"], 0) + 1

        # Separate files by dominant vs. diverse types
        dominant_type = max(type_counts, key=type_counts.get) if type_counts else None
        diverse_files = []  # non-dominant type files
        dominant_files = []

        for fp, info in sorted(file_info.items(), key=lambda x: x[1]["score"], reverse=True):
            if info["file_type"] != dominant_type:
                diverse_files.append(fp)
            else:
                dominant_files.append(fp)

        # Build expansion list: prioritise diverse file types, fill rest with dominant
        expand_files = []
        # Reserve up to 3 slots for diverse files
        diverse_slots = min(len(diverse_files), 3)
        expand_files.extend(diverse_files[:diverse_slots])
        remaining = MAX_EXPAND_FILES - len(expand_files)
        expand_files.extend(dominant_files[:remaining])

        # If we still have room and more diverse files, add them
        if len(expand_files) < MAX_EXPAND_FILES:
            for fp in diverse_files[diverse_slots:]:
                if fp not in expand_files:
                    expand_files.append(fp)
                    if len(expand_files) >= MAX_EXPAND_FILES:
                        break

        logger.info(
            "Expanding files: %s",
            [(fp, file_info[fp]["file_type"], round(file_info[fp]["score"], 3)) for fp in expand_files],
        )

        # Fetch all chunks for those files
        try:
            file_chunks = self.search_engine.get_file_chunks(expand_files)
            logger.info(
                "File-level expansion: %d files -> %d total chunks",
                len(expand_files), len(file_chunks),
            )
        except Exception as e:
            logger.warning("File-level expansion failed: %s", e)
            return results[:MAX_EXPAND_CHUNKS]

        # Distribute chunks fairly across expanded files.
        # Give each file a per-file budget, with diverse files getting first pick.
        per_file_budget = max(MAX_EXPAND_CHUNKS // max(len(expand_files), 1), 4)
        chunks_by_file: dict[str, list] = {}
        for c in file_chunks:
            chunks_by_file.setdefault(c.file_path, []).append(c)

        # Build merged: diverse files first, then dominant, each capped
        merged: list = []
        seen: set = set()
        for fp in expand_files:  # already ordered: diverse first, dominant second
            for c in chunks_by_file.get(fp, [])[:per_file_budget]:
                key = (c.file_path, c.chunk_index)
                if key not in seen:
                    merged.append(c)
                    seen.add(key)
                if len(merged) >= MAX_EXPAND_CHUNKS:
                    break
            if len(merged) >= MAX_EXPAND_CHUNKS:
                break

        # Append remaining search results from non-expanded files
        expanded_set = set(expand_files)
        for r in results:
            if r.file_path not in expanded_set:
                key = (r.file_path, r.chunk_index)
                if key not in seen:
                    merged.append(r)
                    seen.add(key)

        return merged

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
        top_k = top_k or self.config.query.top_k

        # Expand the query for better search results
        search_query = self._expand_query(question)

        # Search with both expanded and original queries, merge results
        results = self._multi_search(question, search_query, top_k, file_type)

        if not results:
            return {
                "answer": "No relevant information found in your indexed files.",
                "sources": [],
                "search_results": [],
            }

        # Expand top files: fetch ALL chunks so LLM sees complete documents
        results = self._expand_with_file_chunks(results)

        # Build context from search results
        context = self._format_context(results)

        # Generate answer with Ollama
        prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        client = self._get_client()
        response = client.chat(
            model=self.config.ollama.model,
            messages=[{"role": "user", "content": prompt}],
            options={"num_ctx": 16384},
            think=False,  # Disable qwen3 thinking mode for faster responses
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
