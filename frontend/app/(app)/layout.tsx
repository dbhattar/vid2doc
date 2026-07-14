"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, getToken, type CurrentUser } from "@/lib/auth";

// A job that fails is refunded server-side immediately (charge + matching
// refund, see backend/app/pipeline.py), but this sidebar balance is only
// ever fetched once on mount -- without a refresh, it keeps showing the
// stale, temporarily-lower number until a full reload, which reads as "my
// balance didn't come back" even though it actually did.
const BALANCE_POLL_MS = 8000;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [balanceCents, setBalanceCents] = useState<number | null>(null);

  const loadBalance = useCallback(() => {
    apiFetch<{ balance_cents: number }>("/api/billing/wallet")
      .then((data) => setBalanceCents(data.balance_cents))
      .catch(() => {
        // Non-critical for the shell to render -- the billing page itself
        // surfaces a real error if the wallet endpoint is actually down.
      });
  }, []);

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
        }
      });
    loadBalance();
    const id = setInterval(loadBalance, BALANCE_POLL_MS);
    return () => clearInterval(id);
  }, [router, loadBalance]);

  return (
    <div className="flex flex-1 overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} user={user} balanceCents={balanceCents} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
