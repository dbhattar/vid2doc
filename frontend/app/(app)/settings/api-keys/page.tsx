"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";

type ApiKey = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

type CreateKeyResponse = ApiKey & { key: string };

export default function ApiKeysPage() {
  const router = useRouter();
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function loadKeys() {
    apiFetch<{ keys: ApiKey[] }>("/api/keys")
      .then((data) => setKeys(data.keys))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load API keys.");
      });
  }

  useEffect(() => {
    loadKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await apiFetch<CreateKeyResponse>("/api/keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setRevealedKey(created.key);
      setCopied(false);
      setName("");
      loadKeys();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create API key.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(key: ApiKey) {
    if (!confirm(`Revoke "${key.name}"? Anything using this key will stop working immediately.`)) return;
    try {
      await apiFetch(`/api/keys/${key.id}`, { method: "DELETE" });
      loadKeys();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to revoke API key.");
    }
  }

  function handleCopy() {
    if (!revealedKey) return;
    navigator.clipboard.writeText(revealedKey);
    setCopied(true);
  }

  return (
    <div className="w-full px-6 py-10">
      <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">API keys</h1>
      <p className="mt-1 text-sm text-ink-soft">Use a key with the <code>X-API-Key</code> header to call the API directly.</p>

      {revealedKey && (
        <div className="mt-6 rounded-lg border border-accent bg-accent-soft p-4">
          <p className="text-sm font-medium text-accent">
            Copy this key now -- you won&apos;t be able to see it again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md border border-line bg-paper px-3 py-2 text-sm">
              {revealedKey}
            </code>
            <button
              onClick={handleCopy}
              className="shrink-0 rounded-md border border-accent px-3 py-2 text-sm font-medium text-accent transition-all duration-150 ease-[var(--ease-spring)] hover:-translate-y-0.5 hover:bg-paper/60"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <button
            onClick={() => setRevealedKey(null)}
            className="mt-3 text-sm text-accent underline"
          >
            Done, I&apos;ve saved it
          </button>
        </div>
      )}

      <form onSubmit={handleCreate} className="mt-8 flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Key name (e.g. CI pipeline)"
          className="flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
        />
        <Button type="submit" disabled={creating || !name.trim()}>
          {creating ? "Creating..." : "Create key"}
        </Button>
      </form>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      <div className="mt-8">
        {keys === null ? (
          <p className="text-sm text-ink-soft">Loading...</p>
        ) : keys.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-soft">
            No API keys yet -- create one above.
          </p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
            {keys.map((key) => (
              <li key={key.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-ink">{key.name}</p>
                  <p className="text-xs text-ink-soft">
                    {key.key_prefix}•••••••••••••••• &middot; created {new Date(key.created_at).toLocaleDateString()}
                    {key.last_used_at && ` · last used ${new Date(key.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                {key.revoked_at ? (
                  <span className="text-xs text-ink-soft">Revoked</span>
                ) : (
                  <button
                    onClick={() => handleRevoke(key)}
                    className="text-sm text-status-error hover:underline"
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      </div>
    </div>
  );
}
