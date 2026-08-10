import {
  ChevronDown,
  ChevronLeft,
  CreditCard,
  FileArchive,
  FileJson,
  FileText,
  FileType2,
  Globe,
  KeyRound,
  LayoutDashboard,
  Menu,
  Mic,
  MessageSquare,
  Monitor,
  Moon,
  ScrollText,
  Share2,
  Shield,
  Sun,
  Users,
  Video,
  Wallet,
  X,
} from "lucide-react";
import { SiGoogledrive, SiMarkdown } from "react-icons/si";

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

export function GlobeIcon({ className }: IconProps) {
  return <Globe className={className} aria-hidden />;
}

export function MenuIcon({ className }: IconProps) {
  return <Menu className={className} aria-hidden />;
}

export function CloseIcon({ className }: IconProps) {
  return <X className={className} aria-hidden />;
}

// File-type download icons. Markdown and Google Drive use their real,
// recognized marks (react-icons' Simple Icons set -- CC0, single-color by
// design, exactly for this "represent a known format/service" use case).
// Word/PDF/Zip have no equivalent free-to-use brand mark (Simple Icons
// doesn't carry Microsoft/Adobe product icons), so those stay distinct
// lucide shapes -- callers tint them per format (red/blue/amber) for the
// same at-a-glance recognition without needing a trademarked logo.

export function MarkdownFileIcon({ className }: IconProps) {
  return <SiMarkdown className={className} aria-hidden />;
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

export function JsonFileIcon({ className }: IconProps) {
  return <FileJson className={className} aria-hidden />;
}

export function ShieldIcon({ className }: IconProps) {
  return <Shield className={className} aria-hidden />;
}

export function UsersIcon({ className }: IconProps) {
  return <Users className={className} aria-hidden />;
}

export function SunIcon({ className }: IconProps) {
  return <Sun className={className} aria-hidden />;
}

export function MoonIcon({ className }: IconProps) {
  return <Moon className={className} aria-hidden />;
}

export function SystemThemeIcon({ className }: IconProps) {
  return <Monitor className={className} aria-hidden />;
}

export function DriveIcon({ className }: IconProps) {
  return <SiGoogledrive className={className} aria-hidden />;
}

export function ShareIcon({ className }: IconProps) {
  return <Share2 className={className} aria-hidden />;
}
