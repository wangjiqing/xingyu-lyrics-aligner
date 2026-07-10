# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner 是本地优先的可信歌词对齐 CLI。v0.6.0 支持把本地音频与用户提供的逐行可信歌词直接对齐，正式定义 SWLRC v1，保留可选的 ASR 候选歌词提取能力，并提供官方 CPU Docker 镜像与可选共享目录 Worker，供 Docker Compose 部署接入。Worker 也可以从音频提取未对齐候选歌词草稿，并持续向上层系统暴露状态、阶段、心跳、事件、配置、结果与失败原因。

普通用户推荐使用：

v0.6.0 会在 CTC 前区分标准 LRC metadata、`NON_LYRIC_HEADER` 和正式演唱歌词。保守识别的
文件头署名块不会消耗对齐字符或 section 演唱行号，原文会保留到 LRC 和结构化结果，但不
生成 SWLRC token。新增的 `firstAlignedLyricStartMs`、`preservedHeaderLines` 和可选
`presentationHints` 均为向后兼容字段；建议时间仅供前奏展示，不属于歌词时间轴。

```bash
xingyu-align
```

`xingyu-lyrics-aligner` 会作为兼容别名保留。`python -m xingyu_lyrics_aligner.cli` 只建议放在开发或故障排查场景中。

## v0.6.0 能做什么

- 读取本地音频文件和逐行可信歌词文本。
- 构建中文 CTC alignment text，但不改写 display lyrics。
- 使用 WhisperX CTC forced alignment，不运行 ASR 听写。
- 导出 `alignment.json`、`lyrics.lrc`、`lyrics.swlrc`、`report.json`。
- 可选使用手工 section manifest 做结构化分段对齐。
- 在官方 CPU Docker 镜像中运行同一套 `xingyu-align` CLI。
- 可选运行 `xingyu-align worker run`，通过共享 `/jobs` 目录服务星语音库 Docker Compose 部署。
- 让 Worker 处理 `LYRIC_DRAFT_EXTRACTION` 任务，把音频转换为未对齐候选歌词草稿。
- 通过 `/jobs/{jobId}/status.json` 暴露 Worker 当前状态快照，并通过
  `/jobs/{jobId}/events.jsonl` 暴露生命周期事件流。
- 定义并校验 SWLRC v1：面向星语音库与星语音乐盒的增强逐字 / 逐词歌词格式。
- 可选通过 Demucs 人声分离与 faster-whisper 从音频提取 ASR 候选歌词，仅供人工复核。
- 可额外生成简体或繁体候选歌词副本，不覆盖原始 ASR 输出。

## 运行边界与已知限制

- ASR transcription 只存在于显式的 `candidate extract` 工作流中，不属于可信歌词对齐默认主路径。
- 不联网匹配歌词，不改写用户歌词，不上传音频。
- Demucs 只用于可选的候选歌词流程。v0.5.0 不包含 UVR、GUI、数据库、HTTP 服务、消息队列或 Docker Socket 访问。
- 默认 CLI 路径不引入常驻进程；Docker Worker 是面向音库集成的可选部署模式。
- macOS 上请求 MPS 时，WhisperX alignment 可能回退 CPU。
- macOS 安装脚本不承诺 Windows CUDA。
- LRC 行级展示可能受播放器实现影响，不同播放器对行间滚动的处理可能不同。
- SWLRC token 时间质量取决于上游对齐结果。缺失 token 时间时可能根据行级时间估算；
  行级时间缺失时会跳过该行，并在 `report.json` 中记录 warning。
- 复杂独白、重叠前景声部和手工 section 边界仍需人工复核；请关注
  `foreground_voice_switch` 与 `section_boundary_review` warning。
- 人声分离不属于可信歌词对齐流程。
- 真实音频、歌词、LRC、JSON 时间轴和模型缓存不要提交到 Git。

## macOS 快捷安装

安装脚本面向 macOS Apple Silicon / CPU 路线，只支持从源码仓库安装。它不会安装 Homebrew，不会修改 shell 配置，也不会自动下载模型。

```bash
git clone https://github.com/wangjiqing/xingyu-lyrics-aligner.git
cd xingyu-lyrics-aligner
./scripts/install-macos.sh
```

也可以直接从 GitHub v0.6.0 tag 安装：

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.6.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.6.0
```

包含候选歌词可选依赖：

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.6.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.6.0 --candidate-lyrics
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
xingyu-align help
xingyu-align align -h
```

模型、缓存、配置和启动器路径细节见
[运行时环境](docs/runtime-environment.zh-CN.md)。

日常使用和星语音库本地集成建议见
[最佳使用方案](docs/guides/best-usage.zh-CN.md)。

之后也可以修改已保存的 CLI 语言：

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

从 GitHub 更新：

```bash
xingyu-align update --run
xingyu-align update --candidate-lyrics --ref v0.6.0 --run
```

## 手动开发安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,alignment]"
```

开发者兜底入口：

```bash
python -m xingyu_lyrics_aligner.cli -h
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

默认输出：

```text
alignment.json
lyrics.lrc
lyrics.swlrc
report.json
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

如果需要给星语音库等本地程序调用，传入 `--json-result`。stdout 只输出一个 JSON
对象；人类可读日志和错误信息写 stderr。

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --device cpu \
  --json-result
```

成功 JSON 包含 `success`、`output_dir`、`files`、`summary` 和 `warnings`。失败时进程返回
非 0，stdout 仍尽量输出可解析 JSON，其中包含 `success: false` 和 `error`。

## Docker CLI

官方 CPU 镜像发布在：

```text
ghcr.io/wangjiqing/xingyu-lyrics-aligner
docker.io/<DOCKERHUB_USERNAME>/xingyu-lyrics-aligner
```

本文默认示例使用 GHCR。发布 workflow 会把同一组版本标签同步推送到 Docker Hub：
`0.6.0`、`0.6`、`latest` 和 `v0.6.0`。
镜像发布 `linux/amd64` 与 `linux/arm64` 多架构 manifest，Apple Silicon Mac 会默认拉取
ARM64 镜像。

运行 doctor：

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.5.0 \
  xingyu-align doctor
```

预热中文对齐模型：

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.5.0 \
  xingyu-align models pull --language zh --device cpu
```

单次对齐：

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.5.0 \
  xingyu-align align \
    --audio /music/song.flac \
    --lyrics /jobs/job-001/trusted-lyrics.txt \
    --output-dir /jobs/job-001/result \
    --language zh \
    --device cpu \
    --json-result
```

镜像以非 root 的 UID/GID `10001:10001` 运行。`/music` 应只读挂载，`/jobs` 与
`/models` 需要可写，`/models` 建议持久化以复用模型缓存。镜像构建阶段不会下载模型。

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

## Docker Worker

星语音库 Docker Compose 部署可启用可选 Worker。v0.5.0 支持两类任务：

- `LYRICS_ALIGNMENT`：可信歌词 + 音频 -> `alignment.json`、LRC、SWLRC。
- `LYRIC_DRAFT_EXTRACTION`：音频 -> 未对齐 ASR 候选歌词文本，供人工校对；它不是可信歌词。

```bash
xingyu-align worker run --jobs-dir /jobs --music-dir /music --device cpu
```

schema v1 请求仍然视为对齐任务。schema v2 请求继续兼容。schema v3 为草稿提取新增 `preset` 与 `overrides`。Worker 通过排他创建 `RUNNING` 后移除 `READY` 来领取任务；`status.json` 使用临时文件加 flush、fsync 和原子 rename 写入；追加 `events.jsonl`；stderr 按 attempt 保留；并写入 `SUCCEEDED`、`FAILED`、`NEEDS_REVIEW` 或 `ABANDONED` 终态 marker。草稿提取任务不会写 `NEEDS_REVIEW`；候选歌词是否确认可信属于音库业务流程。

`status.json` 是唯一当前状态快照，包含 `statusSchemaVersion`、`requestSchemaVersion`、`state`、`stage`、`startedAt`、`stageStartedAt`、`updatedAt`、`heartbeatAt`、`requestedConfig`、`resolvedConfig`、`warnings`、`error` 和 `result` 等稳定字段。`events.jsonl` 是追加式生命周期事件流，用于观察状态切换和 warning，不替代 `stderr.log` 或 `attempts/{attemptId}.stderr.log`。只要 `heartbeatAt` 新鲜，上层应把长任务视为仍在运行；本版不会为模型加载、人声分离或 CTC 对齐伪造百分比进度。

草稿提取会在 `/jobs/{jobId}/result` 下写入 `transcript.cleaned.txt`、`transcript.raw.txt`、`transcript.segments.json` 和 `report.json`。Worker 默认在任务结束后清理人声分离中间文件；仅当 `retainIntermediate: true` 时，`vocals.wav` 会保留在 `/jobs/{jobId}/intermediate`，不会放入 `result`。

Worker 只允许读取 `/music` 下的音频路径，只允许读写 `/jobs` 和 `/models`。它不是 HTTP 服务，不暴露端口，不使用数据库、消息队列或 `/var/run/docker.sock`。v0.5.0 镜像同时安装 alignment 与 candidate-lyrics 依赖，包括 faster-whisper、Demucs 和 TorchCodec，因此比 v0.3.0 更大；首次运行可能下载或预热模型，CPU 草稿提取会比普通对齐更慢、临时磁盘占用也更高。详见
[Docker Worker 协议](docs/docker-worker.md) 和
[Compose 示例](deploy/docker-compose.worker.example.yml)。

## 候选歌词命令

候选歌词是可选的 ASR 输出，用来辅助人工复核。先安装候选歌词依赖：

```bash
python -m pip install -e ".[candidate-lyrics]"
```

提取候选歌词：

```bash
xingyu-align candidate extract \
  --audio "/path/to/song.flac" \
  --output-dir "/path/to/prelyrics" \
  --language zh \
  --preset recommended
```

该命令会输出 `vocals.wav`、`transcript.raw.txt`、`transcript.segments.json`、
`transcript.cleaned.txt` 和 `report.json`。如需跳过 Demucs，可传入
`--skip-separation` 直接转写原始混音音频。

草稿提取预设包括 `fast`、`recommended`、`high-quality` 和
`full-recognition`。`fast` 使用较小 ASR 模型并跳过分离；`recommended`
使用 `medium`、跳过分离并开启 VAD；`high-quality` 使用 `medium` 且启用人声分离；
`full-recognition` 保留分离但关闭 VAD，以减少弱人声、念白和非标准片段被过滤的概率。
`full-recognition` 不等于绝对最高准确度。`--model large-v3`、`--skip-separation`
和 `--no-vad` 等高级参数会覆盖预设。`large-v3` 仍可作为高级模型名使用，但因为更慢、
占用更多内存和磁盘，不进入普通预设。

生成简体或繁体复核副本：

```bash
xingyu-align candidate normalize \
  --input "/path/to/prelyrics/transcript.cleaned.txt" \
  --output-dir "/path/to/prelyrics" \
  --to zh-Hans

xingyu-align candidate normalize \
  --input "/path/to/prelyrics/transcript.cleaned.txt" \
  --output-dir "/path/to/prelyrics" \
  --to zh-Hant
```

这些文件仅用于人工复核、在线歌词比对和后续对齐准备，不是可信歌词。

## 输出文件说明

- `alignment.json`：后续逐字高亮的核心时间轴，保留可信歌词原文和 token 时间。
- `lyrics.lrc`：标准行级 LRC。`--lrc-offset-ms` 只影响这个文件。
- `lyrics.swlrc`：SWLRC v1 逐字 / 逐词高亮输出，使用绝对时间，并固定写入
  `[swlrc:1]`、`[offset:0]` 和 `[tokenization:...]`。`--lrc-offset-ms` 不会作用于
  SWLRC。
- `report.json`：统计、warning、模型和设备信息，不复制整首歌词。
  SWLRC 的 warning、估算 token 数和跳过行数也会记录在这里。

## SWLRC

SWLRC（`.swlrc`）是 Xingyu Lyrics Aligner 定义并输出的增强逐字 / 逐词歌词格式，
供星语音库与星语音乐盒使用。v1 规范见
[docs/specs/swlrc-v1.md](docs/specs/swlrc-v1.md)，可阅读样例见
[docs/examples](docs/examples)。

中文默认输出 `tokenization:char`；如果上游对齐结果中中文是词级 token，导出时会拆成字符
token 以便逐字高亮。英文和其他非中文歌词在已有词级时间时保留词级 token。若 token
缺时间但行级时间完整，导出器会在该行范围内估算并记录数量；若行级时间也缺失，则跳过该行，
不伪造合法时间。

## Python API

```python
from xingyu_lyrics_aligner import align_lyrics

result = align_lyrics(
    audio_path="/music/song.flac",
    lyrics_path="/workspace/song.lrc",
    output_dir="/workspace/alignment-result",
    language="zh",
    device="cpu",
)

print(result.files["swlrc"])
```

返回对象包含结构化文档、输出路径和 SWLRC 导出统计。星语音库一期建议优先通过
`--json-result` 调用 CLI，保持进程隔离；后续如需内嵌，可使用该 API，避免 import 深层内部模块。

## 候选歌词

`xingyu-align candidate` 命令可以从本地音频生成 ASR 候选歌词，供人工复核使用。候选歌词不会替代可信歌词，也不会生成 SWLRC。参见
[候选歌词指南](docs/guides/candidate-lyrics.md)。

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
