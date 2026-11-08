import { API_BASE_URL } from "./api";

// The server renders public pages (so search engines can read them), and from
// inside the Docker network the API is reached by its service name rather than
// the browser-facing NEXT_PUBLIC_API_BASE_URL.
const SERVER_API_BASE_URL = process.env.API_INTERNAL_URL || API_BASE_URL;

/** GET an unauthenticated API path from a Server Component. Returns null on a
 * 404 (so the page can call notFound()), throws on any other failure.
 * Revalidated every few minutes: these pages change when a meeting is
 * published, not per request. */
export async function fetchPublic<T>(path: string): Promise<T | null> {
  const response = await fetch(`${SERVER_API_BASE_URL}${path}`, { next: { revalidate: 300 } });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API ${path} failed: ${response.status}`);
  return (await response.json()) as T;
}
