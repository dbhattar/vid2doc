import io

from fastapi import HTTPException
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .. import drive_connections
from ._common import rate_limited

MAX_PER_HOUR = 20
MAX_CONTENT_CHARS = 100000
DOC_MIME_TYPE = "application/vnd.google-apps.document"


def available(user: dict) -> str | None:
    if not drive_connections.get_connection_for_user(user["id"]):
        return "Connect Google Drive in Settings > Integrations first."
    return None


def run(ctx: dict, args: dict) -> str:
    user = ctx["user"]
    reason = available(user)
    if reason:
        return reason
    title = str(args.get("title", "")).strip()[:200] or "Framewrite agent note"
    content = str(args.get("content", "")).strip()[:MAX_CONTENT_CHARS]
    if not content:
        return "Provide content."
    if rate_limited("save_to_drive", user["id"], MAX_PER_HOUR):
        return f"Drive save limit reached ({MAX_PER_HOUR} per hour) -- try again later."

    # Imported here, not at module top: routes/ imports the rest of the app,
    # and this package is imported while agents.py is being loaded.
    from ..routes.drive import _load_drive_client

    try:
        drive = _load_drive_client(user["id"])
        created = (
            drive.files()
            .create(
                # Uploading plain text with the Google Docs mime type makes Drive convert it into a Doc.
                body={"name": title, "mimeType": DOC_MIME_TYPE},
                media_body=MediaIoBaseUpload(io.BytesIO(content.encode()), mimetype="text/plain", resumable=False),
                fields="id,webViewLink",
            )
            .execute(num_retries=3)
        )
    except HTTPException as e:
        return str(e.detail)
    except HttpError:
        return "Google Drive rejected the save -- try again later."
    return f'Saved as a new Google Doc "{title}": {created.get("webViewLink", "(no link returned)")}'


TOOL = {
    "order": 60,
    "name": "Save to Google Drive",
    "description": "Save the agent's output as a new Google Doc in your connected Drive.",
    "available": available,
    "functions": [
        {
            "type": "function",
            "name": "save_to_drive",
            "description": "Create a NEW Google Doc in the user's Drive with a title and plain-text content (no markdown syntax -- it is not rendered). Never overwrites existing files. Returns the doc link.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                "required": ["title", "content"],
                "additionalProperties": False,
            },
            "strict": True,
            "run": run,
        },
    ],
}
