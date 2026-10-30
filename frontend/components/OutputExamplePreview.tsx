"use client";

import { useState } from "react";

import { OUTPUT_EXAMPLES, SOURCE_VIDEO_NOTE, type ExampleBlock, type ExampleSection } from "@/lib/outputExamples";
import type { Transformation } from "@/lib/jobs";

function Block({ block }: { block: ExampleBlock }) {
  if (block.kind === "p") return <p className="mt-1 text-xs leading-relaxed text-ink-soft">{block.text}</p>;
  if (block.kind === "bullets") {
    return (
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-ink-soft">
        {block.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    );
  }
  return (
    <div className="mt-1 text-xs leading-relaxed">
      <p className="font-medium text-ink">Q: {block.q}</p>
      <p className="text-ink-soft">A: {block.a}</p>
    </div>
  );
}

function Section({ section }: { section: ExampleSection }) {
  return (
    <div className="mt-3 first:mt-0">
      <h4 className="text-sm font-semibold text-ink">{section.heading}</h4>
      {section.blocks.map((block, i) => (
        <Block key={i} block={block} />
      ))}
    </div>
  );
}

/** Static "here's what you'll get" sample for the selected output type.
 * Renders nothing for the full document (the homepage already shows real
 * samples of that one). */
export default function OutputExamplePreview({ transformation }: { transformation: Transformation }) {
  const [expanded, setExpanded] = useState(false);
  const example = OUTPUT_EXAMPLES[transformation];
  if (!example) return null;

  const sections = expanded ? [...example.preview, ...example.more] : example.preview;

  return (
    <div className="mt-4 rounded-md border border-line bg-accent-soft/20 p-4" aria-label="Example output">
      <p className="font-sans text-xs font-semibold uppercase tracking-wide text-accent">Example</p>
      <p className="mt-0.5 text-xs text-ink-soft">{SOURCE_VIDEO_NOTE}</p>
      <div className="mt-3 rounded-md border border-line bg-paper p-4">
        <h3 className="font-display text-base font-bold text-ink">{example.title}</h3>
        <div className="mt-3">
          {sections.map((section) => (
            <Section key={section.heading} section={section} />
          ))}
        </div>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-2 text-xs font-medium text-accent hover:underline"
      >
        {expanded ? "Show less" : "See full example"}
      </button>
    </div>
  );
}
