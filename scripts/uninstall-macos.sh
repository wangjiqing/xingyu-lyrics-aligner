#!/usr/bin/env bash
set -euo pipefail

LAUNCHER="$HOME/.local/bin/xingyu-align"

if [[ -L "$LAUNCHER" || -f "$LAUNCHER" ]]; then
  rm -f "$LAUNCHER"
  echo "Removed launcher: $LAUNCHER"
else
  echo "No launcher found at: $LAUNCHER"
fi

cat <<'EOF'
The project .venv, model cache, outputs, and user music files were not removed.
EOF
