"""Weekly CareerHunter production digest from authenticated GitHub run evidence.

No database, CV, candidate, or ATS source secrets reach this job. Counters are
reported only if matching evidence exists in the successful collector job logs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .telegram_github import send

REPO = "emirhankaya985-cloud/careerhunter-ai-ci"
BASE = "https://api.github.com/repos/" + REPO
RUNS_PATH = "/actions/workflows/daily.yml/runs?branch=main&per_page=100"
COUNT_RE = re.compile(r"PASS: Collected (\d+) job rows; (\d+) newly stored\.")
TZ_TR = timezone(timedelta(hours=3))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api(url: str, token: str, *, text_result: bool = False):
    if not url.startswith(BASE + "/"):
        raise RuntimeError("GitHub endpoint outside permitted repository")
    request = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CareerHunter-Weekly-Report/1.0",
    })
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected GitHub response")
            return json.load(response) if not text_result else response.read(1000000).decode()
    except HTTPError as exc:
        if not text_result or exc.code not in {301, 302, 303, 307}:
            raise RuntimeError("GitHub read failed") from None
        target = exc.headers.get("Location", "")
        parsed = urlparse(target)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("Invalid protected GitHub log redirect")
        # Signed log download receives NO GitHub bearer token. Never print URL.
        with urlopen(Request(target, headers={
            "User-Agent": "CareerHunter-Weekly-Report/1.0",
        }), timeout=30) as response:
            return response.read(1000000).decode("utf-8", errors="replace")


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(TZ_TR) if dt.tzinfo else None
    except ValueError:
        return None


def choose_days(records: list[dict], now: datetime) -> tuple[list[dict | None], list[str]]:
    """A day with multiple scans counts once; successful recovery supersedes failure."""
    end = now.astimezone(TZ_TR).date()
    dates = [(end - timedelta(days=6-i)) for i in range(7)]
    daily: list[dict | None] = []
    for date in dates:
        candidates = [row for row in records
                      if isinstance(row, dict) and row.get("head_branch") == "main"
                      and row.get("event") in {"schedule", "workflow_dispatch"}
                      and (ts := _timestamp(row.get("created_at"))) is not None
                      and ts.date() == date]
        ok = [r for r in candidates if
              r.get("status") == "completed" and r.get("conclusion") == "success"]
        ranked = ok or candidates
        ranked.sort(key=lambda r: _timestamp(r["created_at"]) or
                    datetime.min.replace(tzinfo=TZ_TR), reverse=True)
        daily.append(ranked[0] if ranked else None)
    return daily, [d.isoformat() for d in dates]


def counters(log: str) -> tuple[int, int] | None:
    found = COUNT_RE.findall(log)
    if not found:
        return None
    processed, added = found[-1]
    return int(processed), int(added)


def build_message(records: list[dict], logs_by_run: dict[int, str], now: datetime) -> str:
    chosen, days = choose_days(records, now)
    succeeded = sum(bool(r and r.get("conclusion") == "success" and
                         r.get("status") == "completed") for r in chosen)
    running = sum(bool(r and r.get("status") != "completed") for r in chosen)
    failed = sum(bool(r and r.get("status") == "completed" and
                      r.get("conclusion") != "success") for r in chosen)
    missed = sum(r is None for r in chosen)
    known = [counters(logs_by_run.get(int(r["id"]), "")) for r in chosen if r and
             r.get("conclusion") == "success" and r.get("status") == "completed"]
    valid = [v for v in known if v is not None]
    unknown = len(known) - len(valid)
    lines = [
        "📊 <b>CareerHunter AI | 7 Günlük Otomasyon Raporu</b>",
        f"📅 {days[0]} — {days[-1]} (TRT)",
        f"✅ Başarılı gün: <b>{succeeded}/7</b>",
        f"❌ Başarısız: <b>{failed}</b> · 🕗 Sürüyor: <b>{running}</b> · ⏭️ Atlama: <b>{missed}</b>",
    ]
    if valid:
        lines.extend([
            f"🆕 Günlük taramada yeni kaydedilen ilan toplamı: <b>{sum(v[1] for v in valid)}</b>",
            f"🔎 İşlenen ilan satırı toplamı: <b>{sum(v[0] for v in valid)}</b>",
            f"🧾 İlan sayaçları doğrulanan gün: <b>{len(valid)}/{succeeded}</b>",
        ])
    else:
        lines.append("🧾 Yeni ilan / işlenen satır toplamı: <b>DOĞRULANAMADI</b>")
    if unknown:
        lines.append(f"⚠️ {unknown} başarılı günün satır sayısı loglardan doğrulanamadı.")
    if missed or failed or running:
        lines.append("⚠️ Bir veya daha fazla günlük tarama kanıtı eksik / başarısız.")
    lines.append("🔒 Kişisel CV ve kişi verisi GitHub raporuna aktarılmaz.")
    return "\n".join(lines)


def _run_stats(token: str, now: datetime) -> tuple[list[dict], dict[int, str]]:
    payload = _api(BASE + RUNS_PATH, token)
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise RuntimeError("GitHub daily workflow history unavailable")
    records = payload["workflow_runs"]
    chosen, _ = choose_days(records, now)
    logs: dict[int, str] = {}
    for run in chosen:
        if not run or run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        rid = int(run["id"])
        jobs = _api(BASE + f"/actions/runs/{rid}/jobs?per_page=100", token)
        for job in jobs.get("jobs", []):
            if job.get("name") == "collect" and job.get("conclusion") == "success":
                logs[rid] = _api(BASE + f"/actions/jobs/{int(job['id'])}/logs", token,
                                 text_result=True)
                break
    return records, logs


def main() -> int:
    token = os.getenv("GH_TOKEN", "")
    if (os.getenv("GITHUB_REPOSITORY") != REPO or
            os.getenv("GITHUB_REF") != "refs/heads/main" or not token):
        print("FAIL: weekly digest requires protected production GitHub context")
        return 1
    try:
        records, logs = _run_stats(token, datetime.now(timezone.utc))
        message = build_message(records, logs, datetime.now(timezone.utc))
        accepted = send(message, [{
            "text": "🧭 GitHub Otomasyonları",
            "url": "https://github.com/" + REPO + "/actions",
        }])
        print("PASS: weekly Telegram digest accepted" if accepted else
              "FAIL: weekly Telegram digest was not accepted")
        return 0 if accepted else 1
    except (RuntimeError, HTTPError, URLError, TimeoutError, TypeError,
            ValueError, OSError, KeyError):
        print("FAIL: weekly report verification failed (no secrets printed)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
