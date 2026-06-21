from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"

NOISE_CHARS = set(
    ",.?¿!¡;:\"'‘’“”%~`_+<>=…–—-，。！？、；：（）()[]【】《》〈〉「」『』♪♫♬·・‧～〜〽\\/|^*@#$&"
)


@dataclass(frozen=True)
class TokenSpec:
    text: str
    alignment_text: str
    alignment_length: int


@dataclass(frozen=True)
class LineSpec:
    index: int
    text: str
    alignment_text: str
    tokens: list[TokenSpec]


@dataclass(frozen=True)
class SectionSpec:
    id: str
    audio_start: float
    audio_end: float
    line_start: int
    line_end: int
    kind: str


@dataclass(frozen=True)
class AlignComponents:
    device: str
    align_model: Any
    metadata: Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Direct trusted Chinese lyrics CTC alignment spike."
    )
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--compute-type", default="float32")
    parser.add_argument("--align-model", default=DEFAULT_ALIGN_MODEL)
    parser.add_argument("--model-cache-only", action="store_true")
    parser.add_argument("--foreground-voice-switch-lines", default="")
    parser.add_argument("--section-manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_lyrics(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def clean_alignment_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    chars: list[str] = []
    for char in normalized:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if char in NOISE_CHARS or category.startswith(("P", "S")):
            continue
        chars.append(char)
    return "".join(chars)


def tokenize_display_text(text: str) -> list[str]:
    try:
        import jieba

        return [token for token in jieba.lcut(text, cut_all=False) if token]
    except Exception:
        return [char for char in text if not char.isspace()]


def build_line_specs(lines: list[str]) -> list[LineSpec]:
    specs = []
    for index, line in enumerate(lines):
        tokens = []
        for token in tokenize_display_text(line):
            alignment_text = clean_alignment_text(token)
            tokens.append(
                TokenSpec(
                    text=token,
                    alignment_text=alignment_text,
                    alignment_length=len(alignment_text),
                )
            )
        specs.append(
            LineSpec(
                index=index,
                text=line,
                alignment_text="".join(token.alignment_text for token in tokens),
                tokens=tokens,
            )
        )
    return specs


def parse_line_set(spec: str) -> set[int]:
    out: set[int] = set()
    if not spec.strip():
        return out
    for part in spec.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            start = int(left)
            end = int(right)
            for value in range(start, end + 1):
                out.add(value - 1)
        else:
            out.add(int(item) - 1)
    return out


def load_section_manifest(
    path: Path,
    line_count: int,
    duration: float | None = None,
) -> list[SectionSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("section manifest version must be 1")
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("section manifest must contain at least one section")

    sections: list[SectionSpec] = []
    previous_line_end = 0
    previous_audio_end = 0.0
    seen_ids: set[str] = set()
    for raw in raw_sections:
        if not isinstance(raw, dict):
            raise ValueError("section manifest sections must be objects")
        section_id = str(raw.get("id", "")).strip()
        if not section_id:
            raise ValueError("section id is required")
        if section_id in seen_ids:
            raise ValueError(f"duplicate section id: {section_id}")
        seen_ids.add(section_id)

        section = SectionSpec(
            id=section_id,
            audio_start=float(raw["audio_start"]),
            audio_end=float(raw["audio_end"]),
            line_start=int(raw["line_start"]),
            line_end=int(raw["line_end"]),
            kind=str(raw.get("kind", "singing")),
        )
        if section.audio_start < 0 or section.audio_end <= section.audio_start:
            raise ValueError(f"invalid audio range for section {section.id}")
        if duration is not None and section.audio_end > duration + 0.25:
            raise ValueError(f"section {section.id} exceeds audio duration")
        if section.audio_start + 0.25 < previous_audio_end:
            raise ValueError(f"section {section.id} overlaps previous audio range too much")
        if section.line_start != previous_line_end:
            raise ValueError(
                "section lyric ranges must be contiguous, 0-based, and line_end-exclusive"
            )
        if section.line_end <= section.line_start or section.line_end > line_count:
            raise ValueError(f"invalid lyric line range for section {section.id}")
        sections.append(section)
        previous_line_end = section.line_end
        previous_audio_end = section.audio_end

    if previous_line_end != line_count:
        raise ValueError("section lyric ranges must cover every lyric line exactly once")
    return sections


def align_device_for(device: str) -> str:
    return "cpu" if device == "mps" else device


def load_audio_duration(audio_path: Path) -> tuple[Any, float]:
    import whisperx

    audio = whisperx.load_audio(str(audio_path))
    return audio, len(audio) / 16000.0


def load_align_components(args: argparse.Namespace) -> AlignComponents:
    import whisperx

    device = align_device_for(args.device)
    align_model, metadata = whisperx.load_align_model(
        language_code=args.language,
        device=device,
        model_name=args.align_model,
        model_cache_only=args.model_cache_only,
    )
    return AlignComponents(device=device, align_model=align_model, metadata=metadata)


def run_whisperx_alignment(
    alignment_text: str,
    audio: Any,
    audio_start: float,
    audio_end: float,
    components: AlignComponents,
) -> dict[str, Any]:
    import whisperx

    raw_segments = [
        {
            "text": alignment_text,
            "start": audio_start,
            "end": audio_end,
        }
    ]
    result = whisperx.align(
        raw_segments,
        components.align_model,
        components.metadata,
        audio,
        components.device,
        return_char_alignments=True,
    )
    return {
        "raw_segments": raw_segments,
        "alignment": result,
    }


def collect_char_entries(align_result: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for segment in align_result.get("segments", []):
        if segment.get("chars"):
            for char in segment.get("chars", []):
                text = char.get("char", "")
                if text:
                    entries.append(
                        {
                            "text": text,
                            "start": char.get("start"),
                            "end": char.get("end"),
                            "score": char.get("score"),
                        }
                    )
            continue
        for word in segment.get("words", []):
            text = word.get("word", "")
            if text:
                entries.append(
                    {
                        "text": text,
                        "start": word.get("start"),
                        "end": word.get("end"),
                        "score": word.get("score"),
                    }
                )
    return entries


def token_from_chars(token: TokenSpec, chars: list[dict[str, Any]]) -> dict[str, Any]:
    timed = [
        char for char in chars if char.get("start") is not None and char.get("end") is not None
    ]
    token_out: dict[str, Any] = {
        "text": token.text,
        "alignment_text": token.alignment_text,
        "alignment_length": token.alignment_length,
        "start": None,
        "end": None,
        "estimated": False,
        "missing_characters": max(0, token.alignment_length - len(timed)),
    }
    if timed:
        token_out["start"] = timed[0]["start"]
        token_out["end"] = timed[-1]["end"]
        scores = [char.get("score") for char in timed if char.get("score") is not None]
        if scores:
            token_out["confidence"] = round(sum(scores) / len(scores), 4)
    elif token.alignment_length > 0:
        token_out["estimated"] = True
    return token_out


def backfill_lines(
    line_specs: list[LineSpec],
    char_entries: list[dict[str, Any]],
    foreground_switch_lines: set[int],
    section_id: str | None = None,
    section_kind: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    lines_out: list[dict[str, Any]] = []
    warnings: list[str] = []
    cursor = 0
    previous_end: float | None = None

    for spec in line_specs:
        line_length = len(spec.alignment_text)
        line_chars = char_entries[cursor : cursor + line_length]
        cursor += len(line_chars)

        token_outputs = []
        token_cursor = 0
        for token in spec.tokens:
            n = token.alignment_length
            token_chars = line_chars[token_cursor : token_cursor + n]
            token_cursor += len(token_chars)
            token_outputs.append(token_from_chars(token, token_chars))

        timed_tokens = [
            token
            for token in token_outputs
            if token.get("start") is not None and token.get("end") is not None
        ]
        line_warnings = []
        status = "aligned"

        missing_chars = sum(
            1 for char in line_chars if char.get("start") is None or char.get("end") is None
        )
        if missing_chars:
            line_warnings.append("missing_character_timestamps")

        if len(line_chars) != line_length:
            line_warnings.append("character_count_mismatch")

        if spec.index in foreground_switch_lines:
            line_warnings.append("foreground_voice_switch")

        if not timed_tokens:
            status = "unmatched" if line_length == 0 else "missing_timestamps"
            line_warnings.append("line_without_timing")
            start = None
            end = None
        else:
            start = timed_tokens[0]["start"]
            end = timed_tokens[-1]["end"]
            if missing_chars:
                status = "partial"
            if previous_end is not None and start is not None and start < previous_end:
                line_warnings.append("timing_non_monotonic")
                warnings.append(f"line_{spec.index}_timing_non_monotonic")
                status = "manual_review_required"
            if end is not None:
                previous_end = max(previous_end or end, end)

        line_out = {
            "index": spec.index,
            "text": spec.text,
            "alignment_text": spec.alignment_text,
            "start": start,
            "end": end,
            "status": status,
            "warnings": line_warnings,
            "tokens": token_outputs,
        }
        if section_id is not None:
            line_out["section_id"] = section_id
        if section_kind is not None:
            line_out["section_kind"] = section_kind
        lines_out.append(line_out)

    if cursor != len(char_entries):
        warnings.append("character_count_mismatch")
    return lines_out, warnings


def format_lrc_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    rest = seconds - (minutes * 60)
    return f"{minutes:02d}:{rest:05.2f}"


def write_lrc(path: Path, lines: list[dict[str, Any]]) -> None:
    rows = []
    for line in lines:
        if line.get("start") is not None:
            rows.append(f"[{format_lrc_time(float(line['start']))}]{line['text']}")
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def count_non_monotonic(lines: list[dict[str, Any]]) -> int:
    count = 0
    previous = None
    for line in lines:
        start = line.get("start")
        if start is None:
            continue
        if previous is not None and start < previous:
            count += 1
        previous = max(previous if previous is not None else start, line.get("end") or start)
    return count


def build_summary(
    audio_path: Path,
    lyrics_path: Path,
    duration: float,
    args: argparse.Namespace,
    line_specs: list[LineSpec],
    char_entries: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    elapsed: float,
    global_warnings: list[str],
    alignment_mode: str = "global",
    sections: list[SectionSpec] | None = None,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for line in lines:
        status = str(line["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    input_chars = sum(len(line.alignment_text) for line in line_specs)
    timed_chars = sum(
        1 for char in char_entries if char.get("start") is not None and char.get("end") is not None
    )
    missing_chars = max(0, input_chars - timed_chars)
    aligned_lines = sum(1 for line in lines if line["status"] in {"aligned", "partial"})
    duration_review_line_indices = []
    for line in lines:
        start = line.get("start")
        end = line.get("end")
        if start is None or end is None:
            continue
        line_duration = float(end) - float(start)
        alignment_chars = max(len(str(line.get("alignment_text", ""))), 1)
        if line_duration > 12.0 or line_duration / alignment_chars > 1.2:
            duration_review_line_indices.append(line["index"])
    return {
        "source": {
            "audio_basename": audio_path.name,
            "lyrics_basename": lyrics_path.name,
            "language": args.language,
            "alignment_engine": "whisperx",
            "alignment_model": args.align_model,
            "device_requested": args.device,
            "device_used": align_device_for(args.device),
            "compute_type": args.compute_type,
        },
        "duration_seconds": round(duration, 3),
        "line_count": len(lines),
        "aligned_or_partial_lines": aligned_lines,
        "line_coverage": round(aligned_lines / max(len(lines), 1), 4),
        "status_counts": status_counts,
        "input_alignment_characters": input_chars,
        "output_character_entries": len(char_entries),
        "timed_character_entries": timed_chars,
        "missing_character_timestamps": missing_chars,
        "character_coverage": round(timed_chars / max(input_chars, 1), 4),
        "character_count_matches": input_chars == len(char_entries),
        "non_monotonic_line_count": count_non_monotonic(lines),
        "alignment_mode": alignment_mode,
        "section_count": len(sections or []),
        "section_ids": [section.id for section in sections or []],
        "manual_review_line_indices": [
            line["index"]
            for line in lines
            if line["status"]
            in {"partial", "missing_timestamps", "manual_review_required", "unmatched"}
            or line["warnings"]
        ],
        "duration_review_line_indices": duration_review_line_indices,
        "warnings": global_warnings,
        "elapsed_seconds": round(elapsed, 3),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    report = [
        "# Direct Trusted Lyrics CTC Alignment Local Report",
        "",
        "This report is local validation output. Do not commit it if it was generated "
        "from real songs.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Interpretation Checklist",
        "",
        "- Compare line timings against playback manually; monotonic LRC is not enough.",
        "- Check repeated chorus ordering.",
        "- Check foreground voice switch lines.",
        "- Check lines listed in `manual_review_line_indices`.",
    ]
    path.write_text("\n".join(report) + "\n", encoding="utf-8")


def write_section_report(path: Path, summary: dict[str, Any]) -> None:
    report = [
        "# Sectional CTC Alignment Local Report",
        "",
        "This report is local validation output. Do not commit it if it was generated "
        "from real songs.",
        "",
        "## Aggregate Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| alignment_mode | {summary.get('alignment_mode')} |",
        f"| line_count | {summary.get('line_count')} |",
        f"| aligned_or_partial_lines | {summary.get('aligned_or_partial_lines')} |",
        f"| input_alignment_characters | {summary.get('input_alignment_characters')} |",
        f"| timed_character_entries | {summary.get('timed_character_entries')} |",
        f"| missing_character_timestamps | {summary.get('missing_character_timestamps')} |",
        f"| non_monotonic_line_count | {summary.get('non_monotonic_line_count')} |",
        f"| section_count | {summary.get('section_count')} |",
        "",
        "## Manual Listening Table",
        "",
        "| Checkpoint | Global CTC | Sectional CTC | Notes |",
        "| --- | --- | --- | --- |",
        "| first lines | pending | pending | accurate / slightly early / slightly late |",
        "| before phone section | pending | pending |  |",
        "| phone section | pending | pending |  |",
        "| first singing after phone | pending | pending |  |",
        "| ending | pending | pending |  |",
        "",
        "Do not treat complete character coverage or monotonic LRC as sufficient quality.",
    ]
    path.write_text("\n".join(report) + "\n", encoding="utf-8")


def inspect_environment(args: argparse.Namespace) -> dict[str, Any]:
    env: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "ffmpeg": shutil.which("ffmpeg"),
    }
    try:
        import torch
        import whisperx

        env.update(
            {
                "torch": torch.__version__,
                "whisperx": getattr(whisperx, "__version__", "unknown"),
                "cuda_available": torch.cuda.is_available(),
                "mps_available": bool(getattr(torch.backends, "mps", None))
                and torch.backends.mps.is_available(),
                "device_requested": args.device,
                "device_used": align_device_for(args.device),
            }
        )
    except Exception as exc:
        env["import_error"] = str(exc)
    return env


def align_global(
    full_alignment_text: str,
    audio: Any,
    duration: float,
    components: AlignComponents,
    line_specs: list[LineSpec],
    foreground_switch_lines: set[int],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], dict[str, Any]]:
    alignment_payload = run_whisperx_alignment(
        full_alignment_text,
        audio,
        0.0,
        duration,
        components,
    )
    char_entries = collect_char_entries(alignment_payload["alignment"])
    lines, global_warnings = backfill_lines(line_specs, char_entries, foreground_switch_lines)
    raw = {
        "raw_segments": alignment_payload["raw_segments"],
        "alignment": alignment_payload["alignment"],
    }
    return lines, global_warnings, char_entries, raw


def align_sections(
    sections: list[SectionSpec],
    audio: Any,
    components: AlignComponents,
    line_specs: list[LineSpec],
    foreground_switch_lines: set[int],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], dict[str, Any]]:
    all_lines: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    all_chars: list[dict[str, Any]] = []
    raw_sections: list[dict[str, Any]] = []

    for section in sections:
        section_specs = line_specs[section.line_start : section.line_end]
        section_text = "".join(line.alignment_text for line in section_specs)
        section_payload = run_whisperx_alignment(
            section_text,
            audio,
            section.audio_start,
            section.audio_end,
            components,
        )
        section_chars = collect_char_entries(section_payload["alignment"])
        section_foreground_lines = set(foreground_switch_lines)
        if section.kind == "foreground_voice_switch":
            section_foreground_lines.update(range(section.line_start, section.line_end))
        section_lines, section_warnings = backfill_lines(
            section_specs,
            section_chars,
            section_foreground_lines,
            section_id=section.id,
            section_kind=section.kind,
        )
        all_lines.extend(section_lines)
        all_chars.extend(section_chars)
        for warning in section_warnings:
            all_warnings.append(f"{section.id}:{warning}")
        raw_sections.append(
            {
                "id": section.id,
                "kind": section.kind,
                "audio_start": section.audio_start,
                "audio_end": section.audio_end,
                "line_start": section.line_start,
                "line_end": section.line_end,
                "raw_segments": section_payload["raw_segments"],
                "alignment": section_payload["alignment"],
                "character_entries": section_chars,
            }
        )

    all_lines.sort(key=lambda line: line["index"])
    return all_lines, all_warnings, all_chars, {"sections": raw_sections}


def run() -> int:
    started = time.perf_counter()
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    lyrics = read_lyrics(args.lyrics)
    line_specs = build_line_specs(lyrics)
    full_alignment_text = "".join(line.alignment_text for line in line_specs)
    foreground_switch_lines = parse_line_set(args.foreground_voice_switch_lines)

    env = inspect_environment(args)
    if args.dry_run:
        write_json(
            output_dir / "summary.json",
            {
                "environment": env,
                "line_count": len(line_specs),
                "input_alignment_characters": len(full_alignment_text),
                "dry_run": True,
            },
        )
        return 0

    audio, duration = load_audio_duration(args.audio)
    sections = (
        load_section_manifest(args.section_manifest, len(line_specs), duration)
        if args.section_manifest
        else None
    )
    components = load_align_components(args)
    if sections:
        lines, global_warnings, char_entries, raw_alignment = align_sections(
            sections,
            audio,
            components,
            line_specs,
            foreground_switch_lines,
        )
        alignment_mode = "sectional"
    else:
        lines, global_warnings, char_entries, raw_alignment = align_global(
            full_alignment_text,
            audio,
            duration,
            components,
            line_specs,
            foreground_switch_lines,
        )
        alignment_mode = "global"

    if components.device == "cuda":
        import torch

        torch.cuda.empty_cache()

    normalized = {
        "source": {
            "audio": str(args.audio),
            "lyrics": str(args.lyrics),
            "language": args.language,
            "alignment_engine": "whisperx",
            "alignment_model": args.align_model,
            "alignment_mode": alignment_mode,
            "section_manifest": str(args.section_manifest) if args.section_manifest else None,
        },
        "lines": lines,
        "warnings": global_warnings,
    }
    summary = build_summary(
        args.audio,
        args.lyrics,
        duration,
        args,
        line_specs,
        char_entries,
        lines,
        time.perf_counter() - started,
        global_warnings,
        alignment_mode=alignment_mode,
        sections=sections,
    )

    raw = {
        "environment": env,
        "alignment_mode": alignment_mode,
        "section_manifest": str(args.section_manifest) if args.section_manifest else None,
        **raw_alignment,
        "character_entries": char_entries,
    }

    write_json(output_dir / "alignment.raw.json", raw)
    write_json(output_dir / "alignment.normalized.json", normalized)
    write_json(output_dir / "summary.json", summary)
    write_lrc(output_dir / "sample.lrc", lines)
    write_lrc(output_dir / "simple.lrc", lines)
    write_report(output_dir / "report.md", summary)
    write_section_report(output_dir / "section_report.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
