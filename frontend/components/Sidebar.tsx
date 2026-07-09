"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BillingIcon, ChevronIcon, DashboardIcon, DocumentIcon, KeyIcon } from "@/components/icons";
import UserMenu from "@/components/UserMenu";
import type { CurrentUser } from "@/lib/auth";

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
}: {
  collapsed: boolean;
  onToggle: () => void;
  user: CurrentUser | null;
}) {
  const pathname = usePathname();

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-brand-border bg-surface transition-[width] duration-200 ${
        collapsed ? "w-[68px]" : "w-60"
      }`}
    >
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

      <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
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
      </nav>

      <div className="border-t border-brand-border px-3 py-3">
        <UserMenu user={user} collapsed={collapsed} />
      </div>

      <button
        onClick={onToggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="m-3 mt-0 flex items-center justify-center rounded-lg border border-brand-border p-2 text-muted transition-colors hover:bg-brand-navy-soft hover:text-brand-navy"
      >
        <ChevronIcon className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`} />
      </button>
    </aside>
  );
}
