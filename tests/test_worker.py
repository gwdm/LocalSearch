"""Tests for the worker process extraction functions."""

import os
import tempfile

from localsearch.worker import extract_and_chunk, init_worker


def _setup_worker():
    """Initialise the worker module globals for tests."""
    init_worker(chunk_size=500, chunk_overlap=100, timeout=30)


def test_extract_text_file():
    """Worker should extract and chunk a plain text file."""
    _setup_worker()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as f:
        f.write("Hello from the worker test.\nSecond line here.")
        path = f.name

    try:
        result = extract_and_chunk(path, "text")
        assert result["error"] is None
        assert len(result["chunks"]) >= 1
        assert "Hello from the worker test" in result["chunks"][0]["text"]
        assert result["chunks"][0]["source_file"] == path
        assert result["chunks"][0]["metadata"]["file_type"] == "text"
    finally:
        os.unlink(path)


def test_extract_unknown_type():
    """Worker should return an error for unknown file types."""
    _setup_worker()

    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
        f.write(b"data")
        path = f.name

    try:
        result = extract_and_chunk(path, "unknown_type")
        assert result["error"] is not None
        assert "No extractor" in result["error"]
        assert result["chunks"] == []
    finally:
        os.unlink(path)


def test_extract_missing_file():
    """Worker should return an error for a non-existent file."""
    _setup_worker()

    result = extract_and_chunk("/nonexistent/file.txt", "text")
    assert result["error"] is not None
    assert result["chunks"] == []


def test_extract_empty_text_file():
    """Worker should return error for empty/whitespace-only text files."""
    _setup_worker()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as f:
        f.write("   \n  \n  ")
        path = f.name

    try:
        result = extract_and_chunk(path, "text")
        # An empty-ish file produces no chunks (chunker returns [])
        assert result["error"] is None
        assert result["chunks"] == []
    finally:
        os.unlink(path)


def test_extract_long_text_multiple_chunks():
    """Worker should produce multiple chunks for a long text file."""
    _setup_worker()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    ) as f:
        f.write("This is a sentence for chunking. " * 200)
        path = f.name

    try:
        result = extract_and_chunk(path, "text")
        assert result["error"] is None
        assert len(result["chunks"]) > 1
        # Indices should be sequential
        for i, chunk in enumerate(result["chunks"]):
            assert chunk["chunk_index"] == i
    finally:
        os.unlink(path)
