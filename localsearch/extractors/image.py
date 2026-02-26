"""Image text extractor using Tesseract OCR."""

import logging

from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)


class ImageExtractor(BaseExtractor):
    """Extracts text from images using Tesseract OCR."""

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            raise ExtractionError(
                "Pillow or pytesseract not installed. "
                "Install with: pip install Pillow pytesseract"
            )

        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)

            # Empty text is OK - logos, icons, decorative images have no text
            # Return empty result with metadata instead of error
            return ExtractionResult(
                text=text.strip(),
                metadata={
                    "image_size": f"{image.width}x{image.height}",
                    "image_mode": image.mode,
                },
            )
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to OCR image {file_path}: {e}") from e

    def supported_extensions(self) -> list[str]:
        return [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"]
