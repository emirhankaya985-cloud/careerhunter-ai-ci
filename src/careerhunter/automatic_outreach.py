"""Bounded automatic applications through explicitly published email routes.

Email is sent only when the ATS listing itself explicitly accepts applications
by email, the active listing meets the 60-point and Türkiye-eligibility gates,
the matching encrypted CV is present, and the owner has enabled the one-time
automation/template flags. ATS-only applications remain links; this never
submits a web form.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .models import Contact, Interaction, Job, Opportunity, utc_now

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w-])", re.I)
PERSONAL_EMAIL_DOMAINS = frozenset({"gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                                   "icloud.com", "proton.me", "protonmail.com"})
APPLY_BY_EMAIL_RE = re.compile(
    r"\b(?:email|e-mail)\s+(?:your\s+)?(?:cv|resume|application|curriculum vitae)\b"
    r"|\b(?:send|submit|forward)\s+(?:your\s+)?(?:cv|resume|application|curriculum vitae)\b"
    r"|\bapplications?\s+(?:accepted\s+)?(?:by|via)\s+(?:email|e-mail)\b"
    r"|\bapply\s+by\s+(?:email|e-mail)\b",
    re.I,
)
MAX_SENDS_PER_RUN = 5
TEMPLATE_VERSION = "v1"


def _application_address(job: Job) -> str | None:
    """Return only a listed email adjacent to an explicit email-application instruction."""
    description = job.description or ""
    for match in EMAIL_RE.finditer(description):
        start, end = match.span()
        context = description[max(0, start - 180):min(len(description), end + 180)]
        address = match.group(0).strip().lower()
        local, _, domain = address.rpartition("@")
        if (domain not in PERSONAL_EMAIL_DOMAINS
                and not re.search(r"(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|privacy|legal|support)", local)
                and APPLY_BY_EMAIL_RE.search(context)):
            return address
    return None


def _contact_for(job: Job, address: str) -> Contact:
    identifier = hashlib.sha256(
        "\0".join((job.source, job.job_id, address.casefold())).encode("utf-8")
    ).hexdigest()[:32]
    return Contact(
        person_id="job-email-" + identifier,
        name="Hiring Team",
        company=job.company,
        role="Recruiting / application contact",
        email_public=address,
        primary_source_url=job.job_url,
        category="job_application_email",
        research_sources=[job.source_url, job.job_url],
        verified_context="The ATS listing explicitly instructs applicants to email a CV/application.",
        evidence_text="ATS-listed email address adjacent to an explicit email-application instruction.",
        research_confidence="high",
        status="discovered",
        relationship_type="recruiter",
    )


def _source_is_official(job: Job) -> bool:
    try:
        host = (urlsplit(str(job.source_url)).hostname or "").lower()
    except ValueError:
        return False
    hosts = {
        "greenhouse": {"boards-api.greenhouse.io", "boards.greenhouse.io"},
        "lever": {"api.lever.co", "jobs.lever.co"},
        "ashby": {"api.ashbyhq.com", "jobs.ashbyhq.com"},
    }
    return host in hosts.get(job.source, set())


def _eligible_job(job: Job, *, now: datetime) -> bool:
    if (job.status == "closed" or job.match_score is None or job.match_score < 60
            or job.verification_status not in {"ATS_LISTED", "EMPLOYER_CONFIRMED"}
            or job.remote_type != "remote" or job.experience_level == "senior"
            or job.turkey_eligibility != "verified" or job.eligibility_status != "eligible"
            or not job.verification_observed_at or not _source_is_official(job)):
        return False
    observed = job.verification_observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return now - observed.astimezone(timezone.utc) <= timedelta(hours=24)


def _language(job: Job) -> str:
    text = f"{job.title} {job.location} {job.description}".casefold()
    turkish_terms = ("başvuru", "çalışma", "şirket", "pozisyon", "ekibimize", "aramaktayız")
    return "tr" if sum(term in text for term in turkish_terms) >= 2 else "en"


def _message(profile: dict, job: Job, language: str) -> tuple[str, str]:
    name = str(profile.get("name", "")).strip()
    signoff = name or "Emirhan Kaya"
    if language == "tr":
        subject = f"{job.title} başvurusu — {job.company}"
        body = (f"Merhaba İşe Alım Ekibi,\n\n{job.company} şirketindeki {job.title} "
                "pozisyonuna başvuruyorum. İlgili rol için özgeçmişimi ekte iletiyorum. "
                "Başvurumu değerlendirmeniz için teşekkür ederim.\n\nSaygılarımla,\n" + signoff)
    else:
        subject = f"Application: {job.title} — {job.company}"
        body = (f"Dear Hiring Team,\n\nI am applying for the {job.title} position at "
                f"{job.company}. I have attached my CV for your consideration. "
                "Thank you for reviewing my application.\n\nBest regards,\n" + signoff)
    return subject, body


def run_auto_outreach(repo, jobs: list[Job], *, dry_run: bool = False) -> dict[str, object]:
    """Discover explicit email application routes; send only under all gates."""
    template_approved = os.getenv("CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED") == TEMPLATE_VERSION
    automatic_enabled = (
        os.getenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED") == "true"
        and template_approved
    )
    result: dict[str, object] = {
        "status": "disabled", "discovered_contacts": 0, "eligible_jobs": 0,
        "sent": 0, "failed": 0, "skipped": 0,
        "automatic_dispatch_enabled": automatic_enabled,
        "template_approved": template_approved,
        "gmail_send_enabled": os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true",
        "receipt_writer_configured": bool(
            os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
        ),
        "candidate_profile_available": False,
        "approved_cv_available": False,
    }
    candidates: list[tuple[Job, Contact]] = []
    touched_jobs: list[Job] = []
    for job in jobs:
        address = _application_address(job)
        if not address:
            continue
        contact = _contact_for(job, address)
        job.application_method = "email"
        job.application_contact_id = contact.person_id
        touched_jobs.append(job)
        if not dry_run:
            repo.upsert_contact(contact)
        if (not contact.do_not_contact
                and contact.status not in {"not_interested", "closed", "contacted_automatically"}
                and _eligible_job(job, now=utc_now())):
            candidates.append((job, contact))
    result["discovered_contacts"] = len(touched_jobs)
    result["eligible_jobs"] = len(candidates)
    if touched_jobs and not dry_run:
        repo.update_job_scores(touched_jobs)
    if dry_run:
        result["status"] = "dry_run"
        result["skipped"] = len(candidates)
        return result
    if not candidates:
        result["status"] = "no_email_eligible_jobs"
        return result
    if os.getenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED") != "true":
        result["status"] = "automatic_dispatch_disabled"
        result["skipped"] = len(candidates)
        return result
    if os.getenv("CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED") != TEMPLATE_VERSION:
        result["status"] = "template_approval_missing"
        result["skipped"] = len(candidates)
        return result
    if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
        result["status"] = "gmail_send_disabled"
        result["skipped"] = len(candidates)
        return result
    writer = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
    if not writer:
        result["status"] = "receipt_writer_missing"
        result["skipped"] = len(candidates)
        return result
    from .gmail_send import ApprovedMail, GmailSendError, send_approved_once
    from .personal_profile import load_match_profile
    try:
        profile = load_match_profile()
    except Exception:
        result["status"] = "private_profile_missing"
        result["skipped"] = len(candidates)
        return result
    result["candidate_profile_available"] = True

    seen_company: set[str] = set()
    for job, contact in sorted(candidates, key=lambda item: item[0].match_score or 0, reverse=True):
        company_key = hashlib.sha256(job.company.strip().casefold().encode("utf-8")).hexdigest()
        if company_key in seen_company:
            result["skipped"] = int(result["skipped"]) + 1
            continue
        seen_company.add(company_key)
        language = _language(job)
        try:
            from .cv_vault import load_cv_attachment
            cv_bytes, cv_filename = load_cv_attachment(language)
        except Exception:
            result["status"] = "approved_cv_missing_or_unavailable"
            result["skipped"] = len(candidates) - int(result["sent"])
            return result
        result["approved_cv_available"] = True
        approval_id = hashlib.sha256(
            "\0".join((job.source, job.job_id, contact.person_id)).encode("utf-8")
        ).hexdigest()[:40]
        subject, body = _message(profile, job, language)
        mail = ApprovedMail(
            recipient=contact.email_public or "", subject=subject, body=body,
            contact_evidence_url=str(contact.primary_source_url),
            approval_id=approval_id, approved_by_owner=True,
            reply_to=os.getenv("CAREERHUNTER_APPLICATION_REPLY_TO", "").strip() or None,
            attachment_pdf=cv_bytes, attachment_filename=cv_filename,
            company_key=company_key,
        )
        try:
            message_id = send_approved_once(mail, database_url=writer)
        except GmailSendError as exc:
            # A pending claim on an uncertain provider result is never retried.
            result["failed"] = int(result["failed"]) + 1
            result["status"] = str(exc)
            if str(exc) in {"daily_limit_reached", "daily_company_limit_reached"}:
                result["skipped"] = len(candidates) - int(result["sent"])
                return result
            continue
        opportunity_id = f"{job.source}:{job.job_id}"
        opportunity = repo.get_opportunity(opportunity_id) or Opportunity(
            opportunity_id=opportunity_id, title=job.title, company=job.company,
            job_id=job.job_id, job_url=job.job_url,
        )
        opportunity.status = "applied"
        opportunity.applied_at = utc_now()
        opportunity.cv_sha256 = hashlib.sha256(cv_bytes).hexdigest()
        opportunity.submission_evidence_url = job.job_url
        opportunity.updated_at = utc_now()
        repo.upsert_opportunity(opportunity)
        repo.record_interaction(Interaction(
            interaction_id=f"auto-email:{approval_id}", person_id=contact.person_id,
            interaction_type="email", occurred_at=utc_now(), channel="gmail",
            direction="outbound", outcome="gmail_accepted",
        ))
        contact.status = "contacted_automatically"
        contact.last_contact_at = utc_now()
        repo.upsert_contact(contact)
        # Repository refresh semantics preserve historical status. Apply the
        # post-send transition through its explicit status-update operation.
        update_status = getattr(repo, "update_contact_status", None)
        if callable(update_status):
            update_status(contact.person_id, "contacted_automatically")
        result["sent"] = int(result["sent"]) + 1
        result["last_message_id"] = message_id
        if int(result["sent"]) >= MAX_SENDS_PER_RUN:
            break
    if int(result["sent"]) > 0:
        result["status"] = "sent"
    elif result["status"] == "disabled":
        result["status"] = "no_messages_sent"
    result.pop("last_message_id", None)
    return result

