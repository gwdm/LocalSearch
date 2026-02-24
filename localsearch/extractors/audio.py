"""Audio extractor using faster-whisper for speech-to-text."""

import logging
import tempfile

from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)


class AudioExtractor(BaseExtractor):
    """Extracts text from audio files via speech-to-text (faster-whisper)."""

    def __init__(self, model_size: str = "large-v3", device: str = "cuda",
                 compute_type: str = "float16", language: str | None = None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ExtractionError(
                    "faster-whisper not installed. Install with: pip install faster-whisper"
                )
            logger.info("Loading Whisper model: %s (device=%s, compute=%s)",
                        self.model_size, self.device, self.compute_type)
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            model = self._get_model()
            segments, info = model.transcribe(
                file_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,
            )

            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())

            transcript = " ".join(transcript_parts)
            if not transcript.strip():
                raise ExtractionError(f"No speech detected in audio: {file_path}")

            return ExtractionResult(
                text=transcript,
                metadata={
                    "language": info.language,
                    "language_probability": round(info.language_probability, 3),
                    "duration_seconds": round(info.duration, 1),
                },
            )
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to transcribe audio {file_path}: {e}") from e

    def supported_extensions(self) -> list[str]:
        return [".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac"]
