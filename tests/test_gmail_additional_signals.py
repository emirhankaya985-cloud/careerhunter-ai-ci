"""New categories must not misclassify ordinary application replies."""
from email.message import EmailMessage

import pytest

from careerhunter.inbox_review import classify_eml
from careerhunter.telegram_mail_review import prepare


def eml(subject: str, body: str) -> bytes:
    mail = EmailMessage()
    mail["Message-ID"] = "<distinct-fixture@example.org>"
    mail["Subject"] = subject
    mail.set_content(body)
    return mail.as_bytes()


@pytest.mark.parametrize(("subject", "body", "category"), [
    ("Application received", "We have received your application.", "application"),
    ("Başvurunuz alınmıştır", "İlginiz için teşekkürler.", "application"),
    ("Following up on your application", "Please share availability", "followup"),
    ("Başvurunuzla ilgili güncelleme", "Belgelerinizi bekliyoruz", "followup"),
    ("Your application", "Unfortunately not moving forward", "rejection"),
    ("Checking in", "Hello there", "needs_review"),
])
def test_strict_recruitment_signal_classification(subject, body, category):
    assert classify_eml(eml(subject, body)).proposed_category == category


def test_private_report_labels_application_and_followup_aggregates():
    rendered = prepare({
        "status": "ready", "scanned": 2, "review_required": 2,
        "categories": {"application": 1, "followup": 1},
    })
    assert "Başvuru alındı" in rendered
    assert "Takip / başvuru" in rendered
    assert "ilk kez sınıflandırılan" in rendered
