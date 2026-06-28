FROM python:3.11-slim-bookworm AS runtime

ARG TARGETARCH=arm64

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/models/.cache \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub \
    TRANSFORMERS_CACHE=/models/huggingface/transformers

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        ffmpeg \
        git \
        libgomp1 \
        libglib2.0-0 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /app /music /jobs /models \
    && chown -R app:app /app /jobs /models /home/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY docker/entrypoint.sh /usr/local/bin/xingyu-aligner-entrypoint

RUN python -m pip install --no-cache-dir --upgrade pip \
    && if [ "$TARGETARCH" = "amd64" ]; then \
        python -m pip install --no-cache-dir \
          --index-url https://download.pytorch.org/whl/cpu \
          "torch==2.8.0+cpu" \
          "torchaudio==2.8.0+cpu" \
          "torchvision==0.23.0+cpu"; \
      fi \
    && python -m pip install --no-cache-dir ".[alignment]" \
    && chmod +x /usr/local/bin/xingyu-aligner-entrypoint

USER app

VOLUME ["/jobs", "/models"]

ENTRYPOINT ["xingyu-aligner-entrypoint"]
CMD ["xingyu-align", "--help"]
