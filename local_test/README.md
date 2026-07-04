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

Stages 2 (transcription), 5 (vision judgment), and 6 (topic segmentation)
are skipped automatically if the relevant API key isn't set — stages 1, 3,
and 4 (audio extraction, frame extraction, heuristic frame filtering) work
with no API keys at all.

## Run stages individually

```bash
python 1_extract_audio.py test_video.mp4
python 2_transcribe.py output/audio.wav
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
