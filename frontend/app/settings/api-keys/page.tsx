"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, getToken } from "@/lib/auth";

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
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    loadKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

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
    <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">API keys</h1>
        <Link href="/dashboard" className="text-sm text-zinc-500 hover:underline dark:text-zinc-400">
          Back to dashboard
        </Link>
      </div>

      {revealedKey && (
        <div className="mt-6 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
            Copy this key now -- you won&apos;t be able to see it again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md bg-white px-3 py-2 text-sm dark:bg-black">
              {revealedKey}
            </code>
            <button
              onClick={handleCopy}
              className="shrink-0 rounded-md border border-amber-400 px-3 py-2 text-sm text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:text-amber-200 dark:hover:bg-amber-900"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <button
            onClick={() => setRevealedKey(null)}
            className="mt-3 text-sm text-amber-800 underline dark:text-amber-300"
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
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950"
        />
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
        >
          {creating ? "Creating..." : "Create key"}
        </button>
      </form>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-8">
        {keys === null ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading...</p>
        ) : keys.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No API keys yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {keys.map((key) => (
              <li key={key.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{key.name}</p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {key.key_prefix}•••••••••••••••• &middot; created {new Date(key.created_at).toLocaleDateString()}
                    {key.last_used_at && ` · last used ${new Date(key.last_used_at).toLocaleDateString()}`}
                  </p>
                </div>
                {key.revoked_at ? (
                  <span className="text-xs text-zinc-400">Revoked</span>
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
