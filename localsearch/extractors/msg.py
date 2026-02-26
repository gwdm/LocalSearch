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

        # Try extract_msg first (with encoding fallbacks), then olefile as last resort
        result = self._try_extract_msg(extract_msg, file_path)
        if result is not None:
            return result

        # All extract_msg attempts failed — use olefile fallback
        result = self._try_extract_olefile(file_path)
        if result is not None:
            return result

        raise ExtractionError(f"Failed to extract MSG file {file_path}: all methods exhausted")

    def _try_extract_msg(self, extract_msg, file_path: str) -> ExtractionResult | None:
        """Try to extract using extract_msg with encoding fallbacks.
        Returns None if all attempts fail."""
        encodings = [None] + self._FALLBACK_ENCODINGS  # None = default encoding

        for enc in encodings:
            try:
                if enc is None:
                    msg = extract_msg.Message(file_path)
                else:
                    msg = extract_msg.Message(file_path, overrideEncoding=enc)
            except Exception:
                continue

            try:
                result = self._read_msg_fields(msg, file_path)
                if enc is not None:
                    logger.debug("Extracted %s with fallback encoding %s", file_path, enc)
                return result
            except (UnicodeDecodeError, UnicodeEncodeError):
                # Body/header access failed with this encoding — try next
                continue
            except ExtractionError:
                # No text at all — try next encoding, might decode body with another
                continue
            except Exception:
                continue
            finally:
                try:
                    msg.close()
                except Exception:
                    pass

        return None

    def _try_extract_olefile(self, file_path: str) -> ExtractionResult | None:
        """Fallback extraction using raw OLE property streams."""
        try:
            msg = self._open_via_olefile(file_path)
        except Exception as e:
            logger.debug("olefile fallback failed for %s: %s", file_path, e)
            return None

        try:
            result = self._read_msg_fields(msg, file_path)
            logger.debug("Extracted %s via olefile fallback", file_path)
            return result
        except Exception as e:
            logger.debug("olefile field reading failed for %s: %s", file_path, e)
            return None
        finally:
            try:
                msg.close()
            except Exception:
                pass

    def _read_msg_fields(self, msg, file_path: str) -> ExtractionResult:
        """Read email fields from a msg-like object and build an ExtractionResult."""
        parts = []

        # Email headers — wrap each access in try/except for encoding safety
        for label, attr in [("Subject", "subject"), ("From", "sender"),
                            ("To", "to"), ("CC", "cc"), ("Date", "date")]:
            try:
                val = getattr(msg, attr, None)
                if val:
                    parts.append(f"{label}: {val}")
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass  # skip undecodable header fields

        parts.append("")

        # Email body — this is where most encoding errors occur
        body = msg.body  # may raise UnicodeDecodeError — let it propagate
        if body:
            parts.append(body)

        # Process attachments
        attachment_texts = []
        attachment_names = []
        for attachment in getattr(msg, "attachments", []):
            att_text = self._extract_attachment(attachment)
            if att_text:
                att_name = getattr(attachment, "longFilename", None) or \
                           getattr(attachment, "shortFilename", None) or "unnamed"
                attachment_names.append(att_name)
                attachment_texts.append(f"\n--- Attachment: {att_name} ---\n{att_text}")

        if attachment_texts:
            parts.append("\n".join(attachment_texts))

        text = "\n".join(parts).strip()
        # Empty MSG is OK - blank emails, calendar invites may have no text
        # Return empty result with metadata instead of error
        
        metadata = {
            "subject": "",
            "sender": "",
            "date": "",
            "attachment_count": len(getattr(msg, "attachments", [])),
            "attachments_processed": len(attachment_texts),
        }
        # Safely populate metadata
        for key, attr in [("subject", "subject"), ("sender", "sender"), ("date", "date")]:
            try:
                val = getattr(msg, attr, None)
                metadata[key] = str(val) if val else ""
            except (UnicodeDecodeError, UnicodeEncodeError):
                metadata[key] = "(encoding error)"
        if attachment_names:
            metadata["attachment_names"] = ", ".join(attachment_names)

        return ExtractionResult(text=text, metadata=metadata)

    # Encoding fallback chain for MSG files that fail with their declared code page
    _FALLBACK_ENCODINGS = ["latin-1", "cp1252", "utf-8", "shift_jis", "gb2312", "euc_kr", "windows-950"]

    def _open_via_olefile(self, file_path: str):
        """Fallback: extract basic email fields directly from OLE compound file.

        Returns a lightweight namespace object that mimics the extract_msg.Message
        interface (subject, sender, to, cc, date, body, attachments, close).
        """
        import olefile

        ole = olefile.OleFileIO(file_path)
        try:
            def _read_stream(name: str) -> str:
                """Read a string property from the OLE stream."""
                # Try Unicode stream first, then ASCII
                for suffix in ("001F", "001E"):
                    stream_name = f"__substg1.0_{name}{suffix}"
                    if ole.exists(stream_name):
                        raw = ole.openstream(stream_name).read()
                        if suffix == "001F":
                            return raw.decode("utf-16-le", errors="replace")
                        else:
                            return raw.decode("utf-8", errors="replace")
                return ""

            subject = _read_stream("0037")
            sender  = _read_stream("0C1A") or _read_stream("0042")
            to      = _read_stream("0E04")
            cc      = _read_stream("0E03")
            body    = _read_stream("1000")
            date    = _read_stream("0039")

            # Build a duck-typed object
            class _OleMsg:
                def __init__(self):
                    self.subject = subject or None
                    self.sender = sender or None
                    self.to = to or None
                    self.cc = cc or None
                    self.date = date or None
                    self.body = body or None
                    self.attachments = []  # skip attachments in fallback mode
                def close(self):
                    ole.close()

            logger.debug("Opened %s via olefile fallback", file_path)
            return _OleMsg()
        except Exception:
            ole.close()
            raise

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
                if tmp_path:
                    os.unlink(tmp_path)
            except (OSError, UnboundLocalError):
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
