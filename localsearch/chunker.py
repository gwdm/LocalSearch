"""Text chunker with recursive character splitting."""

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    chunk_index: int
    char_offset: int
    source_file: str
    metadata: dict


class TextChunker:
    """Splits text into overlapping chunks, preserving sentence boundaries."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]

    def chunk(self, text: str, source_file: str, metadata: dict | None = None) -> list[Chunk]:
        """Split text into chunks with overlap.

        Args:
            text: The text to split.
            source_file: Path to the source file.
            metadata: Additional metadata to attach to each chunk.

        Returns:
            List of Chunk objects.
        """
        if not text.strip():
            return []

        metadata = metadata or {}
        splits = self._recursive_split(text)
        chunks = []

        for i, (split_text, char_offset) in enumerate(splits):
            chunks.append(Chunk(
                text=split_text,
                chunk_index=i,
                char_offset=char_offset,
                source_file=source_file,
                metadata=metadata,
            ))

        return chunks

    def _recursive_split(self, text: str) -> list[tuple[str, int]]:
        """Split text recursively by separators, returning (text, offset) pairs."""
        if len(text) <= self.chunk_size:
            return [(text, 0)]

        results: list[tuple[str, int]] = []
        current_offset = 0

        while current_offset < len(text):
            # Determine the end of this chunk
            end = min(current_offset + self.chunk_size, len(text))

            if end < len(text):
                # Try to find a good split point
                split_pos = self._find_split_point(text, current_offset, end)
                chunk_text = text[current_offset:split_pos].strip()
            else:
                chunk_text = text[current_offset:end].strip()
                split_pos = end

            if chunk_text:
                results.append((chunk_text, current_offset))

            # Move forward, accounting for overlap
            if split_pos >= len(text):
                break
            current_offset = split_pos - self.chunk_overlap
            if current_offset <= (results[-1][1] if results else -1):
                current_offset = split_pos

        return results

    def _find_split_point(self, text: str, start: int, end: int) -> int:
        """Find the best split point near `end`, preferring sentence boundaries."""
        # Search backward from end for a good separator
        search_start = max(start + self.chunk_size // 2, start)

        for sep in self._separators:
            pos = text.rfind(sep, search_start, end)
            if pos != -1:
                return pos + len(sep)

        # No good boundary found, split at end
        return end
