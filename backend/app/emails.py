import html

from .mailgun_client import send_email

_DASHBOARD_URL = "https://app.framewrite.cc/dashboard"
_LOGO_URL = "https://framewrite.cc/images/framewrite_logo.png"

# Brand tokens, matching styles.css's :root (navy/accent/bg) so transactional
# email feels like the same product as the marketing site and app.
_NAVY = "#1c2b4a"
_ACCENT = "#e2962f"
_ACCENT_SOFT = "#fbe9cf"
_BG = "#faf9f6"
_BORDER = "#e7e3d9"
_TEXT_MUTED = "#5b6b83"

_STEPS = [
    ("1", "Upload", "Drop in a video or audio file -- no editing, no timestamps to hunt down first."),
    ("2", "We do the work", "Transcript, speaker labels, and the right slides/diagrams pulled out automatically."),
    ("3", "Search it", "Get back a clean document you can search in seconds, instead of rewatching the video."),
]


def _step_row(number: str, title: str, body: str) -> str:
    return f"""
      <tr>
        <td width="36" valign="top" style="padding:0 12px 20px 0;">
          <div style="width:24px;height:24px;border-radius:999px;background:{_ACCENT_SOFT};color:{_NAVY};
                      border:1px solid {_ACCENT};font-family:Arial,Helvetica,sans-serif;font-size:12px;
                      font-weight:700;line-height:22px;text-align:center;">{number}</div>
        </td>
        <td valign="top" style="padding:0 0 20px 0;font-family:Arial,Helvetica,sans-serif;">
          <p style="margin:0 0 2px;font-size:14px;font-weight:700;color:{_NAVY};">{title}</p>
          <p style="margin:0;font-size:14px;color:{_TEXT_MUTED};line-height:1.5;">{body}</p>
        </td>
      </tr>"""


def send_welcome_email(user: dict) -> None:
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    name = html.escape(raw_name)
    subject = "Welcome to Framewrite"

    steps_html = "".join(_step_row(number, title, body) for number, title, body in _STEPS)

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
    <span style="display:none;font-size:0;color:{_BG};line-height:0;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      Upload your first video and see Framewrite turn it into a searchable document.
    </span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:560px;width:100%;background:#ffffff;border:1px solid {_BORDER};
                        border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 0;">
                <img src="{_LOGO_URL}" alt="Framewrite" height="22" style="display:block;height:22px;width:auto;" />
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px;">
                <p style="margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
                          color:{_NAVY};background:{_ACCENT_SOFT};display:inline-block;padding:4px 10px;border-radius:999px;">
                  Now live
                </p>
                <h1 style="margin:14px 0 8px;font-size:22px;line-height:1.3;letter-spacing:-0.01em;color:{_NAVY};">
                  Welcome to Framewrite, {name}
                </h1>
                <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Turn any video into a document you'll actually use -- full transcript, speaker labels,
                  and the right images dropped in at the right spot.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  {steps_html}
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:4px 32px 28px;">
                <a href="{_DASHBOARD_URL}"
                   style="display:inline-block;background:{_NAVY};color:#ffffff;text-decoration:none;
                          font-size:15px;font-weight:600;padding:13px 28px;border-radius:10px;">
                  Upload your first video
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 28px;border-top:1px solid {_BORDER};">
                <p style="margin:20px 0 0;font-size:13px;color:{_TEXT_MUTED};">
                  Pay-as-you-go, no subscription -- $1/hour of video, $0.40/hour of audio.
                </p>
              </td>
            </tr>
          </table>
          <p style="margin:20px 0 0;font-size:12px;color:{_TEXT_MUTED};">
            You're receiving this because you just signed up for Framewrite.
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    text = (
        f"Welcome to Framewrite, {raw_name}!\n\n"
        "Turn any video into a document you'll actually use -- full transcript, speaker labels, "
        "and the right images dropped in at the right spot.\n\n"
        "How it works:\n"
        "1. Upload -- drop in a video or audio file, no editing needed.\n"
        "2. We do the work -- transcript, speaker labels, and the right slides/diagrams pulled out automatically.\n"
        "3. Search it -- get back a clean document you can search in seconds.\n\n"
        f"Upload your first video: {_DASHBOARD_URL}\n\n"
        "Pay-as-you-go, no subscription: $1/hour of video, $0.40/hour of audio.\n\n"
        "-- The Framewrite team"
    )

    send_email(user["email"], subject, text, html=html_body)
