"use client";

import FeedbackButton from "@/components/FeedbackButton";
import { MenuIcon } from "@/components/icons";

// Left side otherwise empty -- reserved for future help/support entry
// points. The user menu lives in the sidebar, not here. The hamburger button
// only renders (via md:hidden) below the md breakpoint, where the sidebar is
// an off-canvas drawer instead of always-visible (see Sidebar.tsx/layout.tsx).
export default function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b border-line bg-paper px-4">
      <button
        onClick={onMenuClick}
        aria-label="Open menu"
        className="flex items-center justify-center p-2 text-ink-soft transition-colors hover:text-ink md:hidden"
      >
        <MenuIcon className="h-5 w-5" />
      </button>
      <div className="flex-1" />
      <FeedbackButton />
    </header>
  );
}
