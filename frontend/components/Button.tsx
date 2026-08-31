export type ButtonVariant = "primary" | "secondary" | "outline";

const BASE =
  "font-sans text-sm font-semibold transition-all duration-150 ease-[var(--ease-spring)] disabled:cursor-default disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2.5 text-accent-ink shadow-[var(--shadow-accent)] hover:-translate-y-0.5 hover:shadow-lg",
  secondary: "text-ink underline decoration-line underline-offset-2 hover:decoration-current",
  // Same visual weight as primary, without the solid fill -- for a page's
  // secondary/alternative actions sitting next to a primary one.
  outline:
    "inline-flex items-center gap-2 rounded-md border border-line px-3.5 py-2 text-ink hover:-translate-y-0.5 hover:border-ink hover:bg-paper-shade",
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
