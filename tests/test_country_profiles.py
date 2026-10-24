from pathlib import Path

import yaml


def test_required_country_profiles_are_complete():
    path = Path(__file__).parents[1] / "config" / "country_profiles.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    countries = data["countries"]
    assert set(countries) == {"United States", "United Kingdom", "Türkiye", "Australia"}
    for profile in countries.values():
        assert profile["official_work_source"].startswith("https://")
        assert profile["strategy"]
        assert isinstance(profile["work_authorization_required"], bool)
