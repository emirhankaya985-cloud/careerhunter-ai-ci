from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import httpx
from .config import load_yaml

def check_source(source: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    observed = datetime.now(timezone.utc).isoformat()
    try:
        response = httpx.get(source["endpoint"], timeout=timeout, headers={"User-Agent": "CareerHunterAI/0.1"})
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else payload
        valid = isinstance(jobs, list)
        return {"source_id": source["id"], "provider": source["provider"], "company": source["company"], "countries": source.get("countries", []), "endpoint": source["endpoint"], "observed_at": observed, "status": "success" if valid else "error", "jobs": len(jobs) if valid else 0, "error": None if valid else "payload does not contain a jobs list"}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"source_id": source.get("id"), "provider": source.get("provider"), "company": source.get("company"), "countries": source.get("countries", []), "endpoint": source.get("endpoint"), "observed_at": observed, "status": "error", "jobs": 0, "error": f"{type(exc).__name__}: {exc}"}

def check_catalog(timeout: float = 15.0) -> list[dict[str, Any]]:
    return [check_source(s, timeout=timeout) for s in load_yaml("source_catalog.yaml").get("sources", [])]
