"""Stage 6: segment the transcript into headed sections via Claude.

Requires ANTHROPIC_API_KEY in the environment (see .env.example).

Sliding windows of ~3500 words with ~500-word overlap; boundaries within 60s
across overlapping windows are deduped, keeping the more specific heading.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

WINDOW_WORDS = 3500
OVERLAP_WORDS = 500
DEDUPE_WINDOW_SECONDS = 60

SYSTEM_PROMPT = """You are segmenting a spoken-word transcript into logical sections for a document.

Identify natural topic boundaries in the given transcript excerpt. For each boundary, return the timestamp where the new topic starts, a short heading (a few words), and a one-line summary of that section. Only mark genuine topic shifts, not every speaker change."""

SEGMENT_TOOL = {
    "name": "submit_sections",
    "description": "Submit topic section boundaries found in this transcript window.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_timestamp": {"type": "number"},
                        "heading": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["start_timestamp", "heading", "summary"],
                },
            }
        },
        "required": ["sections"],
    },
}


def make_windows(segments: list[dict]) -> list[list[dict]]:
    windows = []
    i = 0
    while i < len(segments):
        window, word_count = [], 0
        j = i
        while j < len(segments) and word_count < WINDOW_WORDS:
            window.append(segments[j])
            word_count += len(segments[j]["text"].split())
            j += 1
        windows.append(window)
        if j >= len(segments):
            break
        # step back by roughly OVERLAP_WORDS worth of segments for the next window
        back_words, k = 0, j
        while k > i and back_words < OVERLAP_WORDS:
            k -= 1
            back_words += len(segments[k]["text"].split())
        i = k
    return windows


def segment_window(client, window: list[dict]) -> list[dict]:
    text = "\n".join(f"[{s['start_ts']:.0f}s] {s['speaker']}: {s['text']}" for s in window)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[SEGMENT_TOOL],
        tool_choice={"type": "tool", "name": "submit_sections"},
        messages=[{"role": "user", "content": text}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["sections"]
    return []


def dedupe_sections(all_sections: list[dict]) -> list[dict]:
    all_sections.sort(key=lambda s: s["start_timestamp"])
    deduped = []
    for section in all_sections:
        if deduped and section["start_timestamp"] - deduped[-1]["start_timestamp"] < DEDUPE_WINDOW_SECONDS:
            if len(section["heading"]) > len(deduped[-1]["heading"]):
                deduped[-1] = section
            continue
        deduped.append(section)
    return deduped


def segment_transcript(segments: list[dict]) -> list[dict]:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ANTHROPIC_API_KEY is not set. Get one at https://console.anthropic.com/, "
            "add it to local_test/.env, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    windows = make_windows(segments)
    all_sections = []
    for idx, window in enumerate(windows, start=1):
        sections = segment_window(client, window)
        print(f"Window {idx}/{len(windows)}: {len(sections)} boundaries found")
        all_sections.extend(sections)

    deduped = dedupe_sections(all_sections)

    # fill end_timestamp for each section (= next section's start, or end of transcript)
    last_ts = segments[-1]["end_ts"] if segments else 0
    for i, section in enumerate(deduped):
        section["end_timestamp"] = deduped[i + 1]["start_timestamp"] if i + 1 < len(deduped) else last_ts

    return deduped


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript_json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/sections.json"))
    args = parser.parse_args()

    transcript = json.loads(args.transcript_json.read_text())
    sections = segment_transcript(transcript["segments"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sections, indent=2))
    print(f"\n{len(sections)} sections written to {args.output}")
