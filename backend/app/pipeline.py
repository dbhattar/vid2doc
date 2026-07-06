import os
from pathlib import Path

from . import billing, jobs
from .config import settings
from .stages import assemble, audio, classify, compose, frames, transcribe


def _resolve_engine() -> str:
    engine = settings.TRANSCRIPTION_ENGINE
    if engine != "auto":
        return engine
    if os.environ.get("ASSEMBLYAI_API_KEY"):
        return "assemblyai"
    if os.environ.get("HF_TOKEN"):
        return "whisper-diarized"
    return "whisper"


def _llm_available() -> bool:
    if settings.LLM_PROVIDER == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


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


def run_job(job: dict) -> None:
    job_id = job["id"]
    output_dir = settings.OUTPUT_DIR / job_id

    try:
        jobs.update_job(job_id, progress_stage="extracting_audio")
        audio_path = audio.extract_audio(Path(job["source_path"]), output_dir / "audio.wav")

        jobs.update_job(job_id, progress_stage="transcribing")
        engine = _resolve_engine()
        transcript = transcribe.transcribe_diarize(audio_path, engine=engine, whisper_model=settings.WHISPER_MODEL)
        segments = transcript["segments"]

        jobs.update_job(job_id, progress_stage="extracting_frames")
        raw_frames = frames.extract_frames(Path(job["source_path"]), output_dir / "frames_raw")

        jobs.update_job(job_id, progress_stage="filtering_frames")
        candidates = frames.filter_frames(raw_frames)

        images_meta: list[dict] = []
        tables_meta: list[dict] = []
        sections: list[dict] = []
        title = "Video Transcript"

        if _llm_available():
            jobs.update_job(job_id, progress_stage="classifying_frames")
            images_meta, tables_meta = classify.classify_frames(candidates)

            jobs.update_job(job_id, progress_stage="composing_document")
            sections = compose.compose_document(segments, images_meta + tables_meta)
            title = compose.generate_title(sections)

        if not sections:
            sections = _fallback_sections(segments)

        jobs.update_job(job_id, progress_stage="rendering_document")
        doc_dir = output_dir / "document"
        doc_dir.mkdir(parents=True, exist_ok=True)
        images_by_id = {img["id"]: img for img in images_meta}
        tables_by_id = {tbl["id"]: tbl for tbl in tables_meta}

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
    except Exception as e:
        jobs.update_job(job_id, status="failed", progress_stage=None, error_message=str(e))
        if job.get("user_id") and job.get("billed_cents"):
            billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
