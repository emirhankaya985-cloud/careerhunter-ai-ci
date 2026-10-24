from careerhunter.intelligence.company import build_company_signals
from careerhunter.models import Job


def test_company_signals_are_source_grounded_and_conservative():
    first = Job(
        job_id="1", source="greenhouse", company="Acme", title="Python Developer",
        remote_type="remote", job_url="https://example.com/jobs/1",
        source_url="https://example.com/jobs",
    )
    signals = build_company_signals([first])
    assert {signal.signal_type for signal in signals} == {"hiring_activity", "remote_activity"}
    assert all(signal.evidence_urls for signal in signals)
    assert all("growth" not in signal.claim.lower() for signal in signals)
