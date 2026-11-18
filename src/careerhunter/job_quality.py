"""Conservative Telegram delivery gate for an early-career Python/AI applicant.

Collection is broad; delivery is intentionally narrow. This module operates
on public job metadata only. A score alone never guarantees career relevance,
seniority fit, or permission to work from Türkiye.
"""
from __future__ import annotations

import re
from collections.abc import Mapping


# Leadership, managerial, sales, and non-entry-level roles are not job alerts.
_BLOCKED = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head|vp|vice "
    r"president|chief|architect|sales|marketing|recruiter|recruiting|"
    r"account executive|account manager|product owner|operations program)\b",
    re.IGNORECASE,
)
_TARGET = re.compile(
    r"\b(?:python|back[\s-]?end|server[\s-]?side|machine learning|"
    r"deep learning|ml engineer|ml intern|ai engineer|ai developer|"
    r"ai intern|artificial intelligence|computer vision|"
    r"automation|qa automation|rpa developer|"
    r"data science intern|data scientist intern|"
    r"data engineer intern)\b",
    re.IGNORECASE,
)
_GENERIC_SOFTWARE = re.compile(
    r"\b(?:software engineer|software developer|software engineering "
    r"intern|swe intern|full[\s-]?stack developer|full[\s-]?stack engineer)\b",
    re.IGNORECASE,
)
_STACK = re.compile(
    r"\b(?:python|fastapi|django|flask|pytorch|tensorflow|"
    r"machine learning|backend|back-end|postgresql|llm|"
    r"data pipeline|rest api)\b",
    re.IGNORECASE,
)
_INTERNSHIP = re.compile(
    r"\b(?:intern|internship|new grad|graduate|entry[\s-]?level|junior|"
    r"associate|trainee)\b",
    re.IGNORECASE,
)
_TARGET_LOCATION = re.compile(
    r"\b(?:t[uü]rkiye|turkey|istanbul|ankara|izmir|"
    r"united states|usa|u\.s\.|us|new york|san francisco|"
    r"seattle|boston|austin|chicago|california|"
    r"united kingdom|uk|england|london|manchester|"
    r"australia|sydney|melbourne|brisbane|perth)\b",
    re.IGNORECASE,
)
_OPEN_REMOTE = re.compile(
    r"\b(?:remote|worldwide|anywhere|global)\b", re.IGNORECASE
)
_RESTRICTED_REMOTE = re.compile(
    r"\b(?:us[- ]only|usa[- ]only|uk[- ]only|eu[- ]only|"
    r"remote within (?:the )?(?:us|uk|eu)|"
    r"remote[- /]+(?:us|usa|uk|eu)|"
    r"must (?:reside|be based) in (?:the )?(?:us|uk|eu))\b",
    re.IGNORECASE,
)


def evaluate(job: Mapping[str, object], *, minimum: int = 60) -> tuple[bool, str]:
    """Returns (eligible_for_alert, reason). Does not mutate the job."""
    title = str(job.get("title") or "").strip()
    level = str(job.get("level") or "unknown")
    location = str(job.get("location") or "").strip()
    eligibility = str(job.get("eligibility") or "needs_review")
    description = str(job.get("description") or "")
    skills = " ".join(str(s) for s in job.get("skills", []) or [])
    try:
        score = int(job.get("score") or 0)
    except (TypeError, ValueError):
        return False, "invalid_score"
    if not title or score < minimum:
        return False, "low_score"
    if level == "senior" or _BLOCKED.search(title):
        return False, "senior_or_non_engineering"
    is_remote = str(job.get("remote_type") or "").casefold() == "remote" or bool(_OPEN_REMOTE.search(location)) or bool(
        re.search(r"\b(?:remote|work from home|distributed)\b", description, re.IGNORECASE)
    )
    if not is_remote:
        return False, "not_remote"
    direct_role = bool(_TARGET.search(title))
    broad_software = bool(_GENERIC_SOFTWARE.search(title))
    if not direct_role and not broad_software:
        return False, "not_target_role"
    if broad_software and not direct_role:
        tech_context = skills + " " + description
        if not _STACK.search(tech_context) and not _INTERNSHIP.search(title):
            return False, "generic_software_no_target_stack"
    # Report the region and work authorization as context; country restrictions
    # must not hide relevant remote listings from an all-country search.
    return True, "potential_match"


def is_remote_fit(job: object, *, minimum: int = 75) -> bool:
    """Strict candidate gate for remote shortlist/archive and alerts.

    Remote postings are collected across all countries. Work eligibility is
    reported separately and must not silently hide an otherwise relevant job.
    """
    return (
        getattr(job, "remote_type", None) == "remote"
        and getattr(job, "verification_status", None)
        in {"ATS_LISTED", "EMPLOYER_CONFIRMED"}
        and getattr(job, "status", None) != "closed"
        and getattr(job, "experience_level", None) != "senior"
        and int(getattr(job, "match_score", 0) or 0) >= minimum
    )
