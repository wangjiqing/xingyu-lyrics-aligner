"""Script normalization for candidate lyric transcripts."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path


class ScriptNormalizationError(RuntimeError):
    """User-facing normalization failure."""


def build_script_normalization_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="为候选歌词生成独立的中文字形规范化副本，不覆盖 ASR 原始产物。"
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="输入候选歌词文件，例如 transcript.cleaned.txt。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录。默认使用输入文件所在目录。",
    )
    parser.add_argument(
        "--to",
        choices=["zh-Hans", "zh-Hant"],
        default="zh-Hans",
        help="目标中文字形。默认 zh-Hans。",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="输出文件名。默认 transcript.cleaned.zh-Hans.txt 或 zh-Hant。",
    )
    return parser


def convert_chinese_script(text: str, target: str) -> tuple[str, str]:
    """Convert Chinese script with OpenCC and return converted text plus config."""

    try:
        opencc_module = importlib.import_module("opencc")
    except ImportError as exc:
        raise ScriptNormalizationError(
            "未安装 OpenCC。请执行 `python -m pip install opencc-python-reimplemented`。"
        ) from exc

    config = "t2s" if target == "zh-Hans" else "s2t"
    converter = opencc_module.OpenCC(config)
    return str(converter.convert(text)), config


def default_output_name(target: str) -> str:
    return f"transcript.cleaned.{target}.txt"


def normalize_transcript_script(
    input_path: Path,
    *,
    output_dir: Path | None,
    target: str,
    output_name: str | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    resolved_input = input_path.expanduser().resolve()
    if not resolved_input.exists():
        raise ScriptNormalizationError(f"输入文件不存在：{resolved_input}")
    if not resolved_input.is_file():
        raise ScriptNormalizationError(f"输入路径不是文件：{resolved_input}")

    resolved_output_dir = (
        output_dir.expanduser().resolve() if output_dir is not None else resolved_input.parent
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    source_text = resolved_input.read_text(encoding="utf-8")
    converted_text, opencc_config = convert_chinese_script(source_text, target)

    output_path = resolved_output_dir / (output_name or default_output_name(target))
    report_path = resolved_output_dir / "script-normalization.report.json"
    output_path.write_text(converted_text, encoding="utf-8")

    report: dict[str, object] = {
        "input": str(resolved_input),
        "output": str(output_path),
        "target": target,
        "converter": "opencc",
        "opencc_config": opencc_config,
        "changed": converted_text != source_text,
        "duration_seconds": round(time.perf_counter() - started_at, 3),
        "warnings": ["这是候选歌词的字形规范化副本，不是可信歌词，不会覆盖 ASR 原始产物。"],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = build_script_normalization_parser()
    args = parser.parse_args(argv)
    try:
        report = normalize_transcript_script(
            args.input,
            output_dir=args.output_dir,
            target=args.to,
            output_name=args.output_name,
        )
    except ScriptNormalizationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"字形规范化候选歌词已写入：{report['output']}")
    print("原始 transcript.cleaned.txt 未被覆盖。")
    return 0
