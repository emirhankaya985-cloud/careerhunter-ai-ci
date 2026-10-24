from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from careerhunter.models import Job, RunStats
from careerhunter.reporting.countries import aggregate_country_report, render_country_report


def render_jobs(jobs: list[Job], stats: RunStats) -> str:
    sorted_jobs = sorted(jobs, key=lambda item: item.match_score or 0, reverse=True)
    strong = sum((j.match_score or 0) >= 80 for j in jobs)
    verified = sum(j.turkey_eligibility == "verified" for j in jobs)
    lines = ["# Morning Job Intelligence", "", f"_Üretim zamanı: {datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(timespec='minutes')}_", "",
             f"**Bugün incelenen:** {len(jobs)}  ", f"**Yeni:** {stats.jobs_new}  ",
             f"**Güçlü eşleşme:** {strong}  ", f"**Türkiye uygunluğu doğrulanan:** {verified}", ""]
    lines += [f"**LLM kullanımı:** {stats.llm_calls} çağrı, {stats.llm_tokens} token, ${stats.llm_cost_usd:.4f}", ""]
    if not sorted_jobs:
        lines += ["Uygun veya erişilebilir ilan bulunamadı. Kaynak hataları için çalışma kaydını kontrol et.", ""]
    for index, job in enumerate(sorted_jobs[:10], 1):
        recommendation = (
            "Başvur"
            if (job.match_score or 0) >= 80 and job.eligibility_status == "eligible"
            else "Önce çalışma uygunluğunu doğrula"
            if (job.match_score or 0) >= 65 and job.eligibility_status == "needs_review"
            else "İncele"
            if (job.match_score or 0) >= 65
            else "Düşük öncelik"
        )
        lines += [f"## {index}. {job.company} — {job.title} — {job.match_score}/100", "",
                  f"- İlan: {job.job_url}", f"- Kaynak: {job.source_url}",
                  f"- İlan tarihi: {job.published_at.isoformat() if job.published_at else 'unknown'}",
                  f"- Remote: {job.remote_type}; Türkiye uygunluğu: {job.turkey_eligibility}",
                  f"- Neden: {'; '.join(job.score_reasons)}",
                  f"- Eksikler: {', '.join(job.gaps) if job.gaps else 'unknown'}",
                  f"- Öncelik: {recommendation}", ""]
    lines += ["> Puanlar işe alınma olasılığı değildir. `unknown` Türkiye'den çalışma izni anlamına gelmez.", ""]
    lines.append(render_country_report(aggregate_country_report(jobs)))
    return "\n".join(lines)


def write_report(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

