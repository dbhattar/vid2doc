import json
import os
from pathlib import Path

from . import billing, emails, jobs, users, youtube
from .config import settings
from .stages import assemble, assemble_video, audio, classify, compose, frames, highlights, render_scene, scenes, stock_media, transcribe


class JobCancelled(Exception):
    """Raised by _check_not_cancelled to unwind out of whichever stage was
    about to start -- caught separately from a real failure in run_job's
    except block (no refund-as-error-message, no "failed" status)."""


def _check_not_cancelled(job_id: str) -> None:
    """The single worker has no way to interrupt a blocking ffmpeg/LLM call
    already in flight, so cancellation is cooperative: checked at each stage
    boundary (and, for video_gen, between individual scene renders) rather
    than instantly. A cancel request therefore takes effect within one
    stage's duration, not immediately -- see routes/jobs.py's cancel_job."""
    if jobs.get_job(job_id)["cancel_requested"]:
        raise JobCancelled()


def _resolve_engine() -> str:
    engine = settings.TRANSCRIPTION_ENGINE
    if engine != "auto":
        return engine
    if os.environ.get("ASSEMBLYAI_API_KEY"):
        return "assemblyai"
    if os.environ.get("BASETEN_API_KEY"):
        return "baseten"
    if os.environ.get("HF_TOKEN"):
        return "whisper-diarized"
    return "whisper"


def _llm_available() -> bool:
    if settings.LLM_PROVIDER == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _normalize_speaker_labels(segments: list[dict]) -> list[str]:
    """Raw diarization engines emit inconsistent labels (pyannote:
    SPEAKER_00/SPEAKER_01, AssemblyAI: A/B) -- rewrite in place to clean,
    consistent "Speaker 1", "Speaker 2", ... ordered by first appearance, so
    the label is both engine-agnostic and a sane default before the user
    assigns real names. Returns the ordered list of unique normalized labels."""
    label_map: dict[str, str] = {}
    for s in segments:
        raw = s["speaker"]
        if raw not in label_map:
            label_map[raw] = f"Speaker {len(label_map) + 1}"
        s["speaker"] = label_map[raw]
    return list(label_map.values())


def _fallback_sections(segments: list[dict]) -> list[dict]:
    """No LLM configured: still produce a document, just the raw merged
    transcript under one heading instead of a composed, topic-organized one."""
    return [{
        "heading": "Transcript",
        "blocks": [
            {"type": "paragraph", "text": f"{s['speaker']}: {s['text']}", "ref": 0, "caption": ""}
            for s in segments
        ],
    }]


def _format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _verbatim_transcript_sections(segments: list[dict], speaker_names: dict[str, str] | None = None) -> list[dict]:
    """Audio-transcript jobs (job_type == "audio") skip document composition
    entirely -- this is just the diarized transcript, verbatim, one
    paragraph per speaker turn with a timestamp. No LLM involved, so this
    runs whether or not a compose LLM is configured. speaker_names resolves
    normalized labels ("Speaker 1") to user-assigned real names, if any."""
    speaker_names = speaker_names or {}
    return [{
        "heading": "Transcript",
        "blocks": [
            {
                "type": "paragraph",
                "text": (
                    f"**{speaker_names.get(s['speaker'], s['speaker'])}** "
                    f"({_format_timestamp(s['start_ts'])}): {s['text']}"
                ),
                "ref": 0,
                "caption": "",
            }
            for s in segments
        ],
    }]


def _build_audio_sections(segments: list[dict], summary: str, speaker_names: dict[str, str] | None = None) -> list[dict]:
    """Shared by run_job (initial render) and routes/transcript.py's speaker
    rename endpoint (re-render), so the "how the audio document is built"
    logic exists in exactly one place. Substituting names into `summary`
    is a plain string replace -- safe because generate_summary() is
    instructed to refer to speakers by their exact normalized label."""
    speaker_names = speaker_names or {}
    sections = []
    if summary:
        resolved_summary = summary
        for label, name in speaker_names.items():
            resolved_summary = resolved_summary.replace(label, name)
        sections.append({"heading": "Summary", "blocks": [{"type": "paragraph", "text": resolved_summary, "ref": 0, "caption": ""}]})
    sections.extend(_verbatim_transcript_sections(segments, speaker_names))
    return sections


def _finalize_document(
    job: dict,
    title: str,
    sections: list[dict],
    images_meta: list[dict],
    tables_meta: list[dict],
    extra_files: dict[str, str] | None = None,
) -> None:
    """Shared tail of a job: render + best-effort export, then mark done.
    Called both by run_job's normal path (audio jobs, and video jobs with
    nothing to review) and by resume_after_review (video jobs that paused
    for frame review). `extra_files` writes additional files into doc_dir
    before rendering (used for audio's transcript.json)."""
    job_id = job["id"]
    output_dir = settings.OUTPUT_DIR / job_id

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="rendering_document")
    doc_dir = output_dir / "document"
    doc_dir.mkdir(parents=True, exist_ok=True)
    images_by_id = {img["id"]: img for img in images_meta}
    tables_by_id = {tbl["id"]: tbl for tbl in tables_meta}

    for filename, content in (extra_files or {}).items():
        (doc_dir / filename).write_text(content)

    doc_path = assemble.render_markdown(title, sections, images_by_id, tables_by_id, doc_dir)

    # Best-effort exports on top of the canonical Markdown -- a rendering
    # failure here shouldn't fail the whole job.
    try:
        assemble.render_docx(title, sections, images_by_id, tables_by_id, doc_dir / "document.docx")
    except Exception as e:
        print(f"DOCX export failed for job {job_id}: {e}", flush=True)
    try:
        assemble.render_pdf(title, sections, images_by_id, tables_by_id, doc_dir / "document.pdf")
    except Exception as e:
        print(f"PDF export failed for job {job_id}: {e}", flush=True)

    jobs.update_job(job_id, status="done", progress_stage="done", document_path=str(doc_path))
    emails.notify_job_status_change(job_id)


def _transcribe_segments(job: dict, output_dir: Path) -> list[dict]:
    """Extract + transcribe/diarize -- shared by audio jobs, video jobs that
    skip review entirely, and resume_after_review. Deliberately NOT run
    before the frame-review pause: transcription is a paid API call, and a
    video job that gets abandoned at review shouldn't have incurred it."""
    job_id = job["id"]
    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="extracting_audio")
    audio_path = audio.extract_audio(Path(job["source_path"]), output_dir / "audio.wav")

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="transcribing")
    engine = _resolve_engine()
    transcript = transcribe.transcribe_diarize(audio_path, engine=engine, whisper_model=settings.WHISPER_MODEL)
    return transcript["segments"]


def _compose_and_finalize(job: dict, output_dir: Path, images_meta: list[dict], tables_meta: list[dict]) -> None:
    """Transcribe, compose, and finalize -- the shared tail for a video job
    that has already decided which images/tables to include, whether that
    decision came from a real user's review submission
    (resume_after_review) or was made automatically for an anonymous trial
    job (run_job's trial branch, which has no review step to wait for)."""
    job_id = job["id"]
    segments = _transcribe_segments(job, output_dir)

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="composing_document")
    sections = compose.compose_document(segments, images_meta + tables_meta)
    title = compose.generate_title(sections)
    jobs.update_job(job_id, title=title)

    if not sections:
        sections = _fallback_sections(segments)

    _finalize_document(job, title, sections, images_meta, tables_meta)


def _download_if_needed(job: dict) -> dict:
    """A job imported from YouTube (routes/youtube.py) is created with
    source_path=None and source_url set -- the actual download happens here,
    in the worker, rather than in the API request that created the job (see
    routes/youtube.py's docstring for why). No-op for every other job type,
    which already has source_path set from the start. Re-derives the admin
    duration-cap bypass fresh (rather than trusting a decision baked in at
    job-creation time), since admin status could have changed since."""
    if job.get("source_path"):
        return job

    job_id = job["id"]
    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="downloading")
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / "source.mp4"

    user = users.get_user_by_id(job["user_id"]) if job.get("user_id") else None
    max_duration = None if (user and user.get("is_admin")) else settings.MAX_DURATION_SECONDS

    duration, size_bytes = youtube.download_youtube_video(
        job["source_url"], upload_dir, dest_path, max_duration, settings.MAX_UPLOAD_BYTES
    )
    jobs.update_job(job_id, source_path=str(dest_path), duration_seconds=duration, source_size_bytes=size_bytes)
    return jobs.get_job(job_id)


def resume_after_review(job: dict) -> None:
    """Picks up where run_job left off for a video job that paused at
    "awaiting_review" -- reads review.json (written once, at pause time,
    before transcription or captioning ever ran), filters to the items the
    user kept, generates captions for exactly that filtered set (never spent
    on a frame the user skipped), then hands off to _compose_and_finalize.
    Mirrors routes/transcript.py's set_speaker_names: reuse a persisted
    intermediate artifact for a cheap resume instead of re-running upstream
    stages (here, frame extraction/filtering/classification)."""
    job_id = job["id"]
    output_dir = settings.OUTPUT_DIR / job_id
    review_data = json.loads((output_dir / "review.json").read_text())
    items = review_data["items"]

    included = [i for i in items if i.get("included", True)]

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="captioning_frames")
    captioned = classify.caption_frames(included)
    images_meta = [i for i in captioned if i["kind"] == "image"]
    tables_meta = [i for i in captioned if i["kind"] == "table"]

    _compose_and_finalize(job, output_dir, images_meta, tables_meta)


def _transcribe_and_segment_scenes(job: dict, output_dir: Path) -> None:
    """video_gen jobs: transcribe, segment into scenes, generate on-screen
    headlines, fetch stock media candidates, then pause for review -- mirrors
    the video pipeline's frame-review pause above. Unlike that pause,
    transcription can't be deferred past it here, since scene segmentation
    depends on it; the genuinely expensive step (ffmpeg rendering) is still
    deferred to resume_after_scene_review, preserving the same
    don't-pay-for-abandoned-jobs philosophy."""
    job_id = job["id"]
    segments = _transcribe_segments(job, output_dir)

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="segmenting_scenes")
    scene_list = scenes.segment_scenes(segments)

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="generating_headlines")
    scene_list = highlights.generate_headlines(scene_list, segments)

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="fetching_stock_media")
    media_dir = output_dir / "stock_media"
    for scene in scene_list:
        scene.update(stock_media.fetch_scene_media(scene, media_dir))

    # Checked here too, not just before fetching_stock_media above -- that
    # stage makes a network call per scene and can take a while, so a
    # cancel requested mid-fetch must still be caught before pausing, not
    # after: once this job is sitting in awaiting_review, the worker's
    # subprocess exits normally (it wasn't killed, it finished on its own),
    # so worker.py's kill-loop never gets a chance to notice a still-pending
    # cancel_requested. See worker.py's post-exit catch-up check for the
    # remaining, unavoidable race (cancellation landing in the gap between
    # this check and the status write just below it).
    _check_not_cancelled(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scenes.json").write_text(json.dumps({"scenes": scene_list, "segments": segments}, indent=2))
    jobs.update_job(job_id, status="awaiting_review", progress_stage="awaiting_scene_review")


def resume_after_scene_review(job: dict) -> None:
    """Picks up where _transcribe_and_segment_scenes left off for a video_gen
    job that paused at "awaiting_review" -- reads scenes.json (already
    containing the user's edited headlines and chosen stock candidate,
    written by routes/scene_review.py's submit endpoint), renders each scene,
    then assembles the final video. Mirrors resume_after_review's reuse of a
    persisted intermediate artifact for a cheap resume."""
    job_id = job["id"]
    output_dir = settings.OUTPUT_DIR / job_id
    data = json.loads((output_dir / "scenes.json").read_text())
    scene_list = data["scenes"]
    segments = data["segments"]

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="rendering_scenes")
    clips_dir = output_dir / "scene_clips"
    clip_paths = []
    for scene in scene_list:
        # Checked per-scene, not just once at the top of this stage -- scene
        # rendering is the single most CPU-heavy part of the whole pipeline
        # (see plan/audio-to-video-generation-plan.md's risks section), so a
        # video with many scenes is exactly the "long running job" case
        # cancellation matters most for.
        _check_not_cancelled(job_id)
        candidates = scene.get("candidates") or []
        chosen_index = scene.get("chosen_index", 0)
        media_path = candidates[chosen_index] if chosen_index < len(candidates) else None
        clip_paths.append(
            render_scene.render_scene_clip(scene, media_path, clips_dir / f"scene_{scene['id']}.mp4")
        )

    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="assembling_video")
    final_path = assemble_video.render_final_video(
        clip_paths, segments, output_dir / "audio.wav", output_dir / "video"
    )

    jobs.update_job(job_id, status="done", progress_stage="done", document_path=str(final_path))
    emails.notify_job_status_change(job_id)


def run_job(job: dict) -> None:
    job_id = job["id"]
    output_dir = settings.OUTPUT_DIR / job_id
    is_audio_job = job.get("job_type") == "audio"
    is_video_gen_job = job.get("job_type") == "video_gen"

    try:
        # A job coming back from the frame-review pause -- routes/review.py's
        # submit endpoint re-queues it with this marker instead of resetting
        # progress_stage to a fresh-start value, so the worker (which just
        # calls run_job like any other queued job -- see worker.py) knows to
        # skip straight to transcribing/composing/rendering instead of
        # re-extracting/re-filtering/re-classifying frames.
        if job.get("progress_stage") == "resuming_after_review":
            resume_after_review(job)
            return

        # Same idea, for a video_gen job coming back from the scene-review
        # pause (routes/scene_review.py's submit endpoint).
        if job.get("progress_stage") == "resuming_after_scene_review":
            resume_after_scene_review(job)
            return

        _check_not_cancelled(job_id)
        job = _download_if_needed(job)

        if is_video_gen_job:
            _transcribe_and_segment_scenes(job, output_dir)
            return

        if is_audio_job:
            # No frame capture, no classification, no LLM document
            # composition -- just the verbatim, speaker-tagged transcript
            # plus (if an LLM is configured) a short summary. Keep whatever
            # title was already set from the uploaded filename (see
            # routes/audio.py).
            segments = _transcribe_segments(job, output_dir)
            normalized_speakers = _normalize_speaker_labels(segments)
            summary = ""
            if _llm_available():
                # Cancellation check deliberately outside the try below --
                # that except is a soft-fail for summary generation
                # specifically, and must never swallow a JobCancelled
                # meant for the outer run_job try/except.
                _check_not_cancelled(job_id)
                jobs.update_job(job_id, progress_stage="summarizing")
                try:
                    summary = compose.generate_summary(segments)
                except Exception as e:
                    print(f"Summary generation failed for job {job_id}: {e}", flush=True)
            sections = _build_audio_sections(segments, summary)
            title = job.get("title") or "Audio Transcript"
            transcript_json = json.dumps({
                "speakers": normalized_speakers,
                "speaker_names": {},
                "summary": summary,
                "segments": segments,
            }, indent=2)
            _finalize_document(job, title, sections, [], [], extra_files={"transcript.json": transcript_json})
            return

        # Video: extract, filter, and (if an LLM is configured) classify
        # candidate frames FIRST -- before transcription, which costs money
        # and shouldn't run until the user has actually committed to the job
        # by submitting their frame review. Pause for review as long as
        # there's actually something to review; transcription, composing,
        # and rendering happen later, in resume_after_review.
        _check_not_cancelled(job_id)
        jobs.update_job(job_id, progress_stage="extracting_frames")
        raw_frames = frames.extract_frames(Path(job["source_path"]), output_dir / "frames_raw")

        _check_not_cancelled(job_id)
        jobs.update_job(job_id, progress_stage="filtering_frames")
        candidates = frames.filter_frames(raw_frames)

        images_meta: list[dict] = []
        tables_meta: list[dict] = []
        if candidates and _llm_available():
            _check_not_cancelled(job_id)
            jobs.update_job(job_id, progress_stage="classifying_frames")
            images_meta, tables_meta = classify.classify_frames(candidates)

        if images_meta or tables_meta:
            if job.get("user_id") is None:
                # Anonymous trial job (see routes/trial.py) -- no interactive
                # review; caption and include everything the classifier
                # found, then go straight through. Real users get to pick
                # which frames make the document; trial users get an
                # instant, best-effort demo instead.
                _check_not_cancelled(job_id)
                jobs.update_job(job_id, progress_stage="captioning_frames")
                captioned = classify.caption_frames(images_meta + tables_meta)
                trial_images = [i for i in captioned if i["kind"] == "image"]
                trial_tables = [i for i in captioned if i["kind"] == "table"]
                _compose_and_finalize(job, output_dir, trial_images, trial_tables)
                return

            # Checked here too, not just before classifying_frames above --
            # classification can take a while (one LLM call per candidate),
            # so a cancel requested mid-classification must still be caught
            # before pausing, not after: once this job is sitting in
            # awaiting_review, the worker's subprocess exits normally (it
            # wasn't killed, it finished on its own), so worker.py's own
            # kill-loop never gets a chance to notice a still-pending
            # cancel_requested. See worker.py's post-exit catch-up check for
            # the remaining, unavoidable race (cancellation landing in the
            # gap between this check and the status write just below it).
            _check_not_cancelled(job_id)
            items = [{**item, "included": True} for item in images_meta + tables_meta]
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "review.json").write_text(json.dumps({"items": items}, indent=2))
            jobs.update_job(job_id, status="awaiting_review", progress_stage="awaiting_review")
            return

        # Nothing to review (no LLM configured, or no candidate frames at
        # all) -- proceed straight through to transcription exactly as
        # before this feature.
        segments = _transcribe_segments(job, output_dir)
        _finalize_document(job, "Video Transcript", _fallback_sections(segments), [], [])
    except JobCancelled:
        # Reached a stage boundary after routes/jobs.py's cancel endpoint set
        # cancel_requested -- same refund treatment as a failure, but not
        # logged as an error (progress_stage is left as-is here too, so the
        # UI can show which stage was in progress when it was cancelled).
        jobs.update_job(job_id, status="cancelled")
        if job.get("user_id") and job.get("billed_cents"):
            billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
        emails.notify_job_status_change(job_id)
    except Exception as e:
        # Deliberately leaves progress_stage as whatever it was at the moment
        # of failure (not nulled out) -- the frontend's job-progress stepper
        # uses it to show which stage the job actually died on.
        jobs.update_job(job_id, status="failed", error_message=str(e))
        if job.get("user_id") and job.get("billed_cents"):
            billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
        emails.notify_job_status_change(job_id)
