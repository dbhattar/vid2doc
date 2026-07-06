"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, getToken } from "@/lib/auth";
import { formatCents, MAX_TOPUP_CENTS, MIN_TOPUP_CENTS, TOPUP_PRESETS_CENTS } from "@/lib/billing";

function BillingPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [balanceCents, setBalanceCents] = useState<number | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<number | null>(TOPUP_PRESETS_CENTS[0]);
  const [customAmount, setCustomAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const checkoutStatus = searchParams.get("status");

  const loadWallet = useCallback(() => {
    apiFetch<{ balance_cents: number }>("/api/billing/wallet")
      .then((data) => setBalanceCents(data.balance_cents))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load wallet balance.");
      });
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    loadWallet();
  }, [router, loadWallet]);

  function amountToCharge(): number | null {
    if (customAmount.trim()) {
      const dollars = Number(customAmount);
      if (!Number.isFinite(dollars)) return null;
      return Math.round(dollars * 100);
    }
    return selectedPreset;
  }

  async function handleAddFunds() {
    const amountCents = amountToCharge();
    if (!amountCents || amountCents < MIN_TOPUP_CENTS || amountCents > MAX_TOPUP_CENTS) {
      setError(`Enter an amount between ${formatCents(MIN_TOPUP_CENTS)} and ${formatCents(MAX_TOPUP_CENTS)}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { url } = await apiFetch<{ url: string }>("/api/billing/checkout/topup", {
        method: "POST",
        body: JSON.stringify({ amount_cents: amountCents }),
      });
      window.location.assign(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start checkout.");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Billing</h1>
        <Link href="/dashboard" className="text-sm text-zinc-500 hover:underline dark:text-zinc-400">
          Back to dashboard
        </Link>
      </div>
      <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
        Pay-as-you-go: $1.00 per hour of video, charged only when you convert something.
      </p>

      {checkoutStatus === "success" && (
        <p className="mt-4 rounded-md bg-green-50 p-3 text-sm text-green-700 dark:bg-green-950 dark:text-green-300">
          Payment received. Your balance may take a few seconds to update below.
        </p>
      )}
      {checkoutStatus === "cancelled" && (
        <p className="mt-4 rounded-md bg-zinc-100 p-3 text-sm text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
          Checkout was cancelled -- no changes were made.
        </p>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Wallet balance</p>
        <p className="mt-1 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">
          {balanceCents === undefined ? "..." : formatCents(balanceCents)}
        </p>

        <div className="mt-6">
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Add funds</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {TOPUP_PRESETS_CENTS.map((cents) => (
              <button
                key={cents}
                onClick={() => {
                  setSelectedPreset(cents);
                  setCustomAmount("");
                }}
                className={`rounded-md border px-4 py-2 text-sm font-medium ${
                  selectedPreset === cents && !customAmount
                    ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-50 dark:bg-zinc-50 dark:text-zinc-900"
                    : "border-zinc-300 text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                }`}
              >
                {formatCents(cents)}
              </button>
            ))}
            <input
              type="number"
              min={MIN_TOPUP_CENTS / 100}
              max={MAX_TOPUP_CENTS / 100}
              step="1"
              placeholder="Custom ($)"
              value={customAmount}
              onChange={(e) => {
                setCustomAmount(e.target.value);
                setSelectedPreset(null);
              }}
              className="w-28 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            />
          </div>
          <button
            onClick={handleAddFunds}
            disabled={busy}
            className="mt-4 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
          >
            {busy ? "Redirecting..." : "Add funds"}
          </button>
        </div>
      </div>

      <p className="mt-6 text-xs text-zinc-500 dark:text-zinc-400">
        Documents aren&apos;t guaranteed to be retained past 7 days -- download what you need.
      </p>
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading...</p>
        </div>
      }
    >
      <BillingPageContent />
    </Suspense>
  );
}
