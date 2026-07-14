#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_APP="${1:-$ROOT/dist/macos/星语歌词对齐器.app}"
SMOKE_ROOT="${XINGYU_SMOKE_ROOT:-/tmp/XingyuLyricsAlignerStandalone}"
APP="$SMOKE_ROOT/星语歌词对齐器.app"
DATA_ROOT="${XINGYU_SMOKE_MODEL_ROOT:-/tmp/Xingyu Phase D1 Fresh}"
RUNTIME="$APP/Contents/Resources/runtime"
PYTHON="$RUNTIME/bin/python3"
JOBS="$SMOKE_ROOT/App Data/Development/Jobs"
MUSIC="$SMOKE_ROOT/App Data/Development/Music"
JOB_ID="standalone-中文-space"
CANCEL="${XINGYU_SMOKE_CANCEL:-0}"

rm -rf "$SMOKE_ROOT"
mkdir -p "$SMOKE_ROOT"
cp -R "$SOURCE_APP" "$APP"
env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=/tmp \
  "$APP/Contents/MacOS/XingyuLyricsAligner" >/tmp/xingyu-standalone-app.log 2>&1 &
APP_PID=$!
sleep 2
kill -0 "$APP_PID"
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true

mkdir -p "$JOBS/$JOB_ID" "$MUSIC/$JOB_ID"
"$RUNTIME/bin/ffmpeg" -hide_banner -loglevel error -f lavfi -i 'sine=frequency=440:duration=3' -ar 16000 -ac 1 "$MUSIC/$JOB_ID/source.wav"
cp "$MUSIC/$JOB_ID/source.wav" "$MUSIC/$JOB_ID/source-original.wav"
for extension in m4a flac; do
  "$RUNTIME/bin/ffmpeg" -hide_banner -loglevel error -i "$MUSIC/$JOB_ID/source-original.wav" "$MUSIC/$JOB_ID/source.$extension"
done
PYTHONHOME="$RUNTIME" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$MUSIC/$JOB_ID/source-original.wav" "$MUSIC/$JOB_ID/source.mp3" <<'PY'
import lameenc, sys, wave
with wave.open(sys.argv[1], "rb") as source:
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(128)
    encoder.set_in_sample_rate(source.getframerate())
    encoder.set_channels(source.getnchannels())
    encoded = encoder.encode(source.readframes(source.getnframes())) + encoder.flush()
open(sys.argv[2], "wb").write(encoded)
PY
for extension in wav mp3 m4a flac; do
  "$RUNTIME/bin/ffprobe" -v error -show_entries format=duration -of default=nw=1:nk=1 "$MUSIC/$JOB_ID/source.$extension" >/dev/null
done

XINGYU_SMOKE_CANCEL="$CANCEL" XINGYU_SMOKE_TRACKS="${XINGYU_SMOKE_TRACKS:-0}" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$JOBS/$JOB_ID" "$MUSIC/$JOB_ID/source.wav" <<'PY'
import json, os, pathlib, sys
job = pathlib.Path(sys.argv[1]); audio = pathlib.Path(sys.argv[2])
tracks = os.environ.get("XINGYU_SMOKE_TRACKS") == "1"
(job / "trusted-lyrics.txt").write_text("星语\n", encoding="utf-8")
request = {
  "schemaVersion": 3, "taskType": "DESKTOP_LYRIC_PROCESSING", "jobId": job.name,
  "audioPath": str(audio), "trustedLyricsPath": str(job / "trusted-lyrics.txt"),
  "outputDir": str(job / "result"), "language": "zh", "device": "cpu",
  "exports": {"lrc": True, "swlrc": True, "vocals": tracks, "accompaniment": tracks,
              "alignmentJson": False, "reportJson": False}
}
(job / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
(job / "READY").touch()
if os.environ.get("XINGYU_SMOKE_CANCEL") == "1":
    (job / "CANCEL_REQUESTED").touch()
PY

MODEL_ALIGNMENT="$DATA_ROOT/Models/Alignment/alignment.zh.whisperx"
MODEL_SEPARATION="$DATA_ROOT/Models/Separation/separation.demucs.htdemucs"
COMMON_ENV=(
  env -i HOME="$HOME" PATH="$RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  PYTHONHOME="$RUNTIME" PYTHONDONTWRITEBYTECODE=1 XINGYU_APP_SUPPORT_DIR="$DATA_ROOT"
  XINGYU_RUNTIME_MANIFEST="$RUNTIME/runtime-manifest.json"
  XINGYU_ALIGNMENT_MODEL_DIR="$MODEL_ALIGNMENT" XINGYU_DEMUCS_MODEL_REPO="$MODEL_SEPARATION"
  XINGYU_ALIGNER_FFMPEG="$RUNTIME/bin/ffmpeg" XINGYU_ALIGNER_FFPROBE="$RUNTIME/bin/ffprobe"
  HF_HOME="$DATA_ROOT/Cache/huggingface"
  HUGGINGFACE_HUB_CACHE="$DATA_ROOT/Cache/huggingface/hub"
  TRANSFORMERS_CACHE="$DATA_ROOT/Cache/huggingface/transformers"
  TORCH_HOME="$DATA_ROOT/Cache/torch" XDG_CACHE_HOME="$DATA_ROOT/Cache"
  NLTK_DATA="$RUNTIME/nltk_data:$DATA_ROOT/Runtime/nltk_data"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
)
"${COMMON_ENV[@]}" "$PYTHON" -m xingyu_lyrics_aligner.cli desktop readiness --data-dir "$DATA_ROOT" --json > "$SMOKE_ROOT/readiness.json"
"${COMMON_ENV[@]}" "$PYTHON" -m xingyu_lyrics_aligner.cli worker run --once --jobs-dir "$JOBS" --music-dir "$MUSIC" --device cpu
XINGYU_SMOKE_CANCEL="$CANCEL" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$JOBS/$JOB_ID/status.json" <<'PY'
import json, os, pathlib, sys
status = json.loads(pathlib.Path(sys.argv[1]).read_text())
if os.environ.get("XINGYU_SMOKE_CANCEL") == "1":
    assert status["state"] == "CANCELLED", status
    raise SystemExit
assert status["state"] in {"SUCCEEDED", "NEEDS_REVIEW"}, status
kinds = {item["kind"] for item in status["result"]["artifacts"]}
assert {"LRC", "SWLRC"} <= kinds, status
if os.environ.get("XINGYU_SMOKE_TRACKS") == "1":
    assert {"VOCALS", "ACCOMPANIMENT"} <= kinds, status
    assert pathlib.Path(status["result"]["files"]["vocals"]).stat().st_size > 44
    assert pathlib.Path(status["result"]["files"]["accompaniment"]).stat().st_size > 44
PY
if grep -RIl "$ROOT/.venv" "$SMOKE_ROOT" | grep -q .; then
  echo "Standalone smoke output references repository .venv." >&2
  exit 20
fi
if pgrep -f "$RUNTIME/bin/python3" >/dev/null 2>&1; then
  echo "Standalone smoke left a bundled Python child process running." >&2
  exit 21
fi
echo "Standalone smoke passed: $APP"
