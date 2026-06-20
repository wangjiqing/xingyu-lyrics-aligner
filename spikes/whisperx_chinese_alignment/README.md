# WhisperX Chinese Alignment Spike

This directory is a technical spike only. It is not v0.1.1 product code and does not change the main CLI.

The goal is to test whether WhisperX, or a close Chinese alignment alternative, can align local audio against already trusted Chinese lyrics text and emit line-level plus token-level timings.

## Setup

Use Python `>=3.10,<3.14`; Python 3.11 was used on macOS Apple Silicon.

```bash
cd spikes/whisperx_chinese_alignment
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`ffmpeg` must be installed and on `PATH`.

## Sample Audio

The committed repository intentionally does not include audio. To create a local, copyright-safe spoken Chinese proxy sample on macOS:

```bash
cd spikes/whisperx_chinese_alignment
say -v Tingting -r 145 -o sample_input/sample.aiff "星语在夜里发光。我们听见时间流淌。星语在夜里发光。把每个字轻轻照亮。"
ffmpeg -y -i sample_input/sample.aiff -ar 16000 -ac 1 sample_input/sample.wav
```

This is spoken TTS, not singing. It is enough to verify the alignment API and Chinese character timestamp behavior, but not enough to validate real singing robustness.

In the macOS desktop sandbox used for this spike, `say` produced empty audio containers. The actual run therefore used a non-committed synthetic Edge TTS sample:

```bash
python -m pip install edge-tts
edge-tts --voice zh-CN-XiaoxiaoNeural \
  --text "星语在夜里发光。我们听见时间流淌。星语在夜里发光。把每个字轻轻照亮。" \
  --write-media sample_input/sample.mp3
ffmpeg -y -i sample_input/sample.mp3 -ar 16000 -ac 1 sample_input/sample.wav
```

Do not commit generated audio.

## Run

CPU fallback on macOS:

```bash
cd spikes/whisperx_chinese_alignment
source .venv/bin/activate
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device cpu --compute-type int8 --language zh
```

After models are cached, offline/cache-only CPU alignment:

```bash
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device cpu --compute-type int8 --language zh --model-cache-only
```

Experimental MPS attempt:

```bash
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device mps --compute-type int8 --language zh
```

On the tested macOS 26.5.1 + torch 2.8.0 environment this failed while moving the wav2vec2 alignment model to MPS. Treat CPU as the validated Apple Silicon fallback for now.

Windows CUDA expected path:

```powershell
cd spikes\whisperx_chinese_alignment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_spike.py --audio sample_input\sample.wav --lyrics sample_input\sample_lyrics.txt --device cuda --compute-type float16 --language zh
```

## Outputs

The script writes:

- `sample_output/alignment.raw.json`
- `sample_output/alignment.normalized.json`
- `sample_output/sample.lrc`
- `sample_output/report.md`

Large model files, generated audio, and local caches must not be committed.
