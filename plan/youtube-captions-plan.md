# Use YouTube's own captions instead of transcribing YouTube imports

## Context

YouTube imports (`POST /api/convert_from_youtube`, `routes/youtube.py`) only
ever create `job_type="video"` jobs. `pipeline.py`'s `_download_if_needed()`
downloads the actual video file via `app/youtube.py`'s
`download_youtube_video()` (a single `yt-dlp` CLI invocation), and later,
`_transcribe_segments()` extracts audio from that same file and sends it to
AssemblyAI or Baseten for transcription — a paid, non-trivial-latency step.

Confirmed during exploration: **the video download itself can't be skipped**
even with this change — `job_type="video"`'s frame-extraction stage
(`frames.extract_frames`) needs the real video file regardless of where the
transcript comes from. What *can* be skipped is the audio-extraction +
cloud-transcription step, by using YouTube's own caption track when one
exists — fetchable in the *same* `yt-dlp` call that already downloads the
video (`--write-subs --write-auto-subs`, no extra network round-trip).

The real tradeoff: YouTube captions carry no speaker diarization (everything
becomes one generic "Speaker"). This matters less here than it would for the
separate audio-upload flow, since video jobs compose a topic-organized
document via an LLM (`compose.compose_document`), not a per-speaker verbatim
transcript — that verbatim/speaker-tagged presentation is specifically the
`job_type="audio"` flow's thing, which YouTube import never uses.

**Decided**: this is a silent automatic default — always try captions first,
transparently fall back to today's audio-extraction + AssemblyAI/Baseten
pipeline if the video has no usable caption track. No new UI.

**Real risk flagged upfront**: YouTube's auto-generated captions have a
known "rolling/karaoke" duplication quirk in their native timed-text format
(incremental, overlapping cues meant for realtime display) that can produce
heavily duplicated text if naively converted/parsed. Whether `yt-dlp`'s SRT/
VTT conversion already handles this cleanly, or a parser needs to explicitly
de-duplicate, is **not yet verified** — this plan's first implementation
step is a throwaway spike against real YouTube videos to find out before
writing the real parser, same approach used for the WASM diarization spike
earlier this session.

## Design

1. **Fetch captions in the existing download call.** Extend
   `app/youtube.py`'s `download_youtube_video()`'s `yt-dlp` invocation with
   `--write-subs --write-auto-subs --sub-langs en --sub-format srt`
   (preferring manually-uploaded captions over auto-generated when both
   exist; English only for now — a hardcoded default, not a new setting,
   consistent with how `WHISPER_MODEL` etc. are kept simple). Confirm during
   the spike below which of SRT/VTT actually comes out cleaner for
   auto-captions specifically.
2. **Detect which caption file (if any) was produced.** `yt-dlp` names
   subtitle output based on the video's output template plus a language
   code (e.g. `source.en.srt` alongside `source.mp4`) — check for the
   manual-caption filename pattern first, then the auto-caption pattern;
   use whichever is found. Neither existing is the normal/expected case for
   many videos, not an error.
3. **Parse into segments.** A small hand-rolled SRT parser (the format is
   simple, and a generic library wouldn't handle the YouTube-specific
   de-duplication need anyway) producing
   `{"speaker": "Speaker", "text": ..., "start_ts": ..., "end_ts": ...}` —
   a single constant speaker label per segment, matching the same
   no-diarization convention the old local-Whisper-only path used to use
   before it was removed.
4. **Generalize the existing precomputed-transcript short-circuit.**
   `pipeline.py`'s `_transcribe_segments()` already has exactly this
   mechanism for live recordings — it checks for `live_segments.json` in
   the job's `output_dir` and skips audio-extraction/transcription entirely
   if found (see `routes/live.py`). Rename this to something source-neutral
   (e.g. `precomputed_segments.json`) now that there are two producers of
   it (`routes/live.py` and this new YouTube-caption path), and update both
   the write side (`routes/live.py`) and the check side
   (`_transcribe_segments`) accordingly.
5. **Wiring**: pass `output_dir` into `_download_if_needed(job, output_dir)`
   (currently called without it — a small signature change, one call site
   in `run_job` to update) so the caption-parsing step can write
   `precomputed_segments.json` directly after a successful download, before
   returning.
6. **Fallback is implicit**: if no caption file was found/parseable, simply
   don't write `precomputed_segments.json` — `_transcribe_segments` proceeds
   exactly as it does today, no explicit fallback branching needed.
7. **Out of scope / flagged, not decided here**: whether YouTube-import
   jobs should be billed differently when transcription is skipped (today's
   $1/hour video pricing doesn't itemize the transcription-engine cost) —
   a pricing/business decision, not a technical one, left alone.

## Files

- `app/youtube.py`: extend `download_youtube_video()`'s yt-dlp args; add the
  caption-detection + SRT-parsing logic (new small function(s) in this
  file, since it already owns all yt-dlp interaction).
- `app/pipeline.py`: `_download_if_needed()` signature gains `output_dir`,
  calls the new caption-parsing step and writes `precomputed_segments.json`
  on success; `_transcribe_segments()`'s short-circuit check renamed to
  match; `run_job`'s one call site updated for the new signature.
- `app/routes/live.py`: update the filename it writes to match the rename.

## Verification

1. **Spike first** (throwaway): run `yt-dlp --write-subs --write-auto-subs
   --sub-langs en --sub-format srt --skip-download <url>` directly against
   a few real, known YouTube videos — one with manual captions, one with
   only auto-captions, one with none — to confirm actual file naming,
   format, and whether auto-caption text comes out clean or duplicated.
   This determines the real parsing logic, not assumptions.
2. Unit-test the SRT parser against the sample files the spike produces
   (including a deliberately-duplicated-cue sample if that turns out to be
   real, to lock in the de-duplication behavior).
3. End-to-end: import a real YouTube video via
   `POST /api/convert_from_youtube`, confirm (via logs/timing) the
   transcription stage was actually skipped, and that the resulting
   document's content is reasonable.
4. Confirm the fallback path: import a video with captions disabled and
   confirm it still transcribes normally via AssemblyAI/Baseten as today.
5. Confirm the live-recording flow (`routes/live.py`) still works after the
   filename rename — same finalize-and-check flow as before, just renamed.
