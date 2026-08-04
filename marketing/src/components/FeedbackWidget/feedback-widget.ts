export {};

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: string | HTMLElement,
        options: Record<string, unknown>,
      ) => string | undefined;
      reset: (widget?: string | HTMLElement) => void;
    };
  }
}

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';
const TURNSTILE_POLL_MS = 100;

const root = document.querySelector('.feedback-widget');
const fab = document.getElementById('feedback-fab');
const panel = document.getElementById('feedback-panel') as HTMLElement | null;
const closeBtn = document.getElementById('feedback-close');
const closeSentBtn = document.getElementById('feedback-close-sent');
const form = document.getElementById('feedback-form') as HTMLFormElement | null;
const messageInput = document.getElementById('feedback-message') as HTMLTextAreaElement | null;
const emailInput = document.getElementById('feedback-email') as HTMLInputElement | null;
const submitBtn = document.getElementById('feedback-submit') as HTMLButtonElement | null;
const errorEl = document.getElementById('feedback-error') as HTMLElement | null;
const idleContent = document.querySelector('[data-panel-content="idle"]') as HTMLElement | null;
const sentContent = document.querySelector('[data-panel-content="sent"]') as HTMLElement | null;
const turnstileContainer = document.getElementById('feedback-turnstile');

if (
  root &&
  fab &&
  panel &&
  form &&
  messageInput &&
  emailInput &&
  submitBtn &&
  errorEl &&
  idleContent &&
  sentContent &&
  turnstileContainer
) {
  let turnstileToken: string | null = null;
  let turnstileWidgetId: string | undefined;
  let turnstileRenderStarted = false;
  let open = false;

  function updateSubmitEnabled() {
    submitBtn!.disabled = !messageInput!.value.trim() || !turnstileToken;
  }

  // Explicit + lazy on purpose -- see the comment on #feedback-turnstile in
  // FeedbackWidget.astro. Only called once the panel is visible, so the
  // container has real dimensions to render an iframe into.
  function renderTurnstileIfNeeded() {
    if (turnstileRenderStarted) return;
    const sitekey = turnstileContainer!.dataset.sitekey;
    if (!sitekey) return;
    if (!window.turnstile) {
      setTimeout(renderTurnstileIfNeeded, TURNSTILE_POLL_MS);
      return;
    }
    turnstileRenderStarted = true;
    turnstileWidgetId = window.turnstile.render(turnstileContainer!, {
      sitekey,
      callback: (token: string) => {
        turnstileToken = token;
        updateSubmitEnabled();
      },
      'expired-callback': () => {
        turnstileToken = null;
        updateSubmitEnabled();
      },
    });
  }

  function setOpen(next: boolean) {
    open = next;
    panel!.hidden = !open;
    fab!.setAttribute('aria-expanded', String(open));
    root!.setAttribute('data-state', open ? 'open' : 'closed');
    if (open) renderTurnstileIfNeeded();
  }

  function showPanel(name: 'idle' | 'sent') {
    idleContent!.hidden = name !== 'idle';
    sentContent!.hidden = name !== 'sent';
  }

  function clearError() {
    errorEl!.hidden = true;
    errorEl!.textContent = '';
  }

  function showError(message: string) {
    errorEl!.hidden = false;
    errorEl!.textContent = message;
  }

  fab.addEventListener('click', () => setOpen(!open));
  closeBtn?.addEventListener('click', () => setOpen(false));
  closeSentBtn?.addEventListener('click', () => setOpen(false));

  document.addEventListener('mousedown', (e) => {
    if (open && !root!.contains(e.target as Node)) setOpen(false);
  });

  messageInput.addEventListener('input', updateSubmitEnabled);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = messageInput!.value.trim();
    if (!message || !turnstileToken) return;

    clearError();
    submitBtn!.disabled = true;

    try {
      const res = await fetch(`${API_URL}/api/public/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          email: emailInput!.value.trim() || null,
          turnstile_token: turnstileToken,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to send feedback (${res.status})`);
      }
      messageInput!.value = '';
      emailInput!.value = '';
      showPanel('sent');
    } catch (err) {
      showError(err instanceof Error ? err.message : 'Failed to send feedback.');
      // Pass this widget's own id/container -- omitting it resets every
      // Turnstile widget on the page, including TrialUpload's on the
      // homepage.
      if (window.turnstile) window.turnstile.reset(turnstileWidgetId ?? turnstileContainer!);
      turnstileToken = null;
      updateSubmitEnabled();
    }
  });
}
