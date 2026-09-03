"use client";

import { useEffect, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import AuthenticatedImage from "@/components/AuthenticatedImage";
import { fetchAuthenticatedText } from "@/lib/api";

/** Pulls a leading "## Summary" section (see backend/app/pipeline.py's
 * _prepend_summary_section, video documents only) out of the raw markdown
 * so it can be rendered in its own highlighted callout, matching
 * TranscriptViewer.tsx's audio-summary box. Anything else -- including
 * audio jobs, which don't use DocumentPreview for their summary at all --
 * has no "## Summary" heading and renders completely unaffected. */
function splitSummarySection(markdown: string): { before: string; summary: string | null; after: string } {
  const match = markdown.match(/^## Summary\s*$/m);
  if (!match || match.index == null) return { before: markdown, summary: null, after: "" };
  const start = match.index;
  const rest = markdown.slice(start);
  const nextHeadingOffset = rest.slice(1).search(/^## /m);
  const end = nextHeadingOffset === -1 ? rest.length : nextHeadingOffset + 1;
  return { before: markdown.slice(0, start), summary: rest.slice(0, end), after: rest.slice(end) };
}

/** Renders a finished job's document.md inline, so the result is visible
 * without downloading anything first. Reused as-is on both the owner's job
 * detail page and the public share page -- image resolution is pure
 * relative-URL math against `markdownUrl`, and AuthenticatedImage only
 * attaches a Bearer header when a token happens to exist, so nothing here
 * needs to know whether the viewer is authenticated.
 *
 * `bordered` (default true) draws the top divider + spacing that make sense
 * when this is appended after other content within the same card (the
 * share page's single-card layout, e.g.) -- pass `false` when this is the
 * sole content of its own fresh card, where a divider right under the
 * card's own padding would just be a stray line floating in empty space. */
export default function DocumentPreview({ markdownUrl, bordered = true }: { markdownUrl: string; bordered?: boolean }) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMarkdown(null);
    setError(null);
    fetchAuthenticatedText(markdownUrl)
      .then((text) => {
        if (!cancelled) setMarkdown(text);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load the document preview.");
      });
    return () => {
      cancelled = true;
    };
  }, [markdownUrl]);

  if (error) return <p className={`${bordered ? "mt-6" : ""} text-sm text-status-error`}>{error}</p>;
  if (markdown === null) return <p className={`${bordered ? "mt-6" : ""} text-sm text-ink-soft`}>Loading document...</p>;

  const components: Components = {
    h1: ({ children }) => (
      <h1 className="mb-4 border-b border-line pb-2 font-display text-2xl font-bold tracking-tight text-ink">{children}</h1>
    ),
    h2: ({ children }) => <h2 className="mt-8 mb-3 font-display text-lg font-bold text-ink">{children}</h2>,
    h3: ({ children }) => <h3 className="mt-6 mb-2 font-display text-base font-semibold text-ink">{children}</h3>,
    p: ({ children }) => <p className="mb-4 text-sm leading-relaxed text-ink">{children}</p>,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">
        {children}
      </a>
    ),
    em: ({ children }) => <em className="text-ink-soft">{children}</em>,
    ul: ({ children }) => <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-ink">{children}</ul>,
    ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1 pl-5 text-sm text-ink">{children}</ol>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-accent pl-4 italic text-ink-soft">{children}</blockquote>
    ),
    code: ({ children }) => <code className="rounded-sm border border-line bg-paper-shade px-1 py-0.5 font-mono text-xs">{children}</code>,
    pre: ({ children }) => (
      <pre className="mb-4 overflow-x-auto rounded-md border border-line bg-paper-shade p-3 font-mono text-xs">{children}</pre>
    ),
    table: ({ children }) => (
      <div className="mb-4 overflow-x-auto">
        <table className="w-full border border-line text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-ink font-sans text-xs font-semibold text-paper">{children}</thead>,
    th: ({ children }) => <th className="border border-line px-3 py-2 text-left">{children}</th>,
    td: ({ children }) => <td className="border border-line px-3 py-2 text-ink">{children}</td>,
    img: ({ src, alt }) => {
      if (!src || typeof src !== "string") return null;
      const resolvedSrc = new URL(src, markdownUrl).toString();
      return <AuthenticatedImage src={resolvedSrc} alt={alt || ""} className="w-full rounded-md border border-line" />;
    },
  };

  const { before, summary, after } = splitSummarySection(markdown);

  return (
    <div className={bordered ? "mt-6 border-t border-line pt-6" : ""}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {before}
      </ReactMarkdown>
      {summary && (
        <div className="mb-6 rounded-md bg-paper-shade p-4">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {summary}
          </ReactMarkdown>
        </div>
      )}
      {after && (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {after}
        </ReactMarkdown>
      )}
    </div>
  );
}
