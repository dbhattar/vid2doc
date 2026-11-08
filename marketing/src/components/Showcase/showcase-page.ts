// The /showcase page: every item, newest first, one page at a time. The page
// number lives in the URL (?page=N) so it can be linked and survives reload.
import { fetchShowcase, renderCard } from './showcase-core';

const PAGE_SIZE = 12;

const grid = document.getElementById('showcase-page-grid');
const status = document.getElementById('showcase-page-status');
const pager = document.getElementById('showcase-pager');

function currentPage(): number {
  const raw = Number(new URLSearchParams(window.location.search).get('page'));
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

function pageHref(page: number): string {
  return page === 1 ? '/showcase' : `/showcase?page=${page}`;
}

/** 1 … 4 5 [6] 7 8 … 20: always the first, last, and a window around the
 * current page, with gaps collapsed to an ellipsis. */
function pageNumbers(page: number, pageCount: number): (number | null)[] {
  const wanted = new Set([1, pageCount, page - 2, page - 1, page, page + 1, page + 2]);
  const numbers = [...wanted].filter((n) => n >= 1 && n <= pageCount).sort((a, b) => a - b);
  const out: (number | null)[] = [];
  numbers.forEach((n, i) => {
    if (i > 0 && n - numbers[i - 1] > 1) out.push(null);
    out.push(n);
  });
  return out;
}

function pagerLink(label: string, page: number, options: { current?: boolean; disabled?: boolean; aria?: string }) {
  const el = document.createElement(options.disabled || options.current ? 'span' : 'a');
  el.className = 'showcase-pager-item';
  el.textContent = label;
  if (options.aria) el.setAttribute('aria-label', options.aria);
  if (options.current) {
    el.classList.add('is-current');
    el.setAttribute('aria-current', 'page');
  } else if (options.disabled) {
    el.classList.add('is-disabled');
  } else {
    (el as HTMLAnchorElement).href = pageHref(page);
  }
  return el;
}

function renderPager(page: number, pageCount: number) {
  if (!pager) return;
  pager.replaceChildren();
  if (pageCount <= 1) return;
  pager.appendChild(pagerLink('Previous', page - 1, { disabled: page <= 1, aria: 'Previous page' }));
  for (const n of pageNumbers(page, pageCount)) {
    if (n === null) {
      const gap = document.createElement('span');
      gap.className = 'showcase-pager-gap';
      gap.textContent = '…';
      pager.appendChild(gap);
    } else {
      pager.appendChild(pagerLink(String(n), n, { current: n === page, aria: `Page ${n}` }));
    }
  }
  pager.appendChild(pagerLink('Next', page + 1, { disabled: page >= pageCount, aria: 'Next page' }));
}

async function load() {
  if (!grid || !status) return;
  const page = currentPage();
  try {
    const { items, total } = await fetchShowcase({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
    const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > pageCount) {
      // A stale/hand-edited ?page= past the end -- show the last real page.
      window.location.replace(pageHref(pageCount));
      return;
    }
    if (items.length === 0) {
      status.textContent = 'Nothing to show yet. Check back soon.';
      return;
    }
    status.hidden = true;
    for (const item of items) grid.appendChild(renderCard(item));
    renderPager(page, pageCount);
  } catch {
    status.textContent = "Couldn't load examples right now. Please try again in a moment.";
  }
}

load();
