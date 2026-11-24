"""Read-only production summaries used by GitHub Actions without the website."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.engine.url import make_url

from .database import followups, jobs, opportunities, runs
from .models import FollowUp, Job, Opportunity


def production_database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql" or not parsed.host or not parsed.database:
        raise RuntimeError("GitHub operation requires production PostgreSQL")
    return value


def telegram_job_digest() -> dict[str, object]:
    """Create the small, public-job Telegram digest from PostgreSQL directly."""
    from .job_quality import classify_profile_fit
    from .reporting.countries import classify_job_countries

    engine = create_engine(production_database_url(), pool_pre_ping=True, pool_size=1,
                           max_overflow=0)
    try:
        with engine.connect() as connection:
            latest = connection.execute(
                select(runs).where(runs.c.slot == "jobs")
                .order_by(runs.c.id.desc()).limit(1)
            ).mappings().first()
            if not latest or latest["status"] != "success":
                return {"status": "no_successful_scan", "items": []}
            raw_jobs = connection.execute(
                select(jobs.c.payload)
                .where(jobs.c.first_seen_at >= latest["started_at"])
                .where(jobs.c.closed_at.is_(None))
                .order_by(jobs.c.first_seen_at.desc()).limit(2500)
            ).scalars().all()
    finally:
        engine.dispose()

    try:
        threshold = max(0, min(100, int(os.getenv("TELEGRAM_MIN_SCORE", "75"))))
    except ValueError:
        threshold = 75
    unique: dict[tuple[str, str], Job] = {}
    for raw in raw_jobs:
        job = Job.model_validate_json(raw)
        if job.status == "new":
            unique[(job.source, job.job_id)] = job

    discarded: dict[str, int] = {}
    counts = {"strong_match": 0, "review": 0, "not_suitable": 0}
    selected = []
    country_counts = {"US": 0, "GB": 0, "AU": 0, "TR": 0}
    code_for = {"United States": "US", "United Kingdom": "GB",
                "Australia": "AU", "Türkiye": "TR"}
    for job in unique.values():
        for country in classify_job_countries(SimpleNamespace(location=job.location,
                                                               description="")):
            code = code_for.get(country)
            if code:
                country_counts[code] += 1
        if job.remote_type != "remote":
            discarded["not_remote"] = discarded.get("not_remote", 0) + 1
            continue
        if job.verification_status not in {"ATS_LISTED", "EMPLOYER_CONFIRMED"}:
            discarded["listing_not_verified"] = discarded.get("listing_not_verified", 0) + 1
            continue
        status, reason = classify_profile_fit({
            "title": job.title, "location": job.location, "remote_type": job.remote_type,
            "description": job.description[:12000], "skills": job.skills_required,
            "score": job.match_score or 0, "level": job.experience_level,
            "eligibility": job.eligibility_status,
        }, strong_minimum=threshold)
        counts[status] += 1
        selected.append((job, status, reason))
    selected.sort(key=lambda item: (
        {"strong_match": 2, "review": 1, "not_suitable": 0}[item[1]],
        item[0].match_score or 0, item[0].match_method == "llm",
    ), reverse=True)
    items = [{
        "title": job.title[:90], "company": job.company[:70], "location": job.location[:70],
        "url": str(job.job_url), "score": int(job.match_score or 0),
        "method": job.match_method, "eligibility": job.eligibility_status,
        "level": job.experience_level,
        "application_deadline": job.application_deadline.date().isoformat()
        if job.application_deadline else None,
        "fit_status": status, "fit_reason": reason,
        "matched_skills": job.skills_required[:8],
    } for job, status, reason in selected[:200]]
    return {
        "status": "ready", "run_id": int(latest["id"]),
        "jobs_new": int(latest["jobs_new"] or 0),
        "strong_count": counts["strong_match"], "listed_count": len(selected),
        "quality_rejected": len(unique) - len(selected), "quality_reasons": discarded,
        "fit_counts": counts, "country_signals": country_counts,
        "threshold": threshold, "items": items,
    }


def due_application_followups() -> dict[str, object]:
    """Return only due public job details, without requiring a Render route."""
    now = datetime.now(timezone.utc)
    engine = create_engine(production_database_url(), pool_pre_ping=True, pool_size=1,
                           max_overflow=0)
    try:
        statement = (
            select(followups.c.payload, opportunities.c.payload)
            .select_from(followups.join(
                opportunities,
                followups.c.opportunity_id == opportunities.c.opportunity_id,
            ))
            .where(followups.c.status == "pending")
            .order_by(followups.c.due_at.asc()).limit(500)
        )
        with engine.connect() as connection:
            rows = connection.execute(statement).all()
    finally:
        engine.dispose()
    due = []
    for raw_followup, raw_opportunity in rows:
        followup = FollowUp.model_validate_json(raw_followup)
        opportunity = Opportunity.model_validate_json(raw_opportunity)
        date = followup.due_at.astimezone(timezone.utc)
        if date > now:
            continue
        if (followup.note == "Son başvuru günü için Telegram hatırlatması"
                and date.date() != now.date()):
            continue
        if opportunity.status in {"closed", "rejected"}:
            continue
        due.append({
            "title": opportunity.title[:90], "company": opportunity.company[:70],
            "job_url": str(opportunity.job_url) if opportunity.job_url else None,
            "due_at": date.date().isoformat(),
            "reminder_type": "application_deadline"
            if followup.note == "Son başvuru günü için Telegram hatırlatması"
            else "application_followup",
        })
    return {"status": "ready", "due_count": len(due), "items": due[:10], "bounded": True}
