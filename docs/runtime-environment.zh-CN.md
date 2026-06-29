# 运行时环境

本文档说明 v0.1.1 的运行路径、模型选择和配置边界，用于安装审查与故障排查。

## CLI 入口

普通用户推荐命令：

```bash
xingyu-align
```

兼容别名：

```bash
xingyu-lyrics-aligner
```

两个入口都指向同一个 Typer 应用：

```text
xingyu_lyrics_aligner.cli:app
```

开发兜底入口：

```bash
python -m xingyu_lyrics_aligner.cli
```

## 用户偏好

CLI 可以把用户偏好保存到：

```text
~/.config/xingyu-lyrics-aligner/config.json
```

当前会保存：

```json
{
  "locale": "zh-CN"
}
```

语言优先级：

```text
--locale 参数
> XINGYU_ALIGN_LOCALE 环境变量
> 已保存的用户配置
> en-US 默认值
```

设置或查看已保存偏好：

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

macOS 安装脚本也支持：

```bash
./scripts/install-macos.sh --locale zh-CN
```

交互式运行且未传 `--locale` 时，安装脚本会询问默认 CLI 语言并保存选择。

## 对齐模型

v0.1.1 的中文可信歌词 CTC 对齐使用：

```text
jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
```

来源：

```text
https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
```

模型通过 WhisperX `load_align_model` 加载。`models pull` 只下载或预热
alignment model，不运行 ASR 听写，也不生成歌曲输出。

下载体积由 Hugging Face 上游模型文件决定，可能在本项目之外变化。

## 模型缓存

项目不内置模型权重。Hugging Face 与 Transformers 决定默认缓存位置，通常在用户 home 下，例如：

```text
~/.cache/huggingface/
```

可使用 Hugging Face 生态的环境变量覆盖，例如：

```bash
export HF_HOME="/path/to/hf-cache"
export HUGGINGFACE_HUB_CACHE="/path/to/hf-cache/hub"
```

Xingyu Lyrics Aligner 不删除模型缓存。

## 项目安装目录

macOS 安装脚本支持源码仓库模式和 GitHub 安装模式。

源码仓库模式会创建或复用：

```text
<repo>/.venv/
```

editable install 指向当前源码仓库。如果移动或删除仓库，launcher 可能失效，需要重新运行安装脚本。

GitHub 安装模式会创建或复用：

```text
~/.local/share/xingyu-lyrics-aligner/venv/
```

它会从 `main`、`v0.3.0` 等 Git ref 安装。

## 用户级启动器

macOS 安装脚本会创建：

```text
~/.local/bin/xingyu-align
```

该启动器是一个小 wrapper，实际执行：

```text
<repo>/.venv/bin/xingyu-align
```

GitHub 安装模式下，launcher 指向：

```text
~/.local/share/xingyu-lyrics-aligner/venv/bin/xingyu-align
```

安装脚本不会修改 shell 配置。如果 `~/.local/bin` 不在 `PATH`，需要用户手动加入。

## 输出目录

输出目录由用户指定：

```bash
xingyu-align align --output-dir "/path/to/output"
```

v0.3.0 会写入：

```text
alignment.json
lyrics.lrc
lyrics.swlrc
report.json
```

使用 `--debug-output` 时，还可能写入：

```text
debug.summary.json
```

如需覆盖已有输出文件，必须显式传入 `--overwrite`。

## 配置边界

v0.1.1 有一个很小的用户偏好文件，用于保存默认语言等行为偏好。
对齐任务参数仍通过 CLI 参数传入：

- `--language`
- `--device`
- `--section-manifest`
- `--lrc-offset-ms`
- `--overwrite`
- `--debug-output`

现有 `config.py` 是预留模块，尚未接入 v0.1.1 runtime commands。

## 设备行为

用户可见设备选项：

```text
auto
cpu
cuda
mps
```

对 WhisperX CTC alignment 来说，`mps` 可能回退 CPU。输出会记录 requested device 与 actual alignment device。

## 安装器不会管理的文件

安装器和卸载脚本不会删除：

- `.venv/`
- Hugging Face 模型缓存；
- 对齐输出；
- 用户音乐文件；
- 可信歌词文件。

`scripts/uninstall-macos.sh` 只删除用户级 launcher：

```text
~/.local/bin/xingyu-align
```
