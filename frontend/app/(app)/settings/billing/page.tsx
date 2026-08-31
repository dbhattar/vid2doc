"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents, MAX_TOPUP_CENTS, MIN_TOPUP_CENTS, TOPUP_PRESETS_CENTS } from "@/lib/billing";

function BillingPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [balanceCents, setBalanceCents] = useState<number | undefined>(undefined);
  const [paymentsEnabled, setPaymentsEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<number | null>(TOPUP_PRESETS_CENTS[0]);
  const [customAmount, setCustomAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const checkoutStatus = searchParams.get("status");

  const loadWallet = useCallback(() => {
    apiFetch<{ balance_cents: number; payments_enabled: boolean }>("/api/billing/wallet")
      .then((data) => {
        setBalanceCents(data.balance_cents);
        setPaymentsEnabled(data.payments_enabled);
      })
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
    loadWallet();
  }, [loadWallet]);

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
    <div className="w-full px-6 py-10">
      <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Billing</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Pay-as-you-go: $1.00 per hour of video, $0.40 per hour of audio-only transcription -- charged only when you
        submit something.
      </p>

      {checkoutStatus === "success" && (
        <p className="mt-4 rounded-md bg-status-success-soft p-3 text-sm text-status-success">
          Payment received. Your balance may take a few seconds to update below.
        </p>
      )}
      {checkoutStatus === "cancelled" && (
        <p className="mt-4 rounded-md bg-paper-shade p-3 text-sm text-ink-soft">
          Checkout was cancelled -- no changes were made.
        </p>
      )}
      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {!paymentsEnabled && (
        <p className="mt-4 rounded-md bg-status-warning-soft p-3 text-sm text-status-warning">
          Payments are temporarily unavailable while we resolve an issue with our payment provider. Your
          existing balance and job processing are unaffected -- please check back soon.
        </p>
      )}

      <Card className="mt-8 p-6">
        <p className="text-sm text-ink-soft">Wallet balance</p>
        <p className="mt-1 font-display text-4xl font-bold tracking-tight text-ink">
          {balanceCents === undefined ? "..." : formatCents(balanceCents)}
        </p>

        <div className="mt-6">
          <p className="text-sm font-semibold text-ink">Add funds</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {TOPUP_PRESETS_CENTS.map((cents) => (
              <button
                key={cents}
                onClick={() => {
                  setSelectedPreset(cents);
                  setCustomAmount("");
                }}
                disabled={!paymentsEnabled}
                className={`rounded-md border px-4 py-2 text-sm font-medium transition-all duration-150 ease-[var(--ease-spring)] hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-50 ${
                  selectedPreset === cents && !customAmount
                    ? "border-ink bg-ink text-paper"
                    : "border-line text-ink hover:bg-paper-shade"
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
              disabled={!paymentsEnabled}
              className="w-28 rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft disabled:cursor-default disabled:opacity-50"
            />
          </div>
          <Button onClick={handleAddFunds} disabled={busy || !paymentsEnabled} className="mt-4">
            {busy ? "Redirecting..." : "Add funds"}
          </Button>
        </div>
      </Card>

      <p className="mt-6 text-xs text-ink-soft">
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
          <p className="text-sm text-ink-soft">Loading...</p>
        </div>
      }
    >
      <BillingPageContent />
    </Suspense>
  );
}
