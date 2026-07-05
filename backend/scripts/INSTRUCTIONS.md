# Video → Document Pipeline: Setup & Usage

Turns a video file (+ a transcript you provide) into a formatted PDF/DOCX with
charts embedded as images and on-screen tables rebuilt as real, structured tables.

## 1. Architecture at a glance

```
Video file ──▶ STAGE 0: extract + triage frames          [local, free]
                    │
                    ▼
              STAGE 1: classify frames, extract tables    [AI MODEL CALL #1 — vision]
                    │
Transcript ─────────┤
                    ▼
              STAGE 2: merge into one timeline            [local, free]
                    │
                    ▼
              STAGE 3: compose document plan (JSON)       [AI MODEL CALL #2 — text/LLM]
                    │
                    ▼
              STAGE 4: render to PDF / DOCX               [local, free]
```

Only **Stage 1** and **Stage 3** need an AI model. Stages 0, 2, and 4 are deterministic
code with no model involved — they cost nothing to run repeatedly.

Transcription itself (audio → text) is **out of scope** for this script. Use Otter.ai,
Whisper, or any transcription tool you like, then feed its output into `transcript_segments`.

## 2. Install dependencies

System packages:
```bash
# Debian/Ubuntu
sudo apt-get install ffmpeg tesseract-ocr

# macOS
brew install ffmpeg tesseract
```

Python packages:
```bash
pip install opencv-python-headless pytesseract numpy reportlab python-docx
```

If you plan to call Claude for stages 1/3:
```bash
pip install anthropic
```

## 3. Wire in the two AI model calls

Both call sites in `video_to_doc.py` are dependency-injected functions — the pipeline
doesn't hard-code a provider, so you can swap models without touching pipeline logic.

### AI MODEL CALL #1 — vision (Stage 1: `classify_frame` / `build_visual_assets`)

Needs a **vision-capable** model. Cheapest-to-priciest options:
- Self-hosted, $0 marginal cost: Qwen2.5-VL-7B, DeepSeek-OCR (needs your own GPU)
- Pay-per-call API: Gemini Flash (typically cheapest per image), Claude Haiku, GPT-4o-mini

Example wiring against the Anthropic API:

```python
import base64
import anthropic

client = anthropic.Anthropic(api_key="YOUR_KEY")

def vision_model_call(image_path: str, prompt: str) -> str:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text
```

### AI MODEL CALL #2 — text (Stage 3: `compose_document`)

Any modern LLM works here — this step is pure text (Stage 1 already turned visuals
into descriptions/structured data, so no image input is needed).

```python
def text_model_call(prompt: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

Both prompt templates (`CLASSIFY_PROMPT`, `COMPOSE_PROMPT`) already instruct the model
to return **only JSON** — if you swap providers, keep that instruction, since the
pipeline calls `json.loads()` directly on the response.

> Tip: if your chosen model supports a "JSON mode" or structured-output / tool-use
> feature, use it — it's more reliable than trusting the model to skip preamble text.

## 4. Prepare your transcript

Get this from whatever transcription tool you use, formatted as:

```python
transcript_segments = [
    {"start": 12.4, "text": "Ionic bonds form between a metal and a non-metal...", "speaker": "Jeremy"},
    {"start": 18.9, "text": "...", "speaker": "Jeremy"},
]
```

`start` must be in seconds, matching the video's timeline — this is what lets Stage 2
merge transcript text with the frames extracted in Stage 0.

## 5. Run it

```python
from video_to_doc import run_pipeline

outputs = run_pipeline(
    video_path="my_video.mp4",
    transcript_segments=transcript_segments,
    vision_model_call=vision_model_call,   # from step 3
    text_model_call=text_model_call,       # from step 3
    work_dir="./work",
    out_basename="my_report",
    formats=("pdf", "docx"),
)
print(outputs)   # {'pdf': './work/my_report.pdf', 'docx': './work/my_report.docx'}
```

Or from the command line for a quick smoke test (uses placeholder stub models, **not**
real output — just confirms the plumbing works):
```bash
python3 video_to_doc.py my_video.mp4
```

## 6. Tuning knobs

| Parameter | Where | Effect |
|---|---|---|
| `scene_threshold` (default 0.15) | `find_candidate_frames` | Lower = more sensitive to slide/shot changes. Raise for videos with lots of camera motion (handheld footage) to avoid false triggers. |
| `fixed_interval_seconds` (default 8.0) | `find_candidate_frames` | Safety-net sampling rate for gradual fades/animations. Lower for fast-changing slide decks; higher for long lecture-style video to cut candidate count. |
| dedupe `threshold` (default 4, in `_dedupe`) | Stage 0 | Hamming-distance cutoff for near-duplicate frames. Raise if you're getting too many near-identical candidates. |
| `word_count >= 3` / `is_slide_like` | `find_candidate_frames` | The actual "is this worth sending to the AI model" rule. Loosen if you're missing real content; tighten to cut API costs further. |

## 7. Cost control checklist

- Stage 0 always runs first and is free — never skip straight to calling a vision model
  on every raw frame.
- Expect roughly 15–30 candidate frames per 10 minutes of typical talking-head-with-slides
  video after triage; fast-cutting video (interviews, news) may produce more.
- Stage 1 is one vision call per candidate frame — this is almost always the majority of
  your per-video cost.
- Stage 3 is exactly **one** text call per video (or per chunk, for very long videos —
  see below), regardless of how many frames or transcript segments there are.

## 8. Known limitations / things to extend yourself

- **Very long videos**: Stage 3 sends the entire timeline in one prompt. If it exceeds
  your model's context window, chunk `timeline` by time range, call `compose_document`
  per chunk, then concatenate the resulting `sections` lists before rendering.
- **Table caption/description quality** depends entirely on the vision model's output in
  Stage 1 — garbage in, garbage out. Spot-check a few classified tables before trusting
  a fully automated run on important content.
- **Multi-speaker attribution**: if your transcription tool doesn't do diarization, the
  `speaker` field will be missing/generic — the composer prompt will still work, it just
  won't be able to attribute specific claims to specific speakers.
- **Charts with unreadable exact values** (e.g. a hand-drawn curve): Stage 1's prompt asks
  for a caption/description, not extracted data points. If you need actual numeric data
  out of a chart image, that's a harder, separate problem (see chart-to-data models like
  Deplot) — this pipeline embeds the chart as an image rather than guessing numbers.

## 9. File outputs

Running `run_pipeline(...)` produces, under `work_dir`:
```
work_dir/
├── frames/           # every extracted candidate frame (kept for debugging/audit)
├── {out_basename}.pdf
└── {out_basename}.docx
```
