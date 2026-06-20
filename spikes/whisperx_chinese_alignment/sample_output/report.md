# WhisperX Chinese Alignment Spike Report

## 1. Environment

- Date: 2026-06-20
- Machine: macOS 26.5.1, Apple Silicon arm64
- Python: 3.11.15
- FFmpeg: `/opt/homebrew/bin/ffmpeg` 8.1
- Tested package set:
  - `whisperx==3.8.6`
  - `torch==2.8.0`
  - `torchaudio==2.8.0`
  - `torchvision==0.23.0`
  - `torchcodec==0.7.0`
  - `faster-whisper==1.2.1`
  - `ctranslate2==4.8.0`
  - `transformers==4.57.6`
  - `pyannote-audio==4.0.4`
  - `nltk==3.9.4`
  - `numpy==2.4.6`
  - `pandas==3.0.3`

## 2. Commands

```bash
cd spikes/whisperx_chinese_alignment
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The macOS `say` command produced empty audio in this sandbox, so the actual non-committed synthetic sample was generated with Edge TTS:

```bash
python -m pip install edge-tts
edge-tts --voice zh-CN-XiaoxiaoNeural \
  --text "星语在夜里发光。我们听见时间流淌。星语在夜里发光。把每个字轻轻照亮。" \
  --write-media sample_input/sample.mp3
ffmpeg -y -i sample_input/sample.mp3 -ar 16000 -ac 1 sample_input/sample.wav
```

Baseline ASR plus alignment:

```bash
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device cpu --compute-type int8 --language zh --asr-model tiny --model-cache-only
```

Trusted lyrics alignment only:

```bash
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device cpu --compute-type int8 --language zh --skip-asr --model-cache-only
```

MPS attempt:

```bash
python run_spike.py --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device mps --compute-type int8 --language zh --skip-asr --model-cache-only
```

## 3. Model

- WhisperX: <https://github.com/m-bain/whisperX>, BSD-2-Clause.
- WhisperX 3.8.6 requires Python `>=3.10,<3.14`.
- Chinese alignment model: `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`.
- Model source: <https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn>.
- Model license: Apache-2.0.
- Model note: fine-tuned XLSR-53 wav2vec2 CTC model for Chinese, expects 16 kHz audio.
- Local Hugging Face cache after this spike:
  - Chinese alignment model: about 2.4 GB.
  - `Systran/faster-whisper-tiny`: about 75 MB.
  - Total Hugging Face cache observed: about 2.5 GB.

## 4. Test Audio And Lyrics

- Audio: non-committed synthetic Mandarin TTS, 8.62 seconds, 16 kHz mono WAV.
- Lyrics: `sample_input/sample_lyrics.txt`, four manually trusted lines:
  - 星语在夜里发光
  - 我们听见时间流淌
  - 星语在夜里发光
  - 把每个字轻轻照亮
- This sample verifies Chinese text alignment mechanics. It does not validate real singing, accompaniment, long instrumental gaps, or vocal separation.

## 5. Path A: WhisperX ASR To Alignment

Result: ran on CPU after models were cached.

- WhisperX ASR produced one long segment from `0.251` to `7.878`.
- ASR text was not reliable: `星语` became `新鱼`, and `流淌` became `流逃`.
- Alignment generated character timings for the ASR text, but this is not acceptable as product truth because the text is wrong and line segmentation collapsed.

Conclusion for Path A: useful only as a rough locator. It must not be used as the source of lyrics.

## 6. Path B: Trusted Lyrics Segments To Alignment

Result: ran on CPU.

WhisperX does not expose a direct "whole trusted lyrics + audio" API. It accepts pre-windowed segments shaped like:

```json
{"start": 0.0, "end": 2.01, "text": "星语在夜里发光"}
```

For this run, ASR did not produce enough line segments, so the script used proportional windows across the full audio as a controlled fallback. Inside those windows, `whisperx.align(..., return_char_alignments=True)` accepted the trusted Chinese text and produced character timestamps.

Line-level output:

```lrc
[00:00.26]星语在夜里发光
[00:02.33]我们听见时间流淌
[00:04.47]星语在夜里发光
[00:06.54]把每个字轻轻照亮
```

Normalized JSON contains 4 aligned lines and 30 Chinese character tokens. Example:

```json
{
  "text": "星",
  "start": 0.261,
  "end": 0.502,
  "confidence": 0.956
}
```

Conclusion for Path B: trusted lyrics can participate in WhisperX alignment if we provide plausible segment windows first. WhisperX is not solving line discovery by itself.

## 7. Path C: Alternatives

No replacement implementation was needed to prove the minimum API path, but the gap is clear enough to identify the likely fallback route.

- CTC segmentation / custom wav2vec2 forced alignment is the closest alternative if we need whole-lyrics-to-audio alignment without ASR line windows.
- Nightingale remains worth inspecting because it is explicitly oriented around local forced alignment rather than WhisperX's ASR-first workflow.
- MFA/aeneas/Gentle are less attractive for this spike target: Mandarin singing plus character-level highlighting would need lexicon/phoneme handling and may be heavier or less maintained for this exact use case.

## 8. macOS Apple Silicon

CPU fallback: GO for local development and short/light processing.

- CPU trusted-lyrics alignment completed in about 3.3 seconds after models were cached.
- Full ASR baseline plus alignment completed in about 5.8 seconds after models were cached.
- First run was much slower because it downloaded and converted models.

MPS: not validated.

- `torch.backends.mps.is_available()` returned true.
- Moving the wav2vec2 alignment model to MPS failed:

```text
RuntimeError: The MPS backend is supported on MacOS 13.0+.Current OS version can be queried using `sw_vers`
```

- The tested OS is macOS 26.5.1, so this appears to be a PyTorch 2.8.0/macOS-version compatibility issue or environment detection issue.
- CTranslate2/faster-whisper MPS was not separately validated because the alignment model already failed on MPS.

Additional macOS issue:

- `torchcodec` warned that it could not load FFmpeg 4-7 dylibs while Homebrew FFmpeg 8.1 was installed.
- The spike avoided this by preloading audio with `whisperx.load_audio`, but product code should either document FFmpeg compatibility or avoid torchcodec-dependent decode paths.

## 9. Windows CUDA

Not actually verified in this macOS environment.

Expected validation path:

- Windows 10/11 x64.
- Python 3.11 or 3.12.
- NVIDIA driver compatible with CUDA 12.8.
- CUDA Toolkit 12.8, matching current WhisperX README guidance.
- PyTorch/torchaudio 2.8 CUDA wheels selected by WhisperX packaging.
- FFmpeg installed and on `PATH`.

Command:

```powershell
cd spikes\whisperx_chinese_alignment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_spike.py --audio sample_input\sample.wav --lyrics sample_input\sample_lyrics.txt --device cuda --compute-type float16 --language zh
```

Expected behavior: CUDA should accelerate both faster-whisper ASR and wav2vec2 alignment. This remains an expectation until run on an actual Windows NVIDIA machine.

## 10. Output Adequacy

The spike output is sufficient for a future product proof:

- `alignment.raw.json` preserves WhisperX raw output.
- `alignment.normalized.json` has line-level `start/end/status` and character tokens with `start/end/confidence`.
- `sample.lrc` contains standard line-level LRC.
- Missing or failed alignment can be represented as `missing_time` or `missing_tokens`.

The main gap is upstream line-window generation. If segment windows are wrong, repeated lyrics and long gaps can drift because WhisperX aligns within the provided window.

## 11. Known Failure Cases And Risks

- ASR text is inaccurate for Chinese names/lyrics and merged all lines into one segment in this sample.
- WhisperX does not directly align a complete lyrics document to audio.
- Repeated lyrics are only disambiguated by the segment windows we provide.
- Intro/interlude/outro and missing lyric lines need a separate locator or segmentation layer.
- Real singing, accompaniment, vibrato, sustained vowels, and vocal separation were not validated.
- Chinese punctuation and characters outside the model dictionary may produce missing or interpolated timestamps.
- First-run download is large: the Chinese alignment model alone is about 2.4 GB.
- macOS MPS failed; Apple Silicon support should be treated as CPU-only for now.
- Windows CUDA is not yet actually verified.

## 12. Recommendation

Conclusion: GO WITH CONSTRAINTS.

WhisperX plus the current Chinese wav2vec2 model can be used as a v0.1.1 technical base for the inner alignment step, but not as the whole forced-alignment solution.

Required constraints:

- Product input must remain trusted lyrics text.
- macOS Apple Silicon starts with CPU fallback, not MPS.
- Windows CUDA should be treated as the likely performance target, but must be validated separately.
- We must implement or adopt a robust coarse line-window locator before calling WhisperX alignment.
- ASR may be used only for rough speech-window discovery, never as lyric truth.
- Long audio should be sliced and reviewed with confidence/missing-token warnings.

Recommended next route:

1. Build a narrow prototype that takes trusted lyric lines and externally supplied or heuristically generated line windows, then calls WhisperX alignment.
2. Validate on 5-10 real Chinese song clips with vocals and accompaniment.
3. In parallel, inspect Nightingale or a CTC-segmentation route for whole-lyrics coarse alignment.
4. Run the same script on Windows NVIDIA CUDA and record actual dependency/runtime behavior.
