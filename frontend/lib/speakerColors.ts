// Shared between TranscriptViewer (post-job transcript view) and the live
// recording page, so a speaker's color stays consistent whether you're
// watching it live or reviewing the finished job afterward.
const SPEAKER_COLORS = [
  { avatar: "bg-blue-100 text-blue-700", bar: "bg-blue-400" },
  { avatar: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-400" },
  { avatar: "bg-amber-100 text-amber-700", bar: "bg-amber-400" },
  { avatar: "bg-purple-100 text-purple-700", bar: "bg-purple-400" },
  { avatar: "bg-rose-100 text-rose-700", bar: "bg-rose-400" },
  { avatar: "bg-teal-100 text-teal-700", bar: "bg-teal-400" },
];

export function speakerColorFor(index: number) {
  return SPEAKER_COLORS[index % SPEAKER_COLORS.length];
}

export function speakerInitials(name: string): string {
  return name.trim().slice(0, 2).toUpperCase() || "?";
}
