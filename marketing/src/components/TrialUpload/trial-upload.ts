// The `declare global` augmentation below only applies if this file is
// treated as an ES module -- it already is once Astro/Vite bundles it (it's
// pulled in via `import './trial-upload.ts'`), but this explicit `export {}`
// makes that true for the TS language server analyzing the file in
// isolation too, so it stops flagging window.gtag/turnstile/etc as unknown.
export {};

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
    turnstile?: {
      reset: (widget?: string | HTMLElement) => void;
    };
    onTrialTurnstileSuccess?: (token: string) => void;
    onTrialTurnstileExpired?: () => void;
  }
}

// Duplicated from backend/app/config.py's ALLOWED_EXTENSIONS/AUDIO_EXTENSIONS
// and the trial-specific caps -- this is a static, rarely-changing list, and
// the marketing site has no shared package with the backend to import it
// from. The server enforces the real caps regardless; this is just a fast,
// friendly client-side check.
const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'];
const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma'];
const MAX_VIDEO_SECONDS = 10 * 60;
const MAX_AUDIO_SECONDS = 30 * 60;
const POLL_INTERVAL_MS = 3000;

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

// Persists the in-flight job id across a reload/navigate-away -- otherwise
// a job that takes a couple minutes has no way to be found again once the
// page state is gone, even though it keeps processing (and using up one of
// the 2 free tries/day) server-side regardless of whether anyone's watching.
const STORAGE_KEY = 'framewrite:trialJobId';

function saveJobId(jobId: string) {
  try {
    localStorage.setItem(STORAGE_KEY, jobId);
  } catch {
    // Private-browsing/storage-disabled -- resume-on-reload just won't work
    // for this visitor, not worth surfacing an error for.
  }
}

function clearJobId() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // See saveJobId.
  }
}

function loadJobId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

const PROGRESS_LABELS: Record<string, string> = {
  extracting_audio: 'Extracting audio...',
  transcribing: 'Transcribing...',
  extracting_frames: 'Scanning for slides and diagrams...',
  filtering_frames: 'Scanning for slides and diagrams...',
  classifying_frames: 'Identifying what’s on screen...',
  captioning_frames: 'Writing captions...',
  composing_document: 'Writing your document...',
  rendering_document: 'Formatting your document...',
};

type JobType = 'video' | 'audio';

function jobTypeForFilename(filename: string): JobType | null {
  const dot = filename.lastIndexOf('.');
  if (dot === -1) return null;
  const ext = filename.slice(dot).toLowerCase();
  if (VIDEO_EXTENSIONS.includes(ext)) return 'video';
  if (AUDIO_EXTENSIONS.includes(ext)) return 'audio';
  return null;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function probeDuration(file: File, jobType: JobType): Promise<number> {
  return new Promise((resolve, reject) => {
    const el = document.createElement(jobType === 'video' ? 'video' : 'audio');
    el.preload = 'metadata';
    const url = URL.createObjectURL(file);
    el.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      resolve(el.duration);
    };
    el.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('unreadable'));
    };
    el.src = url;
  });
}

const form = document.getElementById('trial-form');

if (form) {
  const fileInput = document.getElementById('trial-file') as HTMLInputElement;
  const fileLabel = document.getElementById('trial-file-label') as HTMLElement;
  const submitBtn = document.getElementById('trial-submit') as HTMLButtonElement;
  const errorEl = document.getElementById('trial-error') as HTMLElement;
  const processingEl = document.getElementById('trial-processing') as HTMLElement;
  const statusEl = document.getElementById('trial-status') as HTMLElement;
  const resultEl = document.getElementById('trial-result') as HTMLElement;
  const downloadsEl = document.getElementById('trial-downloads') as HTMLElement;
  const failedEl = document.getElementById('trial-failed') as HTMLElement;
  const failedMessageEl = document.getElementById('trial-failed-message') as HTMLElement;
  const retryBtn = document.getElementById('trial-retry') as HTMLButtonElement;
  const startOverBtn = document.getElementById('trial-start-over');
  const ctaLink = document.getElementById('trial-cta');
  const turnstileHintEl = document.getElementById('trial-turnstile-hint');
  const turnstileContainer = document.querySelector('.cf-turnstile');

  const panels: Record<string, HTMLElement> = {
    idle: form as HTMLElement,
    processing: processingEl,
    done: resultEl,
    failed: failedEl,
  };

  const trackEvent = (name: string, params?: Record<string, unknown>) => {
    if (typeof window.gtag === 'function') {
      window.gtag('event', name, params || {});
    }
  };

  let selectedFile: File | null = null;
  let selectedJobType: JobType | null = null;
  let turnstileToken: string | null = null;
  let pollTimeoutId: ReturnType<typeof setTimeout> | undefined;

  function setPanel(name: keyof typeof panels) {
    for (const [key, el] of Object.entries(panels)) {
      el.hidden = key !== name;
    }
  }

  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = '';
  }

  function showError(message: string) {
    errorEl.hidden = false;
    errorEl.textContent = message;
  }

  function updateSubmitEnabled() {
    submitBtn.disabled = !selectedFile || !turnstileToken;
  }

  window.onTrialTurnstileSuccess = (token: string) => {
    turnstileToken = token;
    if (turnstileHintEl) turnstileHintEl.hidden = true;
    updateSubmitEnabled();
  };
  window.onTrialTurnstileExpired = () => {
    turnstileToken = null;
    updateSubmitEnabled();
  };

  fileInput.addEventListener('change', async () => {
    clearError();
    const file = fileInput.files?.[0];
    if (!file) {
      selectedFile = null;
      selectedJobType = null;
      fileLabel.textContent = 'Click to choose a video or audio file...';
      updateSubmitEnabled();
      return;
    }

    const jobType = jobTypeForFilename(file.name);
    if (!jobType) {
      showError('Unsupported file type.');
      fileInput.value = '';
      selectedFile = null;
      updateSubmitEnabled();
      return;
    }

    try {
      const duration = await probeDuration(file, jobType);
      const cap = jobType === 'video' ? MAX_VIDEO_SECONDS : MAX_AUDIO_SECONDS;
      if (duration > cap) {
        showError(
          `This ${jobType} is ${formatDuration(duration)} -- the free trial caps out at ${formatDuration(cap)}.`,
        );
        fileInput.value = '';
        selectedFile = null;
        updateSubmitEnabled();
        return;
      }
    } catch {
      // Can't read duration client-side (unusual container/codec) -- let
      // the server be the real judge. This check is just a fast, friendly
      // heads-up, not the actual enforcement boundary.
    }

    selectedFile = file;
    selectedJobType = jobType;
    fileLabel.textContent = file.name;
    updateSubmitEnabled();
  });

  async function pollStatus(jobId: string) {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/trial/status/${jobId}`);
    } catch {
      pollTimeoutId = setTimeout(() => pollStatus(jobId), POLL_INTERVAL_MS);
      return;
    }
    if (!res.ok) {
      clearJobId();
      failedMessageEl.textContent =
        res.status === 404
          ? "We couldn't find that upload anymore -- it may have expired."
          : 'Something went wrong checking your job.';
      setPanel('failed');
      return;
    }
    const job = await res.json();
    if (job.status === 'done') {
      clearJobId();
      trackEvent('trial_upload_done', { job_type: selectedJobType });
      showResult(job);
      return;
    }
    if (job.status === 'failed') {
      clearJobId();
      trackEvent('trial_upload_failed', { job_type: selectedJobType, reason: job.error });
      failedMessageEl.textContent = job.error || 'Processing failed -- please try a different file.';
      setPanel('failed');
      return;
    }
    statusEl.textContent = PROGRESS_LABELS[job.progress_stage] || 'Processing...';
    pollTimeoutId = setTimeout(() => pollStatus(jobId), POLL_INTERVAL_MS);
  }

  function showResult(job: Record<string, string | undefined>) {
    setPanel('done');
    downloadsEl.innerHTML = '';
    const links: [string | undefined, string][] = [
      [job.document_url, 'Markdown'],
      [job.document_docx_url, 'Word'],
      [job.document_pdf_url, 'PDF'],
      [job.document_transcript_json_url, 'Transcript JSON'],
    ];
    for (const [url, label] of links) {
      if (!url) continue;
      const a = document.createElement('a');
      a.href = url;
      a.textContent = `Download ${label}`;
      a.target = '_blank';
      a.rel = 'noopener';
      downloadsEl.appendChild(a);
    }
  }

  function resetForm() {
    if (pollTimeoutId) clearTimeout(pollTimeoutId);
    clearJobId();
    selectedFile = null;
    selectedJobType = null;
    turnstileToken = null;
    fileInput.value = '';
    fileLabel.textContent = 'Click to choose a video or audio file...';
    clearError();
    updateSubmitEnabled();
    if (window.turnstile) window.turnstile.reset();
    setPanel('idle');
  }

  retryBtn.addEventListener('click', resetForm);
  startOverBtn?.addEventListener('click', resetForm);
  ctaLink?.addEventListener('click', () => trackEvent('trial_upload_cta_click', { job_type: selectedJobType }));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!selectedFile || !selectedJobType || !turnstileToken) return;

    clearError();
    setPanel('processing');
    statusEl.textContent = 'Uploading...';
    trackEvent('trial_upload_submit', { job_type: selectedJobType });

    const formData = new FormData();
    formData.append(selectedJobType, selectedFile);
    formData.append('turnstile_token', turnstileToken);
    const endpoint = selectedJobType === 'audio' ? '/api/trial/transcribe_audio' : '/api/trial/convert_to_doc';

    try {
      const res = await fetch(`${API_URL}${endpoint}`, { method: 'POST', body: formData });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed (${res.status})`);
      }
      const { job_id } = await res.json();
      saveJobId(job_id);
      pollStatus(job_id);
    } catch (err) {
      failedMessageEl.textContent = err instanceof Error ? err.message : 'Upload failed.';
      setPanel('failed');
      if (window.turnstile) window.turnstile.reset();
      turnstileToken = null;
    }
  });

  // If the widget hasn't rendered an iframe after a few seconds, a browser
  // extension (ad blocker/privacy tool) is very likely blocking
  // challenges.cloudflare.com outright -- we can't force it through, but we
  // can at least explain what's happening instead of leaving the submit
  // button silently disabled forever with no clue why.
  const TURNSTILE_RENDER_TIMEOUT_MS = 6000;
  setTimeout(() => {
    if (turnstileToken || !turnstileHintEl) return;
    const rendered = turnstileContainer?.querySelector('iframe');
    if (!rendered) turnstileHintEl.hidden = false;
  }, TURNSTILE_RENDER_TIMEOUT_MS);

  // Resume a job that was still in flight the last time this page was open
  // (reload, closed tab, navigated away and came back) -- otherwise it'd
  // just be lost track of client-side while it keeps processing server-side.
  const resumeJobId = loadJobId();
  if (resumeJobId) {
    setPanel('processing');
    statusEl.textContent = 'Checking your previous upload...';
    pollStatus(resumeJobId);
  }
}
