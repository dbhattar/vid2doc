import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Minimal production Docker image: copy only .next/standalone + .next/static + public.
  output: "standalone",
  // A stray lockfile elsewhere on this machine made Next.js misdetect the
  // workspace root -- pin it explicitly instead of relying on inference.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
