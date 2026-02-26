# LocalSearch – fully containerised build
# Base: NVIDIA CUDA runtime for GPU embedding + Whisper
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS base

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive

# System dependencies ---------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev python3-pip \
        ffmpeg \
        tesseract-ocr \
        libglib2.0-0 libsm6 libxext6 libxrender-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default python
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.11 1

# Upgrade pip
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Application -----------------------------------------------------------
WORKDIR /app

# Install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir . 2>/dev/null || true
# The above may partially fail because package source isn't present yet.
# We do a full install below after copying source.

COPY . .
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite + any runtime data
RUN mkdir -p /data

# Default config location
ENV LOCALSEARCH_CONFIG=/app/config.docker.yaml

# Expose web UI port
EXPOSE 8080

# Entrypoint script handles mode selection (ingest / web / both)
# Strip Windows CRLF line endings before chmod (git on Windows adds \r)
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["both"]
