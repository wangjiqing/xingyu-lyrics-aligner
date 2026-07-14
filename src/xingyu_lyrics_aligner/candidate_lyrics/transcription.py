"""Candidate lyrics extraction from song audio.

This module intentionally produces ASR candidate lyrics only. It does not
participate in trusted-lyrics alignment and does not produce SWLRC.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from xingyu_lyrics_aligner.audio_separation import (
    AudioSeparationError,
    separate_vocals_and_accompaniment,
)
from xingyu_lyrics_aligner.candidate_lyrics.config import (
    DraftExtractionConfig,
    resolve_draft_extraction_config,
)

_SUSPECTED_METADATA_RE = re.compile(
    r"^(?:[词詞]曲|作[词詞]|作曲|编曲|編曲|字幕|歌[词詞]|制作|製作|"
    r"op|sp|publisher|lyrics?|composer)(?=\s|[:：]|$)",
    re.IGNORECASE,
)


class CandidateLyricsError(RuntimeError):
    """User-facing candidate lyric extraction failure."""


@dataclass(frozen=True)
class CandidateLyricsExtractionRequest:
    """Stable service-layer request for candidate lyric extraction."""

    audio_path: Path
    output_dir: Path
    language: str | None = None
    model: str = "medium"
    device: str = "auto"
    skip_separation: bool = False
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    keep_suspected_metadata: bool = False
    retain_intermediate: bool = False
    intermediate_dir: Path | None = None
    task_type: str = "LYRIC_DRAFT_EXTRACTION"
    requested_config: dict[str, object] = field(default_factory=dict)
    resolved_config: DraftExtractionConfig | None = None


@dataclass(frozen=True)
class CandidateLyricsExtractionResult:
    """Files and report produced by candidate lyric extraction."""

    output_dir: Path
    files: dict[str, Path]
    report: dict[str, object]
    intermediate_files: dict[str, Path] = field(default_factory=dict)


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
        description=("从歌曲音频分离人声并转写候选歌词。输出不是可信歌词，也不会生成 SWLRC。")
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
    parser.add_argument("--model", default=None, help="faster-whisper 模型名称。")
    parser.add_argument(
        "--preset",
        default=None,
        help=(
            "ASR 草稿提取预设：fast、recommended、high-quality、full-recognition。"
            "显式 --model/--skip-separation/--no-vad 会覆盖预设。"
        ),
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda", "mps"],
        default="auto",
        help="请求使用的推理设备。",
    )
    parser.add_argument(
        "--skip-separation",
        action="store_true",
        default=None,
        help="跳过 Demucs，直接转写原始混音音频。",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        default=None,
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
    """Preserve the legacy candidate flow while using the shared separator."""

    try:
        separated = separate_vocals_and_accompaniment(audio_path, output_dir)
    except AudioSeparationError as exc:
        if "TorchCodec" in str(exc):
            raise CandidateLyricsError(
                "Demucs 保存 vocals.wav 失败：当前环境缺少 TorchCodec。"
                "请执行 `python -m pip install torchcodec`，然后重新运行命令。"
            ) from exc
        raise CandidateLyricsError(str(exc)) from exc

    vocals_path = output_dir / "vocals.wav"
    shutil.copy2(separated.vocals, vocals_path)
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

    preset = getattr(args, "preset", None)
    skip_separation = getattr(args, "skip_separation", None)
    no_vad = getattr(args, "no_vad", None)
    keep_intermediates = bool(getattr(args, "keep_intermediates", False))
    retain_intermediate = resolve_cli_retain_intermediate(
        preset=preset,
        skip_separation=skip_separation,
        keep_intermediates=keep_intermediates,
    )
    config = resolve_draft_extraction_config(
        preset=getattr(args, "preset", None),
        asr_model=args.model,
        skip_separation=skip_separation,
        vad_filter=None if no_vad is None else not no_vad,
        condition_on_previous_text=args.condition_on_previous_text,
        keep_suspected_metadata=args.keep_suspected_metadata,
        retain_intermediate=retain_intermediate,
    )
    request = CandidateLyricsExtractionRequest(
        audio_path=args.audio,
        output_dir=args.output_dir,
        language=args.language,
        model=config.asr_model,
        device=args.device,
        skip_separation=config.skip_separation,
        vad_filter=config.vad_filter,
        condition_on_previous_text=config.condition_on_previous_text,
        keep_suspected_metadata=config.keep_suspected_metadata,
        # Preserve the v0.3.0 CLI behavior: Demucs vocals.wav is kept by default.
        # Worker callers pass retain_intermediate explicitly and use job/intermediate.
        retain_intermediate=config.retain_intermediate,
        intermediate_dir=None,
        task_type="CANDIDATE_EXTRACT_CLI",
        requested_config={
            "preset": getattr(args, "preset", None),
            "model": args.model,
            "skipSeparation": skip_separation,
            "vadFilter": None if no_vad is None else not no_vad,
            "conditionOnPreviousText": args.condition_on_previous_text,
            "keepSuspectedMetadata": args.keep_suspected_metadata,
            "retainIntermediate": config.retain_intermediate,
        },
        resolved_config=config,
    )
    service = CandidateLyricsExtractionService(separator=separator, transcriber=transcriber)
    return service.extract(request).report


def resolve_cli_retain_intermediate(
    *,
    preset: str | None,
    skip_separation: bool | None,
    keep_intermediates: bool,
) -> bool | None:
    """Preserve legacy CLI vocals behavior without overriding preset defaults."""

    if preset is not None:
        return True if keep_intermediates else None
    if skip_separation is True:
        return keep_intermediates
    return True


class CandidateLyricsExtractionService:
    """Reusable candidate lyric extraction service for CLI and Worker."""

    def __init__(
        self,
        *,
        separator: Separator = separate_vocals_with_demucs,
        transcriber: Transcriber = transcribe_with_faster_whisper,
    ) -> None:
        self.separator = separator
        self.transcriber = transcriber

    def extract(
        self,
        request: CandidateLyricsExtractionRequest,
    ) -> CandidateLyricsExtractionResult:
        """Extract candidate lyrics from audio and write review artifacts."""

        return extract_candidate_lyrics_request(
            request,
            separator=self.separator,
            transcriber=self.transcriber,
        )


def extract_candidate_lyrics_request(
    request: CandidateLyricsExtractionRequest,
    *,
    separator: Separator = separate_vocals_with_demucs,
    transcriber: Transcriber = transcribe_with_faster_whisper,
) -> CandidateLyricsExtractionResult:
    """Extract candidate lyrics from a typed service request."""

    audio_path = request.audio_path.expanduser().resolve()
    output_dir = request.output_dir.expanduser().resolve()

    if not audio_path.exists():
        raise CandidateLyricsError(f"音频文件不存在：{audio_path}")
    if not audio_path.is_file():
        raise CandidateLyricsError(f"音频路径不是文件：{audio_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    warnings = ["仅为 ASR 候选歌词。不要将此输出视为可信歌词，也不要直接作为 SWLRC 输入。"]
    started_at = time.perf_counter()

    intermediate_dir = (
        request.intermediate_dir.expanduser().resolve()
        if request.intermediate_dir is not None
        else output_dir
    )
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    vocals_path: Path | None = None
    transcription_audio = audio_path
    if request.skip_separation:
        warnings.append("已跳过 Demucs 人声分离；ASR 直接使用原始混音音频。")
    else:
        vocals_path = separator(audio_path, intermediate_dir)
        transcription_audio = vocals_path

    transcription = transcriber(
        transcription_audio,
        model_name=request.model,
        language=request.language,
        device=request.device,
        vad_filter=request.vad_filter,
        condition_on_previous_text=request.condition_on_previous_text,
    )
    warnings.extend(transcription.warnings)

    raw_text = "".join(segment.text for segment in transcription.segments).strip()
    suspected_metadata = suspected_metadata_segments(transcription.segments)
    if suspected_metadata and not request.keep_suspected_metadata:
        warnings.append(
            f"已从 cleaned 候选歌词中剔除 {len(suspected_metadata)} 个疑似词曲/字幕署名片段；"
            "原文仍保留在 raw 与 segments 文件中。"
        )
    cleaned_text = clean_transcript_segments(
        transcription.segments,
        keep_suspected_metadata=request.keep_suspected_metadata,
    )

    raw_path = output_dir / "transcript.raw.txt"
    segments_path = output_dir / "transcript.segments.json"
    cleaned_path = output_dir / "transcript.cleaned.txt"
    report_path = output_dir / "report.json"

    raw_path.write_text(raw_text + ("\n" if raw_text else ""), encoding="utf-8")
    write_segments_json(transcription.segments, segments_path)
    cleaned_path.write_text(cleaned_text, encoding="utf-8")

    if vocals_path is not None and not request.retain_intermediate:
        try:
            vocals_path.unlink(missing_ok=True)
        except OSError as exc:
            warnings.append(f"清理中间 vocals.wav 失败：{exc.__class__.__name__}")
        vocals_path = None

    resolved_config = request.resolved_config or resolve_draft_extraction_config(
        asr_model=request.model,
        skip_separation=request.skip_separation,
        vad_filter=request.vad_filter,
        condition_on_previous_text=request.condition_on_previous_text,
        keep_suspected_metadata=request.keep_suspected_metadata,
        retain_intermediate=request.retain_intermediate,
    )
    report: dict[str, object] = {
        "taskType": request.task_type,
        "requestedConfig": request.requested_config,
        "resolvedConfig": resolved_config.to_report_json(),
        "input_audio": str(audio_path),
        "output_dir": str(output_dir),
        "asr_model": request.model,
        "requested_language": request.language,
        "detected_language": transcription.detected_language,
        "device": request.device,
        "asr_options": {
            "vad_filter": request.vad_filter,
            "condition_on_previous_text": request.condition_on_previous_text,
            "keep_suspected_metadata": request.keep_suspected_metadata,
        },
        "separation_enabled": not request.skip_separation,
        "retain_intermediate": request.retain_intermediate,
        "keep_intermediates": request.retain_intermediate,
        "suspected_metadata_segments": suspected_metadata,
        "duration_seconds": round(time.perf_counter() - started_at, 3),
        "summary": {
            "segment_count": len(transcription.segments),
            "raw_character_count": len(raw_text),
            "cleaned_line_count": len([line for line in cleaned_text.splitlines() if line.strip()]),
            "cleaned_character_count": len(cleaned_text.strip()),
        },
        "outputs": {
            "vocals": str(vocals_path) if vocals_path is not None else None,
            "transcript_raw": str(raw_path),
            "transcript_segments": str(segments_path),
            "transcript_cleaned": str(cleaned_path),
            "report": str(report_path),
        },
        "warnings": warnings,
        "errors": [],
    }
    write_report_json(report, report_path)
    files = {
        "transcript_raw": raw_path,
        "transcript_segments": segments_path,
        "transcript_cleaned": cleaned_path,
        "report": report_path,
    }
    intermediate_files = {"vocals": vocals_path} if vocals_path is not None else {}
    return CandidateLyricsExtractionResult(
        output_dir=output_dir,
        files=files,
        report=report,
        intermediate_files=intermediate_files,
    )


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
