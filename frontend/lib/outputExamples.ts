import type { Transformation } from "./jobs";

/** Static sample of what each non-"document" output looks like, shown on the
 * upload form so users can see the result before choosing. All three are
 * written against the same imaginary source video, so they're comparable.
 * Not generated -- keep in sync by hand with what backend/app/stages/
 * transform.py actually produces (headings, timestamp markers, "From the
 * video:" lines, "Sources:" lists). */
export type ExampleBlock = { kind: "p"; text: string } | { kind: "bullets"; items: string[] } | { kind: "qa"; q: string; a: string };

export type ExampleSection = { heading: string; blocks: ExampleBlock[] };

export type OutputExample = {
  title: string;
  /** Always shown. */
  preview: ExampleSection[];
  /** Shown in addition to `preview` once expanded. */
  more: ExampleSection[];
};

export const SOURCE_VIDEO_NOTE = "Sample from a 42-minute webinar, “Going Solar: A Homeowner’s Guide”.";

export const OUTPUT_EXAMPLES: Partial<Record<Transformation, OutputExample>> = {
  notes: {
    title: "Notes: Going Solar — A Homeowner’s Guide",
    preview: [
      {
        heading: "Sizing a system",
        blocks: [
          {
            kind: "bullets",
            items: [
              "Typical home system is 5–8 kW, roughly 14–20 panels (3:12)",
              "South-facing roofs are best; east/west lose about 15% of output (6:40)",
              "Size to last year’s usage, not the biggest roof area (8:05)",
            ],
          },
        ],
      },
      {
        heading: "Costs and incentives",
        blocks: [
          {
            kind: "bullets",
            items: [
              "Installed cost averages $2.50–$3.50 per watt before incentives (14:20)",
              "Federal tax credit covers 30% of the system cost (16:45)",
            ],
          },
        ],
      },
    ],
    more: [
      {
        heading: "Net metering",
        blocks: [
          {
            kind: "bullets",
            items: [
              "Excess power goes back to the grid for a bill credit (21:10)",
              "Some utilities now pay a lower export rate than the retail rate (23:30)",
            ],
          },
        ],
      },
      {
        heading: "Further reading",
        blocks: [
          {
            kind: "bullets",
            items: [
              "Residential Clean Energy Credit -- irs.gov",
              "How net metering works -- energy.gov",
              "Solar installation cost benchmarks -- nrel.gov",
            ],
          },
        ],
      },
    ],
  },
  study_guide: {
    title: "Study guide: Going Solar — A Homeowner’s Guide",
    preview: [
      {
        heading: "Summary",
        blocks: [
          {
            kind: "p",
            text: "The talk walks through how a homeowner decides whether solar makes sense: sizing a system to annual usage, understanding upfront cost and incentives, and how net metering turns excess generation into bill credits.",
          },
        ],
      },
      {
        heading: "Key concepts",
        blocks: [
          {
            kind: "bullets",
            items: [
              "Net metering: a billing arrangement that credits you for power your panels send back to the grid.",
              "Inverter: the device that converts the panels’ DC output into the AC power your home uses.",
            ],
          },
        ],
      },
    ],
    more: [
      {
        heading: "Review questions",
        blocks: [
          {
            kind: "qa",
            q: "Why size a system to annual usage rather than to the roof?",
            a: "Oversizing past your usage means exporting power that may be credited at a lower rate, which lengthens the payback period.",
          },
          {
            kind: "qa",
            q: "How much does an east- or west-facing roof reduce output compared with south-facing?",
            a: "About 15%.",
          },
        ],
      },
    ],
  },
  research: {
    title: "Research: Going Solar — A Homeowner’s Guide",
    preview: [
      {
        heading: "Overview",
        blocks: [
          {
            kind: "p",
            text: "The webinar covers sizing, cost and net metering for residential solar. Below, the claims and policies it mentions are checked against current outside sources.",
          },
        ],
      },
      {
        heading: "Net metering rules",
        blocks: [
          {
            kind: "p",
            text: "From the video: Excess power goes back to the grid for a bill credit, though some utilities pay a lower export rate.",
          },
          {
            kind: "p",
            text: "Several states have moved from full retail-rate credits to “net billing,” where exports are credited at a lower, time-varying rate. Whether this applies depends on your utility, so check its current tariff before sizing a system.",
          },
          {
            kind: "bullets",
            items: ["Net metering policy overview -- energy.gov", "State net metering database -- dsireusa.org"],
          },
        ],
      },
    ],
    more: [
      {
        heading: "Federal tax credit",
        blocks: [
          {
            kind: "p",
            text: "From the video: The federal tax credit covers 30% of the system cost.",
          },
          {
            kind: "p",
            text: "The credit is claimed on your tax return and applies to equipment and installation. It is non-refundable, so a large credit may need to be carried forward across tax years.",
          },
          { kind: "bullets", items: ["Residential Clean Energy Credit -- irs.gov"] },
        ],
      },
    ],
  },
};
