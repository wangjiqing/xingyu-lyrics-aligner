# Changelog

## 0.3.0

- Added the official CPU Docker image for `xingyu-align`.
- Added `xingyu-align worker run`, an optional shared-directory Worker for
  Docker Compose deployments.
- Added strict Worker path validation for `/music` audio inputs and `/jobs`
  request/output files.
- Added Worker status contract with `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`, and
  `ABANDONED`.
- Hardened Worker handoff with exclusive `RUNNING` creation, atomic
  `status.json` writes, required output-file validation, and per-attempt stderr
  logs.
- Added Docker Compose Worker examples under `deploy/`.
- Added GitHub Actions CI for Ruff, mypy, pytest, Docker build, and Docker smoke
  tests.
- Added tag-driven GHCR and Docker Hub image publishing for `0.3.0`, `0.3`,
  and `latest`, including Docker Hub anonymous pull verification and best-effort
  GHCR public visibility handling.
- Kept the default macOS CLI and direct Python API path unchanged.

Docker support in v0.3.0 is CPU-first. The release workflow publishes a
multi-architecture manifest for `linux/amd64` and `linux/arm64`, so Apple
Silicon Macs pull the ARM64 image by default.
