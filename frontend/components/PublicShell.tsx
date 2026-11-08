"use client";

import { useSyncExternalStore } from "react";

import AppShell from "@/components/AppShell";
import { getToken } from "@/lib/auth";

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/** Public pages stay readable by anyone, but a signed-in visitor gets the same
 * sidebar and top bar as the rest of the app. The server and the first client
 * render show the standalone page (the session lives in localStorage), then a
 * signed-in visitor's page is wrapped in the app shell. */
export default function PublicShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const signedIn = useSyncExternalStore(
    subscribe,
    () => getToken() !== null,
    () => false,
  );
  if (signedIn) return <AppShell requireAuth={false}>{children}</AppShell>;
  return <>{children}</>;
}
