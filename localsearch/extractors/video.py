"""Video extractor: extract audio track then transcribe with Whisper."""

import logging
import os
import tempfile

from localsearch.extractors.audio import AudioExtractor
from localsearch.extractors.base import BaseExtractor, ExtractionError, ExtractionResult

logger = logging.getLogger(__name__)


class VideoExtractor(BaseExtractor):
    """Extracts text from video by extracting audio and running Whisper."""

    def __init__(self, audio_extractor: AudioExtractor):
        self.audio_extractor = audio_extractor

    def _extract_audio_track(self, video_path: str, output_path: str) -> None:
        """Extract audio from video using ffmpeg."""
        try:
            import ffmpeg
        except ImportError:
            raise ExtractionError(
                "ffmpeg-python not installed. Install with: pip install ffmpeg-python"
            )

        try:
            (
                ffmpeg
                .input(video_path)
                .output(output_path, acodec="pcm_s16le", ac=1, ar="16000")
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error as e:
            stderr = e.stderr.decode() if e.stderr else "unknown error"
            raise ExtractionError(
                f"ffmpeg failed to extract audio from {video_path}: {stderr}"
            ) from e

    def extract(self, file_path: str) -> ExtractionResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.wav")

            logger.debug("Extracting audio from video: %s", file_path)
            self._extract_audio_track(file_path, audio_path)

            result = self.audio_extractor.extract(audio_path)
            result.metadata["source_type"] = "video"
            return result

    def supported_extensions(self) -> list[str]:
        return [".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".flv"]
