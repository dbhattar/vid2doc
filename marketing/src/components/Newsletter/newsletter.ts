export {};

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

const form = document.getElementById('newsletter-form') as HTMLFormElement | null;
const emailInput = document.getElementById('newsletter-email') as HTMLInputElement | null;
const submitBtn = document.getElementById('newsletter-submit') as HTMLButtonElement | null;
const statusEl = document.getElementById('newsletter-status') as HTMLElement | null;

if (form && emailInput && submitBtn && statusEl) {
  function showStatus(message: string) {
    statusEl!.hidden = false;
    statusEl!.textContent = message;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = emailInput!.value.trim();
    if (!email) return;

    submitBtn!.disabled = true;

    try {
      const res = await fetch(`${API_URL}/api/public/newsletter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to subscribe (${res.status})`);
      }
      if (typeof window.gtag === 'function') window.gtag('event', 'newsletter_signup');
      emailInput!.value = '';
      showStatus("Thanks -- you're on the list.");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : 'Failed to subscribe.');
    } finally {
      submitBtn!.disabled = false;
    }
  });
}
