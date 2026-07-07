"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, getToken, type CurrentUser } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);

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
  }, [router]);

  return (
    <div className="flex flex-1 overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} user={user} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
