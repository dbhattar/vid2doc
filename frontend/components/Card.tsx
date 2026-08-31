/** Rounded, softly-shadowed panel -- part of the 2026-08-31 redesign back
 * toward a rounded/shadowed look (see plan/ui-redesign-plan.md), replacing
 * the sharp-cornered `border-2 border-line` panel used in the "bold &
 * editorial" direction before it.
 * No default padding: callers set their own via className, since padding
 * needs vary by context (p-4 for compact cards, p-6 for page panels). */
export default function Card({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-lg border border-line bg-paper shadow-sm ${className}`} {...props} />;
}
