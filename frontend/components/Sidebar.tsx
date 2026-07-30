"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BillingIcon, ChevronIcon, DashboardIcon, DocumentIcon, DriveIcon, KeyIcon, ShieldIcon, WalletIcon } from "@/components/icons";
import ThemeToggle from "@/components/ThemeToggle";
import UserMenu from "@/components/UserMenu";
import type { CurrentUser } from "@/lib/auth";
import { formatCents } from "@/lib/billing";

const PRIMARY_NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard", Icon: DashboardIcon },
  { href: "/documents", label: "Documents", Icon: DocumentIcon },
];

const SETTINGS_NAV_LINKS = [
  { href: "/settings/api-keys", label: "API keys", Icon: KeyIcon },
  { href: "/settings/integrations", label: "Integrations", Icon: DriveIcon },
  { href: "/settings/billing", label: "Billing", Icon: BillingIcon },
];

const ADMIN_NAV_LINK = { href: "/admin", label: "Admin", Icon: ShieldIcon };

type NavLinkDef = { href: string; label: string; Icon: (props: { className?: string }) => React.ReactElement };

function NavLink({ href, label, Icon, collapsed, active }: NavLinkDef & { collapsed: boolean; active: boolean }) {
  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={`flex items-center gap-3 px-3 py-2 text-sm font-medium transition-colors ${
        collapsed ? "justify-center" : ""
      } ${active ? "bg-accent-soft text-accent" : "text-ink-soft hover:bg-paper-shade hover:text-ink"}`}
    >
      <Icon className="h-5 w-5 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );
}

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
  const isActive = (href: string) => pathname === href || pathname?.startsWith(`${href}/`);

  return (
    <aside
      className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-line bg-paper transition-[width] duration-200 ${
        collapsed ? "w-[68px]" : "w-60"
      }`}
    >
      {/* Logo -- pinned, never scrolls */}
      <div className={`flex h-16 shrink-0 items-center px-4 ${collapsed ? "justify-center px-0" : ""}`}>
        <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden">
          <Image src="/logo-icon.png" alt="" width={28} height={28} className="shrink-0" priority />
          {!collapsed && (
            <span className="whitespace-nowrap font-mono text-base font-semibold tracking-tight">
              <span className="text-ink">FRAME</span>
              <span className="text-accent">WRITE</span>
            </span>
          )}
        </Link>
      </div>

      {/* Nav -- the only part that scrolls, if it ever grows past the
          available height. min-h-0 is required here: a flex-1 child won't
          actually shrink/scroll on its own overflow without it. */}
      <nav className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        <div className="flex flex-col gap-1">
          {PRIMARY_NAV_LINKS.map((link) => (
            <NavLink key={link.href} {...link} collapsed={collapsed} active={isActive(link.href)} />
          ))}
        </div>

        <div className="my-2 border-t border-line" />

        <div className="flex flex-col gap-1">
          {SETTINGS_NAV_LINKS.map((link) => (
            <NavLink key={link.href} {...link} collapsed={collapsed} active={isActive(link.href)} />
          ))}
        </div>
      </nav>

      {/* Footer -- pinned, never scrolls: admin (if applicable), wallet
          balance, user menu, collapse toggle. */}
      <div className="shrink-0 border-t border-line">
        {user?.is_admin && (
          <div className="px-3 pt-3">
            <NavLink {...ADMIN_NAV_LINK} collapsed={collapsed} active={isActive(ADMIN_NAV_LINK.href)} />
          </div>
        )}

        <Link
          href="/settings/billing"
          title={collapsed ? (balanceCents === null ? "Wallet balance" : formatCents(balanceCents)) : undefined}
          className={`flex items-center gap-2.5 px-3 pt-3 text-sm text-ink-soft transition-colors hover:text-ink ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <WalletIcon className="h-4 w-4 shrink-0" />
          {!collapsed && (
            <span className="truncate font-mono">
              {balanceCents === null ? "Loading balance..." : formatCents(balanceCents)}
            </span>
          )}
        </Link>

        <div className="px-3 pb-3 pt-2">
          <UserMenu user={user} collapsed={collapsed} />
        </div>

        <div className={`mx-3 mb-3 flex gap-2 ${collapsed ? "flex-col" : ""}`}>
          <div className="flex-1 border-2 border-line">
            <ThemeToggle collapsed={collapsed} />
          </div>
          <button
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex items-center justify-center border-2 border-line p-2 text-ink-soft transition-colors hover:bg-paper-shade hover:text-ink"
          >
            <ChevronIcon className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`} />
          </button>
        </div>
      </div>
    </aside>
  );
}
