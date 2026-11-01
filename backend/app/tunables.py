"""The registry of settings an admin may change at runtime from the admin
Settings page (routes/admin.py, runtime_config.py), instead of editing
environment variables and redeploying. Pure data -- no imports from the rest of
the app, because config.py imports this to know which names to resolve
dynamically.

Only settings that are safe and meaningful to change live belong here: no
secrets or keys, nothing infrastructural (database, paths, CORS). Each one has
bounds, so a typo on the admin page can't set, say, a negative price or a
zero-second duration limit. The env var (or code default) stays the fallback:
"reset" on the page returns to it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    name: str  # the Settings attribute, e.g. "MAX_DURATION_SECONDS"
    group: str
    label: str
    description: str
    type: str  # "int" | "float" | "bool" | "str" | "choice"
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    max_length: int = 100
    unit: str = ""


def _p(*args, **kwargs) -> Param:
    return Param(*args, **kwargs)


GROUPS = ("Pricing", "Limits", "Features", "Meetings", "Review reminders", "AI models", "Worker")

PARAMS: tuple[Param, ...] = (
    # --- Pricing: seconds of media per cent, so a bigger number is cheaper.
    _p("SECONDS_PER_CENT_VIDEO", "Pricing", "Video rate", "Seconds of video per cent charged. 36 = $1.00/hour; higher is cheaper. Page and marketing copy are not updated automatically.", "int", min=1, max=3600, unit="sec per cent"),
    _p("SECONDS_PER_CENT_AUDIO", "Pricing", "Audio rate", "Seconds of audio per cent. 90 = $0.40/hour.", "int", min=1, max=3600, unit="sec per cent"),
    _p("SECONDS_PER_CENT_VIDEO_GEN", "Pricing", "Video generation rate", "Seconds of generated video per cent. 20 = $1.80/hour.", "int", min=1, max=3600, unit="sec per cent"),
    _p("SECONDS_PER_CENT_RESEARCH", "Pricing", "Research rate", "Seconds of video per cent for the research transformation. 18 = $2.00/hour.", "int", min=1, max=3600, unit="sec per cent"),
    _p("SECONDS_PER_CENT_MEETING", "Pricing", "Meeting rate", "Seconds of meeting per cent. 36 = $1.00/hour.", "int", min=1, max=3600, unit="sec per cent"),
    _p("SIGNUP_BONUS_VIDEO_MINUTES", "Pricing", "Signup bonus", "Minutes of free video credited to a new account (applies to accounts created after the change).", "int", min=0, max=600, unit="minutes"),
    _p("CHAT_ENABLE_FEE_CENTS", "Pricing", "Chat fee", "One-time fee to enable chat on a finished document.", "int", min=0, max=10000, unit="cents"),
    _p("PAYMENTS_ENABLED", "Pricing", "Accept top-ups", "Turn off to stop new wallet top-ups (e.g. during a Stripe incident). Existing balances and jobs are unaffected.", "bool"),
    # --- Limits
    _p("MAX_DURATION_SECONDS", "Limits", "Max media length", "Longest video or audio a non-admin can upload, record or import.", "int", min=60, max=43200, unit="seconds"),
    _p("MAX_UPLOAD_BYTES", "Limits", "Max upload size", "Largest file a user can upload. 2147483648 = 2 GB.", "int", min=1_048_576, max=10_737_418_240, unit="bytes"),
    _p("VIDEO_GEN_MAX_DURATION_SECONDS", "Limits", "Max video-generation length", "Longest narration accepted for generated video.", "int", min=30, max=7200, unit="seconds"),
    # --- Features
    _p("LIVE_RESEARCH_ENABLED", "Features", "Live research", "Allow the live-research side panel during live recording.", "bool"),
    _p("SPEAKER_AUTO_ID_ENABLED", "Features", "Name speakers from the transcript", "One extra LLM call per audio job with 2+ speakers.", "bool"),
    _p("SPEAKER_AUTO_ID_APPLY_CONFIDENCE", "Features", "Auto-apply speaker names at", "Lowest confidence at which a name found in the transcript is filled in automatically. \"high\" is cautious; \"medium\" fills in more names but is wrong more often. Anything below is only suggested.", "choice", choices=("high", "medium")),
    # --- Meetings
    _p("MEETING_BOT_NAME", "Meetings", "Default bot name", "What attendees see when the user doesn't pick a name.", "str", max_length=50),
    _p("MEETING_MAX_SECONDS", "Meetings", "Max meeting length", "The bot leaves after recording this long (applies to bots sent after the change).", "int", min=300, max=28800, unit="seconds"),
    # --- Review reminders
    _p("REVIEW_REMINDER_AFTER_HOURS", "Review reminders", "Remind after", "A job still waiting for review after this long gets one reminder email.", "float", min=0.1, max=720, unit="hours"),
    _p("REVIEW_REMINDER_CHECK_SECONDS", "Review reminders", "Check every", "How often the worker looks for jobs due a reminder.", "int", min=30, max=86400, unit="seconds"),
    # --- AI models
    _p("LLM_PROVIDER", "AI models", "LLM provider", "Which provider writes documents, notes and summaries. Its API key must be set on the server, or jobs fail.", "choice", choices=("anthropic", "openai")),
    _p("OPENAI_MODEL", "AI models", "OpenAI model", "Model id used when the provider is OpenAI. A wrong id makes jobs fail.", "str", max_length=100),
    _p("TRANSCRIPTION_ENGINE", "AI models", "Transcription engine", "\"auto\" picks AssemblyAI or Baseten based on which key is set.", "choice", choices=("auto", "assemblyai", "baseten")),
    # --- Worker
    _p("WORKER_POLL_SECONDS", "Worker", "Job poll interval", "How often an idle worker looks for queued jobs.", "float", min=0.5, max=60, unit="seconds"),
    _p("ANNOUNCEMENT_SEND_DELAY_SECONDS", "Worker", "Announcement email delay", "Pause between announcement emails, to stay under the mail provider's rate limits.", "float", min=0, max=60, unit="seconds"),
)

BY_NAME: dict[str, Param] = {p.name: p for p in PARAMS}
NAMES: frozenset[str] = frozenset(BY_NAME)


class InvalidValue(ValueError):
    """Message is safe to show the admin."""


def validate(param: Param, value) -> object:
    """The typed, bounds-checked value, or InvalidValue. Strict about JSON
    types (a string "5" is not an int) so the stored text always round-trips."""
    if param.type == "bool":
        if not isinstance(value, bool):
            raise InvalidValue("Expected true or false.")
        return value
    if param.type in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidValue("Expected a number.")
        if param.type == "int":
            if isinstance(value, float) and not value.is_integer():
                raise InvalidValue("Expected a whole number.")
            value = int(value)
        else:
            value = float(value)
        if (param.min is not None and value < param.min) or (param.max is not None and value > param.max):
            raise InvalidValue(f"Must be between {param.min:g} and {param.max:g}.")
        return value
    if not isinstance(value, str):
        raise InvalidValue("Expected text.")
    value = " ".join(value.split())
    if param.type == "choice":
        if value not in param.choices:
            raise InvalidValue(f"Must be one of: {', '.join(param.choices)}.")
        return value
    if not value or len(value) > param.max_length or not value.isprintable():
        raise InvalidValue(f"Expected 1-{param.max_length} printable characters.")
    return value


def serialize(param: Param, value) -> str:
    return ("true" if value else "false") if param.type == "bool" else str(value)


def deserialize(param: Param, raw: str):
    """Inverse of serialize; raises InvalidValue for a stored value that no
    longer fits (e.g. bounds were tightened) so the caller can ignore it."""
    if param.type == "bool":
        if raw not in ("true", "false"):
            raise InvalidValue("bad bool")
        return raw == "true"
    if param.type == "int":
        try:
            return validate(param, int(raw))
        except ValueError as e:
            raise InvalidValue(str(e))
    if param.type == "float":
        try:
            return validate(param, float(raw))
        except ValueError as e:
            raise InvalidValue(str(e))
    return validate(param, raw)
