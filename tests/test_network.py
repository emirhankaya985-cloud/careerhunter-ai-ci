from careerhunter.agents.hook_writer import prepare_drafts
from careerhunter.llm.fallback import critique_message
from careerhunter.database import SQLiteRepository
from careerhunter.models import Contact


def verified_contact() -> Contact:
    return Contact(
        person_id="p-1", name="Ada Lovelace", company="Acme", role="Engineer",
        category="technical_network", research_confidence="medium",
        verified_context="Acme's public article about Python automation",
        research_sources=["https://example.com/article"],
    )


def test_verified_context_produces_human_review_drafts():
    contact = prepare_drafts(verified_contact())
    assert contact.status == "draft_ready"
    assert "Ada" in contact.message_variant_a


def test_unverified_contact_does_not_get_draft():
    contact = verified_contact()
    contact.research_confidence = "unverified"
    contact = prepare_drafts(contact)
    assert contact.message_variant_a is None
    assert contact.status == "research_needed"


def test_drafts_are_bilingual_and_never_auto_sent():
    contact = prepare_drafts(verified_contact())
    assert contact.message_variant_a_tr.startswith("Merhaba Ada")
    result = critique_message(contact.message_variant_a,
                              verified_context=contact.verified_context,
                              source_count=len(contact.research_sources))
    assert result["ok"] is True
    assert result["send_allowed_automatically"] is False


def test_critic_rejects_missing_evidence():
    result = critique_message("Hi there", verified_context=None, source_count=0)
    assert result["ok"] is False
    assert result["human_review_required"] is True


def test_contact_status_persists_and_validates(tmp_path):
    repo = SQLiteRepository(tmp_path / "contacts.db")
    repo.upsert_contact(verified_contact())
    updated = repo.update_contact_status("p-1", "contacted_manually")
    assert updated.status == "contacted_manually"
    try:
        repo.update_contact_status("p-1", "send_automatically")
    except Exception:
        pass
    else:
        raise AssertionError("Invalid status must not be accepted")


def test_public_email_and_contact_block_are_persisted(tmp_path):
    repo = SQLiteRepository(tmp_path / "contacts.db")
    values = verified_contact().model_dump()
    values.update(email_public="ada@example.org", primary_source_url="https://example.com/team/ada", do_not_contact=True)
    contact = Contact(**values)
    repo.upsert_contact(contact)
    loaded = repo.list_contacts()[0]
    assert loaded.email_public == "ada@example.org"
    assert str(loaded.primary_source_url) == "https://example.com/team/ada"
    assert loaded.do_not_contact is True
    assert prepare_drafts(loaded).message_variant_a is None


def test_public_email_must_be_valid():
    try:
        values = verified_contact().model_dump()
        values["email_public"] = "not-an-email"
        Contact(**values)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid public email must be rejected")
