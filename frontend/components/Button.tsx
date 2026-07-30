export type ButtonVariant = "primary" | "secondary" | "outline";

const BASE = "font-mono text-sm font-medium uppercase tracking-wide transition-colors disabled:cursor-default disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "inline-flex items-center gap-2 border-2 border-ink bg-ink px-4 py-2 text-paper hover:border-accent hover:bg-accent hover:text-accent-ink",
  secondary: "text-ink underline decoration-line underline-offset-2 hover:decoration-current",
  // Same visual weight as primary, without the solid fill -- for a page's
  // secondary/alternative actions sitting next to a primary one.
  outline: "inline-flex items-center gap-2 border-2 border-line px-3 py-1.5 text-ink hover:bg-paper-shade hover:border-ink",
};

/** Shared button visual style -- use directly on a `<Link>`/`<a>` when the
 * action navigates rather than triggers a handler, so it still looks like a
 * button without being one (invalid nested-interactive-element-wise). */
export function buttonClassName(variant: ButtonVariant = "primary", className = ""): string {
  return `${BASE} ${VARIANTS[variant]} ${className}`.trim();
}

export default function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={buttonClassName(variant, className)} {...props} />;
}
