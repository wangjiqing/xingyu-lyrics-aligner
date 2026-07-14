#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/dist/macos/星语歌词对齐器.app}"
RUNTIME="$APP/Contents/Resources/runtime"
APP_EXECUTABLE="$APP/Contents/MacOS/XingyuLyricsAligner"
PYTHON="$RUNTIME/bin/python3"
FFMPEG="$RUNTIME/bin/ffmpeg"
FFPROBE="$RUNTIME/bin/ffprobe"
INFO="$APP/Contents/Info.plist"

[[ "$(plutil -extract CFBundleShortVersionString raw "$INFO")" == "0.7.0" ]] || {
  echo "Unexpected App version." >&2; exit 9;
}
[[ "$(plutil -extract CFBundleVersion raw "$INFO")" == "1" ]] || {
  echo "Unexpected App build number." >&2; exit 9;
}
[[ "$(plutil -extract LSMinimumSystemVersion raw "$INFO")" == "14.0" ]] || {
  echo "Unexpected minimum macOS version." >&2; exit 9;
}
[[ -f "$APP/Contents/Resources/Assets.car" ]] || { echo "Missing compiled AppIcon assets." >&2; exit 9; }
for notice in Python-LICENSE.txt FFmpeg-LICENSE.txt THIRD-PARTY-NOTICES.md third-party-packages.json base-runtime-components.json model-licenses.md; do
  [[ -f "$RUNTIME/licenses/$notice" ]] || { echo "Missing license material: $notice" >&2; exit 9; }
done
if find "$RUNTIME" -type f \
  \( -name 'libx264*.dylib' -o -name 'libx265*.dylib' -o -name 'libSvtAv1*.dylib' \) | grep -q .; then
  echo "Runtime contains forbidden GPL/extra codec libraries." >&2
  exit 19
fi

for executable in "$APP_EXECUTABLE" "$PYTHON" "$FFMPEG" "$FFPROBE"; do
  [[ -x "$executable" ]] || { echo "Missing executable: $executable" >&2; exit 10; }
  file "$executable" | grep -q 'arm64' || { echo "Not arm64: $executable" >&2; exit 11; }
  file "$executable" | grep -q 'x86_64' && { echo "Unexpected x86_64 slice: $executable" >&2; exit 12; }
done

FORBIDDEN_PATHS="$(grep -RIlE '/Users/[^/]+/Project/xingyu-lyrics-aligner|/opt/homebrew|xingyu-runtime/work' "$RUNTIME" \
  --exclude='runtime-manifest.json' --exclude='packages.freeze.txt' || true)"
if [[ -n "$FORBIDDEN_PATHS" ]]; then
  echo "$FORBIDDEN_PATHS" | head -10 >&2
  echo "Runtime contains a forbidden development path." >&2
  exit 13
fi
STRUCTURED_FORBIDDEN="$(find "$RUNTIME" -type f \( -name '*.pth' -o -name 'pyvenv.cfg' -o -name '*.pc' -o -name '*Config.cmake' -o -name '*Targets.cmake' \) -print0 | xargs -0 grep -IlE '/opt/homebrew|/usr/local|\.venv|/Users/[^/]+/Project' 2>/dev/null || true)"
if [[ -n "$STRUCTURED_FORBIDDEN" ]]; then
  echo "$STRUCTURED_FORBIDDEN" | head -10 >&2
  echo "Runtime metadata contains a forbidden external path." >&2
  exit 13
fi
if find "$RUNTIME" -type f -perm +111 -maxdepth 6 -exec head -n 1 {} \; 2>/dev/null | grep -E '\.venv|/opt/homebrew|/usr/local' >/dev/null; then
  echo "Runtime contains a development shebang." >&2
  exit 14
fi
MACHO_LIST="$(mktemp)"
python3 - "$RUNTIME" "$MACHO_LIST" <<'PY'
import pathlib,sys
root=pathlib.Path(sys.argv[1]); output=pathlib.Path(sys.argv[2])
magics={bytes.fromhex(x) for x in ('feedface','feedfacf','cefaedfe','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca')}
with output.open('wb') as stream:
 for path in root.rglob('*'):
  if path.is_file() and not path.is_symlink():
   try: head=path.open('rb').read(4)
   except OSError: continue
   if head in magics: stream.write(str(path).encode()+b'\0')
PY
while IFS= read -r -d '' binary; do
  file "$binary" | grep -q 'x86_64' && { echo "Unexpected x86_64 library: $binary" >&2; exit 15; }
  if otool -L "$binary" | grep -E '/opt/homebrew|/usr/local|\.venv' >/dev/null; then
    echo "Forbidden dylib dependency: $binary" >&2
    exit 16
  fi
done < "$MACHO_LIST"
rm -f "$MACHO_LIST"

MANIFEST="$RUNTIME/runtime-manifest.json"
[[ -f "$MANIFEST" ]] || { echo "Missing runtime manifest." >&2; exit 17; }
PATH="$RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
PYTHONHOME="$RUNTIME" \
PYTHONDONTWRITEBYTECODE=1 \
XINGYU_ALIGNER_FFMPEG="$FFMPEG" \
XINGYU_ALIGNER_FFPROBE="$FFPROBE" \
  "$PYTHON" - "$RUNTIME" <<'PY'
import hashlib, json, os, pathlib, sys
import importlib.metadata
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "runtime-manifest.json").read_text())
assert manifest["schemaVersion"] == 1
assert manifest["architecture"] == "arm64"
assert manifest["packageVersion"] == "0.7.0"
for item in manifest["files"]:
    path = root / item["relativePath"]
    assert not pathlib.PurePosixPath(item["relativePath"]).is_absolute()
    assert ".." not in pathlib.PurePosixPath(item["relativePath"]).parts
    if item.get("type", "file") == "symlink":
        assert path.is_symlink() and os.readlink(path) == item["target"]
        path.resolve(strict=True).relative_to(root.resolve())
    else:
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_size == item["sizeBytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
actual = {
    str(path.relative_to(root))
    for path in root.rglob("*")
    if not path.is_dir() and path.name != "runtime-manifest.json"
}
recorded_paths = {item["relativePath"] for item in manifest["files"]}
assert actual == recorded_paths, (sorted(actual - recorded_paths)[:10], sorted(recorded_paths - actual)[:10])
import demucs, torch, torchcodec, whisperx, xingyu_lyrics_aligner
licenses = root / "licenses"
inventory = json.loads((licenses / "third-party-packages.json").read_text())
base = json.loads((licenses / "base-runtime-components.json").read_text())
assert base["schemaVersion"] == 1
assert all((licenses / item["licenseFile"]).is_file() for item in base["components"])
canonical = lambda value: value.lower().replace("_", "-").replace(".", "-")
installed = {canonical(d.metadata["Name"]): d.version for d in importlib.metadata.distributions()}
recorded = {canonical(item["name"]): item["version"] for item in inventory}
assert installed == recorded, (sorted(set(installed) - set(recorded)), sorted(set(recorded) - set(installed)))
for item in inventory:
    assert item["spdx"] and item["spdx"] != "UNKNOWN"
    assert item["sourceUrl"]
    assert item["licenseFiles"]
    assert all((licenses / path).is_file() for path in item["licenseFiles"])
PY
PATH="$RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin" PYTHONHOME="$RUNTIME" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m xingyu_lyrics_aligner.cli --version >/dev/null
[[ "$(PATH="$RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin" PYTHONHOME="$RUNTIME" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m xingyu_lyrics_aligner.cli --version)" == "xingyu-lyrics-aligner 0.7.0" ]] || {
  echo "Bundled Engine version is not 0.7.0." >&2; exit 20;
}
PATH="$RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin" PYTHONHOME="$RUNTIME" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m xingyu_lyrics_aligner.cli desktop readiness --data-dir "$(mktemp -d)" --json >/dev/null
"$FFMPEG" -version >/dev/null
"$FFPROBE" -version >/dev/null
if find "$RUNTIME" -type d \( -name 'models--*' -o -name 'hub' \) | grep -q .; then
  echo "Unexpected model cache in runtime." >&2
  exit 18
fi
codesign -dv "$APP" >/dev/null 2>&1 || true
codesign --verify --deep --strict --verbose=4 "$APP"
echo "Bundle verification passed: $APP"
