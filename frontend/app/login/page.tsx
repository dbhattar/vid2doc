"use client";

import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { saveSession, type CurrentUser } from "@/lib/auth";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

const FEATURES = [
  "Automatic transcript with speaker labels",
  "Smart frame capture -- slides, diagrams, key moments",
  "Export to Markdown, Word, or PDF",
];

type GoogleLoginResponse = {
  access_token: string;
  user: CurrentUser;
};

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleGoogleSuccess(credential: string | undefined) {
    if (!credential) {
      setError("Google did not return a credential. Please try again.");
      return;
    }
    setError(null);
    try {
      const data = await apiFetch<GoogleLoginResponse>("/api/auth/google", {
        method: "POST",
        body: JSON.stringify({ id_token: credential }),
      });
      saveSession(data.access_token, data.user);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Please try again.");
    }
  }

  return (
    <div className="flex flex-1 flex-col lg:flex-row">
      {/* Marketing side -- hidden below lg so the form isn't squeezed on phones/tablets. */}
      <div className="relative hidden overflow-hidden bg-ink px-12 py-16 lg:flex lg:w-1/2 lg:flex-col lg:justify-between xl:w-3/5">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage: "radial-gradient(circle, #ffffff 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />

        <Link href="/" className="relative z-10 flex items-center gap-2.5">
          <Image src="/logo-icon.png" alt="" width={32} height={32} priority />
          <span className="font-mono text-lg font-semibold tracking-tight text-paper">
            FRAME<span className="text-accent">WRITE</span>
          </span>
        </Link>

        <div className="relative z-10 max-w-lg">
          <h1 className="font-display text-4xl font-bold tracking-tight text-paper xl:text-5xl">
            Turn any video into a document you&apos;ll actually use.
          </h1>
          <p className="mt-5 text-lg text-paper/70">
            Upload a video and get back a clean, searchable document -- full transcript, speaker
            labels, and the right images dropped in at the right spot.
          </p>

          <ul className="mt-8 space-y-3">
            {FEATURES.map((feature) => (
              <li key={feature} className="flex items-start gap-3 text-paper/90">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                {feature}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative z-10 font-mono text-sm text-paper/50">
          $1.00 per hour of video &middot; pay as you go, no subscription
        </p>
      </div>

      {/* Form side */}
      <div className="flex flex-1 items-center justify-center bg-paper px-6 py-16">
        <div className="w-full max-w-sm text-center">
          <Image src="/logo-icon.png" alt="" width={48} height={48} className="mx-auto lg:hidden" priority />
          <h2 className="mt-4 mb-1 font-display text-2xl font-bold tracking-tight text-ink lg:mt-0">
            Sign in to Framewrite
          </h2>
          <p className="mb-8 text-sm text-ink-soft">Convert videos, manage your jobs, and track usage.</p>

          {GOOGLE_CLIENT_ID ? (
            <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
              <div className="flex justify-center">
                <GoogleLogin
                  onSuccess={(credentialResponse) => handleGoogleSuccess(credentialResponse.credential)}
                  onError={() => setError("Google sign-in failed. Please try again.")}
                />
              </div>
            </GoogleOAuthProvider>
          ) : (
            <p className="text-sm text-status-error">
              Missing NEXT_PUBLIC_GOOGLE_CLIENT_ID -- sign-in is not configured.
            </p>
          )}

          {error && <p className="mt-4 text-sm text-status-error">{error}</p>}
        </div>
      </div>
    </div>
  );
}
