"""Tests for text extractors."""

import os
import tempfile

from localsearch.extractors.text import TextExtractor


def test_text_extractor_reads_utf8():
    """TextExtractor should read UTF-8 text files."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Hello, world!\nSecond line.")
        f.flush()
        path = f.name

    try:
        extractor = TextExtractor()
        result = extractor.extract(path)
        assert "Hello, world!" in result.text
        assert "Second line." in result.text
        assert result.metadata["encoding"] == "utf-8"
    finally:
        os.unlink(path)


def test_text_extractor_reads_latin1():
    """TextExtractor should fall back to latin-1 for non-UTF-8 files."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
        f.write("Caf\xe9 cr\xe8me".encode("latin-1"))
        f.flush()
        path = f.name

    try:
        extractor = TextExtractor()
        result = extractor.extract(path)
        assert "Caf" in result.text
        assert result.metadata["encoding"] == "latin-1"
    finally:
        os.unlink(path)
