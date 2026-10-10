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
  // sherpa-onnx's official vad-asr WASM build is a pthreads (multi-threaded)
  // Emscripten build -- its internal worker pool transfers a SharedArrayBuffer
  // between workers, which browsers only allow from a "cross-origin isolated"
  // page (self.crossOriginIsolated === true). That requires these two response
  // headers on the document; without them the transfer throws a DataCloneError
  // and the live page's speech-recognition worker never reports ready.
  //
  // Scoped to /dashboard/live plus the asset paths it loads (not site-wide)
  // because Cross-Origin-Embedder-Policy blocks any cross-origin subresource
  // that doesn't carry a matching Cross-Origin-Resource-Policy header -- e.g.
  // UserMenu's hotlinked Google avatar image would break under the stricter
  // "require-corp" mode. "credentialless" (rather than "require-corp") avoids
  // that: it still isolates the page, but only strips credentials from
  // cross-origin requests rather than requiring them to opt in via CORP, so
  // the (unauthenticated, public) avatar image keeps loading fine.
  //
  // Also required on /workers/* and /wasm/* themselves, not just the page:
  // per spec, a Worker's own HTTP response must declare a COEP compatible
  // with its creator, even for a same-origin script -- the parent page's
  // header alone isn't enough (confirmed by Chrome refusing to start
  // workers/vadAsrWorker.js otherwise, and sherpa-onnx's vad-asr build spawns
  // its own further-nested pthread workers from files under /wasm/vad-asr/,
  // which need the same treatment).
  async headers() {
    const crossOriginIsolationHeaders = [
      { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
      { key: "Cross-Origin-Embedder-Policy", value: "credentialless" },
    ];
    // The ~58MB of WASM/model assets under /wasm/ are static and rarely change -- there was
    // no override here before, so a repeat visit's reload behavior depended entirely on the
    // browser's own default HTTP heuristics rather than an explicit, long-lived cache. Paired
    // with the /wasm/v1/ version segment (public/wasm/v1/vad-asr, public/wasm/v1/
    // speaker-embedding) so a future model update bumps the path and gets fetched fresh,
    // rather than "immutable" forcing stale clients to keep an old cached copy indefinitely.
    // Deliberately NOT applied to /workers/* (our own actively-developed compiled worker JS,
    // which changes on ordinary fixes and has no cache-busting tied to the build process --
    // "immutable" there risks serving stale/buggy code to returning users) or /dashboard/live
    // (a dynamic page).
    const wasmHeaders = [
      ...crossOriginIsolationHeaders,
      { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
    ];
    return [
      { source: "/dashboard/live", headers: crossOriginIsolationHeaders },
      { source: "/workers/:path*", headers: crossOriginIsolationHeaders },
      { source: "/wasm/:path*", headers: wasmHeaders },
    ];
  },
};

export default nextConfig;
