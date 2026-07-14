#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/macos/星语歌词对齐器.app"
VERSION="0.7.0"
VOLUME="星语歌词对齐器 $VERSION"
DMG="${XINGYU_DMG_OUTPUT:-$ROOT/dist/macos/星语歌词对齐器-$VERSION-arm64-unsigned.dmg}"
RELEASE_MANIFEST="${XINGYU_RELEASE_MANIFEST_OUTPUT:-$ROOT/dist/macos/release-manifest.json}"
APP_SHA_FILE="$ROOT/dist/macos/星语歌词对齐器.app.sha256"
RELEASE_MANIFEST_SHA_FILE="$RELEASE_MANIFEST.sha256"
OVERWRITE=0
REQUIRE_LAYOUT=1
for argument in "$@"; do
  case "$argument" in
    --overwrite) OVERWRITE=1 ;;
    --require-finder-layout) REQUIRE_LAYOUT=1 ;;
    --allow-missing-finder-layout) REQUIRE_LAYOUT=0 ;;
    *) echo "Usage: $0 [--overwrite] [--require-finder-layout|--allow-missing-finder-layout]" >&2; exit 2 ;;
  esac
done
[[ -d "$APP" ]] || { echo "Release App not found: $APP" >&2; exit 3; }
mkdir -p "$(dirname "$DMG")" "$(dirname "$RELEASE_MANIFEST")"
if [[ -e "$DMG" && $OVERWRITE -ne 1 ]]; then
  echo "DMG already exists; pass --overwrite to replace it: $DMG" >&2
  exit 4
fi
"$ROOT/scripts/verify-macos-bundle.sh" "$APP"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/xingyu-dmg.XXXXXX")"
STAGE="$WORK/stage"
RW_DMG="$WORK/release-rw.dmg"
MOUNT="$WORK/mount"
VERIFY_MOUNT="$WORK/verify-mount"
cleanup() {
  hdiutil detach "$MOUNT" -force >/dev/null 2>&1 || true
  hdiutil detach "$VERIFY_MOUNT" -force >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM
mkdir -p "$STAGE/Licenses" "$MOUNT"
ditto "$APP" "$STAGE/星语歌词对齐器.app"
ln -s /Applications "$STAGE/Applications"
cp "$ROOT/packaging/macos/安装说明.txt" "$STAGE/安装说明.txt"
cp -R "$APP/Contents/Resources/runtime/licenses/." "$STAGE/Licenses/"

rm -f "$RW_DMG"
hdiutil create -quiet -fs HFS+ -format UDRW -volname "$VOLUME" -srcfolder "$STAGE" "$RW_DMG"
hdiutil attach -quiet -nobrowse -readwrite -mountpoint "$MOUNT" "$RW_DMG"
LAYOUT_LOG="$WORK/finder-layout.log"
if [[ "${XINGYU_TEST_FINDER_LAYOUT_FAILURE:-0}" == 1 ]]; then
  (exit 42) >"$LAYOUT_LOG" 2>&1 &
else
  osascript >"$LAYOUT_LOG" 2>&1 <<OSA &
tell application "Finder"
  set dmgFolder to POSIX file "$MOUNT" as alias
  open dmgFolder
  set dmgWindow to container window of dmgFolder
  set current view of dmgWindow to icon view
  set toolbar visible of dmgWindow to false
  set statusbar visible of dmgWindow to false
  set bounds of dmgWindow to {180, 180, 820, 600}
  set arrangement of icon view options of dmgWindow to not arranged
  set icon size of icon view options of dmgWindow to 96
  set position of item "星语歌词对齐器.app" of dmgFolder to {170, 170}
  set position of item "Applications" of dmgFolder to {470, 170}
  set position of item "安装说明.txt" of dmgFolder to {170, 340}
  set position of item "Licenses" of dmgFolder to {470, 340}
  update dmgFolder without registering applications
  delay 2
  close dmgWindow
end tell
OSA
fi
LAYOUT_PID=$!
LAYOUT_STATUS=0
for _ in $(seq 1 15); do
  kill -0 "$LAYOUT_PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$LAYOUT_PID" 2>/dev/null; then
  kill "$LAYOUT_PID" 2>/dev/null || true
  wait "$LAYOUT_PID" 2>/dev/null || true
  LAYOUT_STATUS=124
else
  wait "$LAYOUT_PID" || LAYOUT_STATUS=$?
fi
if [[ $LAYOUT_STATUS -eq 0 ]]; then
  echo "DMG Finder icon layout recorded."
else
  cat "$LAYOUT_LOG" >&2
  if [[ $REQUIRE_LAYOUT -eq 1 ]]; then
    echo "Finder layout is required; refusing to publish this candidate." >&2
    exit 5
  fi
  echo "Warning: Finder layout was not applied; explicit fallback mode requires human review." >&2
fi
sync
hdiutil detach -quiet "$MOUNT"
TEMP_DMG="$WORK/candidate.dmg"
hdiutil convert -quiet "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$TEMP_DMG"
hdiutil verify "$TEMP_DMG"
mkdir -p "$VERIFY_MOUNT"
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$VERIFY_MOUNT" "$TEMP_DMG"
[[ -d "$VERIFY_MOUNT/星语歌词对齐器.app" && -L "$VERIFY_MOUNT/Applications" && -f "$VERIFY_MOUNT/安装说明.txt" && -d "$VERIFY_MOUNT/Licenses" ]] || {
  echo "DMG mounted contents are incomplete." >&2; exit 6;
}
hdiutil detach -quiet "$VERIFY_MOUNT"

SHA="$(shasum -a 256 "$TEMP_DMG" | awk '{print $1}')"
TEMP_SHA="$WORK/candidate.sha256"
printf '%s  %s\n' "$SHA" "$(basename "$DMG")" > "$TEMP_SHA"
read -r APP_BYTES APP_SHA < <(python3 - "$APP" <<'PY'
import hashlib, os, pathlib, stat, sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
size = 0
for path in sorted(root.rglob("*"), key=lambda value: str(value.relative_to(root))):
    relative = str(path.relative_to(root)).encode("utf-8")
    metadata = path.lstat()
    if stat.S_ISDIR(metadata.st_mode):
        kind, content = b"D", b""
    elif stat.S_ISLNK(metadata.st_mode):
        kind, content = b"L", os.readlink(path).encode("utf-8")
    elif stat.S_ISREG(metadata.st_mode):
        kind, content = b"F", hashlib.sha256(path.read_bytes()).digest()
        size += metadata.st_size
    else:
        raise SystemExit(f"Unsupported App entry: {path}")
    digest.update(kind + b"\0" + relative + b"\0" + content + b"\n")
print(size, digest.hexdigest())
PY
)
DMG_BYTES="$(stat -f %z "$TEMP_DMG")"
RUNTIME_MANIFEST="$APP/Contents/Resources/runtime/runtime-manifest.json"
RUNTIME_SHA="$(shasum -a 256 "$RUNTIME_MANIFEST" | awk '{print $1}')"
WHEELHOUSE_MANIFEST="$ROOT/packaging/macos/runtime/wheelhouse-manifest.json"
WHEELHOUSE_SHA="$(shasum -a 256 "$WHEELHOUSE_MANIFEST" | awk '{print $1}')"
ENGINE_VERSION="$(plutil -extract packageVersion raw "$RUNTIME_MANIFEST")"
BUILT_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
TEMP_RELEASE_MANIFEST="$WORK/release-manifest.json"
cat > "$TEMP_RELEASE_MANIFEST" <<JSON
{
  "schemaVersion": 1,
  "appVersion": "0.7.0",
  "engineVersion": "$ENGINE_VERSION",
  "pythonPackageVersion": "$ENGINE_VERSION",
  "runtimeVersion": "v1",
  "architecture": "arm64",
  "minimumMacOS": "14.0",
  "buildNumber": "1",
  "developerIdSigned": false,
  "signatureType": "ADHOC",
  "notarized": false,
  "gatekeeperTrusted": false,
  "modelsBundled": false,
  "finderLayoutApplied": $([[ $LAYOUT_STATUS -eq 0 ]] && echo true || echo false),
  "appSizeBytes": $APP_BYTES,
  "dmgSizeBytes": $DMG_BYTES,
  "appSha256": "$APP_SHA",
  "dmgSha256": "$SHA",
  "runtimeManifestSha256": "$RUNTIME_SHA",
  "wheelhouseManifestSha256": "$WHEELHOUSE_SHA",
  "builtAt": "$BUILT_AT"
}
JSON
TEMP_APP_SHA="$WORK/app.sha256"
printf '%s  %s (canonical tree SHA-256)\n' "$APP_SHA" "$(basename "$APP")" > "$TEMP_APP_SHA"
TEMP_RELEASE_SHA="$WORK/release-manifest.sha256"
RELEASE_SHA="$(shasum -a 256 "$TEMP_RELEASE_MANIFEST" | awk '{print $1}')"
printf '%s  %s\n' "$RELEASE_SHA" "$(basename "$RELEASE_MANIFEST")" > "$TEMP_RELEASE_SHA"
if [[ -e "$DMG" && $OVERWRITE -ne 1 ]]; then exit 4; fi
mv -f "$TEMP_DMG" "$DMG"
mv -f "$TEMP_SHA" "$DMG.sha256"
mv -f "$TEMP_RELEASE_MANIFEST" "$RELEASE_MANIFEST"
mv -f "$TEMP_APP_SHA" "$APP_SHA_FILE"
mv -f "$TEMP_RELEASE_SHA" "$RELEASE_MANIFEST_SHA_FILE"
echo "DMG: $DMG"
echo "Size: $DMG_BYTES bytes"
echo "SHA-256: $SHA"
