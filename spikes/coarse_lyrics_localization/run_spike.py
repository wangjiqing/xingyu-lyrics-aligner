from __future__ import annotations

# ruff: noqa: E501
import argparse
import json
import platform
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DIGIT_TO_ZH = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}

CONFUSION_FOLD = {
    "新": "星",
    "腥": "星",
    "鱼": "语",
    "雨": "语",
    "淌": "淌",
    "躺": "淌",
    "逃": "淌",
    "亮": "亮",
    "量": "亮",
    "唱": "唱",
    "常": "唱",
}

STATUS_MATCHED = "matched"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_UNMATCHED = "unmatched"
STATUS_AMBIGUOUS_REPEAT = "ambiguous_repeat"
STATUS_MANUAL_REVIEW = "manual_review_required"


@dataclass(frozen=True)
class TextForm:
    original: str
    normalized: str
    match_key: str


@dataclass(frozen=True)
class AsrSegment:
    index: int
    text: str
    start: float
    end: float
    normalized_text: str
    match_key: str


@dataclass(frozen=True)
class Candidate:
    line_index: int
    segment_start: int | None
    segment_end: int | None
    score: float
    asr_text: str
    anchor_start: float | None
    anchor_end: float | None
    evidence: list[dict[str, Any]]
    status: str
    warnings: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Spike: localize trusted Chinese lyric lines using ASR time anchors."
    )
    parser.add_argument("--audio", type=Path, default=Path("sample_input/sample.wav"))
    parser.add_argument("--lyrics", type=Path, default=Path("sample_input/sample_lyrics.txt"))
    parser.add_argument("--asr-json", type=Path, default=Path("sample_input/asr_fixture.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("sample_output"))
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--asr-model", default="tiny")
    parser.add_argument("--run-whisperx", action="store_true")
    parser.add_argument("--model-cache-only", action="store_true")
    parser.add_argument("--pre-roll", type=float, default=0.75)
    parser.add_argument("--post-roll", type=float, default=0.9)
    parser.add_argument("--low-confidence-extra", type=float, default=0.55)
    parser.add_argument("--min-window", type=float, default=1.5)
    parser.add_argument("--max-span", type=int, default=2)
    parser.add_argument("--match-threshold", type=float, default=0.82)
    parser.add_argument("--low-threshold", type=float, default=0.48)
    return parser.parse_args()


def resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_lyrics(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_for_compare(text: str) -> TextForm:
    nfkc = unicodedata.normalize("NFKC", text).lower()
    chars: list[str] = []
    for char in nfkc:
        if char in DIGIT_TO_ZH:
            chars.append(DIGIT_TO_ZH[char])
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")) or char.isspace():
            continue
        chars.append(char)
    normalized = "".join(chars)
    match_key = "".join(CONFUSION_FOLD.get(char, char) for char in normalized)
    return TextForm(original=text, normalized=normalized, match_key=match_key)


def load_fixture_asr(path: Path) -> dict[str, Any]:
    data = read_json(path)
    data.setdefault("engine", "fixture")
    data.setdefault("language", "zh")
    data.setdefault("segments", [])
    return data


def run_whisperx_asr(args: argparse.Namespace, audio_path: Path) -> dict[str, Any]:
    import torch
    import whisperx

    audio = whisperx.load_audio(str(audio_path))
    duration = len(audio) / 16000.0
    model = whisperx.load_model(
        args.asr_model,
        args.device,
        language=args.language,
        compute_type=args.compute_type,
    )
    result = model.transcribe(audio, batch_size=4, language=args.language)
    del model
    if args.device == "cuda":
        torch.cuda.empty_cache()
    result["engine"] = "whisperx"
    result["model"] = args.asr_model
    result["duration"] = duration
    return result


def build_asr_segments(raw_asr: dict[str, Any]) -> list[AsrSegment]:
    segments = []
    for index, segment in enumerate(raw_asr.get("segments", [])):
        text = str(segment.get("text", "")).strip()
        text_form = normalize_for_compare(text)
        segments.append(
            AsrSegment(
                index=index,
                text=text,
                start=float(segment.get("start", 0.0)),
                end=float(segment.get("end", segment.get("start", 0.0))),
                normalized_text=text_form.normalized,
                match_key=text_form.match_key,
            )
        )
    return segments


def sequence_score(lyrics_key: str, asr_key: str) -> float:
    if not lyrics_key or not asr_key:
        return 0.0
    ratio = SequenceMatcher(None, lyrics_key, asr_key).ratio()
    matches = sum(
        block.size for block in SequenceMatcher(None, lyrics_key, asr_key).get_matching_blocks()
    )
    coverage = matches / max(len(lyrics_key), 1)
    length_balance = min(len(lyrics_key), len(asr_key)) / max(len(lyrics_key), len(asr_key), 1)
    return round((ratio * 0.55) + (coverage * 0.35) + (length_balance * 0.10), 4)


def make_candidate(
    line_index: int,
    line_text: str,
    line_key: str,
    segments: list[AsrSegment],
    start: int,
    end: int,
    args: argparse.Namespace,
) -> Candidate:
    span = segments[start : end + 1]
    asr_key = "".join(segment.match_key for segment in span)
    asr_text = "".join(segment.text for segment in span)
    score = sequence_score(line_key, asr_key)
    warnings: list[str] = []
    if len(span) > 1:
        warnings.append("matched_across_multiple_asr_segments")
    if score < args.match_threshold:
        status = STATUS_LOW_CONFIDENCE if score >= args.low_threshold else STATUS_MANUAL_REVIEW
    else:
        status = STATUS_MATCHED
    if normalize_for_compare(line_text).normalized != normalize_for_compare(asr_text).normalized:
        warnings.append("asr_text_differs_from_trusted_lyrics")
    return Candidate(
        line_index=line_index,
        segment_start=start,
        segment_end=end,
        score=score,
        asr_text=asr_text,
        anchor_start=span[0].start,
        anchor_end=span[-1].end,
        evidence=[
            {
                "text": segment.text,
                "start": segment.start,
                "end": segment.end,
            }
            for segment in span
        ],
        status=status,
        warnings=warnings,
    )


def unmatched_candidate(line_index: int) -> Candidate:
    return Candidate(
        line_index=line_index,
        segment_start=None,
        segment_end=None,
        score=0.0,
        asr_text="",
        anchor_start=None,
        anchor_end=None,
        evidence=[],
        status=STATUS_UNMATCHED,
        warnings=["no_asr_anchor_found"],
    )


def best_candidate_for_line(
    line_index: int,
    line_text: str,
    line_key: str,
    segments: list[AsrSegment],
    cursor: int,
    args: argparse.Namespace,
) -> Candidate:
    best: Candidate | None = None
    for start in range(cursor, len(segments)):
        for end in range(start, min(len(segments), start + args.max_span)):
            candidate = make_candidate(line_index, line_text, line_key, segments, start, end, args)
            if best is None or candidate.score > best.score:
                best = candidate
    if best is None or best.score < args.low_threshold:
        return unmatched_candidate(line_index)
    return best


def greedy_match(
    lyrics: list[str],
    lyric_forms: list[TextForm],
    segments: list[AsrSegment],
    args: argparse.Namespace,
) -> list[Candidate]:
    cursor = 0
    matches: list[Candidate] = []
    seen_lines: dict[str, int] = {}
    for index, (line, form) in enumerate(zip(lyrics, lyric_forms, strict=True)):
        candidate = best_candidate_for_line(index, line, form.match_key, segments, cursor, args)
        warnings = list(candidate.warnings)
        key_count = seen_lines.get(form.match_key, 0)
        if key_count:
            warnings.append("trusted_lyrics_line_repeats")
        seen_lines[form.match_key] = key_count + 1
        if candidate.segment_end is not None:
            cursor = candidate.segment_end + 1
        matches.append(
            Candidate(
                **{
                    **candidate.__dict__,
                    "warnings": warnings,
                }
            )
        )
    return matches


def dynamic_programming_match(
    lyrics: list[str],
    lyric_forms: list[TextForm],
    segments: list[AsrSegment],
    args: argparse.Namespace,
) -> list[Candidate]:
    line_count = len(lyrics)
    segment_count = len(segments)
    skip_asr_penalty = 0.04
    skip_line_penalty = 0.72
    low_conf_penalty = 0.16
    dp = [[float("-inf")] * (segment_count + 1) for _ in range(line_count + 1)]
    back: list[list[tuple[str, int, int, Candidate | None] | None]] = [
        [None] * (segment_count + 1) for _ in range(line_count + 1)
    ]
    dp[0][0] = 0.0
    for i in range(line_count + 1):
        for j in range(segment_count + 1):
            current = dp[i][j]
            if current == float("-inf"):
                continue
            if j < segment_count and current - skip_asr_penalty > dp[i][j + 1]:
                dp[i][j + 1] = current - skip_asr_penalty
                back[i][j + 1] = ("skip_asr", i, j, None)
            if i < line_count and current - skip_line_penalty > dp[i + 1][j]:
                dp[i + 1][j] = current - skip_line_penalty
                back[i + 1][j] = ("skip_line", i, j, unmatched_candidate(i))
            if i < line_count and j < segment_count:
                for span_len in range(1, args.max_span + 1):
                    end = j + span_len - 1
                    if end >= segment_count:
                        break
                    candidate = make_candidate(
                        i,
                        lyrics[i],
                        lyric_forms[i].match_key,
                        segments,
                        j,
                        end,
                        args,
                    )
                    if candidate.score < args.low_threshold:
                        continue
                    value = current + candidate.score
                    if candidate.score < args.match_threshold:
                        value -= low_conf_penalty
                    if value > dp[i + 1][end + 1]:
                        dp[i + 1][end + 1] = value
                        back[i + 1][end + 1] = ("match", i, j, candidate)

    best_j = max(range(segment_count + 1), key=lambda col: dp[line_count][col])
    i = line_count
    j = best_j
    reversed_matches: list[Candidate] = []
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        action, prev_i, prev_j, candidate = step
        if action in {"match", "skip_line"} and candidate is not None:
            reversed_matches.append(candidate)
        i, j = prev_i, prev_j
    matches = list(reversed(reversed_matches))
    by_line = {candidate.line_index: candidate for candidate in matches}
    ordered = [by_line.get(index, unmatched_candidate(index)) for index in range(line_count)]
    return mark_repeat_warnings(ordered, lyric_forms)


def mark_repeat_warnings(matches: list[Candidate], lyric_forms: list[TextForm]) -> list[Candidate]:
    total_counts: dict[str, int] = {}
    seen_counts: dict[str, int] = {}
    for form in lyric_forms:
        total_counts[form.match_key] = total_counts.get(form.match_key, 0) + 1
    marked = []
    for candidate, form in zip(matches, lyric_forms, strict=True):
        warnings = list(candidate.warnings)
        seen_counts[form.match_key] = seen_counts.get(form.match_key, 0) + 1
        if total_counts[form.match_key] > 1:
            warnings.append(
                f"repeat_occurrence_{seen_counts[form.match_key]}_of_{total_counts[form.match_key]}"
            )
        marked.append(Candidate(**{**candidate.__dict__, "warnings": warnings}))
    return marked


def expand_windows(
    candidates: list[Candidate],
    duration: float,
    args: argparse.Namespace,
) -> dict[int, tuple[float | None, float | None, list[str]]]:
    windows: dict[int, tuple[float | None, float | None, list[str]]] = {}
    for candidate in candidates:
        warnings: list[str] = []
        if candidate.anchor_start is None or candidate.anchor_end is None:
            windows[candidate.line_index] = (None, None, warnings)
            continue
        extra = args.low_confidence_extra if candidate.score < args.match_threshold else 0.0
        start = max(0.0, candidate.anchor_start - args.pre_roll - extra)
        end = min(duration, candidate.anchor_end + args.post_roll + extra)
        if end - start < args.min_window:
            center = (start + end) / 2
            half = args.min_window / 2
            start = max(0.0, center - half)
            end = min(duration, center + half)
            warnings.append("window_extended_to_minimum_length")
        windows[candidate.line_index] = (round(start, 3), round(end, 3), warnings)

    ordered = [
        candidate for candidate in candidates if windows[candidate.line_index][0] is not None
    ]
    for left, right in zip(ordered, ordered[1:], strict=False):
        left_start, left_end, left_warnings = windows[left.line_index]
        right_start, right_end, right_warnings = windows[right.line_index]
        if (
            left_end is None
            or right_start is None
            or left.anchor_end is None
            or right.anchor_start is None
        ):
            continue
        if left_end > right_start:
            split = round((left.anchor_end + right.anchor_start) / 2, 3)
            windows[left.line_index] = (
                left_start,
                split,
                left_warnings + ["window_overlap_trimmed"],
            )
            windows[right.line_index] = (
                split,
                right_end,
                right_warnings + ["window_overlap_trimmed"],
            )
    return windows


def candidate_to_line(
    candidate: Candidate,
    lyric: str,
    form: TextForm,
    window: tuple[float | None, float | None, list[str]],
) -> dict[str, Any]:
    status = candidate.status
    warnings = list(candidate.warnings) + list(window[2])
    if status == STATUS_LOW_CONFIDENCE:
        warnings.append("manual_review_recommended")
    return {
        "index": candidate.line_index,
        "text": lyric,
        "normalized_text": form.normalized,
        "match_key": form.match_key,
        "window_start": window[0],
        "window_end": window[1],
        "anchor_start": candidate.anchor_start,
        "anchor_end": candidate.anchor_end,
        "match_score": candidate.score,
        "status": status,
        "asr_evidence": candidate.evidence,
        "warnings": warnings,
    }


def build_normalized_output(
    strategy: str,
    candidates: list[Candidate],
    lyrics: list[str],
    lyric_forms: list[TextForm],
    raw_asr: dict[str, Any],
    audio_path: Path,
    lyrics_path: Path,
    windows: dict[int, tuple[float | None, float | None, list[str]]],
) -> dict[str, Any]:
    lines = [
        candidate_to_line(candidate, lyrics[index], lyric_forms[index], windows[index])
        for index, candidate in enumerate(candidates)
    ]
    warnings = []
    if any(line["status"] != STATUS_MATCHED for line in lines):
        warnings.append("some_lines_require_review_or_are_unmatched")
    if any("repeat" in " ".join(line["warnings"]) for line in lines):
        warnings.append("trusted_lyrics_contains_repeated_lines")
    return {
        "source": {
            "audio": str(audio_path),
            "lyrics": str(lyrics_path),
            "language": raw_asr.get("language", "zh"),
            "asr_engine": raw_asr.get("engine", "unknown"),
        },
        "strategy": strategy,
        "status_vocabulary": [
            STATUS_MATCHED,
            STATUS_LOW_CONFIDENCE,
            STATUS_UNMATCHED,
            STATUS_AMBIGUOUS_REPEAT,
            STATUS_MANUAL_REVIEW,
        ],
        "lines": lines,
        "warnings": warnings,
    }


def normalize_lyrics_json(lyrics: list[str]) -> dict[str, Any]:
    return {
        "lines": [
            {
                "index": index,
                "text": line,
                "normalized_text": normalize_for_compare(line).normalized,
                "match_key": normalize_for_compare(line).match_key,
            }
            for index, line in enumerate(lyrics)
        ],
        "normalization_rules": [
            "Unicode NFKC full-width/half-width normalization",
            "lowercase Latin letters",
            "drop Unicode punctuation, symbols, and whitespace",
            "map Arabic digits 0-9 to Chinese digits for comparison",
            "fold a small hand-written ASR confusion table only for matching keys",
        ],
    }


def summarize_matches(lines: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for line in lines:
        counts[line["status"]] = counts.get(line["status"], 0) + 1
    return {
        "status_counts": counts,
        "average_score": round(
            sum(line["match_score"] for line in lines) / max(len(lines), 1),
            4,
        ),
    }


def write_report(
    path: Path,
    env: dict[str, Any],
    raw_asr: dict[str, Any],
    greedy: dict[str, Any],
    dp: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    greedy_summary = summarize_matches(greedy["lines"])
    dp_summary = summarize_matches(dp["lines"])
    sample_line = next((line for line in dp["lines"] if line["asr_evidence"]), dp["lines"][0])
    report = f"""# Coarse Lyrics Localization Spike Report

## 1. Environment

- Date: 2026-06-20
- Platform: `{env["platform"]}` / `{env["machine"]}`
- Python: `{env["python"].split()[0]}`
- FFmpeg: `{env["ffmpeg"]}`
- WhisperX: `{env["whisperx"]}`
- PyTorch: `{env["torch"]}`
- Requested device: `{env["device"]}`
- CUDA available: `{env["cuda_available"]}`
- MPS available: `{env["mps_available"]}`

## 2. Models

- ASR engine: `{raw_asr.get("engine", "unknown")}`
- ASR model: `{raw_asr.get("model", args.asr_model)}`
- Language: `{raw_asr.get("language", args.language)}`
- Alignment model: not invoked by this spike. The previous WhisperX spike validated `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn` for later character-level refinement.

## 3. Test Audio

- Fixture audio name: `{raw_asr.get("audio", args.audio)}`
- Duration used for window clamping: `{raw_asr.get("duration", "unknown")}s`
- The committed sample uses a small ASR fixture shaped like WhisperX output. Generated audio remains ignored. This isolates coarse localization behavior from model download and ASR nondeterminism.

## 4. Test Lyrics

The lyrics contain repeated chorus lines, ASR-like wrong characters, a long interlude, one line split across two ASR segments, one shortened ASR segment, and one intentionally missing sung line.

## 5. Text Normalization

Comparison-only normalization:

- Unicode NFKC to handle full-width/half-width forms.
- Lowercase Latin text.
- Remove Unicode punctuation, symbols, and whitespace.
- Map Arabic digits to Chinese digits for rough numeric comparison.
- Fold a tiny ASR confusion table for matching only, for example `新/星`, `鱼/语`, and `逃/淌`.

The original trusted lyric text is preserved and is never overwritten by ASR text.

## 6. Greedy Strategy

The greedy matcher walks lyric lines in order. For each line it scans the remaining ASR segments, considers one- or two-segment spans, chooses the highest fuzzy score, then advances the ASR cursor past that span.

Result summary:

```json
{json.dumps(greedy_summary, ensure_ascii=False, indent=2)}
```

Greedy is simple and monotonic, so it avoids matching later lyric lines to earlier ASR segments. Its weakness is local commitment: once it consumes a mediocre repeated-chorus candidate, later lines cannot repair that choice.

## 7. Dynamic Programming Strategy

The DP matcher builds an ordered path across lyric lines and ASR segment spans. It can:

- match a lyric line to a one- or two-segment ASR span;
- skip ASR-only material such as interlude filler;
- skip a lyric line when no adequate ASR anchor exists;
- penalize low-confidence matches.

Cost model:

- match reward = fuzzy score;
- skip ASR penalty = `0.04`;
- skip lyric penalty = `0.72`;
- low confidence penalty = `0.16`;
- candidate rejected below score `{args.low_threshold}`;
- line is low confidence below score `{args.match_threshold}`.

Result summary:

```json
{json.dumps(dp_summary, ensure_ascii=False, indent=2)}
```

DP is more suitable for full songs because it optimizes the whole monotonic path. That matters when repeated chorus lines, missing ASR chunks, or interludes would otherwise cause a local greedy choice to shift the rest of the song.

## 8. Window Expansion

For matched anchors:

```text
window_start = max(0, anchor_start - pre_roll - low_confidence_extra)
window_end = min(audio_duration, anchor_end + post_roll + low_confidence_extra)
```

Parameters:

- pre-roll: `{args.pre_roll}s`
- post-roll: `{args.post_roll}s`
- low-confidence extra: `{args.low_confidence_extra}s`
- minimum window: `{args.min_window}s`

Overlapping adjacent windows are trimmed at the midpoint between the neighboring anchors. Low-confidence matches receive wider windows.

## 9. Failure Cases Observed

- ASR wrong characters: `新鱼` still matched trusted `星语`; `流逃` still matched trusted `流淌` via comparison-only confusion folding.
- Repeated chorus: three occurrences of `星语在夜里发光` stayed in chronological order and were flagged as repeats.
- Long interlude: ASR-only `啦` was skipped by DP rather than matched to a lyric line.
- Split line: `把每个字轻轻照亮` matched across two ASR segments.
- Shortened ASR: `明天继续唱` produced a lower score for trusted `明天还会继续唱`, requiring review.
- Missing sung line: `这一句没有唱出声` remained unmatched instead of forcing a bad window.

## 10. JSON Sample

```json
{json.dumps(sample_line, ensure_ascii=False, indent=2)}
```

## 11. macOS CPU

The fixture localization path is pure Python and completed locally on macOS CPU in milliseconds. Optional WhisperX ASR remains CPU-runnable according to the prior spike, but it is not the reliability source for lyrics text.

## 12. Windows CUDA

Windows CUDA was not verified in this spike. CUDA should only affect optional ASR runtime, not the deterministic localization algorithm. A Windows validation pass should run WhisperX ASR with `--device cuda --compute-type float16` and then compare the same JSON outputs.

## 13. Recommendation

Conclusion: GO WITH CONSTRAINTS.

The approach is promising enough for v0.1.1 pre-implementation: ASR can provide rough time anchors while trusted lyrics remain authoritative. However, formal implementation must keep the coarse locator as a separate boundary before WhisperX character refinement, and all low-confidence or unmatched lines must be surfaced for review.

Recommended architecture boundary:

1. ASR adapter: local audio to raw timed ASR segments.
2. Text normalizer: comparison-only forms, never mutating trusted lyrics.
3. Coarse locator: DP-first line-to-ASR path with greedy/debug fallback.
4. Window builder: expands and trims anchor windows.
5. Fine aligner: WhisperX character-level alignment inside each trusted window.
6. Review layer: exposes low-confidence, unmatched, and repeated-line warnings.
"""
    path.write_text(report, encoding="utf-8")


def run() -> int:
    started = time.perf_counter()
    args = parse_args()
    root = Path(__file__).resolve().parent
    audio_path = resolve_path(root, args.audio)
    lyrics_path = resolve_path(root, args.lyrics)
    asr_path = resolve_path(root, args.asr_json)
    output_dir = resolve_path(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lyrics = read_lyrics(lyrics_path)
    lyric_forms = [normalize_for_compare(line) for line in lyrics]

    whisperx_version = "not_imported"
    torch_version = "not_imported"
    cuda_available = False
    mps_available = False
    if args.run_whisperx:
        raw_asr = run_whisperx_asr(args, audio_path)
        import torch
        import whisperx

        torch_version = torch.__version__
        whisperx_version = getattr(whisperx, "__version__", "unknown")
        cuda_available = torch.cuda.is_available()
        mps_available = (
            bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
        )
    else:
        raw_asr = load_fixture_asr(asr_path)
        try:
            import torch
            import whisperx

            torch_version = torch.__version__
            whisperx_version = getattr(whisperx, "__version__", "unknown")
            cuda_available = torch.cuda.is_available()
            mps_available = (
                bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
            )
        except Exception:
            pass

    segments = build_asr_segments(raw_asr)
    duration = float(
        raw_asr.get("duration") or max((segment.end for segment in segments), default=0.0)
    )

    greedy_candidates = greedy_match(lyrics, lyric_forms, segments, args)
    dp_candidates = dynamic_programming_match(lyrics, lyric_forms, segments, args)
    greedy_windows = expand_windows(greedy_candidates, duration, args)
    dp_windows = expand_windows(dp_candidates, duration, args)

    greedy_output = build_normalized_output(
        "greedy",
        greedy_candidates,
        lyrics,
        lyric_forms,
        raw_asr,
        audio_path,
        lyrics_path,
        greedy_windows,
    )
    dp_output = build_normalized_output(
        "dynamic_programming",
        dp_candidates,
        lyrics,
        lyric_forms,
        raw_asr,
        audio_path,
        lyrics_path,
        dp_windows,
    )

    localization_raw = {
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "asr_segments_normalized": [segment.__dict__ for segment in segments],
        "greedy": greedy_output,
        "dynamic_programming": dp_output,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }

    env = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "ffmpeg": shutil.which("ffmpeg"),
        "whisperx": whisperx_version,
        "torch": torch_version,
        "device": args.device,
        "cuda_available": cuda_available,
        "mps_available": mps_available,
    }

    write_json(output_dir / "asr.raw.json", raw_asr)
    write_json(output_dir / "lyrics.normalized.json", normalize_lyrics_json(lyrics))
    write_json(output_dir / "localization.raw.json", localization_raw)
    write_json(output_dir / "localization.normalized.json", dp_output)
    write_report(output_dir / "report.md", env, raw_asr, greedy_output, dp_output, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
