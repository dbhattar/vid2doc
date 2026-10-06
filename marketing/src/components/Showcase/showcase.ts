type ShowcaseItem = { id: string; title: string | null; duration_seconds: number | null; video_url?: string };

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';
const APP_URL = import.meta.env.PUBLIC_APP_URL || 'http://localhost:3000';

const section = document.getElementById('showcase');
const grid = document.getElementById('showcase-grid');

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '';
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

if (section && grid) {
  fetch(`${API_URL}/api/public/showcase`)
    .then((res) => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then((data: { jobs: ShowcaseItem[] }) => {
      if (!data.jobs || data.jobs.length === 0) return;

      for (const item of data.jobs) {
        const card = document.createElement('a');
        card.className = 'showcase-card';
        card.href = `${APP_URL}/showcase/${item.id}`;

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

        grid.appendChild(card);
      }

      // Hidden by default (see Showcase.astro) -- only revealed once we know
      // there's at least one approved item to show, same "hide the section
      // if there are none" convention as Testimonials.
      section.hidden = false;
    })
    .catch(() => {
      // No API reachable / no approved items -- stay hidden, same as
      // testimonials.ts. Not worth surfacing an error for a marketing section.
    });
}
