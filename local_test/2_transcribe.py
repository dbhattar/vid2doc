"""Stage 2: transcribe + diarize audio via AssemblyAI.

Requires ASSEMBLYAI_API_KEY in the environment (see .env.example).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def transcribe_diarize(audio_path: Path) -> dict:
    import assemblyai as aai

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        print(
            "ASSEMBLYAI_API_KEY is not set. Get one at https://www.assemblyai.com/, "
            "add it to local_test/.env, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(speaker_labels=True)
    transcript = aai.Transcriber().transcribe(str(audio_path), config)

    if transcript.status == aai.TranscriptStatus.error:
        print(f"Transcription failed: {transcript.error}", file=sys.stderr)
        sys.exit(1)

    segments = [
        {
            "speaker": utt.speaker,
            "text": utt.text,
            "start_ts": utt.start / 1000,
            "end_ts": utt.end / 1000,
        }
        for utt in transcript.utterances
    ]
    return {"segments": segments}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/transcript.json"))
    args = parser.parse_args()

    result = transcribe_diarize(args.audio_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(f"Transcript ({len(result['segments'])} segments) written to {args.output}")
