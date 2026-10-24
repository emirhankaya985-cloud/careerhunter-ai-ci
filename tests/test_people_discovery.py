from careerhunter.intelligence.people import discover_public_contacts, parse_team_page


HTML = """
<html><body><article><h2>Jordan Smith</h2><p>Engineering Manager</p>
<a href='https://www.linkedin.com/in/jordan-smith'>LinkedIn</a></article>
<article><h2>Casey Example</h2><p>Designer</p><a href='mailto:casey@example.org'>email</a></article>
<article><h2>Hiring Team</h2><p>We are hiring engineers</p></article></body></html>
"""


def test_only_explicit_people_and_roles_are_discovered():
    result = parse_team_page(HTML, source_url="https://acme.example/team", company="Acme", country="USA")
    assert len(result.contacts) == 2
    jordan = next(c for c in result.contacts if c.name == "Jordan Smith")
    assert jordan.role == "Engineering Manager"
    assert str(jordan.linkedin_url).startswith("https://www.linkedin.com/in/")
    assert str(jordan.primary_source_url) == "https://acme.example/team"
    assert jordan.research_confidence == "medium"


def test_no_inferred_email_or_name_from_hiring_copy():
    result = parse_team_page("<p>We are hiring engineers. Contact talent@example.org</p>",
                             source_url="https://acme.example/careers", company="Acme")
    assert result.contacts == []


def test_source_and_observation_are_always_recorded():
    result = parse_team_page(HTML, source_url="https://acme.example/team", company="Acme")
    assert result.status == "ok"
    assert result.observed_at.tzinfo is not None
    assert all(str(result.source_url) in [str(u) for u in c.research_sources] for c in result.contacts)


def test_same_name_on_different_sources_gets_distinct_evidence_bound_ids():
    html = "<article><h2>Kim</h2><p>Software Engineer</p></article>"
    first = parse_team_page(html, source_url="https://acme.example/team-a", company="Acme")
    second = parse_team_page(html, source_url="https://acme.example/team-b", company="Acme")
    assert first.contacts[0].name == second.contacts[0].name == "Kim"
    assert first.contacts[0].person_id != second.contacts[0].person_id
    assert first.contacts[0].primary_source_url != second.contacts[0].primary_source_url


def test_duplicate_blocks_on_one_source_are_deduplicated():
    html = "<article><h2>Kim</h2><p>Software Engineer</p></article>" \
           "<article><h2>Kim</h2><p>Software Engineer</p></article>"
    result = parse_team_page(html, source_url="https://acme.example/team", company="Acme")
    assert len(result.contacts) == 1


def test_same_name_with_different_explicit_roles_gets_distinct_ids():
    html = "<article><h2>Kim</h2><p>Software Engineer</p></article>" \
           "<article><h2>Kim</h2><p>Engineering Manager</p></article>"
    result = parse_team_page(html, source_url="https://acme.example/team", company="Acme")
    assert len(result.contacts) == 2
    assert {contact.role for contact in result.contacts} == {"Software Engineer", "Engineering Manager"}
    assert len({contact.person_id for contact in result.contacts}) == 2


def test_daily_discovery_reports_new_contacts_and_missing_sources(monkeypatch):
    monkeypatch.setattr(
        "careerhunter.intelligence.people.fetch_team_page",
        lambda url, **kwargs: "<article><h2>Alex Morgan</h2><p>Recruiter</p></article>",
    )
    contacts, errors = discover_public_contacts([
        {"name": "Acme", "team_url": "https://acme.example/team"},
        {"name": "NoSource"},
    ])
    assert [c.name for c in contacts] == ["Alex Morgan"]
    assert any("NoSource" in error and "team_url" in error for error in errors)
