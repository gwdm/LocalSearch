"""Tests for the text chunker."""

from localsearch.chunker import TextChunker


def test_short_text_single_chunk():
    """Short text should return a single chunk."""
    chunker = TextChunker(chunk_size=1000, chunk_overlap=200)
    chunks = chunker.chunk("This is a short text.", source_file="test.txt")
    assert len(chunks) == 1
    assert chunks[0].text == "This is a short text."
    assert chunks[0].source_file == "test.txt"
    assert chunks[0].chunk_index == 0


def test_long_text_multiple_chunks():
    """Long text should be split into multiple chunks."""
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    text = "This is sentence one. " * 20  # ~440 chars
    chunks = chunker.chunk(text, source_file="long.txt")
    assert len(chunks) > 1

    # All chunks should have text
    for chunk in chunks:
        assert len(chunk.text) > 0
        assert chunk.source_file == "long.txt"

    # Chunk indices should be sequential
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_empty_text_no_chunks():
    """Empty text should produce no chunks."""
    chunker = TextChunker()
    chunks = chunker.chunk("", source_file="empty.txt")
    assert len(chunks) == 0

    chunks = chunker.chunk("   ", source_file="whitespace.txt")
    assert len(chunks) == 0


def test_metadata_passed_through():
    """Metadata should be passed to all chunks."""
    chunker = TextChunker(chunk_size=50, chunk_overlap=10)
    text = "Hello world. " * 20
    meta = {"file_type": "text", "encoding": "utf-8"}
    chunks = chunker.chunk(text, source_file="meta.txt", metadata=meta)
    for chunk in chunks:
        assert chunk.metadata["file_type"] == "text"
        assert chunk.metadata["encoding"] == "utf-8"
