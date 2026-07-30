"use client";

import { useEffect, useState } from "react";

import { MoonIcon, SunIcon, SystemThemeIcon } from "@/components/icons";
import {
  applyTheme,
  loadThemePreference,
  nextThemePreference,
  saveThemePreference,
  type ThemePreference,
} from "@/lib/theme";

const ICONS: Record<ThemePreference, (props: { className?: string }) => React.ReactElement> = {
  light: SunIcon,
  dark: MoonIcon,
  system: SystemThemeIcon,
};

const LABELS: Record<ThemePreference, string> = {
  light: "Light theme",
  dark: "Dark theme",
  system: "System theme",
};

export default function ThemeToggle({ collapsed }: { collapsed?: boolean }) {
  // Starts null (not "system") so the first client render doesn't have to
  // guess -- avoids a hydration mismatch, since the server has no way to
  // know what's in localStorage. Synced to the real value immediately after
  // mount, before the user could plausibly notice.
  const [pref, setPref] = useState<ThemePreference | null>(null);

  useEffect(() => {
    setPref(loadThemePreference());
  }, []);

  function handleClick() {
    const current = pref ?? "system";
    const next = nextThemePreference(current);
    setPref(next);
    applyTheme(next);
    saveThemePreference(next);
  }

  const Icon = ICONS[pref ?? "system"];
  const label = LABELS[pref ?? "system"];

  return (
    <button
      onClick={handleClick}
      title={`Theme: ${label} (click to change)`}
      aria-label={`Theme: ${label}. Click to switch.`}
      className={`flex items-center justify-center p-2 text-ink-soft transition-colors hover:bg-paper-shade hover:text-ink ${
        collapsed ? "w-full" : ""
      }`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
