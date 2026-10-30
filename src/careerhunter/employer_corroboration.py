"""Optional independent link proof from a configured employer-owned careers page.

Only an exact clickable link to the specific ATS posting counts. This check
never executes JavaScript, follows redirects, guesses hiring eligibility, or
labels a missing link as fraud. Its result does not replace ATS evidence.
"""
from __future__ import annotations

import ipaddress
from contextlib import nullcontext
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


MAX_HTML_BYTES = 500_000


@dataclass(frozen=True)
class EmployerEvidence:
    verified: bool
    reason: str
    page_url: str


def _https_public_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not host or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            return False
        if (host in {"localhost", "metadata.google.internal"}
                or host.endswith((".localhost", ".local", ".internal"))):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return "." in host and not any(c.isspace() for c in value)
        return False  # Configured careers page must use a hostname, never an IP.
    except ValueError:
        return False


def _same_posting(left: str, right: str) -> bool:
    try:
        a, b = urlsplit(left), urlsplit(right)
        return bool(a.scheme == "https" and b.scheme == "https"
                    and a.hostname and a.hostname == b.hostname
                    and (a.path.rstrip("/") or "/") == (b.path.rstrip("/") or "/")
                    and a.port in (None, 443) and b.port in (None, 443)
                    and not a.username and not b.username)
    except ValueError:
        return False


class _Links(HTMLParser):
    def __init__(self, base: str, target: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.target = target
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and _same_posting(urljoin(self.base, href), self.target):
            self.found = True


def contains_exact_posting_link(html: str, careers_url: str, job_url: str) -> bool:
    parser = _Links(careers_url, job_url)
    parser.feed(html[:MAX_HTML_BYTES])
    return parser.found


def check_employer_page(
    careers_url: str, job_url: str, *, client: httpx.Client | None = None
) -> EmployerEvidence:
    """Check one manually configured careers page, with bounded and safe fetching."""
    if not _https_public_url(careers_url) or not _https_public_url(job_url):
        return EmployerEvidence(False, "unsafe_or_unconfigured_https_url", careers_url)
    context = nullcontext(client) if client is not None else httpx.Client(
        timeout=10, follow_redirects=False, trust_env=False,
        headers={"User-Agent": "CareerHunterAI/0.2", "Accept": "text/html"}
    )
    try:
        with context as http:
            with http.stream("GET", careers_url, follow_redirects=False) as response:
                if response.status_code != 200:
                    return EmployerEvidence(False, "employer_page_unavailable", careers_url)
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type:
                    return EmployerEvidence(False, "not_an_html_careers_page", careers_url)
                raw = bytearray()
                for piece in response.iter_bytes():
                    raw.extend(piece)
                    if len(raw) > MAX_HTML_BYTES:
                        return EmployerEvidence(False, "employer_page_too_large", careers_url)
        found = contains_exact_posting_link(
            raw.decode("utf-8", errors="replace"), careers_url, job_url
        )
        return EmployerEvidence(
            found, "exact_posting_link_on_configured_employer_page" if found
            else "no_direct_link_found_not_proof_of_absence", careers_url
        )
    except (httpx.HTTPError, OSError, UnicodeError):
        return EmployerEvidence(False, "employer_page_network_error", careers_url)
