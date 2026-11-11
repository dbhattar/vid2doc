"""What the source is called in the text the transformations (notes, study
guide, research) send to the model and write into the document: "video" by
default, "recording" when it was made from an audio transcript. The pipeline
sets it once around a job (`with medium.noun("recording"):`) and the prompt and
output strings that say "video" go through `say()`. Only fixed prompt/label text
is passed through `say()` -- never the transcript itself, which may contain the
word.
"""

import contextvars
import re
from contextlib import contextmanager

_noun: contextvars.ContextVar[str] = contextvars.ContextVar("medium_noun", default="video")


@contextmanager
def noun(value: str):
    token = _noun.set(value)
    try:
        yield
    finally:
        _noun.reset(token)


def say(text: str) -> str:
    """`text` with the standalone word "video" (any case of the first letter)
    replaced by the current noun."""
    current = _noun.get()
    if current == "video":
        return text
    return re.sub(r"\b([Vv])ideo\b", lambda m: current.capitalize() if m.group(1) == "V" else current, text)
