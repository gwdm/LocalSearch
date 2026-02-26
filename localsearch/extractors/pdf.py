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

            full_text = "\n\n".join(pages)

            # Track whether OCR was used
            ocr_was_used = False

            # OCR fallback for image-only / scanned PDFs
            if not full_text.strip():
                logger.debug("No text layer in %s, attempting OCR...", file_path)
                ocr_was_used = True
                pages = []
                for page in doc:
                    try:
                        tp = page.get_textpage_ocr(tessdata="", full=True)
                        text = page.get_text(textpage=tp)
                        if text.strip():
                            pages.append(text)
                    except Exception as ocr_err:
                        logger.debug("OCR failed on page %d of %s: %s",
                                     page.number, file_path, ocr_err)
                full_text = "\n\n".join(pages)

            doc.close()

            # Empty PDF is OK - blank pages, image-only PDFs, diagrams
            # Return empty result with metadata instead of error
            return ExtractionResult(
                text=full_text.strip(),
                metadata={"page_count": len(pages), "ocr_used": ocr_was_used},
            )
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to extract PDF {file_path}: {e}") from e

    def supported_extensions(self) -> list[str]:
        return [".pdf"]
