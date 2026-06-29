"""Candidate lyrics extraction from song audio.

This module intentionally produces ASR candidate lyrics only. It does not
participate in trusted-lyrics alignment and does not produce SWLRC.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

_SUSPECTED_METADATA_RE = re.compile(
    r"^(?:[词詞]曲|作[词詞]|作曲|编曲|編曲|字幕|歌[词詞]|制作|製作|"
    r"op|sp|publisher|lyrics?|composer)(?=\s|[:：]|$)",
    re.IGNORECASE,
)


class CandidateLyricsError(RuntimeError):
    """User-facing candidate lyric extraction failure."""


@dataclass(frozen=True)
class WordTiming:
    """Optional word-level timing returned by ASR."""

    start: float | None
    end: float | None
    word: str
    probability: float | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "word": self.word,
            "probability": self.probability,
        }


@dataclass(frozen=True)
class TranscriptSegment:
    """One ASR segment."""

    start: float
    end: float
    text: str
    words: list[WordTiming] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [word.to_json() for word in self.words],
        }


@dataclass(frozen=True)
class TranscriptionResult:
    """ASR result used by candidate lyric extraction."""

    segments: list[TranscriptSegment]
    detected_language: str | None
    warnings: list[str] = field(default_factory=list)


class Separator(Protocol):
    """Vocals separation callable."""

    def __call__(self, audio_path: Path, output_dir: Path) -> Path: ...


class Transcriber(Protocol):
    """ASR transcription callable."""

    def __call__(
        self,
        audio_path: Path,
        *,
        model_name: str,
        language: str | None,
        device: str,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ) -> TranscriptionResult: ...


def build_extract_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从歌曲音频分离人声并转写候选歌词。"
            "输出不是可信歌词，也不会生成 SWLRC。"
        )
    )
    parser.add_argument("--audio", required=True, type=Path, help="输入歌曲音频文件。")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="候选歌词输出目录。",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="可选 ASR 语言提示，例如 zh 或 en；省略时自动检测。",
    )
    parser.add_argument("--model", default="medium", help="faster-whisper 模型名称。")
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda", "mps"],
        default="auto",
        help="请求使用的推理设备。",
    )
    parser.add_argument(
        "--skip-separation",
        action="store_true",
        help="跳过 Demucs，直接转写原始混音音频。",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="关闭 faster-whisper VAD。默认开启，用于减少静音/间奏幻觉。",
    )
    parser.add_argument(
        "--condition-on-previous-text",
        action="store_true",
        help="允许 ASR 参考前文继续生成。默认关闭，用于减少跨段幻觉。",
    )
    parser.add_argument(
        "--keep-suspected-metadata",
        action="store_true",
        help="在 cleaned 文本中保留疑似词曲/字幕署名片段。默认剔除并写入 report。",
    )
    parser.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="保留 vocals.wav 等中间文件。当前脚本默认保留 vocals.wav。",
    )
    return parser


def normalize_transcript_line(text: str) -> str:
    """Normalize whitespace in one transcript segment."""

    return re.sub(r"\s+", " ", text.strip())


def is_suspected_metadata_line(text: str) -> bool:
    """Return true for ASR lines that look like credit/subtitle metadata."""

    normalized = normalize_transcript_line(text).lstrip("《「『【([（")
    return bool(_SUSPECTED_METADATA_RE.match(normalized))


def suspected_metadata_segments(segments: list[TranscriptSegment]) -> list[dict[str, object]]:
    """Return suspected non-lyric metadata segments for report review."""

    suspected: list[dict[str, object]] = []
    for segment in segments:
        text = normalize_transcript_line(segment.text)
        if text and is_suspected_metadata_line(text):
            suspected.append({"start": segment.start, "end": segment.end, "text": text})
    return suspected


def clean_transcript_segments(
    segments: list[TranscriptSegment],
    *,
    keep_suspected_metadata: bool = False,
) -> str:
    """Conservatively clean ASR text without correcting or completing lyrics."""

    lines: list[str] = []
    for segment in segments:
        line = normalize_transcript_line(segment.text)
        if line:
            if not keep_suspected_metadata and is_suspected_metadata_line(line):
                continue
            lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def write_segments_json(segments: list[TranscriptSegment], path: Path) -> None:
    payload = [segment.to_json() for segment in segments]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_report_json(report: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def separate_vocals_with_demucs(audio_path: Path, output_dir: Path) -> Path:
    """Run Demucs two-stem separation and copy vocals.wav into the output dir."""

    if shutil.which("demucs") is None:
        raise CandidateLyricsError(
            "未在 PATH 中找到 Demucs。请执行 `python -m pip install demucs` 安装。"
        )

    work_dir = output_dir / "_demucs"
    command = [
        "demucs",
        "--two-stems",
        "vocals",
        "-o",
        str(work_dir),
        str(audio_path),
    ]
    try:
        subprocess.run(command, check=True, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "TorchCodec is required" in stderr or "No module named 'torchcodec'" in stderr:
            raise CandidateLyricsError(
                "Demucs 保存 vocals.wav 失败：当前环境缺少 TorchCodec。"
                "请执行 `python -m pip install torchcodec`，然后重新运行命令。"
            ) from exc
        raise CandidateLyricsError(f"Demucs 执行失败，退出码 {exc.returncode}。\n{stderr}") from exc

    stem_name = audio_path.stem
    candidates = sorted(work_dir.glob(f"*/{stem_name}/vocals.wav"))
    if not candidates:
        raise CandidateLyricsError(f"Demucs 已结束，但未在 {work_dir} 下找到 vocals.wav。")

    vocals_path = output_dir / "vocals.wav"
    shutil.copy2(candidates[0], vocals_path)
    return vocals_path


def transcribe_with_faster_whisper(
    audio_path: Path,
    *,
    model_name: str,
    language: str | None,
    device: str,
    vad_filter: bool,
    condition_on_previous_text: bool,
) -> TranscriptionResult:
    """Transcribe audio with faster-whisper."""

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise CandidateLyricsError(
            "未安装 faster-whisper。请执行 `python -m pip install faster-whisper` 安装。"
        ) from exc

    warnings: list[str] = []
    actual_device = device
    if device == "auto":
        actual_device = "auto"
    elif device == "mps":
        actual_device = "cpu"
        warnings.append("faster-whisper 不直接支持 Apple MPS；已回退使用 CPU。")

    model = WhisperModel(model_name, device=actual_device)
    raw_segments, info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=vad_filter,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=condition_on_previous_text,
    )

    segments: list[TranscriptSegment] = []
    for raw_segment in raw_segments:
        words = [
            WordTiming(
                start=getattr(word, "start", None),
                end=getattr(word, "end", None),
                word=getattr(word, "word", ""),
                probability=getattr(word, "probability", None),
            )
            for word in (getattr(raw_segment, "words", None) or [])
        ]
        segments.append(
            TranscriptSegment(
                start=float(raw_segment.start),
                end=float(raw_segment.end),
                text=str(raw_segment.text),
                words=words,
            )
        )

    return TranscriptionResult(
        segments=segments,
        detected_language=getattr(info, "language", None),
        warnings=warnings,
    )


def extract_candidate_lyrics(
    args: argparse.Namespace,
    *,
    separator: Separator = separate_vocals_with_demucs,
    transcriber: Transcriber = transcribe_with_faster_whisper,
) -> dict[str, object]:
    """Extract candidate lyrics from audio and write local review artifacts."""

    audio_path = args.audio.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not audio_path.exists():
        raise CandidateLyricsError(f"音频文件不存在：{audio_path}")
    if not audio_path.is_file():
        raise CandidateLyricsError(f"音频路径不是文件：{audio_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    warnings = [
        "仅为 ASR 候选歌词。不要将此输出视为可信歌词，也不要直接作为 SWLRC 输入。"
    ]
    started_at = time.perf_counter()

    vocals_path: Path | None = None
    transcription_audio = audio_path
    if args.skip_separation:
        warnings.append("已跳过 Demucs 人声分离；ASR 直接使用原始混音音频。")
    else:
        vocals_path = separator(audio_path, output_dir)
        transcription_audio = vocals_path

    transcription = transcriber(
        transcription_audio,
        model_name=args.model,
        language=args.language,
        device=args.device,
        vad_filter=not args.no_vad,
        condition_on_previous_text=args.condition_on_previous_text,
    )
    warnings.extend(transcription.warnings)

    raw_text = "".join(segment.text for segment in transcription.segments).strip()
    suspected_metadata = suspected_metadata_segments(transcription.segments)
    if suspected_metadata and not args.keep_suspected_metadata:
        warnings.append(
            f"已从 cleaned 候选歌词中剔除 {len(suspected_metadata)} 个疑似词曲/字幕署名片段；"
            "原文仍保留在 raw 与 segments 文件中。"
        )
    cleaned_text = clean_transcript_segments(
        transcription.segments,
        keep_suspected_metadata=args.keep_suspected_metadata,
    )

    raw_path = output_dir / "transcript.raw.txt"
    segments_path = output_dir / "transcript.segments.json"
    cleaned_path = output_dir / "transcript.cleaned.txt"
    report_path = output_dir / "report.json"

    raw_path.write_text(raw_text + ("\n" if raw_text else ""), encoding="utf-8")
    write_segments_json(transcription.segments, segments_path)
    cleaned_path.write_text(cleaned_text, encoding="utf-8")

    report: dict[str, object] = {
        "input_audio": str(audio_path),
        "output_dir": str(output_dir),
        "asr_model": args.model,
        "requested_language": args.language,
        "detected_language": transcription.detected_language,
        "device": args.device,
        "asr_options": {
            "vad_filter": not args.no_vad,
            "condition_on_previous_text": args.condition_on_previous_text,
            "keep_suspected_metadata": args.keep_suspected_metadata,
        },
        "separation_enabled": not args.skip_separation,
        "keep_intermediates": True if not args.skip_separation else bool(args.keep_intermediates),
        "suspected_metadata_segments": suspected_metadata,
        "duration_seconds": round(time.perf_counter() - started_at, 3),
        "outputs": {
            "vocals": str(vocals_path) if vocals_path is not None else None,
            "transcript_raw": str(raw_path),
            "transcript_segments": str(segments_path),
            "transcript_cleaned": str(cleaned_path),
            "report": str(report_path),
        },
        "warnings": warnings,
    }
    write_report_json(report, report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = build_extract_parser()
    args = parser.parse_args(argv)
    try:
        report = extract_candidate_lyrics(args)
    except CandidateLyricsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    outputs = cast(dict[str, object], report["outputs"])
    print(f"候选歌词已写入：{outputs['transcript_cleaned']}")
    print("这是 ASR 候选歌词，不是可信歌词。")
    return 0
