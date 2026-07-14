#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/.venv/bin/python" "$ROOT/scripts/verify-release-versions.py"
OVERWRITE="${1:-}"
if [[ -n "$OVERWRITE" && "$OVERWRITE" != "--overwrite" ]]; then
  echo "Usage: $0 [--overwrite]" >&2
  exit 2
fi

echo "[1/8] Verifying controlled wheelhouse"
"$ROOT/scripts/prepare-macos-wheelhouse.sh"
echo "[2/8] Building bundled Runtime"
"$ROOT/scripts/build-macos-runtime.sh"
echo "[3/8] Building and ad-hoc signing Release App"
"$ROOT/scripts/build-macos-app.sh"
echo "[4/8] Verifying App Bundle"
"$ROOT/scripts/verify-macos-bundle.sh"
echo "[5/8] Running standalone lyrics smoke"
"$ROOT/scripts/smoke-macos-app.sh"
echo "[6/8] Running standalone dual-track smoke"
XINGYU_SMOKE_TRACKS=1 "$ROOT/scripts/smoke-macos-app.sh"
echo "[7/8] Running cooperative cancellation smoke"
XINGYU_SMOKE_CANCEL=1 "$ROOT/scripts/smoke-macos-app.sh"
echo "[8/8] Packaging strict-layout unsigned DMG"
if [[ "$OVERWRITE" == "--overwrite" ]]; then
  "$ROOT/scripts/package-macos-dmg.sh" --overwrite --require-finder-layout
else
  "$ROOT/scripts/package-macos-dmg.sh" --require-finder-layout
fi
"$ROOT/.venv/bin/python" "$ROOT/scripts/verify-release-versions.py" \
  --runtime-manifest "$ROOT/dist/macos/星语歌词对齐器.app/Contents/Resources/runtime/runtime-manifest.json" \
  --wheelhouse-manifest "$ROOT/packaging/macos/runtime/wheelhouse-manifest.json" \
  --release-manifest "$ROOT/dist/macos/release-manifest.json" \
  --dmg "$ROOT/dist/macos/星语歌词对齐器-0.7.0-arm64-unsigned.dmg"
echo "Release candidate outputs are under $ROOT/dist/macos"
