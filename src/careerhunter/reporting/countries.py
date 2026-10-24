"""Four-country aggregation for daily reports.

The aggregation is deliberately conservative: a job may be shown under more
than one country, while ``unique_jobs`` keeps the global total deduplicated.
Source health is supplied by the collector and never inferred from job rows.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from careerhunter.country_rules import assess_country

COUNTRIES = ("United States", "Australia", "United Kingdom", "Türkiye")
ALIASES = {
    "United States": ("usa", "united states", "u.s.", "u.s.a.", "america", "us"),
    "Australia": ("australia", "aus"),
    "United Kingdom": ("gb", "uk", "united kingdom", "england", "scotland", "wales", "britain"),
    "Türkiye": ("turkey", "türkiye", "turkiye", "türkiye"),
}

# Explicit city/state evidence is useful when ATS payloads omit the country.
CITY_COUNTRY = {
    "new york": "United States", "san francisco": "United States", "seattle": "United States",
    "boston": "United States", "austin": "United States", "chicago": "United States",
    "sydney": "Australia", "melbourne": "Australia", "brisbane": "Australia", "perth": "Australia",
    "london": "United Kingdom", "manchester": "United Kingdom", "edinburgh": "United Kingdom",
    "istanbul": "Türkiye", "ankara": "Türkiye", "izmir": "Türkiye",
}


def classify_job_countries(job: Any) -> set[str]:
    """Return countries supported by explicit location/application evidence.

    ``worldwide``, ``global`` and bare ``remote`` intentionally produce no
    country assignment.  A job can belong to multiple countries when the
    source explicitly lists each one; this is separate from eligibility.
    """
    location = str(getattr(job, "location", "") or "")
    description = str(getattr(job, "description", "") or "")
    loc = location.lower()
    body = description.lower()
    text = f"{loc} {body}"
    if not text.strip() or re.search(r"\b(worldwide|global|anywhere|work from anywhere)\b", loc) and not re.search(
        r"\b(?:us|usa|united states|uk|gb|australia|turkey|türkiye)\b", text
    ):
        return set()
    result: set[str] = set()
    for country, tokens in ALIASES.items():
        for token in tokens:
            pattern = rf"(?<![a-z]){re.escape(token)}(?![a-z])"
            if re.search(pattern, text):
                result.add(country)
                break
    for city, country in CITY_COUNTRY.items():
        if re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", loc):
            result.add(country)
    return result


def _country_for_job(job: Any, country: str) -> bool:
    return country in classify_job_countries(job)


def aggregate_country_report(
    jobs: Iterable[Any],
    *,
    source_results: dict[str, dict[str, Any]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    rows = list(jobs)
    source_results = source_results or {}
    assigned = {j.job_id for country in COUNTRIES for j in rows if _country_for_job(j, country)}
    out: dict[str, Any] = {
        "countries": {},
        "unique_jobs": len({j.job_id for j in rows}),
        "unknown_jobs": len({j.job_id for j in rows} - assigned),
    }
    for country in COUNTRIES:
        selected = [j for j in rows if _country_for_job(j, country)]
        assessments = [assess_country(f"{j.location}\n{j.description}", country, source_url=str(j.source_url)) for j in selected]
        fit = [j for j in selected if (j.match_score or 0) >= 65]
        turkey_open = [a for a in assessments if country == "Türkiye" and a.status == "eligible"]
        sponsorship = [a for a in assessments if any("sponsor" in e.lower() or "visa" in e.lower() for e in a.evidence)]
        src = source_results.get(country, {})
        top = sorted(fit, key=lambda j: j.match_score or 0, reverse=True)[:limit]
        out["countries"][country] = {
            "attempted_sources": int(src.get("attempted", src.get("attempted_sources", 0))),
            "successful_sources": int(src.get("successful", src.get("successful_sources", 0))),
            "active_jobs": len(selected),
            "unknown_jobs": 0,
            "new_jobs": int(src.get("new_jobs", 0)),
            "profile_fit_jobs": len(fit),
            "turkey_eligible_jobs": len(turkey_open),
            "sponsorship_jobs": len(sponsorship),
            "source_errors": list(src.get("errors", src.get("source_errors", []))),
            "opportunities": [{"title": j.title, "company": j.company, "location": j.location,
                               "score": j.match_score, "reason": j.score_reasons,
                               "constraints": j.gaps, "url": str(j.job_url)} for j in top],
        }
    return out


def render_country_report(report: dict[str, Any]) -> str:
    lines = ["## Dört ülke günlük özeti", "", "| Ülke | Başarılı kaynak | İlan | Yeni | Profile uygun | TR uygun | Sponsorluk | Kaynak hatası |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for country, row in report.get("countries", {}).items():
        lines.append(f"| {country} | {row['successful_sources']}/{row['attempted_sources']} | {row['active_jobs']} | {row['new_jobs']} | {row['profile_fit_jobs']} | {row['turkey_eligible_jobs']} | {row['sponsorship_jobs']} | {len(row['source_errors'])} |")
        for opp in row["opportunities"]:
            lines.append(f"  - **{opp['company']} — {opp['title']}** ({opp['score']}/100): {opp['url']}")
        for error in row["source_errors"]:
            lines.append(f"  - Kaynak hatası: {error}")
    return "\n".join(lines) + "\n"
