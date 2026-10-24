"""Conservative discovery of people explicitly published on company pages.

This module intentionally does not guess identities or email addresses.  It can
parse a supplied team/leadership HTML page (or fetch one with bounded retries)
and only returns a contact when both a name and an explicit role are present.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from html import unescape
import re
import hashlib
import time
from urllib.request import Request, urlopen

from careerhunter.models import Contact

ROLE_RE = re.compile(r"\b(engineer|developer|manager|director|recruiter|talent|founder|lead|head|vp|chief|hr|people|data scientist|product|designer|analyst|scientist)\b", re.I)


def _person_id(*, company: str, name: str, role: str = "", source_url: str,
               linkedin_url: str | None = None, email: str | None = None,
               occurrence: int = 0) -> str:
    """Return an evidence-bound identity, never a company/name-only key.

    Names are not unique (especially short names such as ``Kim``).  Bind the
    generated key to the source evidence so two pages cannot silently merge
    records.  A public LinkedIn URL/email is included when present, while the
    source remains part of the key to preserve provenance and avoid accidental
    cross-page merges. Existing persisted IDs remain valid; this only affects
    newly discovered contacts.
    """
    # Role is part of the identity evidence: a page may explicitly list two
    # people with the same short name (e.g. two different "Kim" cards).  The
    # same name+role+source remains stable and deduplicates on re-runs.
    evidence = "|".join((company.strip().casefold(), name.strip().casefold(),
                         role.strip().casefold(),
                         source_url.strip(), (linkedin_url or "").strip(),
                         (email or "").strip().casefold(), str(occurrence)))
    digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", f"{company}-{name}".lower()).strip("-")
    return f"person-{slug}-{digest}"


@dataclass(frozen=True)
class DiscoveryResult:
    contacts: list[Contact]
    source_url: str
    observed_at: datetime
    status: str = "ok"
    error: str | None = None


def discover_public_contacts(companies: list[dict], *, timeout: float = 10,
                              retries: int = 2,
                              cache: dict[str, tuple[float, str]] | None = None
                              ) -> tuple[list[Contact], list[str]]:
    """Discover only explicitly published people from configured public pages.

    A missing URL or an unavailable page is returned as a reportable error; it
    never turns into an inferred contact.  The caller owns persistence so this
    works with the same production repository as jobs and CRM records.
    """
    discovered: list[Contact] = []
    errors: list[str] = []
    for company_cfg in companies:
        company = str(company_cfg.get("name", "")).strip()
        url = str(company_cfg.get("team_url", "")).strip()
        if not company:
            continue
        if not url:
            errors.append(f"{company}: no public team_url configured")
            continue
        try:
            html = fetch_team_page(url, timeout=timeout, retries=retries, cache=cache)
            result = parse_team_page(html, source_url=url, company=company)
            if result.status != "ok":
                errors.append(f"{company}: {result.error or result.status}")
            elif not result.contacts:
                errors.append(f"{company}: source contained no explicit name+role")
            else:
                discovered.extend(result.contacts)
        except Exception as exc:
            errors.append(f"{company}: {type(exc).__name__}: {exc}")
    return discovered, errors


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, list[str], list[str]]] = []
        self._tag = ""
        self._text: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"article", "li", "section", "div"} and self._text:
            self._flush()
        self._tag = tag
        href = dict(attrs).get("href")
        if href and ("linkedin.com/in/" in href or href.startswith("mailto:")):
            self._links.append(href)

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self._text.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"article", "li", "section"}:
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join(self._text).strip()
        if text:
            self.blocks.append((text, self._links[:], self._text[:]))
        self._text, self._links = [], []


def parse_team_page(html: str, *, source_url: str, company: str, country: str = "unknown") -> DiscoveryResult:
    """Parse explicit team cards; no name/email inference is performed."""
    observed = datetime.now(timezone.utc)
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    contacts: list[Contact] = []
    seen: set[str] = set()
    occurrences: dict[tuple[str, str], int] = {}
    block_seen: set[tuple[str, tuple[str, ...]]] = set()
    # Some official team pages publish a short name in a figcaption and the
    # role in a nested cite element (for example, "Kim — Software Engineer").
    # Capture that explicit pairing before generic card parsing; never infer
    # a surname or email from it.
    for match in re.finditer(r"<figcaption[^>]*>\s*([^<,]{1,80})\s*,?\s*<cite[^>]*>\s*([^<]{2,100})", html, re.I | re.S):
        name = " ".join(unescape(match.group(1)).split())
        role = " ".join(unescape(match.group(2)).split()).strip(" ,")
        if not name or not role or not ROLE_RE.search(role):
            continue
        key = (name.casefold(), role.casefold())
        occurrences[key] = occurrences.get(key, 0) + 1
        person_id = _person_id(company=company, name=name, role=role, source_url=source_url,
                               occurrence=occurrences[key])
        if person_id in seen:
            continue
        seen.add(person_id)
        contacts.append(Contact(
            person_id=person_id, name=name, company=company, role=role,
            country=country, primary_source_url=source_url, category="company_page",
            research_sources=[source_url], verified_context=f"Explicitly listed as {role} on company page.",
            research_confidence="medium", status="discovered",
        ))
    for text, links, parts in parser.blocks:
        block_key = (text.casefold(), tuple(links))
        if block_key in block_seen:
            continue
        block_seen.add(block_key)
        role_parts = [p for p in parts if ROLE_RE.search(p)]
        if not role_parts:
            continue
        role = max(role_parts, key=len)
        # A name must be an explicit short text node, not a role, heading, or email.
        candidates = [
            p for p in parts
            if 1 <= len(p.split()) <= 5
            and not ROLE_RE.search(p)
            and p not in role_parts
            and "@" not in p
            and re.fullmatch(r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ.'-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ.'-]*){0,2}", p)
        ]
        if not candidates:
            continue
        name = candidates[0].strip("-:|")
        # A few official team pages publish a single-name identity (for
        # example ``Kim``). It is accepted only as an explicitly capitalized
        # text node paired with a role; no surname is inferred.
        if not re.fullmatch(r"[\wÀ-ÿ.'-]+(?:\s+[\wÀ-ÿ.'-]+){0,4}", name):
            continue
        linkedin = next((x for x in links if "linkedin.com/in/" in x), None)
        email = next((x[7:] for x in links if x.startswith("mailto:")), None)
        key = (name.casefold(), role.casefold())
        occurrences[key] = occurrences.get(key, 0) + 1
        person_id = _person_id(company=company, name=name, role=role, source_url=source_url,
                               linkedin_url=linkedin, email=email,
                               occurrence=occurrences[key])
        if person_id in seen:
            continue
        seen.add(person_id)
        contacts.append(Contact(
            person_id=person_id, name=name, company=company, role=role,
            country=country, linkedin_url=linkedin, email_public=email,
            primary_source_url=source_url, category="company_page",
            research_sources=[source_url], verified_context=f"Explicitly listed as {role} on company page.",
            research_confidence="medium", status="discovered",
        ))
    return DiscoveryResult(contacts, source_url, observed)


def fetch_team_page(url: str, *, timeout: float = 10, retries: int = 2,
                    min_interval: float = 0.5, cache: dict[str, tuple[float, str]] | None = None) -> str:
    """Fetch a public page with bounded retry and in-memory TTL cache."""
    cache = cache if cache is not None else {}
    now = time.monotonic()
    cached = cache.get(url)
    if cached and now - cached[0] < 3600:
        return cached[1]
    time.sleep(max(0, min_interval))
    request = Request(url, headers={"User-Agent": "CareerHunter/1.0 (+public-research)"})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                html = response.read(2_000_000).decode("utf-8", errors="replace")
            cache[url] = (time.monotonic(), html)
            return html
        except Exception as exc:  # network failures are reported to caller
            last = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"public source unavailable: {url}") from last
