#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${XDG_CACHE_HOME:-/models/.cache}" "${HF_HOME:-/models/huggingface}" /jobs /models

exec "$@"
