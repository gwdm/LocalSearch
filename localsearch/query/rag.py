"""RAG: combine search results with Ollama LLM for natural language answers."""

import logging
import re

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
- "software codes" / "license keys" -> software license key serial number product key activation code registration code OEM key CD key
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
- When creating a table: ONLY include rows with actual relevant data.
  NEVER include rows with "Not applicable", "N/A", "No code found", or "Not a software code".
  If a source file does not contain the requested information, OMIT it entirely from the table.
- Do NOT list source files that have no relevant data.
- Do NOT include internal system files, JSON configs, or database files — only list user documents.
- Aim for COMPLETENESS: if the same type of information appears in many files, include ALL of them.

Context:
{context}

Question: {question}

REMINDER: If creating a table, include ONLY rows where you found actual data. OMIT any file that has no relevant information — do NOT write "Not applicable" or "N/A" in any cell. Only list files that contain the specific information requested.

Answer:"""

# --- Broad query detection ---
BROAD_QUERY_PATTERNS = re.compile(
    r'\b(find\s+(me\s+)?all|show\s+(me\s+)?all|list\s+(me\s+)?all|'
    r'every\s+(single\s+)?\w+|all\s+(my|the)\b|everything|'
    r'gather\s+(all|every))\b',
    re.IGNORECASE,
)

# System / internal paths that should never appear in user search results
SYSTEM_PATH_PATTERNS = re.compile(
    r'(qdrant_data[\\/]|__pycache__|localsearch\.egg-info|node_modules|'
    r'[\\/]\.git[\\/]|applied_seq\.json|collection_config\.json)',
    re.IGNORECASE,
)

BROAD_EXPANSION_PROMPT = """You are generating search queries for a personal file archive to find ALL instances of something.
Generate 5-8 DIFFERENT search queries. Each query should contain SPECIFIC WORDS AND PHRASES that would literally appear inside the documents, not just category labels.

BAD example queries (too vague, match irrelevant files):
- "software product keys"  (too broad, matches any product email)
- "office license codes"  (too generic)

GOOD example queries (contain words that appear in actual documents):
- "License Key for your order serial number activation code"
- "Your product key registration code CD key"
- "Emailing Serials serial number key"  
- "order confirmation license activation registration key"
- "purchase software license key product information"

For "find all software codes":
  License Key for order number share-it registration
  serial number activation code product key your license
  Emailing Serials serial product key codes
  Windows product key OEM key activation
  registration code subscription license purchase
  order confirmation software serial number activation code
  CCleaner Diskeeper Paragon license key activation

Each query on its own line. Return ONLY the queries.

User question: {question}

Search queries:"""


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

    def _is_broad_query(self, question: str) -> bool:
        """Detect if the user wants a comprehensive sweep (find ALL, list everything, etc.)."""
        return bool(BROAD_QUERY_PATTERNS.search(question))

    def _expand_query_broad(self, question: str) -> list[str]:
        """For broad queries, generate multiple search queries to cover different angles."""
        client = self._get_client()
        try:
            response = client.chat(
                model=self.config.ollama.model,
                messages=[{"role": "user", "content": BROAD_EXPANSION_PROMPT.format(question=question)}],
                options={"num_ctx": 1024, "num_predict": 300},
                think=False,
            )
            text = response["message"]["content"].strip()
            queries = []
            for line in text.splitlines():
                line = line.strip()
                line = re.sub(r'^[\d]+[.)]\s*', '', line)
                line = re.sub(r'^[-*\u2022]\s*', '', line)
                line = line.strip('"\'\'`')
                line = line.strip()
                if line and 5 < len(line) < 500:
                    queries.append(line)
            if queries:
                logger.info("Broad expansion: %d queries from '%s'", len(queries), question[:50])
                for q in queries:
                    logger.info("  -> %s", q)
                return queries[:8]
        except Exception as e:
            logger.warning("Broad query expansion failed: %s", e)
        return [self._expand_query(question)]

    def _filter_system_files(self, results: list) -> list:
        """Remove results from system/internal files that shouldn't appear in user searches."""
        filtered = [r for r in results if not SYSTEM_PATH_PATTERNS.search(r.file_path)]
        removed = len(results) - len(filtered)
        if removed:
            logger.info("Filtered out %d system-file results", removed)
        return filtered

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

    def _multi_search_broad(self, question: str, search_queries: list[str],
                            top_k: int, file_type: str | None) -> list[SearchResult]:
        """For broad queries, run MULTIPLE search passes with different query variants.

        Each expanded query searches independently, then results are merged and
        deduplicated.  Chunks that appear in results from MULTIPLE queries get
        a score boost (cross-query reinforcement).
        """
        per_query_k = max(top_k // max(len(search_queries), 1), 20)
        all_queries = search_queries + [question]

        # Track (file, chunk) -> {best_score, hit_count, result_obj}
        chunk_map: dict[tuple, dict] = {}

        def _add(hits: list[SearchResult]):
            for r in hits:
                key = (r.file_path, r.chunk_index)
                if key in chunk_map:
                    chunk_map[key]["hit_count"] += 1
                    if r.score > chunk_map[key]["best_score"]:
                        chunk_map[key]["best_score"] = r.score
                        chunk_map[key]["result"] = r
                else:
                    chunk_map[key] = {
                        "best_score": r.score,
                        "hit_count": 1,
                        "result": r,
                    }

        # Run each expanded query
        for query in all_queries:
            _add(self.search_engine.search(query=query, top_k=per_query_k, file_type=file_type))

        # File-type diversity: supplementary non-msg search for every query
        if not file_type:
            diversity_k = max(per_query_k, 15)
            for query in all_queries:
                _add(self.search_engine.search(
                    query=query, top_k=diversity_k, file_type=file_type,
                    exclude_file_types=["msg"],
                ))

        # Build result list with cross-query reinforcement scoring.
        # Chunks matching multiple sub-queries are more likely to be relevant.
        all_results: list[SearchResult] = []
        for key, info in chunk_map.items():
            r = info["result"]
            # Boost score: 20% per additional query match
            boosted_score = info["best_score"] * (1.0 + 0.2 * (info["hit_count"] - 1))
            # Create new result with boosted score
            all_results.append(SearchResult(
                file_path=r.file_path,
                chunk_index=r.chunk_index,
                text=r.text,
                score=min(boosted_score, 1.0),  # cap at 1.0
                file_type=r.file_type,
            ))

        multi_hit = sum(1 for info in chunk_map.values() if info["hit_count"] > 1)
        logger.info("Broad search: %d unique chunks from %d queries (%d multi-hit)",
                    len(all_results), len(all_queries), multi_hit)
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results

    def _expand_with_file_chunks(self, results: list,
                                  max_files: int = 5,
                                  max_chunks: int = 40) -> list:
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

        MAX_EXPAND_FILES = max_files
        MAX_EXPAND_CHUNKS = max_chunks

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
        broad = self._is_broad_query(question)

        if broad:
            logger.info("Broad query detected: '%s'", question[:80])
            effective_top_k = max(top_k * 4, 60)
            search_queries = self._expand_query_broad(question)
            results = self._multi_search_broad(
                question, search_queries, effective_top_k, file_type,
            )
        else:
            search_query = self._expand_query(question)
            results = self._multi_search(question, search_query, top_k, file_type)

        # Filter out system / internal files
        results = self._filter_system_files(results)

        if not results:
            return {
                "answer": "No relevant information found in your indexed files.",
                "sources": [],
                "search_results": [],
            }

        # For broad queries: DON'T expand files (we want breadth across many
        # files, not depth into a few).  Instead, deduplicate to best chunk
        # per file and cap total chunks.
        # For focused queries: expand top files so LLM sees complete documents.
        if broad:
            results = self._select_broad_context(results, max_chunks=40)
        else:
            results = self._expand_with_file_chunks(results)

        # Filter again after expansion (may have re-introduced system files)
        results = self._filter_system_files(results)

        # Build context from search results
        context = self._format_context(results)

        # Use larger context window for broad queries with more chunks
        num_ctx = 32768 if broad else 16384

        # Generate answer with Ollama
        prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        client = self._get_client()
        response = client.chat(
            model=self.config.ollama.model,
            messages=[{"role": "user", "content": prompt}],
            options={"num_ctx": num_ctx},
            think=False,  # Disable qwen3 thinking mode for faster responses
        )

        answer = response["message"]["content"]

        # Post-process: strip "Not applicable" / "N/A" rows from tables
        answer = self._clean_table_rows(answer)

        # Collect unique source files — only from results that contributed to answer
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

    def _select_broad_context(self, results: list[SearchResult],
                               max_chunks: int = 60) -> list[SearchResult]:
        """For broad queries, select a diverse set of chunks across many files.

        Instead of expanding files (depth), we want breadth: the best 2-3
        chunks from each relevant file, capped at max_chunks total.
        """
        # Group by file, keep best chunks per file
        file_chunks: dict[str, list[SearchResult]] = {}
        for r in results:
            file_chunks.setdefault(r.file_path, []).append(r)

        # Sort each file's chunks by score descending
        for fp in file_chunks:
            file_chunks[fp].sort(key=lambda r: r.score, reverse=True)

        # Sort files by their best chunk score
        sorted_files = sorted(
            file_chunks.keys(),
            key=lambda fp: file_chunks[fp][0].score,
            reverse=True,
        )

        # Round-robin: take best chunk from each file first, then second-best, etc.
        selected: list[SearchResult] = []
        seen: set = set()
        max_per_file = 2  # at most 2 chunks per file for broad queries

        for round_idx in range(max_per_file):
            for fp in sorted_files:
                chunks = file_chunks[fp]
                if round_idx < len(chunks):
                    c = chunks[round_idx]
                    key = (c.file_path, c.chunk_index)
                    if key not in seen:
                        selected.append(c)
                        seen.add(key)
                if len(selected) >= max_chunks:
                    break
            if len(selected) >= max_chunks:
                break

        logger.info("Broad context: %d chunks from %d unique files",
                    len(selected), len(set(r.file_path for r in selected)))
        return selected

    def _clean_table_rows(self, text: str) -> str:
        """Remove table rows that contain 'Not applicable', 'N/A', or similar junk.

        The LLM sometimes lists source files with no useful data.  This
        post-processing step removes those rows so only real results remain.
        """
        junk_pattern = re.compile(
            r'\|[^|]*(?:'
            r'Not\s+applicable|N/?A|'
            r'No\s+(?:code|key|serial|software|data)\s+found|'
            r'Not\s+a\s+software\s+code|None\s+found|No\s+relevant|'
            r'No\s+specific\s+\w+\s+(?:key|code|serial|license)|'
            r'\(No\s+specific|'
            r'not\s+visible\s+in\s+the\s+text|'
            r'not\s+(?:fully\s+)?provided\s+in\s+the|'
            r'(?:key|code)\s+provided\s+in\s+the\s+email\s+body|'
            r'not\s+(?:fully\s+)?visible|'
            r'requires?\s+further\s+inspection|'
            r'does\s+not\s+constitute\s+proof|'
            r'Note:\s+If\s+you\s+still\s+have|'
            r'not\s+(?:a\s+)?(?:license|software|product)\s+(?:key|code)'
            r')[^|]*\|',
            re.IGNORECASE,
        )
        lines = text.split('\n')
        cleaned = []
        removed = 0
        for line in lines:
            if line.strip().startswith('|') and junk_pattern.search(line):
                removed += 1
                continue
            cleaned.append(line)
        if removed:
            logger.info("Post-processing: removed %d N/A table rows", removed)
        # Also strip trailing disclaimers about missing entries
        result = '\n'.join(cleaned)
        result = re.sub(
            r'\n*(?:\*{0,2}(?:Note|Please note)\*{0,2}):?\s*.*(?:'
            r'Not applicable|not contain|do not contain|'
            r'no.*license|no.*key|no.*code|noted as such|'
            r'not fully visible|further inspection|not visible|'
            r'obscured|partially.*visible|only.*visible|only.*readable'
            r').*$',
            '', result, flags=re.IGNORECASE | re.DOTALL,
        )
        return result.rstrip()

    def _format_context(self, results: list[SearchResult]) -> str:
        """Format search results into context string for the LLM."""
        parts = []
        for i, result in enumerate(results, 1):
            parts.append(
                f"[Source {i}: {result.file_path}]\n{result.text}\n"
            )
        return "\n".join(parts)
