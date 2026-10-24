from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator
import re


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    job_id: str
    source: Literal["greenhouse", "lever", "ashby"]
    company: str
    title: str
    location: str = "unknown"
    description: str = ""
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    turkey_eligibility: Literal["verified", "unknown", "ineligible"] = "unknown"
    employment_type: str = "unknown"
    experience_level: Literal["junior", "mid", "senior", "unknown"] = "unknown"
    skills_required: list[str] = Field(default_factory=list)
    salary: str | None = None
    published_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_verified_at: datetime = Field(default_factory=utc_now)
    job_url: HttpUrl
    source_url: HttpUrl
    match_score: int | None = Field(default=None, ge=0, le=100)
    eligibility_status: Literal["eligible", "needs_review", "ineligible"] = "needs_review"
    status: Literal["new", "seen", "closed"] = "new"
    score_reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("job_id", "company", "title")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class RunStats(BaseModel):
    slot: str
    started_at: datetime
    finished_at: datetime | None = None
    jobs_processed: int = 0
    jobs_new: int = 0
    jobs_closed: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_cost_usd: float = 0
    status: str = "running"
    error: str | None = None


class CompanySignal(BaseModel):
    company_id: str
    company: str
    signal_type: Literal["hiring_activity", "remote_activity", "technical_relevance"]
    claim: str
    evidence_urls: list[HttpUrl] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    confidence: Literal["low", "medium", "high"] = "low"
    observed_at: datetime = Field(default_factory=utc_now)


class Contact(BaseModel):
    person_id: str
    name: str
    company: str
    role: str
    country: str = "unknown"
    linkedin_url: HttpUrl | None = None
    # Only include an email when it is explicitly published for professional
    # contact (never infer or scrape private addresses).
    email_public: str | None = None
    do_not_contact: bool = False
    primary_source_url: HttpUrl | None = None
    category: str
    research_sources: list[HttpUrl] = Field(default_factory=list)
    shared_interests: list[str] = Field(default_factory=list)
    reason_to_connect: str | None = None
    verified_context: str | None = None
    research_confidence: Literal["unverified", "low", "medium", "high"] = "unverified"
    status: Literal["discovered", "research_needed", "draft_ready", "approved_by_user",
                    "contacted_manually", "connection_accepted", "replied",
                    "conversation_active", "followup_due", "opportunity_created",
                    "not_interested", "closed"] = "research_needed"
    message_variant_a: str | None = None
    message_variant_b: str | None = None
    message_variant_a_tr: str | None = None
    message_variant_b_tr: str | None = None
    last_contact_at: datetime | None = None
    last_reply_at: datetime | None = None
    followup_due_at: datetime | None = None
    notes: str | None = None
    # Evidence captured by live research.  These fields deliberately describe
    # what was observed, not an inferred hiring relationship.
    observed_at: datetime | None = None
    evidence_text: str | None = None
    relationship_type: Literal["employee", "recruiter", "hiring_manager", "unknown"] = "unknown"
    hiring_manager_unknown: bool = True
    proof_artifact_url: str | None = None

    @field_validator("email_public")
    @classmethod
    def public_email_format(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("email_public must be a valid email address")
        return value

    @field_validator("primary_source_url")
    @classmethod
    def source_required_for_public_contact(cls, value: HttpUrl | None) -> HttpUrl | None:
        return value


class Opportunity(BaseModel):
    """A tracked job or networking opportunity in the lightweight CRM."""
    opportunity_id: str
    title: str
    company: str
    job_id: str | None = None
    job_url: HttpUrl | None = None
    status: Literal["discovered", "reviewed", "applied", "interview", "offer", "rejected", "closed"] = "discovered"
    fit_score: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class Interaction(BaseModel):
    interaction_id: str
    person_id: str
    interaction_type: Literal["connection_request", "email", "message", "call", "reply", "note"]
    occurred_at: datetime = Field(default_factory=utc_now)
    channel: str = "unknown"
    direction: Literal["outbound", "inbound", "internal"] = "outbound"
    content: str | None = None
    outcome: str | None = None


class FollowUp(BaseModel):
    followup_id: str
    person_id: str | None = None
    opportunity_id: str | None = None
    due_at: datetime
    status: Literal["pending", "completed", "cancelled"] = "pending"
    note: str
    completed_at: datetime | None = None

