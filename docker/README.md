# Docker Runtime

The official v0.3.0 image is a CPU image for local trusted-lyrics alignment.
Release tags are published to GHCR and mirrored to Docker Hub:

```text
ghcr.io/wangjiqing/xingyu-lyrics-aligner
docker.io/<DOCKERHUB_USERNAME>/xingyu-lyrics-aligner
```

The examples below use GHCR:

Release tags are published as a multi-architecture manifest for `linux/amd64`
and `linux/arm64`. Apple Silicon Macs pull the ARM64 image by default.

On first GHCR publication, GitHub may keep the package private even after a
successful push. If anonymous `docker pull ghcr.io/...` fails, set the package
visibility to public in GitHub Packages. Docker Hub is also published with the
same version tags and is used as the release workflow's required public pull
check.

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.3.0 \
  xingyu-align doctor
```

Preheat the Chinese alignment model into the mounted cache:

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.3.0 \
  xingyu-align models pull --language zh --device cpu
```

Run one alignment:

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.3.0 \
  xingyu-align align \
    --audio /music/song.flac \
    --lyrics /jobs/job-001/trusted-lyrics.txt \
    --output-dir /jobs/job-001/result \
    --language zh \
    --device cpu \
    --json-result
```

The image runs as UID/GID `10001:10001`. Ensure the mounted jobs and model cache
directories are writable by that user, or run the container with an explicit
compatible `--user` value. `/music` can and should be mounted read-only.

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

The image installs the `alignment` extra only. It does not install
`candidate-lyrics`, does not download models during build, does not expose HTTP
ports, and does not use the Docker socket.
