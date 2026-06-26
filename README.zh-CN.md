# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner 是本地优先的可信歌词对齐 CLI。v0.1.1 支持把本地音频与用户提供的逐行可信歌词直接对齐，并导出精简 JSON 时间轴与标准行级 LRC。

普通用户推荐使用：

```bash
xingyu-align
```

`xingyu-lyrics-aligner` 会作为兼容别名保留。`python -m xingyu_lyrics_aligner.cli` 只建议放在开发或故障排查场景中。

## v0.1.1 能做什么

- 读取本地音频文件和逐行可信歌词文本。
- 构建中文 CTC alignment text，但不改写 display lyrics。
- 使用 WhisperX CTC forced alignment，不运行 ASR 听写。
- 导出 `alignment.json`、`lyrics.lrc`、`report.json`。
- 可选使用手工 section manifest 做结构化分段对齐。

## 运行边界与已知限制

- ASR transcription 不是默认主路径。
- 不联网匹配歌词，不改写用户歌词，不上传音频。
- v0.1.1 不包含 Demucs、UVR、GUI、数据库或 Web 服务。
- macOS 上请求 MPS 时，WhisperX alignment 可能回退 CPU。
- macOS 安装脚本不承诺 Windows CUDA。
- LRC 行级展示可能受播放器实现影响，不同播放器对行间滚动的处理可能不同。
- 复杂独白、重叠前景声部和手工 section 边界仍需人工复核；请关注
  `foreground_voice_switch` 与 `section_boundary_review` warning。
- 人声分离不是 v0.1.1 默认能力。
- 真实音频、歌词、LRC、JSON 时间轴和模型缓存不要提交到 Git。

## macOS 快捷安装

安装脚本面向 macOS Apple Silicon / CPU 路线，只支持从源码仓库安装。它不会安装 Homebrew，不会修改 shell 配置，也不会自动下载模型。

```bash
git clone https://github.com/wangjiqing/xingyu-lyrics-aligner.git
cd xingyu-lyrics-aligner
./scripts/install-macos.sh
```

也可以直接从 GitHub v0.2.0 tag 安装：

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.2.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.2.0
```

包含候选歌词可选依赖：

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.2.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.2.0 --candidate-lyrics
```

安装时选择并保存默认 CLI 语言：

```bash
./scripts/install-macos.sh --locale zh-CN
```

如果缺少 `ffmpeg`，请自行安装：

```bash
brew install ffmpeg
```

如果 `~/.local/bin` 不在 `PATH`，安装脚本会打印可复制的 zsh 命令：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

安装后：

```bash
xingyu-align doctor
xingyu-align models pull --language zh
xingyu-align align --help
```

模型、缓存、配置和启动器路径细节见
[运行时环境](docs/runtime-environment.zh-CN.md)。

之后也可以修改已保存的 CLI 语言：

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

从 GitHub 更新：

```bash
xingyu-align update --run
xingyu-align update --candidate-lyrics --ref v0.2.0 --run
```

## 手动开发安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,alignment]"
```

开发者兜底入口：

```bash
python -m xingyu_lyrics_aligner.cli --help
```

## doctor

```bash
xingyu-align doctor
```

用于检查 Python、系统、CPU/GPU 能力提示和 `ffmpeg`。

## 模型下载

检查中文对齐模型状态：

```bash
xingyu-align models status --language zh
```

显式下载或预热中文 alignment model：

```bash
xingyu-align models pull --language zh
```

`pull` 会在下载前显示模型名称、来源和体积提示；它不会运行 ASR，也不会生成歌曲结果。

## 最小对齐命令

```bash
xingyu-align align \
  --audio "/path/to/song.flac" \
  --lyrics "/path/to/song.txt" \
  --output-dir "/path/to/output" \
  --language zh
```

使用手工 section manifest：

```bash
xingyu-align align \
  --audio "/path/to/song.flac" \
  --lyrics "/path/to/song.txt" \
  --output-dir "/path/to/output" \
  --language zh \
  --section-manifest "/path/to/song.sections.json"
```

真实歌曲输出请写到仓库外，或写到已 ignored 的 `local_output/` 等目录。

## 输出文件说明

- `alignment.json`：后续逐字高亮的核心时间轴，保留可信歌词原文和 token 时间。
- `lyrics.lrc`：标准行级 LRC。`--lrc-offset-ms` 只影响这个文件。
- `report.json`：统计、warning、模型和设备信息，不复制整首歌词。

## SWLRC

SWLRC（`.swlrc`）是 Xingyu Lyrics Aligner 定义并输出的增强逐字 / 逐词歌词格式，
供星语音库与星语音乐盒使用。v1 规范见
[docs/specs/swlrc-v1.md](docs/specs/swlrc-v1.md)，可阅读样例见
[docs/examples](docs/examples)。

## 候选歌词

可选脚本可以从本地音频生成 ASR 候选歌词，供人工复核使用。候选歌词不会替代可信歌词，也不会生成 SWLRC。参见
[候选歌词提取脚本](docs/guides/candidate-lyrics.md)。

## 从任意目录调用

macOS 安装脚本会创建：

```text
~/.local/bin/xingyu-align
```

它稳定指向当前源码仓库的 `.venv`，因此可以：

```bash
cd /tmp
xingyu-align --help
```

## 常见问题

### 找不到命令

确认 `~/.local/bin` 在 `PATH`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 缺少 ffmpeg

请手动安装：

```bash
brew install ffmpeg
```

### 模型未准备

运行：

```bash
xingyu-align models pull --language zh
```

### MPS 回退 CPU

这是当前 macOS WhisperX CTC alignment 路线的预期限制。结果元数据会记录 requested device 与 actual alignment device。

### 输出目录已存在

换一个输出目录，或显式传入：

```bash
--overwrite
```

### Git 安全

不要提交真实音频、可信歌词、生成的 LRC、完整 JSON 时间轴、模型缓存、stems 或 `local_output/`。

## 开发检查

```bash
ruff check .
pytest
bash -n scripts/install-macos.sh
```

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。
