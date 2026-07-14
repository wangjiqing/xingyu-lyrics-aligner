#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${XINGYU_RUNTIME_OUTPUT:-$ROOT/build/macos-runtime/runtime}"
DERIVED="$ROOT/build/macos-app-derived"
DIST="$ROOT/dist/macos"
APP="$DIST/星语歌词对齐器.app"

[[ -x "$RUNTIME/bin/python3" ]] || "$ROOT/scripts/build-macos-runtime.sh"
rm -rf "$DERIVED" "$APP.new"
xcodebuild \
  -project "$ROOT/apps/macos/XingyuLyricsAligner.xcodeproj" \
  -scheme XingyuLyricsAligner \
  -configuration Release \
  -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  build
mkdir -p "$DIST"
cp -R "$DERIVED/Build/Products/Release/XingyuLyricsAligner.app" "$APP.new"
mkdir -p "$APP.new/Contents/Resources"
cp -R "$RUNTIME" "$APP.new/Contents/Resources/runtime"
cp "$ROOT/LICENSE" "$APP.new/Contents/Resources/runtime/licenses/Project-LICENSE.txt"
cp "$ROOT/docs/third-party-licenses.md" "$APP.new/Contents/Resources/runtime/licenses/THIRD-PARTY-NOTICES.md"
cp "$ROOT/packaging/macos/runtime/model-licenses.md" "$APP.new/Contents/Resources/runtime/licenses/model-licenses.md"
cp "$APP.new/Contents/Resources/runtime/licenses/FFmpeg-LGPL-2.1.txt" "$APP.new/Contents/Resources/runtime/licenses/FFmpeg-LICENSE.txt"
rm -rf "$APP"
mv "$APP.new" "$APP"
"$ROOT/scripts/sign-macos-app.sh" "$APP" --identity "${XINGYU_CODESIGN_IDENTITY:--}"
"$ROOT/scripts/verify-macos-bundle.sh" "$APP"
echo "$APP"
