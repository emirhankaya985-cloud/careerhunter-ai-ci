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
    if eligibility == "ineligible":
        return False, "not_eligible"
    direct_role = bool(_TARGET.search(title))
    broad_software = bool(_GENERIC_SOFTWARE.search(title))
    if not direct_role and not broad_software:
        return False, "not_target_role"
    if broad_software and not direct_role:
        tech_context = skills + " " + description
        if not _STACK.search(tech_context) and not _INTERNSHIP.search(title):
            return False, "generic_software_no_target_stack"
    if (not location or location.lower() == "unknown") and eligibility != "eligible":
        return False, "location_unknown"
    if _RESTRICTED_REMOTE.search(location) and eligibility != "eligible":
        return False, "region_restricted"
    if eligibility != "eligible":
        has_target_location = bool(_TARGET_LOCATION.search(location))
        generic_remote = bool(_OPEN_REMOTE.search(location))
        # "Remote, Taiwan" is not globally remote: explicit outside-country
        # location cancels a generic remote label unless eligibility is proven.
        chunks = re.split(r"[,;/|]", location.casefold())
        remote_only = all(
            bool(_OPEN_REMOTE.search(c)) or not c.strip()
            for c in chunks
        )
        if not has_target_location and not (generic_remote and remote_only):
            return False, "outside_target_geography"
    return True, "potential_match"
