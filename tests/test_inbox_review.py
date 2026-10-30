"""Review-only mail signals: privacy, quoting, idempotency and false positives."""
from email.message import EmailMessage

import pytest

from careerhunter.inbox_review import (
    MAX_EMAIL_BYTES, analyze_eml_directory, classify_eml, main,
)


def message(subject: str, body: str, message_id="<a@example.org>") -> bytes:
    msg = EmailMessage()
    msg["From"] = "recruiter@example.org"
    msg["To"] = "applicant@example.org"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_bytes()


@pytest.mark.parametrize(("subject", "body", "expected"), [
    ("Interview invitation", "Please share interview availability", "interview"),
    ("Coding assessment", "Complete your technical test", "assessment"),
    ("Your application", "Unfortunately we cannot proceed with this position", "rejection"),
    ("Hello!", "Your application is still under review", "needs_review"),
])
def test_classifications_are_always_review_only(subject, body, expected):
    signal = classify_eml(message(subject, body))
    assert signal.proposed_category == expected
    assert signal.needs_review
    assert len(signal.id_hash) == 64


def test_quoted_rejection_does_not_trigger_new_rejection():
    raw = message("Following up", "We remain interested.\n\nOn Tue recruiter wrote:\n"
                  "Unfortunately we cannot proceed with this position")
    assert classify_eml(raw).proposed_category == "needs_review"


def test_ambiguous_message_requires_manual_review():
    raw = message("Interview invitation", "Unfortunately we cannot proceed with this position")
    assert classify_eml(raw).proposed_category == "needs_review"


def test_duplicate_message_id_deduplication_and_private_cli(tmp_path, capsys):
    folder = tmp_path / "mail"
    folder.mkdir()
    result = tmp_path / "results.json"
    (folder / "a.eml").write_bytes(message("Interview invitation", "Let's meet"))
    (folder / "b.eml").write_bytes(message("Interview invitation", "Let's meet again"))
    assert len(analyze_eml_directory(folder)) == 1
    assert main(["--eml-dir", str(folder), "--output", str(result)]) == 0
    assert "Saved 1 proposed" in capsys.readouterr().out
    assert '"needs_review": true' in result.read_text(encoding="utf-8")
    assert "applicant@example.org" not in result.read_text(encoding="utf-8")


def test_oversize_and_bounded_batch(tmp_path):
    with pytest.raises(ValueError, match="size limit"):
        classify_eml(b"x" * (MAX_EMAIL_BYTES + 1))
    folder = tmp_path / "mail"
    folder.mkdir()
    for i in range(501):
        (folder / f"file{i}.eml").write_bytes(message("Hello", "Hi", f"<{i}@example.org>"))
    with pytest.raises(ValueError, match="Too many"):
        analyze_eml_directory(folder)
