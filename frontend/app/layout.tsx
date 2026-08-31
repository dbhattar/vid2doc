import type { Metadata } from "next";
import { Bricolage_Grotesque, IBM_Plex_Mono, Inter } from "next/font/google";
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
const displayFont = Bricolage_Grotesque({
  variable: "--font-display-sans",
  weight: ["700", "800"],
  subsets: ["latin"],
});

const inter = Inter({
  variable: "--font-inter",
  weight: ["400", "500", "600"],
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  weight: ["400", "500", "600"],
  subsets: ["latin"],
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
