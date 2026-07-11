FROM python:3.11-slim-bookworm AS runtime

ARG TARGETARCH=arm64

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/models/.cache \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface/hub \
    TRANSFORMERS_CACHE=/models/huggingface/transformers \
    NLTK_DATA=/usr/local/share/nltk_data

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
    && python -m pip install --no-cache-dir ".[alignment,candidate-lyrics]" \
    && python -m pip install --no-cache-dir --force-reinstall --no-deps \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.11.0+cpu" \
      "torchaudio==2.11.0+cpu" \
      "torchvision==0.26.0+cpu" \
      "torchcodec==0.14.0+cpu" \
    && chmod +x /usr/local/bin/xingyu-aligner-entrypoint

ADD --checksum=sha256:e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106 \
    https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip \
    /tmp/punkt_tab.zip

RUN python -c "import zipfile; zipfile.ZipFile('/tmp/punkt_tab.zip').extractall('${NLTK_DATA}/tokenizers')" \
    && python -c "import nltk; nltk.data.find('tokenizers/punkt_tab/english/')" \
    && chmod -R a+rX "${NLTK_DATA}" \
    && rm /tmp/punkt_tab.zip

USER app

VOLUME ["/jobs", "/models", "/music"]

ENTRYPOINT ["xingyu-aligner-entrypoint"]
CMD ["xingyu-align", "--help"]
