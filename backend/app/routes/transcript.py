"""Speaker-identity assignment and summary generation for audio transcript
jobs -- see plan/diarization-flow-plan.md. Renaming is a plain, synchronous
re-render (no LLM call, no worker/queue involvement): the transcript.json
already holds everything needed (segments, summary) to rebuild the document
with resolved names in place of "Speaker N" labels. Summary generation is
the one LLM call in this file, and deliberately a separate, user-triggered
action rather than automatic at job-finish time (see pipeline.py's run_job
audio branch for why) -- POST /api/jobs/{job_id}/summary below.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import jobs
from ..deps import get_current_user
from ..pipeline import _build_audio_sections, _llm_available
from ..stages import assemble, compose
from .documents import _owned_done_doc_dir

router = APIRouter()


class SetSpeakerNamesRequest(BaseModel):
    speaker_names: dict[str, str]


def _rerender_audio_document(job_id: str, job: dict, doc_dir, data: dict) -> None:
    """Shared tail of both endpoints below: rebuild sections from the
    (possibly just-updated) transcript.json contents and re-render every
    export format on top of the doc_dir already on disk from the original
    job run. Exports are best-effort, same as the original render in
    pipeline.py -- a DOCX/PDF failure here shouldn't lose the Markdown/JSON
    update that already succeeded."""
    title = job.get("title") or "Audio Transcript"
    sections = _build_audio_sections(data["segments"], data["summary"], data["speaker_names"])
    assemble.render_markdown(title, sections, {}, {}, doc_dir)
    try:
        assemble.render_docx(title, sections, {}, {}, doc_dir / "document.docx")
    except Exception as e:
        print(f"DOCX re-render failed for job {job_id}: {e}", flush=True)
    try:
        assemble.render_pdf(title, sections, {}, {}, doc_dir / "document.pdf")
    except Exception as e:
        print(f"PDF re-render failed for job {job_id}: {e}", flush=True)


@router.post("/api/jobs/{job_id}/speakers")
def set_speaker_names(job_id: str, body: SetSpeakerNamesRequest, current_user: dict = Depends(get_current_user)):
    doc_dir = _owned_done_doc_dir(job_id, current_user)
    job = jobs.get_job(job_id)
    if job["job_type"] != "audio":
        raise HTTPException(status_code=404, detail="Job not found")

    transcript_path = doc_dir / "transcript.json"
    if not transcript_path.is_file():
        raise HTTPException(status_code=404, detail="No transcript available for this job")

    data = json.loads(transcript_path.read_text())
    unknown = set(body.speaker_names) - set(data["speakers"])
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown speaker(s): {', '.join(sorted(unknown))}")

    data["speaker_names"].update(body.speaker_names)
    transcript_path.write_text(json.dumps(data, indent=2))

    _rerender_audio_document(job_id, job, doc_dir, data)
    return data


@router.post("/api/jobs/{job_id}/summary")
def generate_summary(job_id: str, current_user: dict = Depends(get_current_user)):
    """Generates (or regenerates) the one-paragraph summary on demand --
    the only LLM call for an audio job, and never run automatically at
    job-finish time (see pipeline.py's run_job). Safe to call more than
    once: each call overwrites transcript.json's `summary` and re-renders,
    same as renaming a speaker."""
    doc_dir = _owned_done_doc_dir(job_id, current_user)
    job = jobs.get_job(job_id)
    if job["job_type"] != "audio":
        raise HTTPException(status_code=404, detail="Job not found")
    if not _llm_available():
        raise HTTPException(status_code=400, detail="No LLM provider configured -- summaries aren't available.")

    transcript_path = doc_dir / "transcript.json"
    if not transcript_path.is_file():
        raise HTTPException(status_code=404, detail="No transcript available for this job")

    data = json.loads(transcript_path.read_text())
    try:
        data["summary"] = compose.generate_summary(data["segments"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summary generation failed: {e}")
    transcript_path.write_text(json.dumps(data, indent=2))

    _rerender_audio_document(job_id, job, doc_dir, data)
    return data
