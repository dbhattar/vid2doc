import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* h-full, not min-h-full -- this must be capped at exactly the
          viewport height, not just floored at it, or it grows with page
          content and drags the (app) shell's sidebar along when scrolling.
          The (app) layout's own overflow-hidden wrapper is what actually
          contains the dashboard shell, but it can only do that if this
          parent is height-bounded in the first place. */}
      <body className="h-full flex flex-col">{children}</body>
    </html>
  );
}
