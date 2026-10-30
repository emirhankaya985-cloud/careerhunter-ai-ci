"""Employer careers page corroboration requires a direct link and HTTPS."""
import httpx

from careerhunter.employer_corroboration import (
    check_employer_page, contains_exact_posting_link,
)


CAREERS = "https://example.org/careers"
POSTING = "https://jobs.ashbyhq.com/example/role-123"


def test_direct_link_on_employer_page_is_independent_evidence():
    html = '<a href="https://jobs.ashbyhq.com/example/role-123?utm_source=careers">Apply</a>'
    assert contains_exact_posting_link(html, CAREERS, POSTING)


def test_text_mention_wrong_link_and_scripts_do_not_count():
    assert not contains_exact_posting_link(
        '<script>location="https://jobs.ashbyhq.com/example/role-123"</script>',
        CAREERS, POSTING,
    )
    assert not contains_exact_posting_link(
        '<a href="https://jobs.ashbyhq.com/example/different">Role</a>',
        CAREERS, POSTING,
    )


def test_bounded_http_check_can_confirm_exact_link():
    def handler(request):
        assert str(request.url) == CAREERS
        return httpx.Response(
            200, headers={"content-type": "text/html"},
            text=f'<a href="{POSTING}">See vacancy</a>'
        )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_employer_page(CAREERS, POSTING, client=client)
    assert result.verified
    assert result.reason == "exact_posting_link_on_configured_employer_page"


def test_source_error_or_missing_link_is_not_fraud():
    def handler(request):
        return httpx.Response(503, headers={"content-type": "text/html"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_employer_page(CAREERS, POSTING, client=client)
    assert not result.verified
    assert result.reason == "employer_page_unavailable"


def test_disallow_ip_localhost_http_and_nonstandard_port():
    for url in (
        "http://example.org/careers", "https://127.0.0.1/careers",
        "https://localhost/careers", "https://example.local/careers",
        "https://example.org:8080/careers",
    ):
        result = check_employer_page(url, POSTING)
        assert not result.verified
        assert result.reason == "unsafe_or_unconfigured_https_url"


def test_html_page_must_be_bounded():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"x" * 600_000
        )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_employer_page(CAREERS, POSTING, client=client)
    assert not result.verified
    assert result.reason == "employer_page_too_large"
