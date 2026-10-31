"""Public OAuth information only; no account, mail, or database access."""
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

PAGES = {
    "/about": ("CareerHunter", """
<p>CareerHunter is a personal career research and application tracking tool.
It collects public job listings and can summarize recent incoming application,
interview, assessment, rejection, and follow-up emails for the account owner.</p>
<p>The optional Gmail integration requests only gmail.readonly. It cannot send,
delete, label, or modify email. It is intended for the owner's own account.</p>
<p>The private dashboard remains protected by its existing sign-in controls.</p>
"""),
    "/privacy": ("CareerHunter Privacy Policy", """
<p>Effective date: 1 November 2026. CareerHunter is a personal-use tool operated
by its account owner. Gmail access is optional and requires explicit Google
authorization for https://www.googleapis.com/auth/gmail.readonly.</p>
<p><strong>Access and use:</strong> The Gmail reader examines at most 30 recent
inbox messages per invocation, excluding promotional-category messages, to
classify career-related responses and identify items requiring review.</p>
<p><strong>Storage:</strong> Message contents are processed temporarily in memory
by the Gmail reader and are not written to its database, application logs, or
public build artifacts. OAuth credentials are kept in the application's Render
secret environment variables until removed or replaced by the owner.</p>
<p><strong>Sharing:</strong> Authorized reports contain aggregate category counts
and review counts and may be sent to the owner's configured private Telegram
chat. The Gmail reader does not include raw messages, sender addresses, or
message bodies in these reports. Google, Render, and Telegram process the
requests necessary to provide their respective services.</p>
<p><strong>Limits:</strong> Gmail data is not sold, used for advertising, or sent
to a general-purpose AI model for training. The Gmail integration does not send
replies or change Gmail messages or CRM records automatically.</p>
<p>CareerHunter's use and transfer of information received from Google APIs
adheres to the Google API Services User Data Policy, including Limited Use.</p>
<p><strong>Control and removal:</strong> The owner can revoke access through
Google Account's third-party connections, remove the three GMAIL_READONLY_*
credentials in Render, and delete retained Telegram reports in Telegram.
For questions, use the support email displayed on the OAuth consent screen.</p>
"""),
    "/terms": ("CareerHunter Terms of Use", """
<p>Effective date: 1 November 2026. CareerHunter is a personal-use career
research tool. It may only be connected to accounts the operator is authorized
to use. Email classification is informational and requires human review.</p>
<p>The tool does not guarantee job availability, a hiring outcome, uninterrupted
operation, or error-free classification. The owner remains responsible for
reviewing and sending applications and correspondence.</p>
<p>Google authorization may be revoked at any time. Third-party services remain
subject to their own terms and availability. No subscription or payment is
required by this personal Gmail integration.</p>
"""),
}


def render_information(path: str) -> str:
    title, content = PAGES[path]
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>" + escape(title) + "</title>"
        "<style>body{font:17px system-ui;line-height:1.65;max-width:760px;"
        "margin:48px auto;padding:0 22px;color:#172033}nav a{margin-right:18px}"
        "a{color:#1656a5}</style><nav><a href='/about'>About</a>"
        "<a href='/privacy'>Privacy</a><a href='/terms'>Terms</a></nav>"
        "<h1>" + escape(title) + "</h1>" + content + "</html>"
    )


@router.get("/about", response_class=HTMLResponse)
def about() -> HTMLResponse:
    return HTMLResponse(render_information("/about"))


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    return HTMLResponse(render_information("/privacy"))


@router.get("/terms", response_class=HTMLResponse)
def terms() -> HTMLResponse:
    return HTMLResponse(render_information("/terms"))
