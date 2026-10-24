"""Load matching criteria from private deployment settings, never public repo data."""
from __future__ import annotations

import json
import os
from typing import Any

from .config import load_yaml

FIELDS = ("skills", "target_roles", "target_countries", "work_preferences",
          "languages", "experience", "preferred_sectors")


def load_match_profile() -> dict[str, Any]:
    """Use a vetted JSON profile stored only in Render Environment.

    Local development may use the obviously labeled public sample. Production
    scans must fail rather than quietly return scores for the demo candidate.
    """
    encoded = os.environ.get("CAREERHUNTER_PROFILE_JSON", "").strip()
    if not encoded:
        if os.environ.get("RENDER") and not os.environ.get("PYTEST_CURRENT_TEST"):
            raise RuntimeError("Private candidate profile is not configured")
        return load_yaml("profile.yaml")
    if len(encoded) > 12000:
        raise ValueError("Private candidate profile is too large")
    try:
        profile = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ValueError("Private candidate profile is invalid JSON") from exc
    if not isinstance(profile, dict):
        raise ValueError("Private candidate profile must be an object")
    for name in FIELDS:
        value = profile.get(name, [])
        if not isinstance(value, list) or len(value) > 70 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 120
            for item in value
        ):
            raise ValueError(f"Invalid private profile list: {name}")
    if not profile.get("skills") or not profile.get("target_roles"):
        raise ValueError("Private profile must include skills and target roles")
    return profile
