"use client";

import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { saveSession, type CurrentUser } from "@/lib/auth";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

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
    <div className="flex flex-1 items-center justify-center bg-zinc-50 dark:bg-black">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">Sign in to Framewrite</h1>
        <p className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
          Convert videos, manage your jobs, and track usage.
        </p>

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
          <p className="text-sm text-red-600">
            Missing NEXT_PUBLIC_GOOGLE_CLIENT_ID -- sign-in is not configured.
          </p>
        )}

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
