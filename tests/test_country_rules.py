from careerhunter.country_rules import assess_country


def test_country_rules_are_conservative():
    assert assess_country("US remote; visa sponsorship available", "United States").status == "sponsorship_or_rights_evidence"
    assert assess_country("Remote - UK, Skilled Worker sponsorship", "United Kingdom").status == "sponsorship_or_rights_evidence"
    assert assess_country("Remote, Türkiye eligible", "Türkiye").status == "eligible"
    assert assess_country("Sydney hybrid role", "Australia").status == "location_match_needs_rights_check"
    assert assess_country("Global remote role", "Australia").status == "unknown"
