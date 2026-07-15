FROM rust:1.88.0-slim-bookworm AS rust-toolchain

FROM python:3.11-slim-bookworm AS sphn-builder

# Demucs 4.1.0 depends on sphn 0.2.1. PyPI does not publish a Linux arm64
# wheel for that release, so build it once in a controlled builder instead of
# requiring a Rust toolchain in the runtime image.
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup

ENV PATH=/usr/local/cargo/bin:${PATH} \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential \
        cmake \
    && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:3b19b1fece67d979d84080458bed545d1f55ddc5abac6ca5deae2672a184c7fe \
    https://files.pythonhosted.org/packages/b7/94/0957f866030d6071bcfd285977ff3652bacf85e663a634d3172cf47055a7/sphn-0.2.1.tar.gz \
    /tmp/sphn-0.2.1.tar.gz

RUN python -m pip install --no-cache-dir "maturin==1.10.2" \
    && python -m pip wheel --no-cache-dir --no-deps --no-build-isolation \
      --wheel-dir /tmp/wheels /tmp/sphn-0.2.1.tar.gz

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
COPY --from=sphn-builder /tmp/wheels /tmp/sphn-wheels

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --no-deps /tmp/sphn-wheels/sphn-0.2.1-*.whl \
    && python -m pip install --no-cache-dir ".[alignment,candidate-lyrics]" \
    && python -m pip install --no-cache-dir --force-reinstall --no-deps \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.11.0+cpu" \
      "torchaudio==2.11.0+cpu" \
      "torchvision==0.26.0+cpu" \
      "torchcodec==0.14.0+cpu" \
    && python -c "import demucs, sphn; print('Demucs and sphn imports: ok')" \
    && rm -rf /tmp/sphn-wheels \
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
