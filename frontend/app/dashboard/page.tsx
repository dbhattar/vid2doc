"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, getToken, type CurrentUser } from "@/lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }

    apiFetch<CurrentUser>("/api/auth/me")
      .then(setUser)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load your account.");
      });
  }, [router]);

  function handleLogout() {
    clearSession();
    router.replace("/login");
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Dashboard</h1>
        <button
          onClick={handleLogout}
          className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          Log out
        </button>
      </div>

      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Signed in as</p>
        <p className="mt-1 text-base font-medium text-zinc-900 dark:text-zinc-50">{user.email}</p>
      </div>
    </div>
  );
}
