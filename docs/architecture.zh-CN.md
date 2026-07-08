# 架构摘要

Xingyu Lyrics Aligner 是本地优先的 CLI 与 Worker 项目。星语音库集成边界保持在文件系统：上层系统创建 `/jobs/{jobId}` 任务目录，Worker 读取 `request.json`，写入状态、事件、stderr 和结果文件。

## 主要流程

可信歌词对齐：

```text
可信歌词 + 音频
  -> alignment pipeline
  -> alignment.json + lyrics.lrc + lyrics.swlrc + report.json
```

候选歌词草稿提取：

```text
音频
  -> 可选 Demucs 人声分离
  -> faster-whisper 转写
  -> transcript.cleaned.txt + transcript.raw.txt + transcript.segments.json
```

候选歌词是供人工校对的非可信文本，不会替代可信歌词对齐流程，也不会直接生成 SWLRC。

## 分层

- `cli.py`：Typer 命令、参数解析和面向用户的输出。
- `worker.py`：共享目录协议、排他领取、路径校验、状态/事件写入、基于 heartbeat 的 stale 判定和任务分发。
- `alignment/`：可信歌词对齐 pipeline 与 LRC/SWLRC 导出。
- `candidate_lyrics/transcription.py`：CLI 与 Worker 共用的候选歌词提取服务。
- `candidate_lyrics/config.py`：CLI 与 Worker 共用的草稿提取 preset 与 override resolver。
- `candidate_lyrics/script_normalization.py`：候选文本的简体/繁体复核副本生成。
- `schemas/`：对齐、manifest 与 report 的结构化模型。
- `i18n/`：JSON 翻译资源与查询函数。

Worker 不实现第二套 ASR 路径。`LYRIC_DRAFT_EXTRACTION` 委托给与 `xingyu-align candidate extract` 相同的 `CandidateLyricsExtractionService`。

## Worker 协议边界

`schemaVersion: 1` 保留给 v0.3.0 对齐任务。`schemaVersion: 2` 要求 `taskType`。`schemaVersion: 3` 为草稿提取增加 `preset` 与 `overrides`，同时兼容 v1/v2。支持的任务类型：

- `LYRICS_ALIGNMENT`
- `LYRIC_DRAFT_EXTRACTION`

Worker 路径校验比普通 CLI 更严格：

- 音频必须解析到 `--music-dir` 下；
- 歌词和 section manifest 必须解析到当前 job 目录下；
- 输出目录必须精确等于当前 job 的 `result/`；
- 拒绝 symlink 和 `../` 逃逸。

`status.json` 是唯一当前状态快照，并使用临时文件、flush、fsync 和原子 rename 写入。`events.jsonl` 是追加式生命周期事件流。stale 判定优先使用 `status.json.heartbeatAt`，仅在状态文件缺失或损坏时回退到旧 `RUNNING` marker mtime。
