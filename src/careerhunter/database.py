from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy import case, create_engine, delete, func, insert, literal, or_, select, tuple_, update
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import CompanySignal, Contact, FollowUp, Interaction, Job, Opportunity, RunStats, utc_now
from .reporting.countries import ALIASES, CITY_COUNTRY, COUNTRIES


SCHEMA_VERSION = 3
metadata = MetaData()

schema_versions = Table(
    "schema_versions", metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", String, nullable=False),
)
jobs = Table(
    "jobs", metadata,
    Column("source", String, primary_key=True),
    Column("job_id", String, primary_key=True),
    Column("company", String, nullable=False, index=True),
    Column("title", String, nullable=False),
    Column("location", String, nullable=False),
    Column("job_url", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("first_seen_at", String, nullable=False),
    Column("last_seen_at", String, nullable=False),
    Column("last_verified_at", String, nullable=False),
    Column("status", String, nullable=False, default="new"),
    Column("closed_at", String),
    UniqueConstraint("source", "job_url", name="uq_jobs_source_url"),
)
runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slot", String, nullable=False),
    Column("started_at", String, nullable=False),
    Column("finished_at", String),
    Column("jobs_processed", Integer, default=0),
    Column("jobs_new", Integer, default=0),
    Column("jobs_closed", Integer, default=0),
    Column("llm_calls", Integer, default=0),
    Column("llm_tokens", Integer, default=0),
    Column("llm_cost_usd", Float, default=0),
    Column("status", String, nullable=False),
    Column("error", Text),
)
contacts = Table(
    "contacts", metadata,
    Column("person_id", String, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("updated_at", String, nullable=False),
)
company_signals = Table(
    "company_signals", metadata,
    Column("signal_id", String, primary_key=True),
    Column("company_id", String, nullable=False, index=True),
    Column("company", String, nullable=False),
    Column("signal_type", String, nullable=False),
    Column("claim", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("observed_at", String, nullable=False),
    UniqueConstraint("company_id", "signal_type", name="uq_company_signal_type"),
)
opportunities = Table(
    "opportunities", metadata,
    Column("opportunity_id", String, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("status", String, nullable=False, index=True),
    Column("updated_at", String, nullable=False),
)
interactions = Table(
    "interactions", metadata,
    Column("interaction_id", String, primary_key=True),
    Column("person_id", String, nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("occurred_at", String, nullable=False),
)
followups = Table(
    "followups", metadata,
    Column("followup_id", String, primary_key=True),
    Column("person_id", String, index=True),
    Column("opportunity_id", String, index=True),
    Column("payload", Text, nullable=False),
    Column("due_at", String, nullable=False, index=True),
    Column("status", String, nullable=False, index=True),
)
country_assessments = Table(
    "country_assessments", metadata,
    Column("assessment_id", String, primary_key=True),
    Column("source", String, nullable=False),
    Column("job_id", String, nullable=False),
    Column("country", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("observed_at", String, nullable=False),
    UniqueConstraint("source", "job_id", "country", name="uq_country_assessment"),
)
critic_results = Table(
    "critic_results", metadata,
    Column("critic_id", String, primary_key=True),
    Column("person_id", String, nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("observed_at", String, nullable=False),
)


def _sqlite_url(path: Path | str) -> str:
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{resolved.as_posix()}"


def database_url(default_path: Path | str) -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured.replace("postgres://", "postgresql+psycopg://", 1)
    return _sqlite_url(os.getenv("CAREERHUNTER_DB", str(default_path)))


class DatabaseRepository:
    """SQLAlchemy Core repository shared by SQLite and PostgreSQL."""

    def __init__(self, url: str, *, engine: Engine | None = None):
        self.url = url
        self.engine = engine or create_engine(url, pool_pre_ping=True)
        self.initialize()

    def initialize(self) -> None:
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            versions = connection.execute(select(schema_versions.c.version)).scalars().all()
            if SCHEMA_VERSION not in versions:
                connection.execute(insert(schema_versions).values(
                    version=SCHEMA_VERSION, applied_at=utc_now().isoformat()
                ))

    @staticmethod
    def _job_payload(job: Job) -> tuple[str, str]:
        payload = job.model_dump_json()
        canonical = json.dumps(job.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return payload, hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def upsert_jobs(self, incoming: list[Job]) -> int:
        """Persist jobs in bounded batches (one SELECT + one UPSERT per batch).

        Keep the first observation time for existing records; do not create
        duplicates when the same (source, job_id) appears twice in one scan.
        PostgreSQL and SQLite use their native ON CONFLICT, avoiding thousands
        of remote per-record round trips.
        """
        if not incoming:
            return 0
        unique: dict[tuple[str, str], Job] = {}
        for job in incoming:
            key = (job.source, job.job_id)
            if key in unique:
                # The original sequential implementation kept the first
                # observation timestamp when a scan repeated the same key.
                job.first_seen_at = unique[key].first_seen_at
            unique[key] = job
        new_count = 0
        values_to_update = (
            "company", "title", "location", "job_url", "payload",
            "content_hash", "first_seen_at", "last_seen_at",
            "last_verified_at", "status", "closed_at",
        )
        with self.engine.begin() as connection:
            items = list(unique.values())
            for start in range(0, len(items), 100):
                batch = items[start:start + 100]
                keys = [(job.source, job.job_id) for job in batch]
                old = connection.execute(
                    select(jobs.c.source, jobs.c.job_id, jobs.c.first_seen_at)
                    .where(tuple_(jobs.c.source, jobs.c.job_id).in_(keys))
                ).mappings().all()
                existing = {(row["source"], row["job_id"]): row["first_seen_at"] for row in old}
                records = []
                for job in batch:
                    first = existing.get((job.source, job.job_id))
                    if first is not None:
                        job.first_seen_at = datetime.fromisoformat(first)
                        job.status = "seen"
                    else:
                        new_count += 1
                    payload, fingerprint = self._job_payload(job)
                    records.append({
                        "source": job.source,
                        "job_id": job.job_id,
                        "company": job.company,
                        "title": job.title,
                        "location": job.location,
                        "job_url": str(job.job_url),
                        "payload": payload,
                        "content_hash": fingerprint,
                        "first_seen_at": job.first_seen_at.isoformat(),
                        "last_seen_at": job.last_verified_at.isoformat(),
                        "last_verified_at": job.last_verified_at.isoformat(),
                        "status": job.status,
                        "closed_at": None,
                    })
                if self.engine.dialect.name == "postgresql":
                    statement = pg_insert(jobs).values(records)
                elif self.engine.dialect.name == "sqlite":
                    statement = sqlite_insert(jobs).values(records)
                else:
                    raise RuntimeError("Job bulk upsert requires PostgreSQL or SQLite")
                connection.execute(statement.on_conflict_do_update(
                    index_elements=[jobs.c.source, jobs.c.job_id],
                    set_={name: getattr(statement.excluded, name) for name in values_to_update},
                ))
        return new_count

    def update_job_scores(self, rescored: list[Job]) -> int:
        """Refresh matching evidence without mutating first-seen or job status.

        Unlike upsert_jobs, this leaves verified timestamps, closure flags and
        new-job counters intact. It is safe for backfills and LLM enrichment.
        """
        if not rescored:
            return 0
        modified = 0
        with self.engine.begin() as connection:
            for job in rescored:
                payload, digest = self._job_payload(job)
                result = connection.execute(
                    update(jobs).where(
                        jobs.c.source == job.source,
                        jobs.c.job_id == job.job_id,
                    ).values(payload=payload, content_hash=digest)
                )
                modified += result.rowcount or 0
        return modified

    def mark_closed(self, source: str, company: str, seen_ids: set[str]) -> int:
        """Close missing jobs only after the caller completed a successful source scan."""
        with self.engine.begin() as connection:
            rows = connection.execute(select(jobs.c.job_id, jobs.c.payload).where(
                jobs.c.source == source, jobs.c.company == company, jobs.c.closed_at.is_(None)
            )).mappings().all()
            missing = [row for row in rows if row["job_id"] not in seen_ids]
            now = utc_now().isoformat()
            for row in missing:
                payload = json.loads(row["payload"])
                payload["status"] = "closed"
                connection.execute(update(jobs).where(
                    jobs.c.source == source, jobs.c.job_id == row["job_id"]
                ).values(status="closed", closed_at=now, payload=json.dumps(payload)))
            return len(missing)

    def list_jobs(self, active_only: bool = True, limit: int = 100) -> list[Job]:
        statement = select(jobs.c.payload).order_by(jobs.c.last_verified_at.desc()).limit(limit)
        if active_only:
            statement = statement.where(jobs.c.closed_at.is_(None))
        with self.engine.connect() as connection:
            payloads = connection.execute(statement).scalars().all()
        return [Job.model_validate_json(payload) for payload in payloads]

    def get_job(self, source: str, job_id: str) -> Job | None:
        """Find an exact source/job_id pair, not an ambiguous title match."""
        with self.engine.connect() as connection:
            value = connection.execute(select(jobs.c.payload).where(
                jobs.c.source == source, jobs.c.job_id == job_id
            )).scalar_one_or_none()
        return Job.model_validate_json(value) if value else None

    def update_job_evidence(self, job: Job) -> bool:
        """Persist verification evidence only; never imply submission or closure."""
        payload, digest = self._job_payload(job)
        values = {"payload": payload, "content_hash": digest}
        if job.verification_status == "ATS_LISTED" and job.verification_observed_at:
            values["last_verified_at"] = job.verification_observed_at.isoformat()
        with self.engine.begin() as connection:
            result = connection.execute(update(jobs).where(
                jobs.c.source == job.source, jobs.c.job_id == job.job_id
            ).values(**values))
        return bool(result.rowcount)

    def count_new_jobs_since(self, since: datetime) -> int:
        """Count unique jobs first observed since ``since`` by (source, job_id)."""
        cutoff = since.astimezone(timezone.utc).isoformat()
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(jobs.c.source, jobs.c.job_id).where(jobs.c.first_seen_at >= cutoff)
            ).all()
        return len({(row[0], row[1]) for row in rows})

    def aggregate_job_counts(self, since: datetime) -> dict[str, int]:
        """Return full-table counts without loading every job payload."""
        cutoff = since.astimezone(timezone.utc).isoformat()
        location = func.lower(jobs.c.location)
        country = case(
            (location.like("%united states%") | location.like("% usa%") | (location == "us"), "US"),
            (location.like("%australia%"), "AU"),
            (location.like("%united kingdom%") | location.like("% uk%"), "GB"),
            (location.like("%turkey%") | location.like("%türkiye%"), "TR"),
            else_="UNKNOWN",
        ).label("country")
        with self.engine.connect() as connection:
            total = connection.execute(select(func.count()).select_from(jobs)).scalar_one()
            new = connection.execute(select(func.count()).select_from(jobs).where(jobs.c.first_seen_at >= cutoff)).scalar_one()
            rows = connection.execute(select(country, func.count()).select_from(jobs).group_by(country)).all()
        result = {"total": int(total), "new_24h": int(new)}
        result.update({f"country_{row[0].lower()}": int(row[1]) for row in rows})
        return result

    def aggregate_country_counts(self, since: datetime) -> dict[str, dict[str, int]]:
        """Count country scopes from the full jobs table, not a 500-row dashboard page.

        Only the publisher's location field provides country-scope evidence.
        Description mentions, generic worldwide remote and explicit permission
        to work from Türkiye are NOT physical-country location evidence.
        A job naming multiple countries can appear in multiple country buckets;
        each bucket's new jobs are a subset of its own total jobs.
        """
        cutoff = since.astimezone(timezone.utc).isoformat()
        # SQL-portable normalization (SQLite and PostgreSQL), including Turkish İ.
        normalized = func.lower(func.replace(jobs.c.location, "İ", "i"))
        for separator in (",", "/", "|", "-", ";", ".", ":", "(", ")", "[", "]", "\n", "\t"):
            normalized = func.replace(normalized, separator, " ")
        padded = literal(" ") + normalized + literal(" ")

        fields = []
        for index, country in enumerate(COUNTRIES):
            # Boundary matching avoids identifying "us" inside "Australia"
            # or "uk" inside unrelated words. City aliases work only in location.
            aliases = set(ALIASES[country])
            aliases.update(city for city, target in CITY_COUNTRY.items() if target == country)
            tokens = {" ".join(token.lower().replace(".", " ").split()) for token in aliases}
            matching = or_(*(padded.like(f"% {token} %") for token in sorted(tokens)))
            fields.extend((
                func.sum(case((matching, 1), else_=0)).label(f"total_{index}"),
                func.sum(case((matching & (jobs.c.first_seen_at >= cutoff), 1), else_=0)).label(
                    f"new_{index}"
                ),
            ))

        with self.engine.connect() as connection:
            row = connection.execute(select(*fields).select_from(jobs)).mappings().one()
        return {
            country: {
                "total": int(row[f"total_{index}"] or 0),
                "new_24h": int(row[f"new_{index}"] or 0),
            }
            for index, country in enumerate(COUNTRIES)
        }

    def record_run(self, stats: RunStats) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(runs).values(
                slot=stats.slot, started_at=stats.started_at.isoformat(),
                finished_at=stats.finished_at.isoformat() if stats.finished_at else None,
                jobs_processed=stats.jobs_processed, jobs_new=stats.jobs_new,
                jobs_closed=stats.jobs_closed, llm_calls=stats.llm_calls,
                llm_tokens=stats.llm_tokens, llm_cost_usd=stats.llm_cost_usd,
                status=stats.status, error=stats.error,
            ))

    def latest_run(self) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(runs).order_by(runs.c.id.desc()).limit(1)
            ).mappings().first()
        return dict(row) if row else None

    def upsert_contact(self, contact: Contact) -> None:
        now = utc_now().isoformat()
        with self.engine.begin() as connection:
            exists = connection.execute(select(contacts.c.person_id).where(
                contacts.c.person_id == contact.person_id
            )).first()
            # Research refreshes must never erase a user's communication history.
            if exists:
                old_payload = connection.execute(select(contacts.c.payload).where(
                    contacts.c.person_id == contact.person_id)).scalar_one()
                old = Contact.model_validate_json(old_payload)
                for field in ("status", "last_contact_at", "last_reply_at", "followup_due_at", "notes"):
                    if getattr(old, field) is not None and (field != "status" or old.status != "research_needed"):
                        setattr(contact, field, getattr(old, field))
            values = {"payload": contact.model_dump_json(), "updated_at": now}
            if exists:
                connection.execute(update(contacts).where(
                    contacts.c.person_id == contact.person_id
                ).values(**values))
            else:
                connection.execute(insert(contacts).values(
                    person_id=contact.person_id, **values
                ))

    def list_contacts(self, limit: int = 100) -> list[Contact]:
        with self.engine.connect() as connection:
            payloads = connection.execute(select(contacts.c.payload).order_by(
                contacts.c.updated_at.desc()
            ).limit(limit)).scalars().all()
        return [Contact.model_validate_json(payload) for payload in payloads]

    def update_contact_status(self, person_id: str, status: str) -> Contact:
        with self.engine.begin() as connection:
            payload = connection.execute(select(contacts.c.payload).where(
                contacts.c.person_id == person_id
            )).scalar_one_or_none()
            if payload is None:
                raise KeyError(f"Contact not found: {person_id}")
            contact = Contact.model_validate({**json.loads(payload), "status": status})
            connection.execute(update(contacts).where(
                contacts.c.person_id == person_id
            ).values(payload=contact.model_dump_json(), updated_at=utc_now().isoformat()))
        return contact

    def upsert_opportunity(self, opportunity: Opportunity) -> None:
        values = {"payload": opportunity.model_dump_json(), "status": opportunity.status,
                  "updated_at": opportunity.updated_at.isoformat()}
        with self.engine.begin() as connection:
            exists = connection.execute(select(opportunities.c.opportunity_id).where(
                opportunities.c.opportunity_id == opportunity.opportunity_id)).first()
            if exists:
                connection.execute(update(opportunities).where(
                    opportunities.c.opportunity_id == opportunity.opportunity_id).values(**values))
            else:
                connection.execute(insert(opportunities).values(
                    opportunity_id=opportunity.opportunity_id, **values))

    def list_opportunities(self, status: str | None = None, limit: int = 100) -> list[Opportunity]:
        statement = select(opportunities.c.payload).order_by(opportunities.c.updated_at.desc()).limit(limit)
        if status:
            statement = statement.where(opportunities.c.status == status)
        with self.engine.connect() as connection:
            payloads = connection.execute(statement).scalars().all()
        return [Opportunity.model_validate_json(payload) for payload in payloads]

    def get_opportunity(self, opportunity_id: str) -> Opportunity | None:
        with self.engine.connect() as connection:
            value = connection.execute(select(opportunities.c.payload).where(
                opportunities.c.opportunity_id == opportunity_id
            )).scalar_one_or_none()
        return Opportunity.model_validate_json(value) if value else None

    def record_interaction(self, interaction: Interaction) -> None:
        with self.engine.begin() as connection:
            values = {"person_id": interaction.person_id, "payload": interaction.model_dump_json(),
                      "occurred_at": interaction.occurred_at.isoformat()}
            exists = connection.execute(select(interactions.c.interaction_id).where(
                interactions.c.interaction_id == interaction.interaction_id)).first()
            if exists:
                connection.execute(update(interactions).where(
                    interactions.c.interaction_id == interaction.interaction_id).values(**values))
            else:
                connection.execute(insert(interactions).values(
                    interaction_id=interaction.interaction_id, **values))

    def list_interactions(self, person_id: str | None = None, limit: int = 100) -> list[Interaction]:
        statement = select(interactions.c.payload).order_by(interactions.c.occurred_at.desc()).limit(limit)
        if person_id:
            statement = statement.where(interactions.c.person_id == person_id)
        with self.engine.connect() as connection:
            payloads = connection.execute(statement).scalars().all()
        return [Interaction.model_validate_json(payload) for payload in payloads]

    def upsert_followup(self, followup: FollowUp) -> None:
        values = {"person_id": followup.person_id, "opportunity_id": followup.opportunity_id,
                  "payload": followup.model_dump_json(), "due_at": followup.due_at.isoformat(),
                  "status": followup.status}
        with self.engine.begin() as connection:
            exists = connection.execute(select(followups.c.followup_id).where(
                followups.c.followup_id == followup.followup_id)).first()
            if exists:
                connection.execute(update(followups).where(
                    followups.c.followup_id == followup.followup_id).values(**values))
            else:
                connection.execute(insert(followups).values(followup_id=followup.followup_id, **values))

    def list_followups(self, pending_only: bool = False, limit: int = 100) -> list[FollowUp]:
        statement = select(followups.c.payload).order_by(followups.c.due_at.asc()).limit(limit)
        if pending_only:
            statement = statement.where(followups.c.status == "pending")
        with self.engine.connect() as connection:
            payloads = connection.execute(statement).scalars().all()
        return [FollowUp.model_validate_json(payload) for payload in payloads]

    def update_followup_status(self, followup_id: str, status: str) -> FollowUp:
        with self.engine.begin() as connection:
            payload = connection.execute(select(followups.c.payload).where(
                followups.c.followup_id == followup_id)).scalar_one_or_none()
            if payload is None:
                raise KeyError(f"Follow-up not found: {followup_id}")
            update_data = {"status": status}
            if status == "completed":
                update_data["completed_at"] = utc_now().isoformat()
            followup = FollowUp.model_validate({**json.loads(payload), "status": status,
                                                **({"completed_at": update_data["completed_at"]} if "completed_at" in update_data else {})})
            connection.execute(update(followups).where(followups.c.followup_id == followup_id).values(
                payload=followup.model_dump_json(), status=status))
        return followup

    def upsert_company_signal(self, signal: CompanySignal) -> None:
        with self.engine.begin() as connection:
            existing = connection.execute(select(company_signals.c.signal_id).where(
                company_signals.c.company_id == signal.company_id,
                company_signals.c.signal_type == signal.signal_type,
            )).scalar_one_or_none()
            values = {
                "company": signal.company,
                "claim": signal.claim,
                "payload": signal.model_dump_json(),
                "observed_at": signal.observed_at.isoformat(),
            }
            if existing:
                connection.execute(update(company_signals).where(
                    company_signals.c.signal_id == existing
                ).values(**values))
            else:
                connection.execute(insert(company_signals).values(
                    signal_id=f"{signal.company_id}:{signal.signal_type}",
                    company_id=signal.company_id,
                    signal_type=signal.signal_type,
                    **values,
                ))

    def list_company_signals(self, limit: int = 100) -> list[CompanySignal]:
        with self.engine.connect() as connection:
            payloads = connection.execute(select(company_signals.c.payload).order_by(
                company_signals.c.observed_at.desc()
            ).limit(limit)).scalars().all()
        return [CompanySignal.model_validate_json(payload) for payload in payloads]

    def upsert_country_assessment(self, source: str, job_id: str, country: str,
                                  payload: dict[str, Any], observed_at: str | None = None) -> None:
        observed = observed_at or utc_now().isoformat()
        aid = f"{source}:{job_id}:{country}"
        values = {"payload": json.dumps(payload, ensure_ascii=False, default=str), "observed_at": observed}
        with self.engine.begin() as connection:
            exists = connection.execute(select(country_assessments.c.assessment_id).where(
                country_assessments.c.source == source, country_assessments.c.job_id == job_id,
                country_assessments.c.country == country)).scalar_one_or_none()
            if exists:
                connection.execute(update(country_assessments).where(country_assessments.c.assessment_id == exists).values(**values))
            else:
                connection.execute(insert(country_assessments).values(assessment_id=aid, source=source,
                    job_id=job_id, country=country, **values))

    def list_country_assessments(self, job_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        statement = select(country_assessments).order_by(country_assessments.c.observed_at.desc()).limit(limit)
        if job_id:
            statement = statement.where(country_assessments.c.job_id == job_id)
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]

    def upsert_critic_result(self, person_id: str, payload: dict[str, Any], observed_at: str | None = None) -> None:
        observed = observed_at or utc_now().isoformat()
        cid = f"{person_id}:message"
        with self.engine.begin() as connection:
            exists = connection.execute(select(critic_results.c.critic_id).where(critic_results.c.critic_id == cid)).scalar_one_or_none()
            values = {"person_id": person_id, "payload": json.dumps(payload, ensure_ascii=False, default=str), "observed_at": observed}
            if exists:
                connection.execute(update(critic_results).where(critic_results.c.critic_id == cid).values(**values))
            else:
                connection.execute(insert(critic_results).values(critic_id=cid, **values))

    def list_critic_results(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(critic_results).order_by(critic_results.c.observed_at.desc()).limit(limit)).mappings().all()]

    def clear_all(self) -> None:
        """Test helper; never called by production workflows."""
        with self.engine.begin() as connection:
            connection.execute(delete(followups))
            connection.execute(delete(interactions))
            connection.execute(delete(opportunities))
            connection.execute(delete(contacts))
            connection.execute(delete(runs))
            connection.execute(delete(jobs))
            connection.execute(delete(country_assessments))
            connection.execute(delete(critic_results))


class SQLiteRepository(DatabaseRepository):
    """Backward-compatible local repository constructor."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        super().__init__(_sqlite_url(self.path))


def create_repository(default_path: Path | str) -> DatabaseRepository:
    return DatabaseRepository(database_url(default_path))


def import_legacy_sqlite(path: Path | str, target: DatabaseRepository) -> dict[str, int]:
    """Copy legacy JSON payloads into the configured database without deleting the source."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    counts = {"jobs_read": 0, "jobs_new": 0, "contacts_read": 0}
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        job_rows = connection.execute("SELECT payload FROM jobs").fetchall()
        imported_jobs = [Job.model_validate_json(row["payload"]) for row in job_rows]
        counts["jobs_read"] = len(imported_jobs)
        counts["jobs_new"] = target.upsert_jobs(imported_jobs)
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "contacts" in tables:
            contact_rows = connection.execute("SELECT payload FROM contacts").fetchall()
            for row in contact_rows:
                target.upsert_contact(Contact.model_validate_json(row["payload"]))
            counts["contacts_read"] = len(contact_rows)
    finally:
        connection.close()
    return counts
