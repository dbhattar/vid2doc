"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BillingIcon, ChevronIcon, DashboardIcon, DocumentIcon, KeyIcon, WalletIcon } from "@/components/icons";
import UserMenu from "@/components/UserMenu";
import type { CurrentUser } from "@/lib/auth";
import { formatCents } from "@/lib/billing";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard", Icon: DashboardIcon },
  { href: "/documents", label: "Documents", Icon: DocumentIcon },
  { href: "/settings/api-keys", label: "API keys", Icon: KeyIcon },
  { href: "/settings/billing", label: "Billing", Icon: BillingIcon },
];

export default function Sidebar({
  collapsed,
  onToggle,
  user,
  balanceCents,
}: {
  collapsed: boolean;
  onToggle: () => void;
  user: CurrentUser | null;
  balanceCents: number | null;
}) {
  const pathname = usePathname();

  return (
    <aside
      className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-brand-border bg-surface transition-[width] duration-200 ${
        collapsed ? "w-[68px]" : "w-60"
      }`}
    >
      {/* Logo -- pinned, never scrolls */}
      <div className={`flex h-16 shrink-0 items-center px-4 ${collapsed ? "justify-center px-0" : ""}`}>
        <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden">
          <Image src="/logo-icon.png" alt="" width={28} height={28} className="shrink-0 rounded-md" priority />
          {!collapsed && (
            <span className="whitespace-nowrap text-base font-extrabold tracking-tight">
              <span className="text-brand-navy">FRAME</span>
              <span className="text-brand-amber">WRITE</span>
            </span>
          )}
        </Link>
      </div>

      {/* Nav -- the only part that scrolls, if it ever grows past the
          available height. min-h-0 is required here: a flex-1 child won't
          actually shrink/scroll on its own overflow without it. */}
      <nav className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        <div className="flex flex-col gap-1">
          {NAV_LINKS.map(({ href, label, Icon }) => {
            const active = pathname === href || pathname?.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  collapsed ? "justify-center" : ""
                } ${
                  active
                    ? "bg-brand-amber-soft text-brand-amber-dark"
                    : "text-muted hover:bg-brand-navy-soft hover:text-brand-navy"
                }`}
              >
                <Icon className="h-5 w-5 shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Footer -- pinned, never scrolls: wallet balance, user menu, collapse toggle. */}
      <div className="shrink-0 border-t border-brand-border">
        <Link
          href="/settings/billing"
          title={collapsed ? (balanceCents === null ? "Wallet balance" : formatCents(balanceCents)) : undefined}
          className={`flex items-center gap-2.5 px-3 pt-3 text-sm text-muted transition-colors hover:text-brand-navy ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <WalletIcon className="h-4 w-4 shrink-0" />
          {!collapsed && (
            <span className="truncate">{balanceCents === null ? "Loading balance..." : formatCents(balanceCents)}</span>
          )}
        </Link>

        <div className="px-3 pb-3 pt-2">
          <UserMenu user={user} collapsed={collapsed} />
        </div>

        <button
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="mx-3 mb-3 flex items-center justify-center rounded-lg border border-brand-border p-2 text-muted transition-colors hover:bg-brand-navy-soft hover:text-brand-navy"
        >
          <ChevronIcon className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`} />
        </button>
      </div>
    </aside>
  );
}
