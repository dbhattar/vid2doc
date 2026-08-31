"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { BillingIcon, ChevronIcon, ClapperboardIcon, CloseIcon, DashboardIcon, DocumentIcon, DriveIcon, KeyIcon, LiveIcon, MicrophoneIcon, ShieldIcon, VideoCameraIcon, WalletIcon } from "@/components/icons";
import ThemeToggle from "@/components/ThemeToggle";
import UserMenu from "@/components/UserMenu";
import type { CurrentUser } from "@/lib/auth";
import { formatCents } from "@/lib/billing";

const PRIMARY_NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard", Icon: DashboardIcon },
  { href: "/dashboard/video", label: "Video", Icon: VideoCameraIcon },
  { href: "/dashboard/audio", label: "Audio", Icon: MicrophoneIcon },
  { href: "/dashboard/live", label: "Live", Icon: LiveIcon },
  { href: "/dashboard/video-gen", label: "Video Gen", Icon: ClapperboardIcon },
  { href: "/documents", label: "Documents", Icon: DocumentIcon },
];

const SETTINGS_NAV_LINKS = [
  { href: "/settings/api-keys", label: "API keys", Icon: KeyIcon },
  { href: "/settings/integrations", label: "Integrations", Icon: DriveIcon },
  { href: "/settings/billing", label: "Billing", Icon: BillingIcon },
];

const ADMIN_NAV_LINK = { href: "/admin", label: "Admin", Icon: ShieldIcon };

type NavLinkDef = { href: string; label: string; Icon: (props: { className?: string }) => React.ReactElement };

// `collapsed` (desktop icon-rail mode) only ever hides the label at md+ --
// below md the drawer is either fully open or fully closed, never narrow,
// so a label hidden for "collapsed" must still show up on mobile.
function labelClass(collapsed: boolean) {
  return collapsed ? "md:hidden" : "";
}

function NavLink({
  href,
  label,
  Icon,
  collapsed,
  active,
  onNavigate,
}: NavLinkDef & { collapsed: boolean; active: boolean; onNavigate: () => void }) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      className={`flex items-center gap-3 px-3 py-2 text-sm font-medium transition-colors ${
        collapsed ? "md:justify-center" : ""
      } ${active ? "bg-accent-soft text-accent" : "text-ink-soft hover:bg-paper-shade hover:text-ink"}`}
    >
      <Icon className="h-5 w-5 shrink-0" />
      <span className={`truncate ${labelClass(collapsed)}`}>{label}</span>
    </Link>
  );
}

export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
  user,
  balanceCents,
}: {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  user: CurrentUser | null;
  balanceCents: number | null;
}) {
  const pathname = usePathname();
  // "/dashboard" itself is exact-match only -- otherwise it'd also light up
  // for "/dashboard/video" etc., which have their own nav entries now.
  const isActive = (href: string) =>
    href === "/dashboard" ? pathname === href : pathname === href || pathname?.startsWith(`${href}/`);

  // Tapping a nav link should close the mobile drawer, same as any standard
  // off-canvas menu -- otherwise it stays open, covering the page you just
  // navigated to.
  useEffect(() => {
    onMobileClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return (
    <>
      {/* Backdrop -- mobile only, sits behind the drawer (z-40 vs z-50) but
          above page content; tapping it closes the drawer, standard
          off-canvas-menu behavior. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-ink/40 md:hidden" onClick={onMobileClose} aria-hidden="true" />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-full w-60 shrink-0 flex-col overflow-hidden border-r border-line bg-paper transition-all duration-200 md:static md:z-auto md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "md:w-[68px]" : "md:w-60"}`}
      >
        {/* Logo -- pinned, never scrolls. Close button only shows below md,
            where this is an overlay drawer rather than part of the layout. */}
        <div className={`flex h-16 shrink-0 items-center justify-between px-4 ${collapsed ? "md:justify-center md:px-0" : ""}`}>
          <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden">
            <Image src="/logo-icon.png" alt="" width={28} height={28} className="shrink-0" priority />
            <span className={`whitespace-nowrap font-mono text-base font-semibold tracking-tight ${labelClass(collapsed)}`}>
              <span className="text-ink">FRAME</span>
              <span className="text-accent">WRITE</span>
            </span>
          </Link>
          <button
            onClick={onMobileClose}
            aria-label="Close menu"
            className="p-1 text-ink-soft transition-colors hover:text-ink md:hidden"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Nav -- the only part that scrolls, if it ever grows past the
            available height. min-h-0 is required here: a flex-1 child won't
            actually shrink/scroll on its own overflow without it. */}
        <nav className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
          <div className="flex flex-col gap-1">
            {PRIMARY_NAV_LINKS.map((link) => (
              <NavLink key={link.href} {...link} collapsed={collapsed} active={isActive(link.href)} onNavigate={onMobileClose} />
            ))}
          </div>

          <div className="my-2 border-t border-line" />

          <div className="flex flex-col gap-1">
            {SETTINGS_NAV_LINKS.map((link) => (
              <NavLink key={link.href} {...link} collapsed={collapsed} active={isActive(link.href)} onNavigate={onMobileClose} />
            ))}
          </div>
        </nav>

        {/* Footer -- pinned, never scrolls: admin (if applicable), wallet
            balance, user menu, collapse toggle. */}
        <div className="shrink-0 border-t border-line">
          {user?.is_admin && (
            <div className="px-3 pt-3">
              <NavLink {...ADMIN_NAV_LINK} collapsed={collapsed} active={isActive(ADMIN_NAV_LINK.href)} onNavigate={onMobileClose} />
            </div>
          )}

          <Link
            href="/settings/billing"
            title={collapsed ? (balanceCents === null ? "Wallet balance" : formatCents(balanceCents)) : undefined}
            className={`flex items-center gap-2.5 px-3 pt-3 text-sm text-ink-soft transition-colors hover:text-ink ${
              collapsed ? "md:justify-center" : ""
            }`}
          >
            <WalletIcon className="h-4 w-4 shrink-0" />
            <span className={`truncate font-mono ${labelClass(collapsed)}`}>
              {balanceCents === null ? "Loading balance..." : formatCents(balanceCents)}
            </span>
          </Link>

          <div className="px-3 pb-3 pt-2">
            <UserMenu user={user} collapsed={collapsed} />
          </div>

          <div className={`mx-3 mb-3 flex gap-2 ${collapsed ? "md:flex-col" : ""}`}>
            <div className="flex-1 border-2 border-line">
              <ThemeToggle collapsed={collapsed} />
            </div>
            <button
              onClick={onToggle}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="hidden items-center justify-center border-2 border-line p-2 text-ink-soft transition-colors hover:bg-paper-shade hover:text-ink md:flex"
            >
              <ChevronIcon className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`} />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
