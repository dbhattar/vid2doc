// Homepage showcase carousel + its popup detail view. Cards are plain
// buttons (not links) -- clicking one opens the modal below instead of
// navigating away to a separate page, per the redesign that replaced the
// old "card links out to the frontend app's own /showcase/[id] page" setup.
// The modal renders the complete view itself (video, full markdown document,
// downloads) rather than linking out to that page -- see renderDocument
// below for the from-scratch markdown rendering (that page uses React +
// react-markdown, not available here; `marked` + a small CSS block is this
// project's equivalent).
import { marked } from 'marked';

type ShowcaseListItem = {
  id: string;
  title: string | null;
  duration_seconds: number | null;
  video_url?: string;
  document_url?: string;
};

type ShowcaseDetail = ShowcaseListItem & {
  featured_since: string;
  document_docx_url?: string;
  document_pdf_url?: string;
  document_transcript_json_url?: string;
};

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

const section = document.getElementById('showcase');
const track = document.getElementById('showcase-grid');
const prevButton = document.getElementById('showcase-prev') as HTMLButtonElement | null;
const nextButton = document.getElementById('showcase-next') as HTMLButtonElement | null;

const overlay = document.getElementById('showcase-modal-overlay');
const modalBody = document.getElementById('showcase-modal-body');
const modalCloseButton = document.getElementById('showcase-modal-close');
const modalTitleId = 'showcase-modal-title';

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '';
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

// ---- carousel nav ---------------------------------------------------------

/** Shows the prev/next arrows only once the track actually overflows --
 * on a wide screen with few items there may be nothing to scroll to. */
function updateNavVisibility() {
  if (!track || !prevButton || !nextButton) return;
  const overflowing = track.scrollWidth > track.clientWidth + 1;
  prevButton.hidden = !overflowing;
  nextButton.hidden = !overflowing;
}

function scrollByOneCard(direction: 1 | -1) {
  if (!track) return;
  const firstCard = track.firstElementChild as HTMLElement | null;
  const gap = 20;
  const amount = (firstCard?.getBoundingClientRect().width ?? track.clientWidth * 0.8) + gap;
  track.scrollBy({ left: amount * direction, behavior: 'smooth' });
}

prevButton?.addEventListener('click', () => scrollByOneCard(-1));
nextButton?.addEventListener('click', () => scrollByOneCard(1));
window.addEventListener('resize', updateNavVisibility);

// ---- markdown rendering ---------------------------------------------------

/** Pulls a leading "## Summary" section (see backend/app/pipeline.py's
 * _prepend_summary_section, video documents only) out of the raw markdown so
 * it can be rendered in its own highlighted box -- mirrors
 * frontend/components/DocumentPreview.tsx's splitSummarySection exactly
 * (same regex, same "up to the next ## heading" boundary). Anything without
 * that heading (including audio jobs, which never reach this showcase flow
 * anyway) is returned unchanged as `before`. */
function splitSummarySection(markdown: string): { before: string; summary: string | null; after: string } {
  const match = markdown.match(/^## Summary\s*$/m);
  if (!match || match.index == null) return { before: markdown, summary: null, after: '' };
  const start = match.index;
  const rest = markdown.slice(start);
  const nextHeadingOffset = rest.slice(1).search(/^## /m);
  const end = nextHeadingOffset === -1 ? rest.length : nextHeadingOffset + 1;
  return { before: markdown.slice(0, start), summary: rest.slice(0, end), after: rest.slice(end) };
}

/** Parses one markdown chunk to HTML and resolves every image's `src`
 * against `baseUrl` (the document's own URL) -- a DOM walk after the fact
 * rather than a custom marked renderer, so this keeps working regardless of
 * marked's internal renderer API shape across versions. Images here are an
 * arbitrary public S3/CDN URL (see backend/app/routes/public_jobs.py), same
 * as DocumentPreview's `external` mode -- a plain `<img>` needs no CORS
 * setup, only the markdown fetch itself does. */
function renderMarkdownChunk(markdown: string, baseUrl: string): HTMLDivElement {
  const container = document.createElement('div');
  container.innerHTML = marked.parse(markdown, { async: false }) as string;
  container.querySelectorAll('img').forEach((img) => {
    const src = img.getAttribute('src');
    if (src) {
      try {
        img.src = new URL(src, baseUrl).toString();
      } catch {
        // Malformed URL -- leave as-is rather than break the whole render.
      }
    }
    img.loading = 'lazy';
  });
  container.querySelectorAll('a').forEach((a) => {
    a.target = '_blank';
    a.rel = 'noreferrer';
  });
  // A wide generated table (common in these documents) would otherwise force
  // the whole modal wider than its fixed max-width instead of just scrolling
  // its own row -- wrap each table so only it scrolls horizontally.
  container.querySelectorAll('table').forEach((table) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'showcase-modal-table-wrap';
    table.parentNode?.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });
  return container;
}

function renderDocumentInto(container: HTMLElement, markdown: string, baseUrl: string) {
  container.replaceChildren();
  const { before, summary, after } = splitSummarySection(markdown);
  container.appendChild(renderMarkdownChunk(before, baseUrl));
  if (summary) {
    const summaryBox = document.createElement('div');
    summaryBox.className = 'showcase-modal-summary';
    summaryBox.appendChild(renderMarkdownChunk(summary, baseUrl));
    container.appendChild(summaryBox);
  }
  if (after) {
    container.appendChild(renderMarkdownChunk(after, baseUrl));
  }
}

// ---- modal ------------------------------------------------------------

// Tracks which item the modal is currently showing, so a fetch that resolves
// after the user has closed the modal (or opened a different card) doesn't
// overwrite whatever's showing now with stale data.
let currentItemId: string | null = null;

function closeModal() {
  if (!overlay) return;
  currentItemId = null;
  overlay.hidden = true;
  document.body.style.removeProperty('overflow');
  // Stop playback (and any sound) the instant the modal closes, rather than
  // leaving a video running behind a now-hidden overlay.
  modalBody?.querySelector('video')?.pause();
}

function setLoadingMessage(container: HTMLElement, text: string) {
  container.replaceChildren();
  const p = document.createElement('p');
  p.className = 'showcase-modal-loading';
  p.textContent = text;
  container.appendChild(p);
}

/** Builds the modal's fixed shell once per open -- video, title, meta, plus
 * two containers (`actions`/`document`) filled in independently and
 * asynchronously by renderActions()/loadDocument() below. Keeping those two
 * separate from this skeleton (rather than re-rendering everything each time
 * new data arrives, as an earlier version of this file did) matters for the
 * video specifically: recreating it every time the detail fetch resolved
 * restarted playback from 0 even if the visitor had already pressed play. */
function buildModalSkeleton(item: ShowcaseListItem): { actions: HTMLDivElement; document: HTMLDivElement } {
  if (!modalBody) throw new Error('modal body missing');
  modalBody.replaceChildren();

  if (item.video_url) {
    const video = document.createElement('video');
    video.className = 'showcase-modal-video';
    video.src = item.video_url;
    video.controls = true;
    video.autoplay = true;
    video.playsInline = true;
    modalBody.appendChild(video);
  }

  const title = document.createElement('h3');
  title.className = 'showcase-modal-title';
  title.id = modalTitleId;
  title.textContent = item.title?.trim() || 'Untitled document';
  modalBody.appendChild(title);

  const meta = document.createElement('p');
  meta.className = 'showcase-modal-meta';
  const duration = formatDuration(item.duration_seconds);
  meta.textContent = duration ? `${duration} · featured on Framewrite` : 'Featured on Framewrite';
  modalBody.appendChild(meta);

  const actions = document.createElement('div');
  actions.className = 'showcase-modal-actions';
  setLoadingMessage(actions, 'Loading download links...');
  modalBody.appendChild(actions);

  const documentContainer = document.createElement('div');
  documentContainer.className = 'showcase-modal-document';
  setLoadingMessage(documentContainer, 'Loading document...');
  modalBody.appendChild(documentContainer);

  return { actions, document: documentContainer };
}

function renderActions(container: HTMLElement, detail: ShowcaseDetail) {
  container.replaceChildren();
  const downloads: { href: string | undefined; label: string; variant: 'btn-primary' | 'btn-secondary' }[] = [
    { href: detail.document_url, label: 'Download Markdown', variant: 'btn-primary' },
    { href: detail.document_docx_url, label: 'Download Word', variant: 'btn-secondary' },
    { href: detail.document_pdf_url, label: 'Download PDF', variant: 'btn-secondary' },
    { href: detail.document_transcript_json_url, label: 'Download Transcript', variant: 'btn-secondary' },
  ];
  for (const { href, label, variant } of downloads) {
    if (!href) continue;
    const link = document.createElement('a');
    link.className = variant;
    link.href = href;
    link.download = '';
    link.textContent = label;
    container.appendChild(link);
  }
}

async function loadDocument(container: HTMLElement, item: ShowcaseListItem) {
  if (!item.document_url) {
    container.replaceChildren();
    return;
  }
  try {
    const res = await fetch(item.document_url);
    if (!res.ok) throw new Error(res.statusText);
    const markdown = await res.text();
    if (currentItemId !== item.id) return; // closed/changed while in flight
    renderDocumentInto(container, markdown, item.document_url);
  } catch {
    if (currentItemId !== item.id) return;
    setLoadingMessage(container, "Couldn't load the document preview.");
  }
}

function openModal(listItem: ShowcaseListItem) {
  if (!overlay) return;
  currentItemId = listItem.id;
  overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  const { actions, document: documentContainer } = buildModalSkeleton(listItem);
  // The list payload already includes document_url (see
  // backend/app/routes/public_jobs.py's _build_showcase_response) -- the
  // document itself can start rendering immediately, in parallel with the
  // detail fetch below, which exists only for the extra download links
  // (docx/pdf/transcript) that endpoint adds.
  loadDocument(documentContainer, listItem);

  fetch(`${API_URL}/api/public/showcase/${listItem.id}`)
    .then((res) => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then((detail: ShowcaseDetail) => {
      if (currentItemId !== listItem.id) return;
      renderActions(actions, detail);
    })
    .catch(() => {
      if (currentItemId !== listItem.id) return;
      setLoadingMessage(actions, 'Could not load the download links for this item.');
    });
}

modalCloseButton?.addEventListener('click', closeModal);
overlay?.addEventListener('click', (ev) => {
  // Only the backdrop itself, not a click that bubbled up from inside the
  // modal panel -- clicking "outside" the popup is what should close it.
  if (ev.target === overlay) closeModal();
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && overlay && !overlay.hidden) closeModal();
});

// ---- initial load ---------------------------------------------------------

if (section && track) {
  fetch(`${API_URL}/api/public/showcase`)
    .then((res) => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then((data: { jobs: ShowcaseListItem[] }) => {
      if (!data.jobs || data.jobs.length === 0) return;

      for (const item of data.jobs) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'showcase-card';
        card.addEventListener('click', () => openModal(item));

        if (item.video_url) {
          const preview = document.createElement('video');
          preview.className = 'showcase-preview';
          preview.src = item.video_url;
          preview.muted = true;
          preview.loop = true;
          preview.playsInline = true;
          preview.autoplay = true;
          preview.preload = 'metadata';
          card.appendChild(preview);
        }

        const title = document.createElement('p');
        title.className = 'showcase-title';
        title.textContent = item.title?.trim() || 'Untitled document';
        card.appendChild(title);

        const meta = document.createElement('p');
        meta.className = 'showcase-meta';
        meta.textContent = formatDuration(item.duration_seconds);
        card.appendChild(meta);

        track.appendChild(card);
      }

      // Hidden by default (see Showcase.astro) -- only revealed once we know
      // there's at least one approved item to show, same "hide the section
      // if there are none" convention as Testimonials.
      section.hidden = false;
      updateNavVisibility();
    })
    .catch(() => {
      // No API reachable / no approved items -- stay hidden, same as
      // testimonials.ts. Not worth surfacing an error for a marketing
      // section.
    });
}
