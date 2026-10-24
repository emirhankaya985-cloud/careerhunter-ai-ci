from careerhunter.source_health import check_source

def test_health_rejects_malformed_payload(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"unexpected": []}
    monkeypatch.setattr("careerhunter.source_health.httpx.get", lambda *a, **k: Response())
    result = check_source({"id":"x","provider":"greenhouse","company":"X","countries":["US"],"endpoint":"https://x"})
    assert result["status"] == "error"

def test_health_accepts_jobs_payload(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"jobs": [{"id": 1}]}
    monkeypatch.setattr("careerhunter.source_health.httpx.get", lambda *a, **k: Response())
    result = check_source({"id":"x","provider":"greenhouse","company":"X","countries":["US"],"endpoint":"https://x"})
    assert result["status"] == "success" and result["jobs"] == 1
