import type { Job, JobType } from "./jobs";

/** One entry per real backend `progress_stage` token, in the exact order
 * pipeline.py sets them (see backend/app/pipeline.py) -- this is the
 * "maximal" path for each job_type: some stages are conditional server-side
 * (e.g. classifying_frames only runs if an LLM is configured), but since the
 * frontend only ever observes the *current* progress_stage via polling (no
 * stage-history log exists), a skipped conditional stage simply flashes past
 * as instantly-done once the job moves beyond it. Not worth solving further. */
export type StageDef = {
  key: string;
  label: string;
  flavor: string;
  /** Only true for the two review-pause pseudo-stages -- rendered as a
   * static "your turn" state, never the pulsing "in progress" one. */
  awaitingInput?: boolean;
};

export type StageStatus = "done" | "current" | "awaiting-input" | "failed" | "cancelled" | "pending";

const VIDEO_STAGES: StageDef[] = [
  { key: "downloading", label: "Downloading video", flavor: "Pulling the video down from the source URL." },
  { key: "extracting_frames", label: "Extracting frames", flavor: "Stepping through the video frame by frame." },
  { key: "filtering_frames", label: "Filtering frames", flavor: "Dropping near-duplicates and dead air." },
  { key: "classifying_frames", label: "Classifying frames", flavor: "Sorting what's on screen — slides, tables, diagrams." },
  { key: "captioning_frames", label: "Captioning frames", flavor: "Writing a caption for every frame that made the cut." },
  { key: "awaiting_review", label: "Awaiting your review", flavor: "Your call — pick which frames belong in the document.", awaitingInput: true },
  { key: "extracting_audio", label: "Extracting audio", flavor: "Pulling the audio track for transcription." },
  { key: "transcribing", label: "Transcribing", flavor: "Listening closely and writing down every word." },
  { key: "composing_document", label: "Composing document", flavor: "Organizing the transcript and frames into sections." },
  { key: "rendering_document", label: "Rendering document", flavor: "Laying out the final Markdown, Word, and PDF." },
];

const AUDIO_STAGES: StageDef[] = [
  { key: "extracting_audio", label: "Extracting audio", flavor: "Preparing the audio for transcription." },
  { key: "transcribing", label: "Transcribing", flavor: "Listening closely and writing down every word, speaker by speaker." },
  { key: "summarizing", label: "Summarizing", flavor: "Boiling the conversation down to the key points." },
  { key: "rendering_document", label: "Rendering document", flavor: "Laying out the transcript as a document." },
];

const VIDEO_GEN_STAGES: StageDef[] = [
  { key: "extracting_audio", label: "Extracting audio", flavor: "Preparing your narration for transcription." },
  { key: "transcribing", label: "Transcribing", flavor: "Listening closely and writing down every word." },
  { key: "segmenting_scenes", label: "Segmenting scenes", flavor: "Splitting the narration into scenes." },
  { key: "generating_headlines", label: "Generating headlines", flavor: "Writing an on-screen headline for each scene." },
  { key: "fetching_stock_media", label: "Fetching stock media", flavor: "Scouting footage and photos to match each scene." },
  { key: "awaiting_scene_review", label: "Awaiting your review", flavor: "Your call — review the scenes and swap in better footage.", awaitingInput: true },
  { key: "rendering_scenes", label: "Rendering scenes", flavor: "Rendering each scene with its footage and captions." },
  { key: "assembling_video", label: "Assembling video", flavor: "Stitching every scene into the final video." },
];

export function getStagesForJobType(jobType: JobType): StageDef[] {
  if (jobType === "audio") return AUDIO_STAGES;
  if (jobType === "video_gen") return VIDEO_GEN_STAGES;
  return VIDEO_STAGES;
}

/** stages.length (past the end, everything checked) once the job is done;
 * -1 if progress_stage doesn't match anything in this job_type's list
 * (queued, or a transient resuming_after_* marker) -- callers treat -1 as
 * "every stage still pending, nothing current yet." */
function getCurrentStageIndex(stages: StageDef[], job: Job): number {
  if (job.status === "done") return stages.length;
  return stages.findIndex((s) => s.key === job.progress_stage);
}

/** The one place all per-row status branching happens -- ProgressBar and
 * ProgressStepper only render this, they never re-derive it. */
export function getStageStatuses(job: Job): { stage: StageDef; status: StageStatus }[] {
  const stages = getStagesForJobType(job.job_type);
  const currentIndex = getCurrentStageIndex(stages, job);

  return stages.map((stage, i) => {
    if (i < currentIndex) return { stage, status: "done" as const };
    if (i > currentIndex) return { stage, status: "pending" as const };
    // i === currentIndex
    if (job.status === "failed") return { stage, status: "failed" as const };
    if (job.status === "cancelled") return { stage, status: "cancelled" as const };
    if (stage.awaitingInput) return { stage, status: "awaiting-input" as const };
    return { stage, status: "current" as const };
  });
}
