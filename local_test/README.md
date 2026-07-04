# Local pipeline test scripts

Standalone scripts to validate each core pipeline stage against a real video
before wiring anything into the full FastAPI/DB/R2 app. Each script can be
run individually, or all together via `run_pipeline.py`.

## Setup

```bash
cd local_test
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in ASSEMBLYAI_API_KEY and ANTHROPIC_API_KEY in .env once you have them
# for local diarization instead of AssemblyAI, fill in HF_TOKEN instead (see below)
```

Requires `ffmpeg` and `tesseract` on PATH (already installed on this machine).

## Get a test video

```bash
python 0_download_video.py "<YOUTUBE_URL>"
# or a custom output path / resolution cap:
python 0_download_video.py "<YOUTUBE_URL>" --output my_video.mp4 --max-height 480
```

Requires `yt-dlp` (`brew install yt-dlp`). Downloads capped at 720p by default to keep the file small and fast to iterate on.

## Run everything

```bash
python run_pipeline.py test_video.mp4
```

By default (`--transcription-engine auto`), stage 2 picks the best available
engine: AssemblyAI if `ASSEMBLYAI_API_KEY` is set, else local Whisper +
pyannote diarization if `HF_TOKEN` is set, else plain local Whisper (no
diarization) as the last resort — so stage 2 always runs with no API key at
all if needed. Stages 5 (vision judgment) and 6 (topic segmentation) still
need `ANTHROPIC_API_KEY` and are skipped without it; stages 1, 3, and 4
(audio extraction, frame extraction, heuristic frame filtering) never need
any API key.

Force a specific transcription engine:

```bash
python run_pipeline.py test_video.mp4 --transcription-engine assemblyai
python run_pipeline.py test_video.mp4 --transcription-engine whisper-diarized --whisper-model small
python run_pipeline.py test_video.mp4 --transcription-engine whisper --whisper-model small
```

Three transcription engines, in order of how "real" the speaker diarization is:

| Engine | Diarization | Needs |
|---|---|---|
| `assemblyai` | Real (hosted) | `ASSEMBLYAI_API_KEY` |
| `whisper-diarized` | Real (local, via pyannote) | `HF_TOKEN` (see below), slower — two full passes over the audio |
| `whisper` | None — single placeholder "Speaker" | nothing |

### Setting up `whisper-diarized` (local diarization, no hosted API)

1. Create a Hugging Face account and accept the gated model terms on both:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
2. Generate a read-access token: https://huggingface.co/settings/tokens
3. Add it to `local_test/.env` as `HF_TOKEN=...`

## Run stages individually

```bash
python 1_extract_audio.py test_video.mp4
python 2_transcribe.py output/audio.wav                             # AssemblyAI (default)
python 2_transcribe.py output/audio.wav --engine whisper             # local Whisper, no diarization, no API key
python 2_transcribe.py output/audio.wav --engine whisper-diarized    # local Whisper + pyannote diarization
python 3_extract_frames.py test_video.mp4
python 4_filter_frames.py output/frames_raw
python 5_vision_judge.py output/candidate_frames.json
python 6_topic_segments.py output/transcript.json
python 7_assemble.py
```

All outputs land in `output/`, including the final `output/document/document.md`
with images in `output/document/images/`.

## What to look at

- `output/candidate_frames.json` — check the raw-frame-count to candidate-count
  ratio (should land around 5-15% for a typical talking-head + slides video).
- `output/accepted_frames.json` — spot-check captions/relevance calls.
- `output/document/document.md` — open in a Markdown viewer, confirm images
  land in sensible places relative to the surrounding transcript text.
