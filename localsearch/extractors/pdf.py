"""PDF text extractor using PyMuPDF."""

import logging

from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """Extracts text from PDF files using PyMuPDF (fitz)."""

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ExtractionError("PyMuPDF not installed. Install with: pip install PyMuPDF")

        try:
            doc = fitz.open(file_path)
            pages = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text)
            doc.close()

            full_text = "\n\n".join(pages)
            if not full_text.strip():
                raise ExtractionError(f"No text extracted from PDF: {file_path}")

            return ExtractionResult(
                text=full_text,
                metadata={"page_count": len(pages)},
            )
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to extract PDF {file_path}: {e}") from e

    def supported_extensions(self) -> list[str]:
        return [".pdf"]
