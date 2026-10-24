"""Repeatable public-source verification (no contact is ever sent).

Example::
    python -m careerhunter.live_verify --db proof.sqlite --output proof.json

The default Dropbox URLs are public examples; the run stores the fetched
observation, bounded evidence text, job, and explicitly discovered employees
in the supplied *isolated* SQLite database.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from careerhunter.database import DatabaseRepository, _sqlite_url
from careerhunter.intelligence.people import fetch_team_page, parse_team_page
from careerhunter.models import Job
from careerhunter.agents.hook_writer import prepare_drafts
from careerhunter.country_rules import assess_country
from careerhunter.llm.fallback import critique_message
from careerhunter.models import Opportunity
from careerhunter.intelligence.company import build_company_signals
from careerhunter.dashboard import snapshot, _html_page

DEFAULT_JOB = "https://www.dropbox.jobs/en/jobs/8280093/senior-corporate-enterprise-platform-engineer-windows/"
DEFAULT_TEAM = "https://www.dropbox.jobs/en/teams/engineering/"


def fetch_public(url: str, *, timeout: float = 15) -> str:
    request = Request(url, headers={"User-Agent": "CareerHunter/1.0 (+public-research)"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(2_000_000)
        if response.headers.get("Content-Encoding") == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return payload.decode("utf-8", errors="replace")


def fetch_json(url: str, *, timeout: float = 15) -> dict:
    """Fetch a public ATS JSON response without requiring browser markup."""
    request = Request(url, headers={"User-Agent": "CareerHunter/1.0 (+public-research)",
                                    "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(2_000_000)
    try:
        value = json.loads(payload.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("ATS response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ATS response must be a JSON object")
    return value


def _source_ats_job(payload: dict, url: str) -> dict[str, str]:
    """Normalize a Greenhouse job API payload into the live proof schema.

    Greenhouse's public endpoint deliberately has no JSON-LD.  Company is
    accepted only when the API supplies it (or as an explicit ``company``
    field in a controlled fixture); it is never inferred from a hostname.
    """
    title = str(payload.get("title") or "").strip()
    job_id = str(payload.get("id") or payload.get("job_id") or "").strip()
    description = _text(str(payload.get("content") or payload.get("description") or ""))
    loc = payload.get("location")
    location = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
    org = payload.get("company") or payload.get("hiringOrganization")
    company = org.get("name", "") if isinstance(org, dict) else str(org or "")
    absolute_url = str(payload.get("absolute_url") or payload.get("url") or url).strip()
    if not title or not job_id or not company or not location or len(description) < 40:
        raise RuntimeError("ATS payload lacks required id, title, company, location, or description")
    return {"job_id": job_id, "title": title, "company": company,
            "location": location, "description": description[:12000],
            "job_url": absolute_url}


def _is_ats_api(url: str) -> bool:
    lowered = url.lower()
    return "boards-api.greenhouse.io/" in lowered or "api.lever.co/" in lowered


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _meta(html: str, name: str) -> str | None:
    match = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)', html, re.I)
    return match.group(1).strip() if match else None


def _source_job(html: str, url: str) -> dict[str, str]:
    """Extract JobPosting JSON-LD fields and reject incomplete job pages."""
    values = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            obj = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        items = obj if isinstance(obj, list) else obj.get("@graph", []) if isinstance(obj, dict) else []
        if isinstance(obj, dict) and obj.get("@type"):
            items = [obj]
        values.extend(x for x in items if isinstance(x, dict) and "JobPosting" in str(x.get("@type")))
    item = values[0] if values else {}
    title = str(item.get("title") or "").strip()
    org = item.get("hiringOrganization") or {}
    raw_company = org.get("name") if isinstance(org, dict) else org
    company = str(raw_company or "").strip()
    loc = item.get("jobLocation") or item.get("applicantLocationRequirements") or ""
    location = json.dumps(loc, ensure_ascii=False) if isinstance(loc, (dict, list)) else str(loc)
    description = _text(str(item.get("description") or html))
    if not title:
        title = next((_text(x) for x in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.I | re.S) if _text(x)), "")
    if not company:
        author = _meta(html, "author") or ""
        title_company = re.search(r"\|\s*([^|]+?)\s+Careers\b", _text(html), re.I)
        company = author.strip() or (title_company.group(1).strip() if title_company else "")
    if not company:
        raise RuntimeError("job page lacks hiringOrganization.name; refusing to infer company from domain")
    identifier = item.get("identifier")
    job_id = identifier.get("value") if isinstance(identifier, dict) else None
    if not job_id:
        path_id = re.sub(r"[^a-zA-Z0-9_-]+", "", url.rsplit("/", 2)[-2] if "/" in url.rstrip("/") else "")
        job_id = path_id or ""
    if not job_id:
        raise RuntimeError("job page lacks a stable identifier")
    if not title or len(description) < 120 or not values:
        raise RuntimeError("job page lacks a validated JobPosting JSON-LD payload")
    if not location:
        raise RuntimeError("job page lacks job location or applicant location requirements")
    return {"job_id": job_id, "title": title, "company": company,
            "location": location or _text(html), "description": description[:12000]}


def run(*, db_path: Path, output: Path, job_url: str = DEFAULT_JOB,
        team_url: str = DEFAULT_TEAM, dashboard_output: Path | None = None) -> dict:
    observed = datetime.now(timezone.utc)
    try:
        if _is_ats_api(job_url):
            fields = _source_ats_job(fetch_json(job_url), job_url)
            source_kind = "greenhouse_api"
        else:
            job_html = fetch_public(job_url)
            page_text = _text(job_html)
            if len(page_text) < 10:
                raise RuntimeError("job source returned no usable text")
            fields = _source_job(job_html, job_url)
            source_kind = "public_job_page"
    except Exception as exc:
        proof = {"status": "error", "observed_at": observed.isoformat(),
                 "failed_stage": "job_source", "sources": {"job_url": job_url, "team_url": team_url},
                 "errors": [str(exc)],
                 "safety": {"automatic_send": False, "messages_sent": 0}}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        return proof
    try:
        team_html = fetch_team_page(team_url, retries=2, min_interval=0.2)
    except Exception as exc:
        proof = {"status": "error", "observed_at": observed.isoformat(),
                 "failed_stage": "team_source", "sources": {"job_url": job_url, "team_url": team_url},
                 "errors": [f"team source: {exc}"],
                 "job": {"url": job_url, "title": fields["title"], "company": fields["company"]},
                 "safety": {"automatic_send": False, "messages_sent": 0}}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        return proof
    evidence = fields["description"]
    job = Job(job_id=fields["job_id"], source="greenhouse", company=fields["company"],
              title=fields["title"], location=fields["location"], description=evidence,
              remote_type="remote" if "remote" in (fields["location"] + evidence).lower() else "unknown",
              job_url=fields.get("job_url", job_url), source_url=job_url)
    repo = DatabaseRepository(_sqlite_url(db_path))
    new_jobs = repo.upsert_jobs([job])
    discovery = parse_team_page(team_html, source_url=team_url, company=fields["company"], country="USA")
    if discovery.status != "ok" or not discovery.contacts:
        raise RuntimeError(f"people source yielded no explicit contacts: {team_url}")
    country_assessments = {country: asdict(assess_country(f"{job.location}\n{job.description}", country, source_url=job_url))
                           for country in ("United States", "United Kingdom", "Türkiye", "Australia")}
    signals = build_company_signals([job])
    for signal in signals:
        repo.upsert_company_signal(signal)
    opportunity = Opportunity(opportunity_id=f"live-{job.job_id}", title=job.title,
                              company=job.company, job_id=job.job_id, job_url=job.job_url,
                              status="reviewed", fit_score=job.match_score)
    repo.upsert_opportunity(opportunity)
    critics = []
    for contact in discovery.contacts:
        contact.notes = "company_employee; hiring_manager_unknown"
        contact.verified_context = f"{contact.verified_context} Evidence page fetched at {observed.isoformat()}."
        contact.evidence_text = contact.verified_context
        contact.observed_at = observed
        contact = prepare_drafts(contact)
        critique = critique_message(contact.message_variant_a, verified_context=contact.verified_context,
                                    source_count=len(contact.research_sources))
        critics.append({"person_id": contact.person_id, **critique})
        repo.upsert_contact(contact)
    contacts = [c.model_dump(mode="json") for c in discovery.contacts]
    if dashboard_output:
        dashboard_output.parent.mkdir(parents=True, exist_ok=True)
        dashboard_output.write_text(_html_page(snapshot(repo)), encoding="utf-8")
    proof = {"status": "ok", "observed_at": observed.isoformat(), "job": {
        "url": fields.get("job_url", job_url), "title": fields["title"], "evidence_text": evidence,
        "new_records": new_jobs, "source_kind": source_kind},
        "country_assessments": country_assessments,
        "company_signals": len(signals), "opportunity_id": opportunity.opportunity_id,
        "critics": critics,
        "dashboard": str(dashboard_output.resolve()) if dashboard_output else None,
        "people_source": {"url": team_url, "observed_at": discovery.observed_at.isoformat(),
                           "contacts": contacts, "relationship": "company_employee",
                           "hiring_manager": "unknown_not_inferred"},
        "safety": {"automatic_send": False, "messages_sent": 0,
                   "database": str(db_path.resolve())}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("outputs/live-proof.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("outputs/live-proof.json"))
    parser.add_argument("--job-url", default=DEFAULT_JOB)
    parser.add_argument("--team-url", default=DEFAULT_TEAM)
    parser.add_argument("--dashboard-output", type=Path, default=None)
    args = parser.parse_args()
    proof = run(db_path=args.db, output=args.output, job_url=args.job_url, team_url=args.team_url, dashboard_output=args.dashboard_output)
    print(json.dumps({"status": proof["status"],
                      "contacts": len(proof.get("people_source", {}).get("contacts", [])),
                      "new_jobs": proof.get("job", {}).get("new_records", 0),
                      "output": str(args.output)}, ensure_ascii=False))
    if proof["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
