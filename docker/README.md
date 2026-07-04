# Docker Runtime

The official v0.4.0 image is a CPU-oriented Worker and CLI image. It can run
both trusted-lyrics alignment and candidate lyric draft extraction.

```text
ghcr.io/wangjiqing/xingyu-lyrics-aligner
docker.io/wangjiqing/xingyu-lyrics-aligner
```

Release tags are published as a multi-architecture manifest for `linux/amd64`
and `linux/arm64`. Apple Silicon Macs pull the ARM64 image by default.

The v0.4.0 image installs `.[alignment,candidate-lyrics]`, including
faster-whisper, Demucs, TorchCodec, and their runtime dependencies. It is larger
than v0.3.0. The image does not download models during build; first use may
download or warm model files into `/models`.

The final image pins the CPU PyTorch runtime to `torch==2.11.0+cpu`,
`torchaudio==2.11.0+cpu`, `torchvision==0.26.0+cpu`, and
`torchcodec==0.14.0+cpu` so TorchCodec loads without CUDA libraries. Build logs
may show a WhisperX metadata warning because WhisperX 3.8.6 declares
`torch~=2.8.0`; the Docker release smoke test imports WhisperX and TorchCodec
after the final CPU runtime is installed.

```bash
docker run --rm \
  --user 10001:10001 \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.4.0 \
  xingyu-align doctor
```

Run the shared-directory Worker:

```bash
docker run --rm \
  --user 10001:10001 \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.4.0 \
  xingyu-align worker run --jobs-dir /jobs --music-dir /music --device cpu
```

Run one alignment directly:

```bash
docker run --rm \
  --user 10001:10001 \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.4.0 \
  xingyu-align align \
    --audio /music/song.flac \
    --lyrics /jobs/job-001/trusted-lyrics.txt \
    --output-dir /jobs/job-001/result \
    --language zh \
    --device cpu \
    --json-result
```

The image runs as UID/GID `10001:10001`. Ensure `/jobs` and `/models` are
writable by that user. Mount `/music` read-only. Do not publish ports and do not
mount `/var/run/docker.sock`.

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

CPU candidate lyric draft extraction is significantly slower than alignment and
can use more temporary disk because it may run Demucs and faster-whisper. Draft
outputs are unaligned candidate text for manual review, not trusted lyrics.
