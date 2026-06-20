from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WhisperX Chinese alignment spike for trusted lyrics text."
    )
    parser.add_argument("--audio", type=Path, default=Path("sample_input/sample.wav"))
    parser.add_argument("--lyrics", type=Path, default=Path("sample_input/sample_lyrics.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("sample_output"))
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--asr-model", default="tiny")
    parser.add_argument("--align-model", default=DEFAULT_ALIGN_MODEL)
    parser.add_argument("--skip-asr", action="store_true")
    parser.add_argument("--model-cache-only", action="store_true")
    return parser.parse_args()


def read_lyrics(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_lrc_time(seconds: float | None) -> str:
    if seconds is None:
        seconds = 0.0
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:05.2f}"


def normalize_segments(
    segments: list[dict[str, Any]],
    lyrics_lines: list[str],
    audio_path: Path,
    language: str,
    engine: str,
    warnings: list[str],
) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    for index, text in enumerate(lyrics_lines):
        segment = segments[index] if index < len(segments) else {}
        chars = segment.get("chars") or []
        words = segment.get("words") or []
        tokens: list[dict[str, Any]] = []
        if chars:
            for char in chars:
                token_text = char.get("char", "")
                if token_text.strip():
                    tokens.append(
                        {
                            "text": token_text,
                            "start": char.get("start"),
                            "end": char.get("end"),
                            "confidence": char.get("score"),
                        }
                    )
        elif words:
            for word in words:
                tokens.append(
                    {
                        "text": word.get("word", ""),
                        "start": word.get("start"),
                        "end": word.get("end"),
                        "confidence": word.get("score"),
                    }
                )
        status = "aligned"
        if segment.get("start") is None or segment.get("end") is None:
            status = "missing_time"
        if not tokens:
            status = "missing_tokens"
        lines.append(
            {
                "index": index,
                "text": text,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "status": status,
                "tokens": tokens,
            }
        )
    if len(segments) != len(lyrics_lines):
        warnings.append(
            "Aligned segment count "
            f"{len(segments)} differs from lyric line count {len(lyrics_lines)}."
        )
    return {
        "source": {
            "audio": str(audio_path),
            "language": language,
            "alignment_engine": engine,
        },
        "lines": lines,
        "warnings": warnings,
    }


def write_lrc(path: Path, normalized: dict[str, Any]) -> None:
    rows = []
    for line in normalized["lines"]:
        if line["start"] is not None:
            rows.append(f"[{format_lrc_time(line['start'])}]{line['text']}")
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def proportional_segments(lyrics_lines: list[str], duration: float) -> list[dict[str, Any]]:
    char_counts = [max(len(line), 1) for line in lyrics_lines]
    total = sum(char_counts)
    cursor = 0.0
    segments = []
    for index, (line, count) in enumerate(zip(lyrics_lines, char_counts, strict=True)):
        seg_duration = duration * count / total
        start = cursor
        end = duration if index == len(lyrics_lines) - 1 else cursor + seg_duration
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": line})
        cursor = end
    return segments


def trusted_segments_from_asr(
    lyrics_lines: list[str], asr_segments: list[dict[str, Any]], duration: float
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if len(asr_segments) >= len(lyrics_lines):
        segments = []
        for index, line in enumerate(lyrics_lines):
            base = asr_segments[index]
            segments.append(
                {
                    "start": float(base["start"]),
                    "end": float(base["end"]),
                    "text": line,
                    "asr_text_replaced": base.get("text", ""),
                }
            )
        if len(asr_segments) != len(lyrics_lines):
            warnings.append(
                "ASR produced extra segments; trusted-lyrics path used the first "
                "lyric-line count only."
            )
        return segments, warnings
    warnings.append(
        "ASR did not produce enough segments; trusted-lyrics path fell back to "
        "proportional windows."
    )
    return proportional_segments(lyrics_lines, duration), warnings


def run() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent
    audio_path = (root / args.audio).resolve() if not args.audio.is_absolute() else args.audio
    lyrics_path = (root / args.lyrics).resolve() if not args.lyrics.is_absolute() else args.lyrics
    output_dir = (
        (root / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    import torch
    import whisperx

    lyrics_lines = read_lyrics(lyrics_path)
    audio = whisperx.load_audio(str(audio_path))
    duration = len(audio) / 16000.0
    warnings: list[str] = []

    env_info: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "ffmpeg": shutil.which("ffmpeg"),
        "torch": torch.__version__,
        "torch_cuda_available": torch.cuda.is_available(),
        "torch_mps_available": bool(getattr(torch.backends, "mps", None))
        and torch.backends.mps.is_available(),
        "whisperx": getattr(whisperx, "__version__", "unknown"),
        "requested_device": args.device,
        "compute_type": args.compute_type,
    }

    asr_result: dict[str, Any] = {"segments": [], "language": args.language}
    if not args.skip_asr:
        model = whisperx.load_model(
            args.asr_model,
            args.device,
            language=args.language,
            compute_type=args.compute_type,
        )
        asr_result = model.transcribe(audio, batch_size=4, language=args.language)
        del model
        if args.device == "cuda":
            torch.cuda.empty_cache()

    model_a, metadata = whisperx.load_align_model(
        language_code=args.language,
        device=args.device,
        model_name=args.align_model,
        model_cache_only=args.model_cache_only,
    )

    path_a: dict[str, Any] | None = None
    if asr_result.get("segments"):
        path_a = whisperx.align(
            asr_result["segments"],
            model_a,
            metadata,
            audio,
            args.device,
            return_char_alignments=True,
        )

    trusted_segments, segment_warnings = trusted_segments_from_asr(
        lyrics_lines, asr_result.get("segments", []), duration
    )
    warnings.extend(segment_warnings)
    path_b = whisperx.align(
        trusted_segments,
        model_a,
        metadata,
        audio,
        args.device,
        return_char_alignments=True,
    )

    raw = {
        "environment": env_info,
        "input": {
            "audio": str(audio_path),
            "lyrics": str(lyrics_path),
            "duration_seconds": duration,
            "lyrics_lines": lyrics_lines,
        },
        "path_a_asr_then_alignment": path_a,
        "path_b_trusted_lyrics_segments": {
            "input_segments": trusted_segments,
            "alignment": path_b,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    normalized = normalize_segments(
        path_b["segments"],
        lyrics_lines,
        audio_path,
        args.language,
        "whisperx",
        warnings,
    )
    write_json(output_dir / "alignment.raw.json", raw)
    write_json(output_dir / "alignment.normalized.json", normalized)
    write_lrc(output_dir / "sample.lrc", normalized)
    write_report(output_dir / "report.md", raw, normalized, args)
    return 0


def write_report(
    path: Path, raw: dict[str, Any], normalized: dict[str, Any], args: argparse.Namespace
) -> None:
    env = raw["environment"]
    aligned = sum(1 for line in normalized["lines"] if line["status"] == "aligned")
    token_count = sum(len(line["tokens"]) for line in normalized["lines"])
    lines = [
        "# WhisperX Chinese Alignment Spike Report",
        "",
        "## Environment",
        "",
        f"- Python: `{env['python'].split()[0]}`",
        f"- Platform: `{env['platform']}` / `{env['machine']}`",
        f"- FFmpeg: `{env['ffmpeg']}`",
        f"- torch: `{env['torch']}`",
        f"- whisperx: `{env['whisperx']}`",
        f"- Requested device: `{env['requested_device']}`",
        f"- CUDA available: `{env['torch_cuda_available']}`",
        f"- MPS available: `{env['torch_mps_available']}`",
        "",
        "## Commands",
        "",
        "```bash",
        "python -m venv .venv",
        "source .venv/bin/activate",
        "python -m pip install -r requirements.txt",
        (
            "python run_spike.py --audio sample_input/sample.wav "
            f"--lyrics sample_input/sample_lyrics.txt --device {args.device} "
            f"--compute-type {args.compute_type} --language {args.language}"
            + (" --skip-asr" if args.skip_asr else "")
            + (" --model-cache-only" if args.model_cache_only else "")
        ),
        "```",
        "",
        "## Model",
        "",
        f"- Alignment model: `{args.align_model}`",
        "- Source: Hugging Face model used by WhisperX for `zh` alignment.",
        "- License: Apache-2.0 for the Chinese wav2vec2 model; WhisperX is BSD-2-Clause.",
        "",
        "## Results",
        "",
        f"- Audio duration: `{raw['input']['duration_seconds']:.2f}s`",
        "- Path A ASR segments: "
        f"`{len((raw['path_a_asr_then_alignment'] or {}).get('segments', []))}`",
        f"- Path B trusted lyric lines aligned: `{aligned}/{len(normalized['lines'])}`",
        f"- Path B token count: `{token_count}`",
        f"- Elapsed: `{raw['elapsed_seconds']}s`",
        "",
        "## Sample LRC",
        "",
        "```lrc",
    ]
    for line in normalized["lines"]:
        if line["start"] is not None:
            lines.append(f"[{format_lrc_time(line['start'])}]{line['text']}")
    lines.extend(
        [
            "```",
            "",
            "## Warnings",
            "",
        ]
    )
    lines.extend([f"- {warning}" for warning in normalized["warnings"]] or ["- None from script."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(run())
