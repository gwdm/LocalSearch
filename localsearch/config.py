"""Configuration management for LocalSearch."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class QdrantConfig:
    host: str = "localhost"
    port: int = 6333
    collection: str = "localsearch"


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "llama3"


@dataclass
class EmbeddingConfig:
    model: str = "mixedbread-ai/mxbai-embed-large-v1"
    batch_size: int = 64
    device: str = "cuda"


@dataclass
class WhisperConfig:
    model_size: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: Optional[str] = None


@dataclass
class ChunkingConfig:
    chunk_size: int = 1000
    chunk_overlap: int = 200


@dataclass
class ScannerConfig:
    max_file_size_mb: int = 500
    use_content_hash: bool = False
    batch_size: int = 1000


@dataclass
class QueryConfig:
    top_k: int = 10
    score_threshold: float = 0.3


@dataclass
class PipelineConfig:
    cpu_workers: int = 4                 # Parallel worker processes for CPU extraction
    extraction_timeout: int = 300        # Max seconds per file (CPU extraction)
    gpu_timeout: int = 1800              # Max seconds per file (audio/video transcription)
    embed_batch_size: int = 512          # Chunks to accumulate before embedding
    type_max_mb: dict = field(default_factory=lambda: {
        "text": 100,
        "pdf": 500,
        "docx": 200,
        "image": 50,
        "msg": 200,
        "audio": 2000,
        "video": 5000,
    })


@dataclass
class ExtensionsConfig:
    text: list[str] = field(default_factory=lambda: [
        ".txt", ".md", ".csv", ".json", ".xml", ".html", ".log",
        ".yaml", ".yml", ".ini", ".cfg", ".conf", ".rst", ".tex",
    ])
    pdf: list[str] = field(default_factory=lambda: [".pdf"])
    docx: list[str] = field(default_factory=lambda: [".docx"])
    audio: list[str] = field(default_factory=lambda: [
        ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac",
    ])
    video: list[str] = field(default_factory=lambda: [
        ".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".flv",
    ])
    image: list[str] = field(default_factory=lambda: [
        ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
    ])
    msg: list[str] = field(default_factory=lambda: [".msg"])

    def all_extensions(self) -> set[str]:
        """Return all supported extensions as a set."""
        result: set[str] = set()
        for ext_list in [self.text, self.pdf, self.docx, self.audio, self.video, self.image, self.msg]:
            result.update(ext_list)
        return result

    def get_type(self, extension: str) -> Optional[str]:
        """Return the file type for a given extension."""
        ext = extension.lower()
        for type_name in ["text", "pdf", "docx", "audio", "video", "image", "msg"]:
            if ext in getattr(self, type_name):
                return type_name
        return None


@dataclass
class Config:
    scan_paths: list[str] = field(default_factory=list)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    query: QueryConfig = field(default_factory=QueryConfig)
    metadata_db: str = "localsearch_meta.db"
    log_level: str = "INFO"


def _merge_dataclass(dc: object, data: dict) -> None:
    """Update dataclass fields from a dict, ignoring unknown keys.

    Dict fields are merged (updated) rather than replaced, so partial
    overrides in YAML work correctly.
    """
    for key, value in data.items():
        if hasattr(dc, key):
            current = getattr(dc, key)
            if isinstance(current, dict) and isinstance(value, dict):
                current.update(value)
            else:
                setattr(dc, key, value)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from a YAML file.

    Search order:
    1. Explicit path argument
    2. LOCALSEARCH_CONFIG environment variable
    3. ./config.yaml in current directory
    4. Default config values
    """
    cfg = Config()

    path = config_path or os.environ.get("LOCALSEARCH_CONFIG")
    if path is None:
        candidate = Path("config.yaml")
        if candidate.exists():
            path = str(candidate)

    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if "scan_paths" in data:
            cfg.scan_paths = data["scan_paths"]
        if "metadata_db" in data:
            cfg.metadata_db = data["metadata_db"]
        if "log_level" in data:
            cfg.log_level = data["log_level"]

        for section_name in ["qdrant", "ollama", "embedding", "whisper",
                             "chunking", "scanner", "pipeline", "query",
                             "extensions"]:
            if section_name in data and isinstance(data[section_name], dict):
                _merge_dataclass(getattr(cfg, section_name), data[section_name])

    return cfg
