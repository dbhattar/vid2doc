import { NextResponse } from "next/server";

// This app has no Server Actions, so nothing legitimate ever sends a
// `Next-Action` header. Internet scanners do (probing for Server Action
// vulnerabilities, with a made-up action id like "x"), and each probe would
// otherwise reach Next's action handler and log "Failed to find Server Action".
// Answer them here, before any rendering, with a quiet 404.
//
// The matcher only runs this for requests that carry the header, so normal
// traffic never goes through it.
export function proxy() {
  return new NextResponse(null, { status: 404 });
}

export const config = {
  matcher: [{ source: "/:path*", has: [{ type: "header", key: "next-action" }] }],
};
