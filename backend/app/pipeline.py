import os
from pathlib import Path

from . import jobs
from .config import settings
from .stages import assemble, audio, frames, sections, transcribe, vision


def _resolve_engine() -> str:
    engine = settings.TRANSCRIPTION_ENGINE
    if engine != "auto":
        return engine
    if os.environ.get("ASSEMBLYAI_API_KEY"):
        return "assemblyai"
    if os.environ.get("HF_TOKEN"):
        return "whisper-diarized"
    return "whisper"


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

        accepted_frames: list[dict] = []
        section_list: list[dict] = []
        if os.environ.get("ANTHROPIC_API_KEY"):
            jobs.update_job(job_id, progress_stage="judging_frames")
            accepted_frames = vision.judge_frames(candidates, segments)

            jobs.update_job(job_id, progress_stage="segmenting_topics")
            section_list = sections.segment_transcript(segments)

        jobs.update_job(job_id, progress_stage="assembling_document")
        matched_frames = assemble.match_frames_to_segments(accepted_frames, segments)
        doc_dir = output_dir / "document"
        doc_path = assemble.assemble_document(section_list, segments, matched_frames, doc_dir)

        jobs.update_job(job_id, status="done", progress_stage="done", document_path=str(doc_path))
    except Exception as e:
        jobs.update_job(job_id, status="failed", progress_stage=None, error_message=str(e))
