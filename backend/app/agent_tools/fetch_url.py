import re
from html.parser import HTMLParser

from ._common import wrap_untrusted
from ._net import FetchError, safe_get

MAX_TEXT_CHARS = 10000

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer", "header", "aside", "form", "iframe"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text)."""
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return parser.title.strip(), text


def run(ctx: dict, args: dict) -> str:
    url = str(args.get("url", "")).strip()
    try:
        final_url, body, content_type = safe_get(url)
    except FetchError as e:
        return f"Couldn't fetch that page: {e}"
    if content_type == "text/html":
        title, text = html_to_text(body)
        text = f"Title: {title}\n\n{text}" if title else text
    else:
        text = body
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[truncated]"
    return wrap_untrusted(text or "(the page had no readable text)", final_url)


TOOL = {
    "order": 40,
    "name": "Fetch web page",
    "description": "Read the text of a public web page from a URL.",
    "functions": [
        {
            "type": "function",
            "name": "fetch_url",
            "description": "Fetch a public web page by URL and return its readable text. Only public http(s) sites work.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            "strict": True,
            "run": run,
        },
    ],
}
