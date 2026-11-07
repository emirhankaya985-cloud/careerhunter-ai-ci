"""Turkey ATS configs must match companies' real public Lever posting sites."""
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_turkey_company_boards_are_supported_lever_sites():
    companies = yaml.safe_load(
        (ROOT / "config/companies.yaml").read_text(encoding="utf-8")
    )["companies"]
    catalog = yaml.safe_load(
        (ROOT / "config/source_catalog.yaml").read_text(encoding="utf-8")
    )["sources"]

    expected = {"Insider": "insiderone", "Peak": "peakgames"}
    for company, slug in expected.items():
        company_config = next(c for c in companies if c["name"] == company)
        source_config = next(c for c in catalog if c["company"] == company)
        assert company_config["lever"] == slug
        assert "greenhouse" not in company_config
        assert "TR" in company_config["countries"]
        assert source_config["provider"] == "lever"
        assert source_config["slug"] == slug
        assert source_config["endpoint"] == (
            f"https://api.lever.co/v0/postings/{slug}?mode=json"
        )
        assert source_config["careers_url"] == f"https://jobs.lever.co/{slug}"
