"""Base extractor interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractionResult:
    text: str
    metadata: dict


class BaseExtractor(ABC):
    """Abstract base class for file content extractors."""

    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """Extract text content from a file.

        Args:
            file_path: Absolute path to the file.

        Returns:
            ExtractionResult with extracted text and metadata.

        Raises:
            ExtractionError: If extraction fails.
        """

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return list of file extensions this extractor handles."""


class ExtractionError(Exception):
    """Raised when text extraction fails."""
