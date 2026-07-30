import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono } from "next/font/google";
import Script from "next/script";

import GoogleAnalytics from "@/components/GoogleAnalytics";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  weight: ["600", "900"],
  style: ["normal", "italic"],
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
      className={`${fraunces.variable} ${plexMono.variable} h-full antialiased`}
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
