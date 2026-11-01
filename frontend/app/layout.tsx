import type { Metadata } from "next";
import localFont from "next/font/local";
import Script from "next/script";

import GoogleAnalytics from "@/components/GoogleAnalytics";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

// Bricolage Grotesque replaces Fraunces as the display face (see
// plan/ui-redesign-plan.md) -- a bold geometric grotesque with personality,
// matching the marketing site's choice for the same reason (see that
// project's base.css: Cabinet Grotesk, the plan's original pick, isn't
// cleanly self-hostable). Inter is new (body/UI text, replacing the plain
// system-sans stack); IBM Plex Mono stays for genuinely monospace content.
//
// Self-hosted (app/fonts/, latin subset) rather than next/font/google: the
// Google loader fetches from fonts.googleapis.com at build time, and Docker
// builds (production and local) repeatedly failed on it with Turbopack's
// "next/font/google queries have exactly one entry" -- a build shouldn't
// depend on that network call.
const displayFont = localFont({
  variable: "--font-display-sans",
  src: "./fonts/bricolage-grotesque-latin-wght-normal.woff2",
  weight: "200 800",
  display: "swap",
});

const inter = localFont({
  variable: "--font-inter",
  src: "./fonts/inter-latin-wght-normal.woff2",
  weight: "100 900",
  display: "swap",
});

const plexMono = localFont({
  variable: "--font-plex-mono",
  src: [
    { path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ibm-plex-mono-latin-600-normal.woff2", weight: "600", style: "normal" },
  ],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Framewrite",
  description: "Turn any video into a searchable document.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${displayFont.variable} ${inter.variable} ${plexMono.variable} h-full antialiased`}
    >
      {/* h-full, not min-h-full -- this must be capped at exactly the
          viewport height, not just floored at it, or it grows with page
          content and drags the (app) shell's sidebar along when scrolling.
          The (app) layout's own overflow-hidden wrapper is what actually
          contains the dashboard shell, but it can only do that if this
          parent is height-bounded in the first place. */}
      <body className="h-full flex flex-col">
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
        {children}
        <GoogleAnalytics />
      </body>
    </html>
  );
}
