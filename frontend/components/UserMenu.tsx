"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ChevronDownIcon } from "@/components/icons";
import { clearSession, type CurrentUser } from "@/lib/auth";

export default function UserMenu({ user, collapsed }: { user: CurrentUser | null; collapsed?: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function handleLogout() {
    clearSession();
    router.replace("/login");
  }

  const name = user?.display_name || user?.email || "Account";
  const initial = (user?.display_name || user?.email || "?").charAt(0).toUpperCase();

  const avatar = user?.avatar_url ? (
    // eslint-disable-next-line @next/next/no-img-element -- avoids configuring next/image remotePatterns for Google's avatar CDN for one 32px image
    <img src={user.avatar_url} alt="" width={32} height={32} className="h-8 w-8 shrink-0 rounded-full" referrerPolicy="no-referrer" />
  ) : (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-navy text-sm font-semibold text-white">
      {initial}
    </span>
  );

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        title={collapsed ? name : undefined}
        className={`flex w-full items-center gap-2.5 rounded-lg py-1.5 text-left transition-colors hover:bg-brand-navy-soft ${
          collapsed ? "justify-center px-0" : "px-1.5"
        }`}
      >
        {avatar}
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">{name}</span>
              {user?.email && <span className="block truncate text-xs text-muted">{user.email}</span>}
            </span>
            <ChevronDownIcon className={`h-4 w-4 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`} />
          </>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-56 rounded-xl border border-brand-border bg-surface p-1.5 shadow-soft">
          <div className="border-b border-brand-border px-3 py-2">
            <p className="truncate text-sm font-medium text-foreground">{name}</p>
            {user?.email && <p className="truncate text-xs text-muted">{user.email}</p>}
          </div>
          <button
            onClick={handleLogout}
            className="mt-1 flex w-full items-center rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
