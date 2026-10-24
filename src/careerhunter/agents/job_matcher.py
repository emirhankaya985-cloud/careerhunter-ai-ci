from __future__ import annotations

import re
from datetime import datetime, timezone

from careerhunter.models import Job
from careerhunter.country_rules import assess_country


class RuleBasedMatcher:
    def __init__(self, profile: dict, keywords: dict):
        self.profile = profile
        self.keywords = keywords

    def score(self, job: Job) -> Job:
        text = f"{job.title} {job.description} {job.location}".lower()
        title = job.title.lower()
        negative = [x.lower() for x in self.keywords.get("turkey_negative", [])]
        positive_geo = [x.lower() for x in self.keywords.get("turkey_positive", [])]
        senior_terms = [x.lower() for x in self.keywords.get("senior", [])]
        junior_terms = [x.lower() for x in self.keywords.get("junior", [])]

        if any(term in text for term in negative):
            job.turkey_eligibility = "ineligible"
            job.eligibility_status = "ineligible"
            job.match_score = 0
            job.score_reasons = ["Türkiye dışındaki ikamet koşulu açıkça belirtilmiş"]
            return job

        years = [int(x) for x in re.findall(r"(?:at least\s+)?(\d+)\+?\s+years?", text)]
        if years and max(years) >= 7:
            job.experience_level = "senior"
            job.match_score = 20
            job.score_reasons = [f"İlan {max(years)} yıl deneyim istiyor"]
            job.gaps = ["Profesyonel üretim deneyimi"]
            return job

        skills = [s.lower() for s in self.profile.get("skills", [])]
        matched = [s for s in skills if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text)]
        technical = round(35 * min(len(matched) / max(min(len(skills), 4), 1), 1))

        is_senior = any(term in title for term in senior_terms)
        is_junior = any(term in title for term in junior_terms)
        job.experience_level = "senior" if is_senior else "junior" if is_junior else "unknown"
        experience = 25 if is_junior else 5 if is_senior else 15

        target_tokens = set(" ".join(self.profile.get("target_roles", [])).lower().split())
        career_hits = len({token for token in target_tokens if len(token) > 3 and re.search(rf"\b{re.escape(token)}\b", title)})
        career = min(20, career_hits * 4)

        if any(term in text for term in positive_geo):
            job.turkey_eligibility = "verified"
            job.eligibility_status = "eligible"
            remote = 10
        elif job.remote_type == "remote":
            job.turkey_eligibility = "unknown"
            job.eligibility_status = "needs_review"
            remote = 5
        else:
            remote = 0

        freshness = 5
        if job.published_at:
            age = (datetime.now(timezone.utc) - job.published_at).days
            freshness = 10 if age <= 7 else 7 if age <= 30 else 3 if age <= 90 else 0

        job.skills_required = matched
        job.match_score = min(100, technical + experience + career + remote + freshness)
        job.score_reasons = [
            f"Teknik eşleşmeler: {', '.join(matched) if matched else 'bulunamadı'}",
            f"Deneyim seviyesi: {job.experience_level}",
            f"Türkiye uygunluğu: {job.turkey_eligibility}",
        ]
        for country in self.profile.get("target_countries", ["United States", "United Kingdom", "Türkiye", "Australia"]):
            assessment = assess_country(text, country)
            job.score_reasons.append(f"{country} uygunluk taraması: {assessment.status}")
        job.gaps = [s for s in self.profile.get("skills", []) if s.lower() not in text][:4]
        return job

