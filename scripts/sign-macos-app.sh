#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/dist/macos/星语歌词对齐器.app}"
IDENTITY="-"
if [[ "${2:-}" == "--identity" && -n "${3:-}" ]]; then
  IDENTITY="$3"
elif [[ $# -gt 1 ]]; then
  echo "Usage: $0 [app] [--identity identity]" >&2
  exit 2
fi
[[ -d "$APP" ]] || { echo "App not found: $APP" >&2; exit 3; }

MAIN="$APP/Contents/MacOS/XingyuLyricsAligner"
RUNTIME="$APP/Contents/Resources/runtime"
PYTHON="$RUNTIME/bin/python3"
SIGN_OPTIONS=(--force --sign "$IDENTITY")
if [[ "$IDENTITY" == "-" ]]; then
  SIGN_OPTIONS+=(--timestamp=none)
else
  SIGN_OPTIONS+=(--timestamp --options runtime)
fi

sign_macho_files() {
  local selector="$1"
  local candidates
  case "$selector" in
    dylib) candidates="$(mktemp)"; find "$APP/Contents" -type f -name '*.dylib' -print0 | sort -z > "$candidates" ;;
    extension) candidates="$(mktemp)"; find "$APP/Contents" -type f -name '*.so' -print0 | sort -z > "$candidates" ;;
    executable) candidates="$(mktemp)"; find "$APP/Contents" -type f -perm +111 ! -name '*.dylib' ! -name '*.so' -print0 | sort -z > "$candidates" ;;
  esac
  while IFS= read -r -d '' candidate; do
    [[ "$candidate" == "$MAIN" ]] && continue
    file "$candidate" | grep -q 'Mach-O' || continue
    codesign "${SIGN_OPTIONS[@]}" "$candidate"
  done < "$candidates"
  rm -f "$candidates"
}

# Correct inside-out order. install_name_tool/lipo work must already be complete.
sign_macho_files dylib
sign_macho_files extension
sign_macho_files executable

# Signing changes the bytes of key Runtime binaries. Refresh only their recorded
# sizes/hashes before sealing the main executable and outer bundle.
PYTHONDONTWRITEBYTECODE=1 PYTHONHOME="$RUNTIME" "$PYTHON" - "$RUNTIME" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
path = root / "runtime-manifest.json"
manifest = json.loads(path.read_text(encoding="utf-8"))
for item in manifest["files"]:
    if item.get("type", "file") != "file":
        continue
    target = root / item["relativePath"]
    item["sizeBytes"] = target.stat().st_size
    item["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

codesign "${SIGN_OPTIONS[@]}" "$MAIN"
codesign "${SIGN_OPTIONS[@]}" "$APP"
codesign --verify --deep --strict --verbose=4 "$APP"
if [[ "$IDENTITY" == "-" ]]; then
  echo "Ad-hoc signature applied (not Developer ID): $APP"
else
  echo "Signature applied with identity '$IDENTITY': $APP"
fi
