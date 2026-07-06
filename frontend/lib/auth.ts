export type CurrentUser = {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  stripe_customer_id: string | null;
  created_at: string;
};

const TOKEN_KEY = "framewrite_token";
const USER_KEY = "framewrite_user";

// localStorage only exists in the browser -- every caller of these is a
// Client Component, but guard anyway since Next.js can still evaluate
// module top-level code during the server render pass.
const canUseStorage = () => typeof window !== "undefined";

export function saveSession(accessToken: string, user: CurrentUser): void {
  if (!canUseStorage()) return;
  window.localStorage.setItem(TOKEN_KEY, accessToken);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getToken(): string | null {
  if (!canUseStorage()) return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): CurrentUser | null {
  if (!canUseStorage()) return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}
