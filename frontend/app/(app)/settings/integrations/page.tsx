"use client";

import { GoogleOAuthProvider, useGoogleLogin } from "@react-oauth/google";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { DriveIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";

type DriveStatus = { connected: boolean; google_email: string | null };

function ConnectButton({ onConnected, onError }: { onConnected: (email: string) => void; onError: () => void }) {
  const login = useGoogleLogin({
    flow: "auth-code",
    scope: DRIVE_SCOPE,
    // Google's popup CodeClient (unlike the implicit/token flow) has no
    // `prompt` option to force re-consent -- if a refresh_token isn't
    // returned (e.g. reconnecting after already granting access once), the
    // backend's /api/drive/connect returns a clear error telling the user
    // to revoke access at myaccount.google.com/permissions and retry.
    onSuccess: async ({ code }) => {
      try {
        const data = await apiFetch<{ connected: boolean; google_email: string }>("/api/drive/connect", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
        onConnected(data.google_email);
      } catch {
        onError();
      }
    },
    onError,
  });

  return (
    <Button onClick={() => login()}>
      <DriveIcon className="h-4 w-4" />
      Connect Google Drive
    </Button>
  );
}

export default function IntegrationsPage() {
  const router = useRouter();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [googleEmail, setGoogleEmail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  useEffect(() => {
    apiFetch<DriveStatus>("/api/drive/status")
      .then((data) => {
        setConnected(data.connected);
        setGoogleEmail(data.google_email);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load Google Drive status.");
      });
  }, [router]);

  async function handleDisconnect() {
    if (!confirm("Disconnect Google Drive? You'll need to reconnect before using Save to Drive again.")) return;
    setDisconnecting(true);
    try {
      await apiFetch("/api/drive/connect", { method: "DELETE" });
      setConnected(false);
      setGoogleEmail(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to disconnect Google Drive.");
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <div className="w-full px-6 py-10">
      <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Integrations</h1>
      <p className="mt-1 text-sm text-ink-soft">Connect Google Drive to save generated documents there with one click.</p>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      <Card className="mt-8 flex items-center justify-between p-6">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center bg-paper-shade text-ink-soft">
            <DriveIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-ink">Google Drive</p>
            {connected === null ? (
              <p className="text-sm text-ink-soft">Loading...</p>
            ) : connected ? (
              <p className="text-sm text-ink-soft">Connected as {googleEmail}</p>
            ) : (
              <p className="text-sm text-ink-soft">Not connected</p>
            )}
          </div>
        </div>

        {connected === null ? null : connected ? (
          <Button variant="outline" onClick={handleDisconnect} disabled={disconnecting}>
            {disconnecting ? "Disconnecting..." : "Disconnect"}
          </Button>
        ) : GOOGLE_CLIENT_ID ? (
          <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
            <ConnectButton
              onConnected={(email) => {
                setConnected(true);
                setGoogleEmail(email);
              }}
              onError={() => setError("Google Drive connection failed. Please try again.")}
            />
          </GoogleOAuthProvider>
        ) : (
          <p className="text-sm text-status-error">Missing NEXT_PUBLIC_GOOGLE_CLIENT_ID -- not configured.</p>
        )}
      </Card>
      </div>
    </div>
  );
}
