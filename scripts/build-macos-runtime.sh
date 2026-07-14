#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_JSON="$ROOT/packaging/macos/runtime/runtime-source.json"
LOCK_FILE="$ROOT/packaging/macos/runtime/requirements.lock"
HASH_LOCK="$ROOT/packaging/macos/runtime/requirements-hashes.lock"
CACHE_ROOT="${XINGYU_RUNTIME_CACHE_DIR:-$ROOT/.build-cache/macos-runtime}"
OUTPUT="${XINGYU_RUNTIME_OUTPUT:-$ROOT/build/macos-runtime/runtime}"
WORK_ROOT="$CACHE_ROOT/work"
DOWNLOADS="$CACHE_ROOT/downloads"
WHEELHOUSE="${XINGYU_WHEELHOUSE:-$CACHE_ROOT/wheelhouse}"
LOCK_DIR="$CACHE_ROOT/build.lock"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "macOS arm64 is required." >&2
  exit 2
fi
mkdir -p "$DOWNLOADS" "$WORK_ROOT"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another runtime build is active: $LOCK_DIR" >&2
  exit 3
fi
cleanup() { rm -rf "$LOCK_DIR" "$WORK_ROOT/current"; }
trap cleanup EXIT INT TERM

json_value() {
  plutil -extract "$1.$2" raw "$SOURCE_JSON"
}
download_verified() {
  local url="$1" destination="$2" expected="$3"
  if [[ ! -f "$destination" ]] || [[ "$(shasum -a 256 "$destination" | awk '{print $1}')" != "$expected" ]]; then
    rm -f "$destination.partial"
    curl -fL --retry 3 --continue-at - -o "$destination.partial" "$url"
    [[ "$(shasum -a 256 "$destination.partial" | awk '{print $1}')" == "$expected" ]] || { echo "Checksum failed: $destination" >&2; exit 4; }
    mv "$destination.partial" "$destination"
  fi
}

PYTHON_URL="$(json_value python url)"
PYTHON_SHA="$(json_value python sha256)"
FFMPEG_URL="$(json_value ffmpeg url)"
FFMPEG_SHA="$(json_value ffmpeg sha256)"
NLTK_URL="$(json_value nltk punktTabUrl)"
NLTK_SHA="$(json_value nltk punktTabSha256)"
PYTHON_ARCHIVE="$DOWNLOADS/${PYTHON_URL##*/}"
PYTHON_ARCHIVE="${PYTHON_ARCHIVE//%2B/+}"
FFMPEG_ARCHIVE="$DOWNLOADS/${FFMPEG_URL##*/}"
NLTK_ARCHIVE="$DOWNLOADS/punkt_tab.zip"
download_verified "$PYTHON_URL" "$PYTHON_ARCHIVE" "$PYTHON_SHA"
download_verified "$FFMPEG_URL" "$FFMPEG_ARCHIVE" "$FFMPEG_SHA"
download_verified "$NLTK_URL" "$NLTK_ARCHIVE" "$NLTK_SHA"

WORK="$WORK_ROOT/current"
STAGING="$WORK/runtime"
mkdir -p "$WORK/python-source" "$WORK/ffmpeg-source" "$WORK/ffmpeg-dest" "$STAGING"
tar -xzf "$PYTHON_ARCHIVE" -C "$WORK/python-source"
cp -R "$WORK/python-source/python/." "$STAGING/"

FFMPEG_CACHE="$CACHE_ROOT/ffmpeg-7.1.3-arm64-lgpl-v2"
FFMPEG_CONFIGURE_ARGS=(
  --prefix=/xingyu-runtime --arch=arm64 --cc=clang --disable-gpl --disable-nonfree
  --disable-doc --disable-debug --disable-autodetect --enable-ffmpeg --enable-ffprobe
  --enable-shared --disable-static
)
XCODE_VERSION="$(xcodebuild -version | tr '\n' ' ')"
CLANG_VERSION="$(clang --version | head -n 1)"
SDK_VERSION="$(xcrun --sdk macosx --show-sdk-version)"
CONFIGURE_HASH="$(printf '%s\0' "${FFMPEG_CONFIGURE_ARGS[@]}" | shasum -a 256 | awk '{print $1}')"
FFMPEG_CACHE_VALID=0
if [[ -f "$FFMPEG_CACHE/cache-manifest.json" ]]; then
  FFMPEG_CACHE_VALID="$(python3 - "$FFMPEG_CACHE" "$FFMPEG_SHA" "$CONFIGURE_HASH" "$XCODE_VERSION" "$CLANG_VERSION" "$SDK_VERSION" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); manifest=json.loads((root/'cache-manifest.json').read_text())
expected=(sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5],sys.argv[6])
actual=(manifest.get('sourceSha256'),manifest.get('configureArgsHash'),manifest.get('xcodeVersion'),manifest.get('clangVersion'),manifest.get('sdkVersion'))
ok=manifest.get('schemaVersion') == 1 and manifest.get('architecture') == 'arm64' and actual == expected
for item in manifest.get('files',[]):
 p=root/item['relativePath']; ok=ok and p.is_file() and not p.is_symlink() and p.stat().st_size==item['sizeBytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
print(1 if ok else 0)
PY
)"
fi
if [[ "$FFMPEG_CACHE_VALID" != 1 ]]; then
  rm -rf "$FFMPEG_CACHE" "$FFMPEG_CACHE.new"
  tar -xJf "$FFMPEG_ARCHIVE" -C "$WORK/ffmpeg-source" --strip-components=1
  (
    cd "$WORK/ffmpeg-source"
    ./configure "${FFMPEG_CONFIGURE_ARGS[@]}"
    make -j"$(sysctl -n hw.ncpu)"
    make DESTDIR="$WORK/ffmpeg-dest" install
  )
  FFMPEG_INSTALL="$WORK/ffmpeg-dest/xingyu-runtime"
  cp "$WORK/ffmpeg-source/COPYING.LGPLv2.1" "$FFMPEG_INSTALL/FFmpeg-LGPL-2.1.txt"
  mv "$FFMPEG_INSTALL" "$FFMPEG_CACHE.new"
  mv "$FFMPEG_CACHE.new" "$FFMPEG_CACHE"
  for dylib in "$FFMPEG_CACHE/lib/"*.dylib; do
    [[ -L "$dylib" ]] && continue
    install_name_tool -id "@rpath/$(basename "$dylib")" "$dylib"
  done
  for binary in "$FFMPEG_CACHE/bin/ffmpeg" "$FFMPEG_CACHE/bin/ffprobe" "$FFMPEG_CACHE/lib/"*.dylib; do
    [[ -L "$binary" ]] && continue
    while IFS= read -r dependency; do
      [[ "$dependency" == *"/xingyu-runtime/lib/"* ]] && install_name_tool -change "$dependency" "@rpath/$(basename "$dependency")" "$binary"
    done < <(otool -L "$binary" | tail -n +2 | awk '{print $1}')
  done
  install_name_tool -add_rpath "@executable_path/../lib" "$FFMPEG_CACHE/bin/ffmpeg"
  install_name_tool -add_rpath "@executable_path/../lib" "$FFMPEG_CACHE/bin/ffprobe"
  python3 - "$FFMPEG_CACHE" "$FFMPEG_SHA" "$CONFIGURE_HASH" "$XCODE_VERSION" "$CLANG_VERSION" "$SDK_VERSION" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); files=[]
for path in sorted([root/'bin/ffmpeg',root/'bin/ffprobe',*root.glob('lib/*.dylib')]):
 if path.is_file() and not path.is_symlink():
  files.append({'relativePath':str(path.relative_to(root)),'sizeBytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
payload={'schemaVersion':1,'sourceSha256':sys.argv[2],'configureArgsHash':sys.argv[3],'xcodeVersion':sys.argv[4],'clangVersion':sys.argv[5],'sdkVersion':sys.argv[6],'architecture':'arm64','files':files}
(root/'cache-manifest.json').write_text(json.dumps(payload,indent=2)+'\n')
PY
fi
XINGYU_LGPL_FFMPEG_PREFIX="$FFMPEG_CACHE" "$ROOT/scripts/prepare-macos-wheelhouse.sh" >/dev/null
cp "$FFMPEG_CACHE/bin/ffmpeg" "$STAGING/bin/ffmpeg"
cp "$FFMPEG_CACHE/bin/ffprobe" "$STAGING/bin/ffprobe"
cp -R "$FFMPEG_CACHE/lib/." "$STAGING/lib/"

RUNTIME_PYTHON="$STAGING/bin/python3"
LOCK_SHA="$(shasum -a 256 "$HASH_LOCK" | awk '{print $1}')"
SOURCE_SHA="$(shasum -a 256 "$SOURCE_JSON" | awk '{print $1}')"
PYTHON_PACKAGE_CACHE="$CACHE_ROOT/python-packages-$LOCK_SHA-$FFMPEG_SHA-$SOURCE_SHA"
if [[ -x "$PYTHON_PACKAGE_CACHE/bin/python3" ]]; then
  rm -rf "$STAGING"
  cp -R "$PYTHON_PACKAGE_CACHE" "$STAGING"
  RUNTIME_PYTHON="$STAGING/bin/python3"
else
  "$RUNTIME_PYTHON" -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --no-index \
    --find-links "$WHEELHOUSE" \
    --require-hashes \
    -r "$HASH_LOCK"
  cp -R "$STAGING" "$PYTHON_PACKAGE_CACHE.new"
  rm -rf "$PYTHON_PACKAGE_CACHE"
  mv "$PYTHON_PACKAGE_CACHE.new" "$PYTHON_PACKAGE_CACHE"
fi
find "$STAGING/lib/python3.11/site-packages" -name direct_url.json -delete
rm -rf "$STAGING/lib/pkgconfig"
for script in "$STAGING/bin/"*; do
  [[ -f "$script" ]] || continue
  first_line="$(head -n 1 "$script" 2>/dev/null || true)"
  if [[ "$first_line" == '#!'*'python'* ]]; then
    sed -i '' '1s|^#!.*python[^ ]*|#!/usr/bin/env python3|' "$script"
  fi
done
find "$STAGING" -type f \( -name '*.so' -o -name '*.dylib' -o -path '*/bin/*' \) -print0 | while IFS= read -r -d '' binary; do
  description="$(file "$binary")"
  if [[ "$description" == *"Mach-O universal binary"* && "$description" == *"arm64"* ]]; then
    lipo "$binary" -thin arm64 -output "$binary.arm64"
    mv "$binary.arm64" "$binary"
  fi
done
TORCH_LIBOMP="$STAGING/lib/python3.11/site-packages/torch/lib/libomp.dylib"
if [[ -f "$TORCH_LIBOMP" ]]; then
  install_name_tool -id "@rpath/libomp.dylib" "$TORCH_LIBOMP"
  codesign --force --sign - "$TORCH_LIBOMP"
fi
mkdir -p "$STAGING/nltk_data" "$STAGING/licenses"
mkdir -p "$STAGING/nltk_data/tokenizers"
ditto -x -k "$NLTK_ARCHIVE" "$STAGING/nltk_data/tokenizers/punkt_tab"
cp "$STAGING/lib/python3.11/LICENSE.txt" "$STAGING/licenses/Python-LICENSE.txt"
cp "$FFMPEG_CACHE/FFmpeg-LGPL-2.1.txt" "$STAGING/licenses/FFmpeg-LGPL-2.1.txt"
cp "$FFMPEG_CACHE/FFmpeg-LGPL-2.1.txt" "$STAGING/licenses/FFmpeg-LICENSE.txt"
cp "$ROOT/packaging/macos/runtime/base-runtime-components.json" "$STAGING/licenses/base-runtime-components.json"
cp "$ROOT/LICENSE" "$STAGING/licenses/Apache-2.0.txt"
cp "$ROOT/LICENSE" "$STAGING/licenses/Project-LICENSE.txt"
cp "$ROOT/docs/third-party-licenses.md" "$STAGING/licenses/THIRD-PARTY-NOTICES.md"
cp "$ROOT/packaging/macos/runtime/model-licenses.md" "$STAGING/licenses/model-licenses.md"
cp "$ROOT/packaging/macos/runtime/licenses/"*.txt "$STAGING/licenses/"
"$RUNTIME_PYTHON" "$ROOT/scripts/collect-macos-runtime-licenses.py" "$STAGING/licenses"
"$RUNTIME_PYTHON" -m pip freeze --all | LC_ALL=C sort > "$STAGING/packages.freeze.txt"
find "$STAGING" -type f -name '*.pyc' -delete
find "$STAGING" -type d -name __pycache__ -empty -delete
PYTHONDONTWRITEBYTECODE=1 SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" "$RUNTIME_PYTHON" "$ROOT/scripts/generate-macos-runtime-manifest.py" "$STAGING" "$SOURCE_JSON" "$HASH_LOCK"

for module in torch torchcodec whisperx demucs xingyu_lyrics_aligner; do
  PATH="$STAGING/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    PYTHONDONTWRITEBYTECODE=1 \
    XINGYU_ALIGNER_FFMPEG="$STAGING/bin/ffmpeg" \
    XINGYU_ALIGNER_FFPROBE="$STAGING/bin/ffprobe" \
    "$RUNTIME_PYTHON" -c "import $module; print('$module import ok')"
done
if find "$STAGING/lib/python3.11/site-packages" -type f \
  \( -name 'libx264*.dylib' -o -name 'libx265*.dylib' -o -name 'libSvtAv1*.dylib' \) | grep -q .; then
  echo "Runtime contains forbidden GPL/extra PyAV codec libraries." >&2
  exit 20
fi
rm -rf "$OUTPUT.new"
mkdir -p "$(dirname "$OUTPUT")"
mv "$STAGING" "$OUTPUT.new"
rm -rf "$OUTPUT"
mv "$OUTPUT.new" "$OUTPUT"
echo "$OUTPUT"
