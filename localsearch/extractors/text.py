"""Text file extractor for plain text formats."""

import logging
from pathlib import Path

from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)

# Encodings to try in order
_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]


class TextExtractor(BaseExtractor):
    """Extracts text from plain text files."""

    def extract(self, file_path: str) -> ExtractionResult:
        for enc in _ENCODINGS:
            try:
                text = Path(file_path).read_text(encoding=enc)
                return ExtractionResult(
                    text=text,
                    metadata={"encoding": enc},
                )
            except UnicodeDecodeError:
                continue
            except OSError as e:
                raise ExtractionError(f"Cannot read file {file_path}: {e}") from e

        raise ExtractionError(f"Could not decode {file_path} with any supported encoding")

    def supported_extensions(self) -> list[str]:
        return [
            ".txt", ".md", ".csv", ".json", ".xml", ".html", ".log",
            ".yaml", ".yml", ".ini", ".cfg", ".conf", ".rst", ".tex",
        ]
