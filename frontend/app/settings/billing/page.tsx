"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import AppHeader from "@/components/AppHeader";
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
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-10">
        <h1 className="text-2xl font-bold tracking-tight text-brand-navy dark:text-foreground">Billing</h1>
        <p className="mt-1 text-sm text-muted">
          Pay-as-you-go: $1.00 per hour of video, charged only when you convert something.
        </p>

        {checkoutStatus === "success" && (
          <p className="mt-4 rounded-lg bg-green-50 p-3 text-sm text-green-700 dark:bg-green-950 dark:text-green-300">
            Payment received. Your balance may take a few seconds to update below.
          </p>
        )}
        {checkoutStatus === "cancelled" && (
          <p className="mt-4 rounded-lg bg-brand-navy-soft p-3 text-sm text-muted">
            Checkout was cancelled -- no changes were made.
          </p>
        )}
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        <div className="mt-8 rounded-2xl border border-brand-border bg-surface p-6 shadow-soft">
          <p className="text-sm text-muted">Wallet balance</p>
          <p className="mt-1 text-4xl font-bold tracking-tight text-brand-navy dark:text-foreground">
            {balanceCents === undefined ? "..." : formatCents(balanceCents)}
          </p>

          <div className="mt-6">
            <p className="text-sm font-semibold text-foreground">Add funds</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {TOPUP_PRESETS_CENTS.map((cents) => (
                <button
                  key={cents}
                  onClick={() => {
                    setSelectedPreset(cents);
                    setCustomAmount("");
                  }}
                  className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                    selectedPreset === cents && !customAmount
                      ? "border-brand-navy bg-brand-navy text-white"
                      : "border-brand-border text-foreground hover:bg-brand-navy-soft"
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
                className="w-28 rounded-lg border border-brand-border bg-surface px-3 py-2 text-sm outline-none transition-shadow focus:border-brand-amber-dark focus:ring-2 focus:ring-brand-amber-soft"
              />
            </div>
            <button
              onClick={handleAddFunds}
              disabled={busy}
              className="mt-4 rounded-lg bg-brand-navy px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
            >
              {busy ? "Redirecting..." : "Add funds"}
            </button>
          </div>
        </div>

        <p className="mt-6 text-xs text-muted">
          Documents aren&apos;t guaranteed to be retained past 7 days -- download what you need.
        </p>
      </div>
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
