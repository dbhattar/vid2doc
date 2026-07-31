"use client";

import Link from "next/link";

import DocumentSection from "@/components/DocumentSection";
import { MicrophoneIcon, VideoCameraIcon } from "@/components/icons";

export default function DocumentsPage() {
  return (
    <div className="w-full px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Documents</h1>
      <p className="mt-1 text-sm text-ink-soft">Every document Framewrite has finished generating for you.</p>

      <DocumentSection jobType="video" title="Video documents" Icon={VideoCameraIcon} pageSize={9} />
      <DocumentSection jobType="audio" title="Audio transcripts" Icon={MicrophoneIcon} pageSize={9} />

      <p className="mt-10 text-center text-sm text-ink-soft">
        Nothing here yet? Convert a{" "}
        <Link href="/dashboard/video" className="underline hover:text-accent">
          video
        </Link>{" "}
        or{" "}
        <Link href="/dashboard/audio" className="underline hover:text-accent">
          audio
        </Link>{" "}
        file.
      </p>
    </div>
  );
}
