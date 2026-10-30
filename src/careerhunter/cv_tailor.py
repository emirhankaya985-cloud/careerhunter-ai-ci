"""Deterministic, evidence-bound per-vacancy CV tailoring.

Never makes up jobs, qualifications, degrees, achievements or ATS guarantees.
No external network or LLM is involved. Private profile data stays local.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class TailoredCV:
    markdown: str
    matched_skills: tuple[str, ...]
    unmatched_profile_skills: tuple[str, ...]


def _string(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _string(item))]


def _mentioned(skill: str, vacancy: str) -> bool:
    # Whole-token matching avoids treating e.g. "Go" as part of "Django".
    return bool(re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", vacancy, re.IGNORECASE))


def _entries(label: str, value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        if isinstance(item, str) and _string(item):
            lines.append("- " + _string(item))
        elif isinstance(item, Mapping):
            # Preserve only explicit owner-supplied facts; never synthesize dates.
            title = _string(item.get("title")) or _string(item.get("name"))
            company = _string(item.get("company"))
            dates = _string(item.get("dates"))
            if not title:
                continue
            meta = " — ".join(v for v in (title, company, dates) if v)
            lines.append("- " + meta)
            for bullet in _strings(item.get("bullets")):
                lines.append("  - " + bullet)
    return ["## " + label, *lines, ""] if lines else []


def tailor_cv(profile: Mapping[str, Any], job: Mapping[str, Any]) -> TailoredCV:
    """Reorder *declared* skills by vacancy evidence, retaining all truthful facts."""
    title, company = _string(job.get("title")), _string(job.get("company"))
    if not title or not company:
        raise ValueError("Job must include a title and company")
    skills = _strings(profile.get("skills"))
    if not skills:
        raise ValueError("Private candidate profile must provide verified skills")
    # Do not dump the job description into the CV. Use it only for relevance.
    vacancy = " ".join((title, _string(job.get("description"))))
    matched = [skill for skill in skills if _mentioned(skill, vacancy)]
    other = [skill for skill in skills if skill not in matched]
    name = _string(profile.get("name")) or "Candidate"
    lines = [f"# {name}", "", f"Target position: {title} — {company}", ""]
    for key, prefix in (("location", "Location"), ("email", "Email"),
                        ("linkedin_url", "LinkedIn"), ("github_url", "GitHub")):
        if value := _string(profile.get(key)):
            lines.append(f"{prefix}: {value}")
    if lines[-1] != "":
        lines.append("")
    if summary := _string(profile.get("summary")):
        lines.extend(["## Professional summary", summary, ""])
    lines.extend(["## Skills", ", ".join(matched + other), ""])
    lines.extend(_entries("Work experience", profile.get("experience")))
    lines.extend(_entries("Projects", profile.get("projects")))
    if education := _string(profile.get("education")):
        if education.casefold() not in {"not specified", "unknown"}:
            lines.extend(["## Education", education, ""])
    if languages := _strings(profile.get("languages")):
        lines.extend(["## Languages", ", ".join(languages), ""])
    return TailoredCV("\n".join(lines).rstrip() + "\n", tuple(matched), tuple(other))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Locally tailor a factual, ATS-readable Markdown CV")
    parser.add_argument("--profile", type=Path, required=True, help="PRIVATE local JSON profile")
    parser.add_argument("--job", type=Path, required=True, help="JSON object containing a job")
    parser.add_argument("--output", type=Path, required=True, help="Local .md output path")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if args.profile.resolve().is_relative_to(root) or args.output.resolve().is_relative_to(root):
        parser.error("Private profile and generated CV must be outside the public repository")
    if args.output.suffix.lower() != ".md":
        parser.error("Output must be .md; PDF/DOCX export is not implemented")
    profile, job = json.loads(args.profile.read_text(encoding="utf-8")), json.loads(
        args.job.read_text(encoding="utf-8")
    )
    if not isinstance(profile, dict) or not isinstance(job, dict):
        parser.error("Profile and job must each be JSON objects")
    cv = tailor_cv(profile, job)
    if not args.output.parent.is_dir():
        parser.error("Output directory must already exist")
    args.output.write_text(cv.markdown, encoding="utf-8")
    print(f"Wrote local CV: {args.output} ({len(cv.matched_skills)} directly matching skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
