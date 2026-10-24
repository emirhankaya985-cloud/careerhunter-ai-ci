from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import re

OFFICIAL_SOURCES = {
    "United States": "https://www.uscis.gov/working-in-the-united-states",
    "United Kingdom": "https://www.gov.uk/skilled-worker-visa",
    "Türkiye": "https://www.csgb.gov.tr/en/frequently-asked-questions/directorate-general-of-international-labour-force/work-permit/",
    "Australia": "https://immi.homeaffairs.gov.au/visas/working-in-australia/temporary-work-visas",
}


@dataclass(frozen=True)
class CountryAssessment:
    country: str
    status: str
    evidence: list[str]
    reason: str = ""
    evidence_url: str | None = None
    observed_on: str = field(default_factory=lambda: date.today().isoformat())
    confidence: str = "low"
    missing_fields: tuple[str, ...] = ()
    dimensions: dict[str, str] = field(default_factory=dict)


def _found(text, terms):
    return [x for x in terms if re.search(rf"(?<!\w){re.escape(x)}(?!\w)", text)]


def assess_country(
    text: str, country: str, *, source_url: str | None = None, observed_on: str | None = None
) -> CountryAssessment:
    t = (text or "").lower()
    loc = {
        "United States": ["remote - us", "us remote", "united states", "usa", "u.s."],
        "United Kingdom": ["remote - uk", "uk remote", "united kingdom", "london", "england"],
        "Türkiye": [
            "turkey",
            "türkiye",
            "istanbul",
            "ankara",
            "remote from turkey",
            "türkiye eligible",
        ],
        "Australia": ["remote - australia", "australia remote", "australia", "sydney", "melbourne"],
    }.get(country, [])
    pos = [
        "sponsorship",
        "visa sponsorship",
        "h1b",
        "opt",
        "stem opt",
        "skilled worker",
        "certificate of sponsorship",
        "subclass 482",
        "skills in demand",
        "work permit",
        "çalışma izni",
        "international contractor",
        "contractor",
        "eor",
        "employer of record",
    ]
    neg = [
        "no sponsorship",
        "without sponsorship",
        "us only",
        "u.s. only",
        "uk residents only",
        "must have existing work rights",
        "existing work authorization required",
        "australia residents only",
        "local candidates only",
        "not open to international applicants",
    ]
    lh, ph, nh = (_found(t, x) for x in (loc, pos, neg))
    ev = lh + ph + nh
    remote = bool(re.search(r"\bremote\b|work from home|distributed", t))
    # Generic "worldwide" language is not proof that a Türkiye-based worker
    # can be hired; require an explicit Türkiye/remote-from-Türkiye statement.
    intl = bool(re.search(r"remote from turkey|work from turkey|türkiye'den|türkiye eligible", t))
    emp = (
        "employee"
        if re.search(r"\bemployee\b|full[- ]time employment", t)
        else (
            "contractor"
            if "contractor" in t
            else ("eor" if re.search(r"\beor\b|employer of record", t) else "unknown")
        )
    )
    relocation = (
        "required"
        if re.search(r"relocat|must be based|on[- ]site|hybrid", t)
        else ("not_required" if remote and intl else "unknown")
    )
    timezone = (
        "specified"
        if re.search(r"timezone|time zone|utc[+-]|eastern time|gmt|cet|aest", t)
        else "unknown"
    )
    salary = (
        "disclosed"
        if re.search(r"[$€£]|\busd\b|\beur\b|\bgbp\b|\baud\b|salary|compensation", t)
        else "unknown"
    )
    status = (
        "not_eligible_without_rights_evidence"
        if nh
        else (
            "sponsorship_or_rights_evidence"
            if ph and (lh or intl)
            else (
                "eligible"
                if country == "Türkiye" and (lh or intl)
                else ("location_match_needs_rights_check" if lh else "unknown")
            )
        )
    )
    miss = []
    if not lh and not intl:
        miss.append("physical_location_or_remote_scope")
    if not ph and country != "Türkiye":
        miss.append("work_rights_or_sponsorship")
    if emp == "unknown":
        miss.append("employment_model")
    if timezone == "unknown":
        miss.append("timezone_expectation")
    if salary == "unknown":
        miss.append("salary_currency_and_period")
    dims = {
        "physical_location": "mentioned" if lh else "unknown",
        "remote_from_turkey": "explicit" if intl else ("remote_only" if remote else "unknown"),
        "work_rights": "negative" if nh else ("evidence" if ph else "unknown"),
        "employment_model": emp,
        "relocation": relocation,
        "timezone": timezone,
        "salary": salary,
    }
    conf = "high" if nh or (lh and ph) else ("medium" if lh or intl else "low")
    return CountryAssessment(
        country,
        status,
        ev,
        "; ".join(ev) or "No explicit country or work-rights evidence found.",
        source_url or OFFICIAL_SOURCES.get(country),
        observed_on or date.today().isoformat(),
        conf,
        tuple(miss),
        dims,
    )
