"""Explainable, evidence-bound, private-profile job matching.

This baseline requires no external LLM key. Generative AI enrichment is a
separate, optional second pass and is never represented as part of this score.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from careerhunter.models import Job
from careerhunter.country_rules import assess_country


SKILL_ALIASES = {
    "Python": ("python",),
    "SQL": ("sql", "postgresql", "mysql", "sqlalchemy"),
    "PostgreSQL": ("postgresql", "postgres",),
    "FastAPI": ("fastapi",),
    "PyTorch": ("pytorch", "torch"),
    "Machine Learning": ("machine learning", "ml engineer", "mlops"),
    "Computer Vision": ("computer vision", "image processing", "object detection"),
    "YOLO": ("yolo", "ultralytics"),
    "OpenCV": ("opencv",),
    "AI Automation": ("ai automation", "workflow automation", "automated workflows"),
    "Docker": ("docker", "containerization"),
    "Playwright": ("playwright", "browser automation"),
    "REST API": ("rest api", "restful", "api development"),
    "RAG": ("retrieval augmented generation", "rag"),
    "JavaScript": ("javascript", "typescript", "node.js"),
    "Data Analysis": ("data analysis", "data analytics", "pandas"),
}
ROLE_FAMILIES = (
    (("python", "backend", "back-end", "software engineer", "software developer"),
     ("Python", "Backend", "Software")),
    (("machine learning", "ml engineer", "ai engineer", "artificial intelligence",
      "computer vision", "deep learning"), ("AI", "Machine Learning", "Computer Vision")),
    (("automation", "qa engineer", "test engineer", "sdet", "rpa"),
     ("Automation", "QA")),
    (("technical support", "technical operations", "support engineer",
      "solutions engineer"), ("Technical Support",)),
    (("data engineer", "data analyst"), ("Data",)),
)


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text))


class RuleBasedMatcher:
    """Weighted personal fit scoring with explicit eligibility uncertainty."""

    def __init__(self, profile: dict, keywords: dict):
        self.profile = profile
        self.keywords = keywords

    def score(self, job: Job) -> Job:
        title = job.title.casefold()
        location = job.location.casefold()
        text = f"{job.title} {job.location} {job.description[:18000]}".casefold()
        # Some ATS feeds encode Remote Worldwide only in the location field.
        # Do not infer global work eligibility from a bare "Remote" label.
        remote = (job.remote_type == "remote" or _contains(title, "remote")
                  or _contains(location, "remote"))
        junior_terms = self.keywords.get("junior", []) + [
            "intern", "apprentice", "trainee", "new graduate"]
        senior_terms = self.keywords.get("senior", []) + ["head of", "vp", "vice president"]

        is_senior = any(_contains(title, term.casefold()) for term in senior_terms)
        is_junior = any(_contains(title, term.casefold()) for term in junior_terms)
        min_years = [
            int(v) for v in re.findall(
                r"(?:minimum|at least|requires?|with|of)?\s*(\d{1,2})\+?\s+"
                r"years?(?:\s+(?:of\s+)?(?:relevant\s+|professional\s+|industry\s+)?experience)?", text

            )
        ]
        requires_senior_experience = bool(min_years and max(min_years) >= 5)
        if is_senior or requires_senior_experience:
            job.experience_level = "senior"
            experience_points = 2
        elif is_junior:
            job.experience_level = "junior"
            experience_points = 25
        else:
            job.experience_level = "unknown"
            experience_points = 13

        declared = list(dict.fromkeys(
            str(skill).strip() for skill in self.profile.get("skills", []) if str(skill).strip()
        ))
        matched = [
            skill for skill in declared if any(
                _contains(text, alias)
                for alias in SKILL_ALIASES.get(skill, (skill.casefold(),))
            )
        ]
        denom = min(5, max(1, len(declared)))
        technical = round(35 * min(len(matched) / denom, 1))

        roles = [str(role).casefold() for role in self.profile.get("target_roles", [])]
        matched_family = False
        for title_terms, family_terms in ROLE_FAMILIES:
            if any(_contains(title, token) for token in title_terms) and any(
                any(_contains(role, hint.casefold()) for hint in family_terms)
                for role in roles
            ):
                matched_family = True
                break
        generic_role_terms = {"engineer", "developer", "analyst", "support", "intern"}
        title_role = any(_contains(title, role) for role in roles if role)
        generic_overlap = any(_contains(title, x) for x in generic_role_terms)
        career_points = 20 if title_role or matched_family else 6 if generic_overlap else 0

        # "Remote" alone is not evidence of eligibility from Türkiye.
        # Do not infer work permits or visa sponsorship for other countries.
        abroad_only = any(_contains(text, term) for term in (
            "us only", "usa only", "united states only", "uk only",
            "eu only", "must be based in the us", "must reside in the us",
            "remote within the us", "remote within the uk")) or bool(re.search(
                r"(?<!\\w)(?:us|usa|uk|eu|germany|united[ -]states|united[ -]kingdom)"
                r"[- ]+only(?!\\w)", text
            ))
        global_remote = remote and any(
            _contains(text, term) for term in (
                "worldwide remote", "remote worldwide", "work from anywhere",
                "remote from anywhere", "global remote", "remote globally")
        )
        explicit_turkey = remote and any(
            _contains(text, term) for term in (
                "remote in turkey", "remote from turkey", "remote from türkiye",
                "based in turkey", "based in türkiye")
        )
        domestic = any(_contains(location, term) for term in (
            "turkey", "türkiye", "istanbul", "ankara", "izmir", "i̇zmir"))
        if abroad_only and remote:
            job.turkey_eligibility = "ineligible"
            job.eligibility_status = "ineligible"
            remote_points = 0
        elif explicit_turkey or global_remote or domestic:
            job.turkey_eligibility = "verified"
            job.eligibility_status = "eligible"
            remote_points = 10
        else:
            job.turkey_eligibility = "unknown"
            job.eligibility_status = "needs_review"
            remote_points = 5 if remote else 0

        freshness = 5
        if job.published_at:
            age = max(0, (datetime.now(timezone.utc) - job.published_at).days)
            freshness = 10 if age <= 7 else 7 if age <= 30 else 3 if age <= 90 else 0

        total = technical + experience_points + career_points + remote_points + freshness
        if is_senior or requires_senior_experience:
            total = min(total, 20)
        if abroad_only and remote:
            total = 0
        job.match_score = min(100, max(0, total))
        job.skills_required = matched
        job.score_reasons = [
            "Eşleşen teknolojiler: " + (", ".join(matched) if matched else "bulunamadı"),
            "Pozisyon hedefi: " + ("uyumlu" if career_points == 20 else "kısmen / belirsiz"),
            "Deneyim seviyesi: " + job.experience_level,
            "Türkiye'den çalışma: " + job.turkey_eligibility,
        ]
        if requires_senior_experience:
            job.score_reasons.append("İlan deneyim beklentisi: en az 5 yıl")
        for country in self.profile.get("target_countries", [
            "United States", "United Kingdom", "Türkiye", "Australia"
        ]):
            assessment = assess_country(text, country)
            job.score_reasons.append(f"{country} uygunluk taraması: {assessment.status}")
        job.gaps = []
        if is_senior or requires_senior_experience:
            job.gaps.append("Senior / yüksek deneyim gereksinimi")
        if job.eligibility_status == "needs_review":
            job.gaps.append("Türkiye'den çalışma veya vize/sponsorluk şartı doğrulanmalı")
        if job.eligibility_status == "ineligible":
            job.gaps.append("Remote çalışma bölgesi Türkiye'yi kapsamıyor")
        job.match_method = "rules"
        return job
