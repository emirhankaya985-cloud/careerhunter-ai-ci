"""Read-only local dashboard data API and export helpers.

The module deliberately uses the existing repository read methods and never
creates demo records or mutates CRM state.  It is suitable for a small local
UI (or a scheduled export) without adding a web-framework dependency.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .database import DatabaseRepository, database_url
from .country_rules import assess_country
from .llm.fallback import critique_message


@dataclass(frozen=True)
class DashboardFilters:
    country: str | None = None
    company: str | None = None
    role: str | None = None
    eligibility: str | None = None
    remote: str | None = None
    sponsorship: str | None = None
    crm_status: str | None = None


def _country(job: Any) -> str:
    text = f"{job.location} {job.description}".lower()
    for name, terms in (("usa", ("united states", "u.s.", " usa", "new york", "california")),
                        ("uk", ("united kingdom", "uk", "london", "england")),
                        ("australia", ("australia", "sydney", "melbourne")),
                        ("turkey", ("turkey", "türkiye", "istanbul", "ankara"))):
        if any(term in text for term in terms):
            return name
    return "unknown"


def _sponsorship(job: Any) -> str:
    text = job.description.lower()
    if any(term in text for term in ("visa sponsorship", "sponsor", "h-1b", "skilled worker", "subclass 482")):
        return "yes"
    return "no"


def _matches(job: Any, f: DashboardFilters) -> bool:
    checks = ((f.country, _country(job)), (f.company, job.company),
              (f.eligibility, job.eligibility_status), (f.remote, job.remote_type),
              (f.sponsorship, _sponsorship(job)))
    for expected, actual in checks:
        if expected and expected.lower() not in str(actual).lower():
            return False
    return not f.role or f.role.lower() in f"{job.title} {job.description}".lower()


def snapshot(repo: DatabaseRepository, filters: DashboardFilters | None = None,
             limit: int = 500) -> dict[str, Any]:
    """Return current jobs and CRM records, filtered without writing data."""
    filters = filters or DashboardFilters()
    jobs = []
    countries = ("United States", "United Kingdom", "Türkiye", "Australia")
    assessments = repo.list_country_assessments(limit=max(limit * 4, 500))
    assessments_by_job: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for assessment in assessments:
        assessments_by_job.setdefault((assessment["source"], assessment["job_id"]), []).append(assessment)
    for job in repo.list_jobs(active_only=False, limit=limit):
        if not _matches(job, filters):
            continue
        row = job.model_dump(mode="json")
        persisted = {a["country"]: json.loads(a["payload"])
                     for a in assessments_by_job.get((job.source, job.job_id), [])}
        row["country_assessments"] = persisted or {country: asdict(assess_country(
            f"{job.location}\n{job.description}", country, source_url=str(job.job_url)))
            for country in countries}
        jobs.append(row)
    contacts = []
    critics = {row["person_id"]: row for row in repo.list_critic_results(limit=max(limit, 500))}
    for contact in repo.list_contacts(limit=limit):
        row = contact.model_dump(mode="json")
        saved = critics.get(contact.person_id)
        row["critic"] = json.loads(saved["payload"]) if saved else critique_message(contact.message_variant_a,
            verified_context=contact.verified_context,
            source_count=len(contact.research_sources))
        contacts.append(row)
    signals = [s.model_dump(mode="json") for s in repo.list_company_signals(limit=limit)]
    opportunities = [o.model_dump(mode="json") for o in repo.list_opportunities(limit=limit)
                     if not filters.crm_status or o.status == filters.crm_status]
    followups = [f.model_dump(mode="json") for f in repo.list_followups(limit=limit)]
    snapshot_at = datetime.now(timezone.utc).isoformat()
    snapshot_id = hashlib.sha256(f"{snapshot_at}:{len(jobs)}:{len(contacts)}".encode()).hexdigest()[:16]
    aggregates = repo.aggregate_job_counts(datetime.now(timezone.utc) - timedelta(hours=24))
    country_aggregates = repo.aggregate_country_counts(datetime.now(timezone.utc) - timedelta(hours=24))
    aggregates["countries"] = country_aggregates
    return {"filters": asdict(filters), "snapshot_at": snapshot_at, "snapshot_id": snapshot_id,
            "aggregates": aggregates,
            "jobs": jobs, "contacts": contacts,
            "opportunities": opportunities, "followups": followups,
            "company_signals": signals,
            "latest_run": repo.latest_run()}


def export_snapshot(data: dict[str, Any], path: str | Path, fmt: str = "json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        with target.open("w", newline="", encoding="utf-8") as handle:
            rows = data.get("jobs", [])
            writer = csv.DictWriter(handle, fieldnames=["job_id", "company", "title", "location",
                                                        "remote_type", "eligibility_status", "job_url"])
            writer.writeheader()
            writer.writerows({k: row.get(k, "") for k in writer.fieldnames} for row in rows)
    else:
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def _html_page(data: dict[str, Any]) -> str:
    """Render a deliberately dependency-free, read-only dashboard."""
    jobs, contacts, opps, followups = data["jobs"], data["contacts"], data["opportunities"], data["followups"]
    signals = data.get("company_signals", [])
    f = data["filters"]
    def cell(value: Any) -> str:
        return escape(str(value or ""))
    def assessments(j: dict[str, Any]) -> str:
        return "".join(f'<details><summary>{cell(country)}: {cell(a.get("status"))} ({cell(a.get("confidence"))})</summary>'
                       f'<b>Evidence:</b> {cell(", ".join(a.get("evidence", [])) or "none")}<br>'
                       f'<b>Missing:</b> {cell(", ".join(a.get("missing_fields", [])) or "none")}<br>'
                       f'<b>Dimensions:</b> {cell(json.dumps(a.get("dimensions", {}), ensure_ascii=False))}<br>'
                       f'<a href="{cell(a.get("evidence_url"))}" target="_blank" rel="noreferrer">assessment source</a></details>'
                       for country, a in j.get("country_assessments", {}).items())
    job_rows = "".join(
        f'<tr><td>{cell(j["company"])}</td><td>{cell(j["title"])}</td><td>{cell(j["location"])}</td>'
        f'<td>{cell(j.get("remote_type"))}</td><td>{cell(j.get("eligibility_status"))}</td>'
        f'<td><a href="{cell(j["job_url"])}" target="_blank" rel="noreferrer">evidence</a></td><td>{assessments(j)}</td></tr>' for j in jobs)
    def source_links(c: dict[str, Any]) -> str:
        source = f'<a href="{cell(c.get("primary_source_url"))}" target="_blank" rel="noreferrer">source</a>'
        proof = c.get("proof_artifact_url")
        if proof:
            source += f' · <a href="{cell(proof)}" target="_blank" rel="noreferrer">proof</a>'
        return source
    contact_rows = "".join(
        f'<tr><td>{cell(c["name"])}</td><td>{cell(c["company"])}</td><td>{cell(c["role"])}</td>'
        f'<td>{cell(c.get("status"))}</td><td>{cell(c.get("email_public"))}</td>'
        f'<td>{cell(c.get("relationship_type"))}</td><td>{"unknown" if c.get("hiring_manager_unknown", True) else "observed"}</td>'
        f'<td>{cell(c.get("observed_at"))}</td><td>{cell(c.get("evidence_text") or c.get("verified_context"))}</td>'
        f'<td>{source_links(c)}</td></tr>' for c in contacts)
    opp_rows = "".join(f'<tr><td>{cell(o["title"])}</td><td>{cell(o["company"])}</td><td>{cell(o["status"])}</td><td>{cell(o.get("fit_score"))}</td><td>{cell(o.get("notes"))}</td></tr>' for o in opps)
    signal_rows = "".join(f'<tr><td>{cell(s["company"])}</td><td>{cell(s["signal_type"])}</td><td>{cell(s["claim"])}</td><td>{cell(s.get("confidence"))}</td><td>{cell(", ".join(s.get("evidence_urls", [])))}</td></tr>' for s in signals)
    critic_rows = "".join(f'<tr><td>{cell(c["name"])}</td><td>{"PASS" if c.get("critic", {}).get("ok") else "REVIEW"}</td><td>{cell(", ".join(c.get("critic", {}).get("issues", [])) or "none")}</td></tr>' for c in contacts)
    follow_rows = "".join(f'<tr><td>{cell(x.get("due_at"))}</td><td>{cell(x.get("person_id"))}</td><td>{cell(x.get("note"))}</td><td>{cell(x.get("status"))}</td></tr>' for x in followups)
    draft_rows = "".join(f'<tr><td>{cell(c["name"])}</td><td>{cell(c.get("message_variant_a"))}</td><td>{cell(c.get("message_variant_a_tr"))}</td></tr>' for c in contacts if c.get("message_variant_a") or c.get("message_variant_a_tr"))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CareerHunter</title>
<style>body{{font:14px system-ui;margin:0;background:#f5f7fb;color:#172033}}header{{background:#192a56;color:white;padding:18px 5vw}}main{{max-width:1400px;margin:22px auto;padding:0 18px}}nav a{{color:white;margin-right:18px}}.cards{{display:flex;gap:10px;flex-wrap:wrap}}.card{{background:white;padding:14px 20px;border-radius:8px;box-shadow:0 1px 4px #ccd}}section{{background:white;margin:18px 0;padding:16px;border-radius:8px;overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #e3e8f0;text-align:left;vertical-align:top}}th{{background:#eef2f8}}input,button{{padding:7px;margin:3px}}.draft{{max-width:500px;white-space:pre-wrap}}</style></head>
<body><header><h1>CareerHunter AI</h1><nav><a href="/">Overview</a><a href="#jobs">Jobs</a><a href="#people">People</a><a href="#crm">CRM</a><a href="#drafts">Drafts</a><a href="#followups">Follow-ups</a></nav></header><main>
<form method="get"><input name="country" placeholder="country" value="{cell(f.get("country"))}"><input name="role" placeholder="role" value="{cell(f.get("role"))}"><input name="company" placeholder="company" value="{cell(f.get("company"))}"><input name="eligibility" placeholder="eligibility" value="{cell(f.get("eligibility"))}"><button>Filter</button></form>
<div class="cards"><div class="card"><b>{len(jobs)}</b><br>jobs</div><div class="card"><b>{len(contacts)}</b><br>people</div><div class="card"><b>{len(opps)}</b><br>CRM opportunities</div><div class="card"><b>{len(followups)}</b><br>follow-ups</div></div>
<section id="jobs"><h2>Jobs and evidence</h2><table><tr><th>Company</th><th>Role</th><th>Location</th><th>Remote</th><th>Eligibility</th><th>Source</th><th>Four-country assessment, evidence and missing fields</th></tr>{job_rows}</table></section>
<section id="people"><h2>People and source evidence</h2><p>Observed facts are shown with their capture time. A person is not treated as a hiring manager unless the source explicitly proves that relationship.</p><table><tr><th>Name</th><th>Company</th><th>Role</th><th>Status</th><th>Public email</th><th>Relationship</th><th>Hiring manager</th><th>Observed at</th><th>Evidence text</th><th>Source / proof</th></tr>{contact_rows}</table></section>
<section id="crm"><h2>CRM and company details</h2><table><tr><th>Opportunity</th><th>Company</th><th>Status</th><th>Fit</th><th>Notes</th></tr>{opp_rows}</table><h3>Company signals and evidence</h3><table><tr><th>Company</th><th>Signal</th><th>Claim</th><th>Confidence</th><th>Evidence URLs</th></tr>{signal_rows}</table></section>
<section id="critic"><h2>Message critic findings</h2><table><tr><th>Person</th><th>Result</th><th>Findings</th></tr>{critic_rows}</table></section>
<section id="drafts"><h2>Message drafts (manual sending only)</h2><table><tr><th>Person</th><th>English draft</th><th>Turkish draft</th></tr>{draft_rows}</table></section>
<section id="followups"><h2>Follow-ups</h2><table><tr><th>Due</th><th>Person</th><th>Note</th><th>Status</th></tr>{follow_rows}</table></section>
</main><script>const payload={json.dumps(data, ensure_ascii=False, default=str)}; for (const [name,obj] of [['careerhunter.json',payload],['careerhunter.csv',payload.jobs||[]]]) {{ const a=document.createElement('a'); a.download=name; a.textContent='Download '+name; a.href='data:application/'+(name.endsWith('csv')?'csv':'json')+','+encodeURIComponent(name.endsWith('csv')?JSON.stringify(obj):JSON.stringify(obj)); a.style='margin:8px'; document.body.append(a); }}</script></body></html>'''


def serve(repo: DatabaseRepository, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the read-only browser UI; binds localhost by default."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            filters = DashboardFilters(query.get("country"), query.get("company"), query.get("role"), query.get("eligibility"), query.get("remote"), query.get("sponsorship"), query.get("crm_status"))
            body = _html_page(snapshot(repo, filters)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_: Any) -> None: return
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CareerHunter read-only dashboard export")
    parser.add_argument("--output", type=Path, default=Path("reports/dashboard.json"))
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--country")
    parser.add_argument("--company")
    parser.add_argument("--role")
    parser.add_argument("--eligibility")
    parser.add_argument("--remote")
    parser.add_argument("--sponsorship")
    parser.add_argument("--crm-status")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--serve", action="store_true", help="serve the read-only browser dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    repo = DatabaseRepository(database_url(Path("data/careerhunter.db")))
    if args.serve:
        serve(repo, args.host, args.port)
        return 0
    filters = DashboardFilters(args.country, args.company, args.role, args.eligibility,
                               args.remote, args.sponsorship, args.crm_status)
    export_snapshot(snapshot(repo, filters, limit=args.limit), args.output, args.format)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
