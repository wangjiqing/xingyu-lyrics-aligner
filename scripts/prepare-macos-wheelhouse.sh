#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_JSON="$ROOT/packaging/macos/runtime/runtime-source.json"
REQUIREMENTS="$ROOT/packaging/macos/runtime/requirements.lock"
HASH_LOCK="$ROOT/packaging/macos/runtime/requirements-hashes.lock"
MANIFEST="$ROOT/packaging/macos/runtime/wheelhouse-manifest.json"
CACHE_ROOT="${XINGYU_RUNTIME_CACHE_DIR:-$ROOT/.build-cache/macos-runtime}"
WHEELHOUSE="${XINGYU_WHEELHOUSE:-$CACHE_ROOT/wheelhouse}"
DOWNLOADS="$CACHE_ROOT/downloads"
BOOTSTRAP="$CACHE_ROOT/wheelhouse-python"
REFRESH=0

if [[ "${1:-}" == "--refresh-lock" ]]; then
  REFRESH=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--refresh-lock]" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "macOS arm64 is required." >&2
  exit 3
fi

PYTHON_URL="$(plutil -extract python.url raw "$SOURCE_JSON")"
PYTHON_SHA="$(plutil -extract python.sha256 raw "$SOURCE_JSON")"
ARCHIVE="$DOWNLOADS/${PYTHON_URL##*/}"
ARCHIVE="${ARCHIVE//%2B/+}"
mkdir -p "$DOWNLOADS"
if [[ ! -f "$ARCHIVE" ]] || [[ "$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')" != "$PYTHON_SHA" ]]; then
  rm -f "$ARCHIVE.partial"
  curl -fL --retry 3 -o "$ARCHIVE.partial" "$PYTHON_URL"
  [[ "$(shasum -a 256 "$ARCHIVE.partial" | awk '{print $1}')" == "$PYTHON_SHA" ]] || {
    echo "python-build-standalone checksum mismatch." >&2
    exit 4
  }
  mv "$ARCHIVE.partial" "$ARCHIVE"
fi
if [[ ! -x "$BOOTSTRAP/bin/python3" ]]; then
  rm -rf "$BOOTSTRAP.new"
  mkdir -p "$BOOTSTRAP.new"
  tar -xzf "$ARCHIVE" -C "$BOOTSTRAP.new" --strip-components=1
  rm -rf "$BOOTSTRAP"
  mv "$BOOTSTRAP.new" "$BOOTSTRAP"
fi
PYTHON="$BOOTSTRAP/bin/python3"

"$PYTHON" - "$SOURCE_JSON" <<'PY' > "$CACHE_ROOT/build-tools.tsv"
import json, pathlib, sys
for item in json.loads(pathlib.Path(sys.argv[1]).read_text()).get("pythonBuildTools", []):
    print(item["name"], item["version"], item["url"], item["sha256"], sep="\t")
PY
while IFS=$'\t' read -r TOOL_NAME TOOL_VERSION TOOL_URL TOOL_SHA; do
  TOOL_WHEEL="$DOWNLOADS/${TOOL_URL##*/}"
  if [[ ! -f "$TOOL_WHEEL" ]] || [[ "$(shasum -a 256 "$TOOL_WHEEL" | awk '{print $1}')" != "$TOOL_SHA" ]]; then
    rm -f "$TOOL_WHEEL.partial"
    curl -fL --retry 3 -o "$TOOL_WHEEL.partial" "$TOOL_URL"
    [[ "$(shasum -a 256 "$TOOL_WHEEL.partial" | awk '{print $1}')" == "$TOOL_SHA" ]] || {
      echo "Build tool checksum mismatch: $TOOL_NAME" >&2; exit 11;
    }
    mv "$TOOL_WHEEL.partial" "$TOOL_WHEEL"
  fi
  if [[ "$($PYTHON -m pip show "$TOOL_NAME" 2>/dev/null | awk '/^Version:/{print $2}')" != "$TOOL_VERSION" ]]; then
    "$PYTHON" -m pip install --no-index --no-deps "$TOOL_WHEEL"
  fi
done < "$CACHE_ROOT/build-tools.tsv"

if [[ $REFRESH -eq 1 ]]; then
  rm -rf "$WHEELHOUSE.new"
  mkdir -p "$WHEELHOUSE.new"
  "$PYTHON" - "$SOURCE_JSON" "$REQUIREMENTS" "$CACHE_ROOT/requirements-wheels-only.lock" <<'PY'
import json, pathlib, sys
source = json.loads(pathlib.Path(sys.argv[1]).read_text())
excluded = {item["name"].lower() for item in source.get("pythonSdists", [])}
lines = pathlib.Path(sys.argv[2]).read_text().splitlines()
pathlib.Path(sys.argv[3]).write_text(
    "\n".join(line for line in lines if line.split("==", 1)[0].lower() not in excluded) + "\n"
)
PY
  "$PYTHON" -m pip download \
    --disable-pip-version-check \
    --no-deps \
    --only-binary=:all: \
    --dest "$WHEELHOUSE.new" \
    -r "$CACHE_ROOT/requirements-wheels-only.lock"
  "$PYTHON" - "$SOURCE_JSON" <<'PY' > "$CACHE_ROOT/sdists.tsv"
import json, pathlib, sys
for item in json.loads(pathlib.Path(sys.argv[1]).read_text()).get("pythonSdists", []):
    print(item["name"], item["url"], item["sha256"], item["sourceDateEpoch"], sep="\t")
PY
  while IFS=$'\t' read -r SDIST_NAME SDIST_URL SDIST_SHA SDIST_EPOCH; do
    SDIST="$DOWNLOADS/${SDIST_URL##*/}"
    if [[ ! -f "$SDIST" ]] || [[ "$(shasum -a 256 "$SDIST" | awk '{print $1}')" != "$SDIST_SHA" ]]; then
      rm -f "$SDIST.partial"
      curl -fL --retry 3 -o "$SDIST.partial" "$SDIST_URL"
      [[ "$(shasum -a 256 "$SDIST.partial" | awk '{print $1}')" == "$SDIST_SHA" ]] || {
        echo "Pinned sdist checksum mismatch: $SDIST" >&2
        exit 9
      }
      mv "$SDIST.partial" "$SDIST"
    fi
    if [[ "$SDIST_NAME" == "av" ]]; then
      [[ -n "${XINGYU_LGPL_FFMPEG_PREFIX:-}" ]] || {
        echo "PyAV requires XINGYU_LGPL_FFMPEG_PREFIX." >&2; exit 10;
      }
      PKG_CONFIG_PATH="$XINGYU_LGPL_FFMPEG_PREFIX/lib/pkgconfig" \
      PKG_CONFIG="$ROOT/scripts/pkg-config-macos-ffmpeg.py" \
      CFLAGS="-I$XINGYU_LGPL_FFMPEG_PREFIX/include" \
      LDFLAGS="-L$XINGYU_LGPL_FFMPEG_PREFIX/lib -Wl,-rpath,@loader_path/../../../.." \
      PIP_NO_CACHE_DIR=1 SOURCE_DATE_EPOCH="$SDIST_EPOCH" \
        "$PYTHON" -m pip wheel --no-deps --no-build-isolation \
          --config-settings="--build-option=--ffmpeg-dir=$XINGYU_LGPL_FFMPEG_PREFIX" \
          --wheel-dir "$WHEELHOUSE.new" "$SDIST"
    else
      PIP_NO_CACHE_DIR=1 SOURCE_DATE_EPOCH="$SDIST_EPOCH" \
        "$PYTHON" -m pip wheel --no-deps --no-build-isolation \
          --wheel-dir "$WHEELHOUSE.new" "$SDIST"
    fi
  done < "$CACHE_ROOT/sdists.tsv"
  rm -f "$WHEELHOUSE.new"/xingyu_lyrics_aligner-*.whl
  SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct)}" \
    "$PYTHON" -m pip wheel \
      --disable-pip-version-check \
      --no-deps \
      --wheel-dir "$WHEELHOUSE.new" \
      "$ROOT"
  "$PYTHON" "$ROOT/scripts/generate-macos-wheelhouse-lock.py" \
    "$WHEELHOUSE.new" "$REQUIREMENTS" "$HASH_LOCK.new" "$MANIFEST.new" "$SOURCE_JSON"
  rm -rf "$WHEELHOUSE"
  mv "$WHEELHOUSE.new" "$WHEELHOUSE"
  mv "$HASH_LOCK.new" "$HASH_LOCK"
  mv "$MANIFEST.new" "$MANIFEST"
else
  [[ -f "$HASH_LOCK" && -f "$MANIFEST" ]] || {
    echo "Wheelhouse lock is missing; run $0 --refresh-lock explicitly." >&2
    exit 5
  }
  [[ -d "$WHEELHOUSE" ]] || {
    echo "Wheelhouse cache is missing: $WHEELHOUSE" >&2
    echo "Run $0 --refresh-lock to download and verify pinned wheels." >&2
    exit 6
  }
  "$PYTHON" "$ROOT/scripts/generate-macos-wheelhouse-lock.py" \
    "$WHEELHOUSE" "$REQUIREMENTS" "$HASH_LOCK.check" "$MANIFEST.check" "$SOURCE_JSON"
  cmp "$HASH_LOCK" "$HASH_LOCK.check" >/dev/null || {
    rm -f "$HASH_LOCK.check" "$MANIFEST.check"
    echo "Wheelhouse hashes do not match requirements-hashes.lock." >&2
    exit 7
  }
  cmp "$MANIFEST" "$MANIFEST.check" >/dev/null || {
    rm -f "$HASH_LOCK.check" "$MANIFEST.check"
    echo "Wheelhouse content does not match wheelhouse-manifest.json." >&2
    exit 8
  }
  rm -f "$HASH_LOCK.check" "$MANIFEST.check"
fi
echo "$WHEELHOUSE"
