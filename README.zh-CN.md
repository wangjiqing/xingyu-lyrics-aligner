# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner 是一个本地优先的歌词强制对齐工具骨架。用户提供音频文件与可信歌词文本；未来版本会把歌词对齐到音频时间轴，并导出行级 LRC、词级或字级 JSON 时间轴。

v0.1.0 的目标很克制：建立 Python 工程基础、CLI 形状、最小国际化、设备检查、数据模型和文档边界。当前版本不做真实模型推理。

## 当前范围

v0.1.0 已包含：

- Python `src/` layout 与 `pyproject.toml`。
- Typer CLI 入口：`xingyu-align`。
- 命令：`doctor`、`models list`、`models status`、`align`。
- 最小 `en-US` 与 `zh-CN` CLI 文案资源。
- 设备策略定义：`auto`、`cpu`、`cuda`、`mps`。
- 面向未来任务 manifest、模型 manifest、对齐结果与导出结果的 Pydantic 数据模型。
- smoke tests 以及基础 lint、format、type-check 配置。

v0.1.0 不包含：

- Whisper 自动听写或自动识别歌词。
- 人声分离。
- 真实强制对齐。
- 模型下载或内置模型权重。
- 数据库、Web UI 或桌面 UI。

## 开发安装

项目使用 Python `>=3.11,<3.14`。这个范围既能使用较新的 Python 能力，又为未来 macOS Apple Silicon、Windows CUDA 与 CPU 场景下的 PyTorch 生态兼容性留出保守空间。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## CLI 预览

```bash
xingyu-align doctor
xingyu-align models list
xingyu-align models status
xingyu-align align --audio song.wav --lyrics lyrics.txt --device auto --language zh-CN
```

`align` 当前只校验输入，不会伪造任何对齐结果。

语言可以通过环境变量或预留的全局参数切换：

```bash
XINGYU_ALIGN_LOCALE=zh-CN xingyu-align doctor
xingyu-align --locale zh-CN doctor
```

## 计划中的输入输出

计划输入：

- 本地音频文件。
- 用户提供的可信歌词文本，或未来从星语音库边界传入的歌词文本。
- 可选设备与语言提示。

计划输出：

- 行级 LRC。
- 包含行级、词级、字级映射的内部 JSON。
- 面向人工校对流程的 confidence 与 review status 字段。
- 任务 manifest，记录 audio hash、lyrics hash、device、model version、language、alignment mode、created time。

## 本地优先原则

音频与歌词默认应在本地处理。项目核心对齐流程不应把音频上传到第三方 API。

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。

## 开发检查

```bash
ruff format .
ruff check .
mypy
pytest
```
