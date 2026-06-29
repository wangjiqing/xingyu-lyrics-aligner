# Xingyu Lyrics Aligner 最佳使用方案

这份 README 面向两类场景：

- 人工为单首歌生成对齐结果；
- 星语音库通过本地命令或 Docker Compose Worker 批量调用对齐器。

默认推荐路径仍是本地 CLI 调用，不引入常驻进程。Docker Worker 是面向星语音库
Docker Compose 部署的可选执行器；它不引入 HTTP 服务、数据库、消息队列或 Docker
Socket。

## 总体原则

- 输入必须是用户确认过的可信歌词，不要把 ASR 候选歌词直接当作可信歌词。
- 对齐主路径只做 forced alignment，不做歌词搜索、不改写歌词、不上传音频。
- 默认输出 `alignment.json`、`lyrics.lrc`、`lyrics.swlrc`、`report.json`。
- 星语音乐盒优先读取 `lyrics.swlrc`，没有 SWLRC 时再回退到 LRC。
- `--lrc-offset-ms` 只影响 `lyrics.lrc`，不影响 `lyrics.swlrc`。
- 单曲人工使用优先直接运行 CLI；星语音库 Docker 部署可启用共享目录 Worker。
- 不启用 Worker 时，对齐器不会增加后台进程。
- 真实音频、真实歌词和生成产物不要提交到 Git。

## 首次准备

```bash
xingyu-align doctor
xingyu-align models status --language zh
xingyu-align models pull --language zh
```

如果 `doctor` 提示缺少 `ffmpeg`，先安装：

```bash
brew install ffmpeg
```

如果命令不可用，确认 `~/.local/bin` 在 `PATH` 中：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## 单首歌人工对齐

准备：

- 音频文件：`/music/song.flac`
- 已人工确认的逐行可信歌词：`/workspace/song.lrc` 或 `/workspace/song.txt`
- 输出目录：`/workspace/alignment-result`

推荐命令：

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --device cpu
```

输出目录中应看到：

```text
alignment.json
lyrics.lrc
lyrics.swlrc
report.json
```

建议检查：

- `lyrics.swlrc` 能被星语音乐盒用于逐字 / 逐词高亮；
- `report.json` 中是否有 `warnings`；
- `estimated_token_count` 是否偏高；
- `skipped_line_count` 是否大于 0。

## 星语音库本地调用

音库一期推荐使用 `--json-result`，stdout 只解析一个 JSON 对象，stderr 进入日志。

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --device cpu \
  --json-result
```

成功时 stdout 形态：

```json
{
  "success": true,
  "output_dir": "/workspace/alignment-result",
  "files": {
    "alignment_json": "/workspace/alignment-result/alignment.json",
    "lrc": "/workspace/alignment-result/lyrics.lrc",
    "swlrc": "/workspace/alignment-result/lyrics.swlrc",
    "report": "/workspace/alignment-result/report.json"
  },
  "summary": {
    "line_count": 0,
    "aligned_line_count": 0,
    "token_count": 0,
    "coverage": 0.0,
    "estimated_token_count": 0,
    "skipped_line_count": 0
  },
  "warnings": []
}
```

失败时：

- 进程退出码非 0；
- stdout 仍尽量是可解析 JSON；
- stderr 保存人类可读错误。

```json
{
  "success": false,
  "error": {
    "code": "INPUT_NOT_FOUND",
    "message": "Audio file does not exist: /music/song.flac"
  }
}
```

音库侧建议：

- 只以 stdout JSON 和退出码作为机器契约；
- 成功后读取 `files.swlrc`；
- 将 `summary` 和 `warnings` 存入导入日志；
- 若 `skipped_line_count > 0` 或 `coverage` 明显偏低，标记为需要人工复核；
- 不依赖 stdout 中的人类提示，因为 `--json-result` 模式下 stdout 预留给 JSON。

## 星语音库 Docker Compose Worker

Docker 部署时可以让音库只写共享任务目录，由 Worker 容器领取任务。Compose 片段：

```yaml
services:
  xingyu-lyrics-aligner-worker:
    image: ghcr.io/wangjiqing/xingyu-lyrics-aligner:${ALIGNER_IMAGE_TAG:-0.3.0}
    command:
      - xingyu-align
      - worker
      - run
      - --jobs-dir
      - /jobs
      - --device
      - cpu
    restart: unless-stopped
    volumes:
      - ${MUSIC_DIR}:/music:ro
      - ${ALIGNMENT_JOBS_DIR}:/jobs
      - ${ALIGNER_MODEL_CACHE_DIR}:/models
```

不要挂载 `/var/run/docker.sock`，不要使用 `privileged: true`。音频目录只读，任务目录和模型缓存目录分开。容器默认以 UID/GID `10001:10001` 运行，宿主机上的
`${ALIGNMENT_JOBS_DIR}` 与 `${ALIGNER_MODEL_CACHE_DIR}` 需要允许该用户写入，或在 Compose
里显式设置兼容的 `user:`。

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

首次使用前预热模型：

```bash
docker run --rm \
  -v "${MUSIC_DIR}:/music:ro" \
  -v "${ALIGNMENT_JOBS_DIR}:/jobs" \
  -v "${ALIGNER_MODEL_CACHE_DIR}:/models" \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.3.0 \
  xingyu-align models pull --language zh --device cpu
```

Worker 任务目录：

```text
/jobs/job-001/
  request.json
  trusted-lyrics.txt
  sections.json
  READY
  status.json
  stderr.log
  result/
    alignment.json
    lyrics.lrc
    lyrics.swlrc
    report.json
```

`request.json` 示例：

```json
{
  "schemaVersion": 1,
  "jobId": "job-001",
  "audioPath": "/music/artist/song.flac",
  "lyricsPath": "/jobs/job-001/trusted-lyrics.txt",
  "outputDir": "/jobs/job-001/result",
  "language": "zh",
  "device": "cpu",
  "sectionManifestPath": null,
  "createdAt": "2026-06-28T00:00:00Z"
}
```

路径限制是机器契约：`audioPath` 必须在 `/music` 下；歌词、section manifest 和输出目录必须在 `/jobs` 下。Worker 通过排他创建
`RUNNING` 后移除 `READY` 领取任务；`status.json` 用临时文件加原子 rename 写入；写入成功状态前会校验 `alignment.json`、`lyrics.lrc`、`lyrics.swlrc` 和
`report.json` 均存在。失败 traceback 写入 `attempts/{attemptId}.stderr.log`，`stderr.log`
是最新 attempt 的便捷副本。最终状态为 `SUCCEEDED`、`NEEDS_REVIEW`、`FAILED` 或
`ABANDONED`。

CPU 是 v0.3.0 的 Docker 默认支持边界。GPU 后续需要单独验证 PyTorch、WhisperX、CUDA
runtime 与宿主机驱动，不在本版本假装完整支持。

## 候选歌词流程

如果没有可信歌词，可以先生成候选歌词供人工复核：

```bash
xingyu-align candidate extract \
  --audio "/music/song.flac" \
  --output-dir "/workspace/prelyrics" \
  --language zh \
  --model medium
```

候选歌词不是可信歌词。推荐流程是：

1. 生成 `transcript.cleaned.txt`；
2. 人工校对歌词文本、分行和版本；
3. 将人工确认后的文本另存为可信歌词；
4. 再执行 `xingyu-align align`。

## 需要分段时

遇到长前奏、间奏、串烧或明显声部切换时，可以使用 section manifest：

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --section-manifest "/workspace/song.sections.json"
```

如果 `report.json` 中出现 `foreground_voice_switch` 或 `section_boundary_review`，
建议人工听一遍相关段落。

## SWLRC 质量判断

SWLRC 使用绝对时间，默认：

```text
[swlrc:1]
[offset:0]
[tokenization:char]
```

中文默认字符级 token；英文在已有词级时间时保留词级 token。

降级规则：

- token 有完整时间：直接导出；
- token 缺时间但行有完整时间：在行内或相邻 token 边界内估算；
- 行级时间缺失：跳过该行，并在报告中记录。

不要把估算 token 理解为模型精确逐字结果。输出质量仍取决于音频、歌词版本、分行和上游对齐质量。

## 覆盖已有输出

默认不会覆盖已有正式输出文件。确实要重跑时使用：

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --device cpu \
  --overwrite
```

`--overwrite` 会覆盖同名的 `alignment.json`、`lyrics.lrc`、`lyrics.swlrc` 和 `report.json`。

## 推荐目录布局

```text
/workspace/song-id/
  trusted-lyrics.txt
  sections.json
  alignment-result/
    alignment.json
    lyrics.lrc
    lyrics.swlrc
    report.json
```

真实音频可以留在音乐库目录，由调用方传入绝对路径。对齐输出建议放在每首歌独立目录，避免批量任务互相覆盖。

## 最小 Python API

CLI 是一期推荐集成方式。后续如果需要内嵌 Python，可使用顶层 API：

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

不要从 `alignment.pipeline`、`formats.swlrc` 等深层内部模块拼装业务调用。

## 快速排查

- 命令找不到：检查 `~/.local/bin` 是否在 `PATH`。
- 模型未准备：运行 `xingyu-align models pull --language zh`。
- 输出目录已有文件：换目录或传入 `--overwrite`。
- SWLRC 缺行：查看 `report.json` 的 `skipped_line_count` 和 `warnings`。
- 高亮不够细：确认歌词语言、tokenization 和 `estimated_token_count`。
- 音乐盒显示偏移：先确认音频和歌词版本，再只对 LRC 使用 `--lrc-offset-ms`；SWLRC offset 后续应单独设计，不复用 LRC 参数。
