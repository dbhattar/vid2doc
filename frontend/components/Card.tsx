/** Sharp-cornered, border-separated panel -- replaces the old
 * `rounded-2xl border ... shadow-soft` pattern repeated across the app.
 * No default padding: callers set their own via className, since padding
 * needs vary by context (p-4 for compact cards, p-6 for page panels). */
export default function Card({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`border-2 border-line bg-paper ${className}`} {...props} />;
}
