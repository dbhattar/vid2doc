"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/settings", label: "Profile & preferences" },
  { href: "/settings/api-keys", label: "API keys" },
  { href: "/settings/integrations", label: "Integrations" },
  { href: "/settings/billing", label: "Billing" },
];

/** One home for every account setting: a tab bar over the existing pages. */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div>
      <nav aria-label="Settings" className="border-b border-line px-6 pt-6">
        <ul className="flex gap-1 overflow-x-auto">
          {TABS.map((tab) => {
            const active = pathname === tab.href;
            return (
              <li key={tab.href}>
                <Link
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={`block whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                    active ? "border-accent text-accent" : "border-transparent text-ink-soft hover:text-ink"
                  }`}
                >
                  {tab.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {children}
    </div>
  );
}
