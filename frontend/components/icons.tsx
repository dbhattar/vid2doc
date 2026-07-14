import {
  ChevronDown,
  ChevronLeft,
  CreditCard,
  FileArchive,
  FileCode,
  FileText,
  FileType2,
  KeyRound,
  LayoutDashboard,
  Mic,
  MessageSquare,
  ScrollText,
  Video,
  Wallet,
} from "lucide-react";

type IconProps = { className?: string };

export function DashboardIcon({ className }: IconProps) {
  return <LayoutDashboard className={className} aria-hidden />;
}

export function KeyIcon({ className }: IconProps) {
  return <KeyRound className={className} aria-hidden />;
}

export function DocumentIcon({ className }: IconProps) {
  return <FileText className={className} aria-hidden />;
}

export function BillingIcon({ className }: IconProps) {
  return <CreditCard className={className} aria-hidden />;
}

export function ChevronIcon({ className }: IconProps) {
  return <ChevronLeft className={className} aria-hidden />;
}

export function ChevronDownIcon({ className }: IconProps) {
  return <ChevronDown className={className} aria-hidden />;
}

export function WalletIcon({ className }: IconProps) {
  return <Wallet className={className} aria-hidden />;
}

export function FeedbackIcon({ className }: IconProps) {
  return <MessageSquare className={className} aria-hidden />;
}

export function VideoCameraIcon({ className }: IconProps) {
  return <Video className={className} aria-hidden />;
}

export function MicrophoneIcon({ className }: IconProps) {
  return <Mic className={className} aria-hidden />;
}

// File-type download icons -- distinct glyphs per format (no trademarked
// app logos, lucide doesn't ship those) so each download button reads
// differently even before the tooltip text loads.

export function MarkdownFileIcon({ className }: IconProps) {
  return <FileCode className={className} aria-hidden />;
}

export function ArchiveIcon({ className }: IconProps) {
  return <FileArchive className={className} aria-hidden />;
}

export function WordFileIcon({ className }: IconProps) {
  return <FileType2 className={className} aria-hidden />;
}

export function PdfFileIcon({ className }: IconProps) {
  return <ScrollText className={className} aria-hidden />;
}
