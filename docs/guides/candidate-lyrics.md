# 候选歌词提取

本命令用于从歌曲音频生成 ASR 候选歌词，辅助人工听写、人工检索和后续对齐准备。

它不会替代可信歌词原文，不会接入正式 WhisperX / CTC 对齐主流程，也不会生成 `.swlrc`。

## 安装

候选歌词能力是可选依赖：

```bash
python -m pip install -e ".[candidate-lyrics]"
```

还需要系统中存在 `ffmpeg`。macOS 可使用：

```bash
brew install ffmpeg
```

## 提取候选歌词

```bash
xingyu-align candidate extract \
  --audio "/path/to/song.flac" \
  --output-dir "/path/to/output" \
  --language zh \
  --model medium
```

输出文件：

- `vocals.wav`：Demucs 分离出的人声文件；使用 `--skip-separation` 时不会生成；
- `transcript.raw.txt`：ASR 原始拼接文本；
- `transcript.segments.json`：ASR segment 列表，包含开始、结束、文本与可用词级时间；
- `transcript.cleaned.txt`：基础清洗后的候选歌词文本；
- `report.json`：输入、模型、语言、ASR 参数、是否人声分离、疑似署名片段和 warning。

默认行为：

- 使用 Demucs 分离人声；
- 使用 faster-whisper 转写；
- 开启 VAD，减少静音、间奏和残响幻觉；
- 关闭 previous-text conditioning，减少跨段续写幻觉；
- 从 `transcript.cleaned.txt` 中剔除疑似 `词曲`、`作词`、`作曲`、`字幕` 等非歌词署名片段；
- 原始内容仍保留在 `transcript.raw.txt` 与 `transcript.segments.json` 中。

调试参数：

- `--skip-separation`：跳过 Demucs，直接转写原音频；
- `--no-vad`：关闭 faster-whisper VAD；
- `--condition-on-previous-text`：允许 ASR 参考前文继续生成；
- `--keep-suspected-metadata`：在 cleaned 文本中保留疑似署名片段。

## 生成简体副本

为了人工检索或比对，可以额外生成简体字形副本。该步骤不会覆盖 `transcript.cleaned.txt`。

```bash
xingyu-align candidate normalize \
  --input "/path/to/output/transcript.cleaned.txt" \
  --output-dir "/path/to/output" \
  --to zh-Hans
```

输出文件：

- `transcript.cleaned.zh-Hans.txt`
- `script-normalization.report.json`

## 人工检索

当 ASR 候选歌词准确度差距较大时，可以人工打开歌词搜索页查找参考文本：

- https://www.lrcgc.com/so

推荐流程：

1. 用歌曲名和歌手名搜索；
2. 人工复制参考歌词到本地临时文件；
3. 对照 `transcript.cleaned.txt` 和 `transcript.cleaned.zh-Hans.txt` 审核差异；
4. 只有人工确认版本、来源和合法性后，才可进入可信歌词或后续 SWLRC 对齐准备。

## 边界

候选歌词不是可信歌词。脚本输出只能用于人工确认、在线歌词比对或后续对齐辅助，不应直接发布为正式歌词，也不应直接写入星语音库。
