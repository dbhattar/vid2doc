"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

import { clearSession, getStoredUser, type CurrentUser } from "@/lib/auth";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/settings/api-keys", label: "API keys" },
  { href: "/settings/billing", label: "Billing" },
];

function subscribeToNothing() {
  return () => {};
}

// `user` is optional -- pages that don't already fetch it themselves can omit
// it and this falls back to localStorage. useSyncExternalStore (not a plain
// effect) is what makes that SSR-safe: it renders `getServerSnapshot`'s value
// (null) on the server and on the client's first hydration pass, then
// updates to the real localStorage value right after -- no hydration
// mismatch warning, unlike reading localStorage directly during render.
export default function AppHeader({ user: userProp }: { user?: CurrentUser | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const storedUser = useSyncExternalStore(subscribeToNothing, getStoredUser, () => null);
  const user = userProp ?? storedUser;

  function handleLogout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-10 border-b border-brand-border/70 bg-background/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-4xl items-center justify-between gap-4 px-6 py-4">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <Image src="/logo-icon.png" alt="" width={28} height={28} className="rounded-md" priority />
          <span className="text-base font-extrabold tracking-tight">
            <span className="text-brand-navy dark:text-foreground">FRAME</span>
            <span className="text-brand-amber">WRITE</span>
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV_LINKS.map((link) => {
            const active = pathname === link.href || pathname?.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-brand-amber-soft text-brand-amber-dark dark:bg-brand-navy-soft dark:text-brand-amber"
                    : "text-muted hover:text-brand-navy dark:hover:text-foreground"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-3">
          {user?.email && (
            <span className="hidden text-sm text-muted sm:inline">{user.email}</span>
          )}
          <button
            onClick={handleLogout}
            className="rounded-full border border-brand-border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-brand-navy-soft"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}
