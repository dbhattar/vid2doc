"use client";

import FeedbackButton from "@/components/FeedbackButton";

// Left side intentionally empty for now -- reserved for future help/support
// entry points. The user menu lives in the sidebar, not here.
export default function TopBar() {
  return (
    <header className="flex h-16 shrink-0 items-center justify-end border-b border-brand-border bg-background px-4">
      <FeedbackButton />
    </header>
  );
}
