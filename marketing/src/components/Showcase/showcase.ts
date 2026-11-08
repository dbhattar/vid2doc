// Homepage showcase carousel: a few random examples (a different handful on
// each visit), with the popup detail view and card rendering shared with the
// /showcase page via showcase-core.ts.
import { fetchShowcase, renderCard } from './showcase-core';

const HOMEPAGE_ITEM_COUNT = 5;

const section = document.getElementById('showcase');
const track = document.getElementById('showcase-grid');
const prevButton = document.getElementById('showcase-prev') as HTMLButtonElement | null;
const nextButton = document.getElementById('showcase-next') as HTMLButtonElement | null;

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

// ---- initial load ---------------------------------------------------------

if (section && track) {
  fetchShowcase({ limit: HOMEPAGE_ITEM_COUNT, random: true })
    .then(({ items }) => {
      if (items.length === 0) return;
      for (const item of items) track.appendChild(renderCard(item));

      // Hidden by default (see Showcase.astro) -- only revealed once we know
      // there's at least one item to show, same "hide the section if there
      // are none" convention as Testimonials.
      section.hidden = false;
      updateNavVisibility();
    })
    .catch(() => {
      // No API reachable / nothing to show -- stay hidden, same as
      // testimonials.ts. Not worth surfacing an error for a marketing
      // section.
    });
}
