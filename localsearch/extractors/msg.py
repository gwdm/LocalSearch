"""Outlook .msg email extractor with embedded attachment support."""

import logging
import tempfile
import os
from pathlib import Path

from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)


class MsgExtractor(BaseExtractor):
    """Extracts text from Outlook .msg files including embedded attachments."""

    def __init__(self, extractors: dict | None = None):
        """Args:
            extractors: Dict of file_type -> BaseExtractor for processing attachments.
                        If None, attachments are skipped.
        """
        self._attachment_extractors = extractors or {}

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            import extract_msg
        except ImportError:
            raise ExtractionError(
                "extract-msg not installed. Install with: pip install extract-msg"
            )

        try:
            msg = extract_msg.Message(file_path)
        except Exception as e:
            # Retry with latin-1 for files with unsupported code pages (e.g. 4093)
            if "code page" in str(e).lower() or "codepage" in str(e).lower():
                try:
                    msg = extract_msg.Message(file_path, overrideEncoding="latin-1")
                    logger.debug("Retried %s with latin-1 encoding", file_path)
                except Exception as e2:
                    raise ExtractionError(f"Failed to open MSG file {file_path}: {e2}") from e2
            else:
                raise ExtractionError(f"Failed to open MSG file {file_path}: {e}") from e

        try:
            parts = []

            # Email headers
            if msg.subject:
                parts.append(f"Subject: {msg.subject}")
            if msg.sender:
                parts.append(f"From: {msg.sender}")
            if msg.to:
                parts.append(f"To: {msg.to}")
            if msg.cc:
                parts.append(f"CC: {msg.cc}")
            if msg.date:
                parts.append(f"Date: {msg.date}")

            parts.append("")

            # Email body
            body = msg.body
            if body:
                parts.append(body)

            # Process attachments
            attachment_texts = []
            attachment_names = []
            for attachment in msg.attachments:
                att_text = self._extract_attachment(attachment)
                if att_text:
                    att_name = getattr(attachment, "longFilename", None) or \
                               getattr(attachment, "shortFilename", None) or "unnamed"
                    attachment_names.append(att_name)
                    attachment_texts.append(f"\n--- Attachment: {att_name} ---\n{att_text}")

            if attachment_texts:
                parts.append("\n".join(attachment_texts))

            text = "\n".join(parts).strip()
            if not text:
                raise ExtractionError(f"No text extracted from MSG: {file_path}")

            metadata = {
                "subject": msg.subject or "",
                "sender": msg.sender or "",
                "date": str(msg.date or ""),
                "attachment_count": len(msg.attachments),
                "attachments_processed": len(attachment_texts),
            }
            if attachment_names:
                metadata["attachment_names"] = ", ".join(attachment_names)

            return ExtractionResult(text=text, metadata=metadata)

        finally:
            msg.close()

    def _extract_attachment(self, attachment) -> str | None:
        """Extract text from an attachment by saving to temp and using the appropriate extractor.
        If the attachment is an Excel OLE object (CLSID 00020820), extract as a .xls file and process as text.
        """
        import extract_msg

        # Handle embedded .msg files (emails within emails)
        if isinstance(attachment, extract_msg.Message):
            try:
                result = self.extract_embedded_msg(attachment)
                return result
            except Exception as e:
                logger.debug("Failed to extract embedded MSG: %s", e)
                return None

        filename = getattr(attachment, "longFilename", None) or \
                   getattr(attachment, "shortFilename", None)
        if not filename:
            return None

        ext = Path(filename).suffix.lower()
        data = getattr(attachment, "data", None)
        if not data:
            return None

        # Map extension to extractor type
        extractor = None
        for type_name, ext_instance in self._attachment_extractors.items():
            if hasattr(ext_instance, "supported_extensions"):
                if ext in ext_instance.supported_extensions():
                    extractor = ext_instance
                    break

        # Special handling for Excel OLE objects (CLSID 00020820)
        # If no extractor, but the attachment has a CLSID for Excel, treat as .xls
        if extractor is None and hasattr(attachment, "clsid"):
            clsid = getattr(attachment, "clsid", "").lower()
            if clsid == "00020820-0000-0000-c000-000000000046":
                # Use text extractor on the raw binary as .xls
                extractor = self._attachment_extractors.get("text")
                ext = ".xls"
                logger.info(f"Processing Excel OLE attachment as text: {filename}")

        if extractor is None:
            return None

        # Write to temp file, extract, clean up
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            result = extractor.extract(tmp_path)
            return result.text
        except Exception as e:
            logger.debug("Failed to extract attachment %s: %s", filename, e)
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def extract_embedded_msg(self, msg) -> str | None:
        """Extract text from an embedded MSG (email within email)."""
        parts = []
        if msg.subject:
            parts.append(f"Subject: {msg.subject}")
        if msg.sender:
            parts.append(f"From: {msg.sender}")
        if msg.body:
            parts.append(msg.body)
        text = "\n".join(parts).strip()
        return text if text else None

    def supported_extensions(self) -> list[str]:
        return [".msg"]
