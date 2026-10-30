"""Evidence and privacy regression tests for deterministic CV tailoring."""
import json

import pytest

from careerhunter.cv_tailor import main, tailor_cv


JOB = {"company": "Example Corp", "title": "Junior Python Backend Developer",
       "description": "Python, FastAPI and PostgreSQL; optional Go"}
PROFILE = {
    "name": "Example Applicant", "skills": ["Go", "Python", "FastAPI", "SQL"],
    "experience": [{"title": "Data Intern", "company": "Example Co", "dates": "2025",
                    "bullets": ["Built a real public API"]}],
    "projects": [{"name": "Vision API", "bullets": ["Used PyTorch"]}],
    "education": "Engineering student", "languages": ["Turkish", "English"],
}


def test_cv_prioritizes_only_existing_evidenced_skills():
    result = tailor_cv(PROFILE, JOB)
    assert result.matched_skills == ("Go", "Python", "FastAPI")
    assert result.unmatched_profile_skills == ("SQL",)
    assert "Go, Python, FastAPI, SQL" in result.markdown
    assert "Example Applicant" in result.markdown
    assert "Built a real public API" in result.markdown
    assert "Used PyTorch" in result.markdown


def test_cv_does_not_hallucinate_skills_or_employment():
    minimal = {"skills": ["Python"], "education": "not specified", "experience": []}
    output = tailor_cv(minimal, JOB).markdown
    assert "PostgreSQL" not in output
    assert "Data Intern" not in output
    assert "## Education" not in output
    assert "## Work experience" not in output


def test_rejects_missing_validated_private_skill_or_vacancy():
    with pytest.raises(ValueError, match="verified skills"):
        tailor_cv({"skills": []}, JOB)
    with pytest.raises(ValueError, match="title and company"):
        tailor_cv(PROFILE, {"title": "Python Developer"})


def test_go_is_not_falsely_matched_inside_django():
    result = tailor_cv({"skills": ["Go", "Python"]},
                       {"title": "Python Engineer", "company": "Demo", "description": "Django"})
    assert result.matched_skills == ("Python",)


def test_cli_reads_private_local_json_and_writes_markdown(tmp_path, capsys):
    private = tmp_path / "profile.json"
    job = tmp_path / "job.json"
    out = tmp_path / "tailored.md"
    private.write_text(json.dumps(PROFILE), encoding="utf-8")
    job.write_text(json.dumps(JOB), encoding="utf-8")
    assert main(["--profile", str(private), "--job", str(job), "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Example Applicant\n")
    assert "Wrote local CV:" in capsys.readouterr().out
