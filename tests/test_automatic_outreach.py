from datetime import timedelta

from careerhunter.automatic_outreach import _application_address, run_auto_outreach
from careerhunter.models import Job, utc_now


def job(*, score=60, description="To apply, email your CV to recruiting@example.org.",
        company="Example"):
    return Job(
        job_id="job-001", source="greenhouse", company=company,
        title="Junior Python Backend Developer", location="Turkey",
        description=description, remote_type="remote", experience_level="junior",
        match_score=score, verification_status="ATS_LISTED",
        verification_observed_at=utc_now(), turkey_eligibility="verified",
        eligibility_status="eligible", job_url="https://boards.greenhouse.io/example/jobs/1",
        source_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
    )


class Repo:
    def __init__(self):
        self.contacts = {}
        self.updated_jobs = []
        self.opportunities = []
        self.interactions = []

    def upsert_contact(self, contact):
        self.contacts[contact.person_id] = contact

    def update_contact_status(self, person_id, status):
        self.contacts[person_id].status = status

    def update_job_scores(self, jobs):
        self.updated_jobs.extend(jobs)

    def get_opportunity(self, _opportunity_id):
        return None

    def upsert_opportunity(self, opportunity):
        self.opportunities.append(opportunity)

    def record_interaction(self, interaction):
        self.interactions.append(interaction)


def enable_auto(monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED", "true")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED", "v1")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "postgresql://writer")


def test_discovery_requires_explicit_email_application_instruction():
    assert _application_address(job()) == "recruiting@example.org"
    assert _application_address(job(description="Questions? contact support@example.org")) is None
    assert _application_address(job(description="Send your CV to candidate@gmail.com")) is None


def test_dry_run_never_writes_contacts_or_sends(monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED", "true")
    repo = Repo()
    result = run_auto_outreach(repo, [job()], dry_run=True)
    assert result["status"] == "dry_run"
    assert result["eligible_jobs"] == 1
    assert repo.contacts == {}
    assert repo.updated_jobs == []


def test_score_below_60_is_never_auto_eligible(monkeypatch):
    enable_auto(monkeypatch)
    repo = Repo()
    result = run_auto_outreach(repo, [job(score=59)])
    assert result["eligible_jobs"] == 0
    assert result["status"] == "no_email_eligible_jobs"
    assert not repo.opportunities


def test_disabled_global_switch_discovers_but_does_not_send(monkeypatch):
    monkeypatch.delenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED", raising=False)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    repo = Repo()
    result = run_auto_outreach(repo, [job()])
    assert result["status"] == "automatic_dispatch_disabled"
    assert result["automatic_dispatch_enabled"] is False
    assert result["gmail_send_enabled"] is True
    assert result["receipt_writer_configured"] is False
    assert result["discovered_contacts"] == 1
    assert repo.contacts
    assert not repo.opportunities


def test_unverified_or_stale_or_ineligible_listing_is_not_eligible():
    stale = job().model_copy(update={"verification_observed_at": utc_now() - timedelta(hours=25)})
    unknown = job().model_copy(update={"turkey_eligibility": "unknown"})
    unverified = job().model_copy(update={"verification_status": "REVIEW_REQUIRED"})
    for record in (stale, unknown, unverified):
        assert _application_address(record)
        repo = Repo()
        result = run_auto_outreach(repo, [record])
        assert result["eligible_jobs"] == 0


def test_auto_send_requires_cv_and_records_gmail_acceptance(monkeypatch):
    enable_auto(monkeypatch)
    monkeypatch.setattr("careerhunter.personal_profile.load_match_profile", lambda: {
        "name": "Emirhan Kaya", "skills": ["Python"],
        "target_roles": ["Python Backend Developer"],
    })
    monkeypatch.setattr("careerhunter.cv_vault.load_cv_attachment", lambda language: (
        b"%PDF-1.7\n%%EOF", f"careerhunter_cv_{language}.pdf"))
    sent = []

    def send(mail, *, database_url):
        sent.append((mail, database_url))
        return "gmailMessage123"

    monkeypatch.setattr("careerhunter.gmail_send.send_approved_once", send)
    repo = Repo()
    result = run_auto_outreach(repo, [job()])
    assert result["status"] == "sent"
    assert result["sent"] == 1
    assert len(sent) == 1
    mail, writer = sent[0]
    assert mail.recipient == "recruiting@example.org"
    assert mail.approved_by_owner is True
    assert mail.attachment_filename == "careerhunter_cv_en.pdf"
    assert mail.attachment_pdf.startswith(b"%PDF-")
    assert writer == "postgresql://writer"
    assert repo.opportunities[0].status == "applied"
    assert repo.interactions[0].outcome == "gmail_accepted"
    assert next(iter(repo.contacts.values())).status == "contacted_automatically"


def test_missing_cv_blocks_without_attempting_send(monkeypatch):
    enable_auto(monkeypatch)
    monkeypatch.setattr("careerhunter.personal_profile.load_match_profile", lambda: {
        "name": "Emirhan Kaya", "skills": ["Python"], "target_roles": ["Python Developer"],
    })
    monkeypatch.setattr("careerhunter.cv_vault.load_cv_attachment",
                        lambda _language: (_ for _ in ()).throw(LookupError("cv_not_uploaded")))
    monkeypatch.setattr("careerhunter.gmail_send.send_approved_once",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sent")))
    result = run_auto_outreach(Repo(), [job()])
    assert result["status"] == "approved_cv_missing_or_unavailable"
    assert result["sent"] == 0


def test_outreach_readiness_reports_switches_without_enabling_dispatch(monkeypatch):
    monkeypatch.delenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED", raising=False)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED", raising=False)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_SEND_ENABLED", raising=False)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", raising=False)
    result = run_auto_outreach(Repo(), [job()])
    assert result["status"] == "automatic_dispatch_disabled"
    assert result["automatic_dispatch_enabled"] is False
    assert result["template_approved"] is False
    assert result["gmail_send_enabled"] is False
    assert result["receipt_writer_configured"] is False
    assert result["candidate_profile_available"] is False
    assert result["approved_cv_available"] is False
    assert result["sent"] == 0
