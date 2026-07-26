"""Speaker-identity assignment for audio transcript jobs -- see
plan/diarization-flow-plan.md. Renaming is a plain, synchronous re-render
(no LLM call, no worker/queue involvement): the transcript.json already
holds everything needed (segments, summary) to rebuild the document with
resolved names in place of "Speaker N" labels.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import jobs
from ..deps import get_current_user
from ..pipeline import _build_audio_sections
from ..stages import assemble
from .documents import _owned_done_doc_dir

router = APIRouter()


class SetSpeakerNamesRequest(BaseModel):
    speaker_names: dict[str, str]


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

    return data
