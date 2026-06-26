from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from pytest import MonkeyPatch

from xingyu_lyrics_aligner.candidate_lyrics import script_normalization


class FakeOpenCC:
    def __init__(self, config: str) -> None:
        self.config = config

    def convert(self, text: str) -> str:
        if self.config == "t2s":
            return text.replace("聲聲慢", "声声慢").replace("風", "风")
        return text.replace("声声慢", "聲聲慢").replace("风", "風")


def install_fake_opencc(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "opencc", types.SimpleNamespace(OpenCC=FakeOpenCC))


def test_normalize_transcript_writes_zh_hans_copy_without_overwriting_source(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_opencc(monkeypatch)
    source = tmp_path / "transcript.cleaned.txt"
    source.write_text("聲聲慢\n風吹過\n", encoding="utf-8")

    report = script_normalization.normalize_transcript_script(
        source,
        output_dir=None,
        target="zh-Hans",
    )

    assert source.read_text(encoding="utf-8") == "聲聲慢\n風吹過\n"
    output = tmp_path / "transcript.cleaned.zh-Hans.txt"
    assert output.read_text(encoding="utf-8") == "声声慢\n风吹過\n"
    assert report["output"] == str(output)
    assert report["target"] == "zh-Hans"
    assert report["changed"] is True
    report_json = json.loads((tmp_path / "script-normalization.report.json").read_text("utf-8"))
    assert report_json["opencc_config"] == "t2s"


def test_normalize_transcript_supports_custom_output_name(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_opencc(monkeypatch)
    source = tmp_path / "input.txt"
    out = tmp_path / "out"
    source.write_text("声声慢\n", encoding="utf-8")

    report = script_normalization.normalize_transcript_script(
        source,
        output_dir=out,
        target="zh-Hant",
        output_name="candidate.zh-Hant.txt",
    )

    assert (out / "candidate.zh-Hant.txt").read_text(encoding="utf-8") == "聲聲慢\n"
    assert report["opencc_config"] == "s2t"


def test_normalize_transcript_missing_input_is_clear(tmp_path: Path) -> None:
    try:
        script_normalization.normalize_transcript_script(
            tmp_path / "missing.txt",
            output_dir=None,
            target="zh-Hans",
        )
    except script_normalization.ScriptNormalizationError as exc:
        assert "输入文件不存在" in str(exc)
    else:
        raise AssertionError("missing input should raise ScriptNormalizationError")


def test_convert_chinese_script_missing_opencc_is_clear(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "opencc", raising=False)

    original_import_module = script_normalization.importlib.import_module

    def fake_import_module(name: str) -> object:
        if name == "opencc":
            raise ImportError("no opencc")
        return original_import_module(name)

    monkeypatch.setattr(script_normalization.importlib, "import_module", fake_import_module)

    try:
        script_normalization.convert_chinese_script("聲聲慢", "zh-Hans")
    except script_normalization.ScriptNormalizationError as exc:
        assert "未安装 OpenCC" in str(exc)
        assert "opencc-python-reimplemented" in str(exc)
    else:
        raise AssertionError("missing OpenCC should raise ScriptNormalizationError")
