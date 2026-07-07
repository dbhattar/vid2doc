"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
    <div className="mx-auto w-full max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-brand-navy">API keys</h1>
      <p className="mt-1 text-sm text-muted">Use a key with the <code>X-API-Key</code> header to call the API directly.</p>

      {revealedKey && (
        <div className="mt-6 rounded-2xl border border-brand-amber/40 bg-brand-amber-soft p-4">
          <p className="text-sm font-medium text-brand-amber-dark">
            Copy this key now -- you won&apos;t be able to see it again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-lg bg-surface px-3 py-2 text-sm">
              {revealedKey}
            </code>
            <button
              onClick={handleCopy}
              className="shrink-0 rounded-lg border border-brand-amber/50 px-3 py-2 text-sm font-medium text-brand-amber-dark transition-colors hover:bg-white/60"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <button
            onClick={() => setRevealedKey(null)}
            className="mt-3 text-sm text-brand-amber-dark underline"
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
          className="flex-1 rounded-lg border border-brand-border bg-surface px-3 py-2 text-sm outline-none transition-shadow focus:border-brand-amber-dark focus:ring-2 focus:ring-brand-amber-soft"
        />
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded-lg bg-brand-navy px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
        >
          {creating ? "Creating..." : "Create key"}
        </button>
      </form>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-8">
        {keys === null ? (
          <p className="text-sm text-muted">Loading...</p>
        ) : keys.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-brand-border p-6 text-center text-sm text-muted">
            No API keys yet -- create one above.
          </p>
        ) : (
          <ul className="divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
            {keys.map((key) => (
              <li key={key.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-foreground">{key.name}</p>
                  <p className="text-xs text-muted">
                    {key.key_prefix}•••••••••••••••• &middot; created {new Date(key.created_at).toLocaleDateString()}
                    {key.last_used_at && ` · last used ${new Date(key.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                {key.revoked_at ? (
                  <span className="text-xs text-muted">Revoked</span>
                ) : (
                  <button
                    onClick={() => handleRevoke(key)}
                    className="text-sm text-red-600 hover:underline"
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
  );
}
