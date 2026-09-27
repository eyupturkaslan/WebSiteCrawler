import json

from sitecrawler.audit import audit, health_score
from sitecrawler.cli import main
from sitecrawler.crawler import Crawler


def kinds_for(issues, url_suffix):
    return {i.kind for i in issues if i.url.endswith(url_suffix)}


def test_crawl_finds_pages_and_respects_robots(site_url):
    result = Crawler(site_url, delay=0).run()
    urls = {p.url for p in result.pages}

    assert site_url in urls
    assert site_url + "about.html" in urls
    assert site_url + "blog/post.html" in urls
    assert site_url + "missing.html" in urls
    # Fragment links collapse into the same page.
    assert sum(1 for u in urls if "about.html" in u) == 1
    # robots.txt disallows /private/.
    assert site_url + "private/secret.html" not in urls
    assert site_url + "private/secret.html" in result.blocked_by_robots
    # External links are never crawled.
    assert not any("external.invalid" in u for u in urls)


def test_utf8_without_charset_header_is_decoded(site_url):
    result = Crawler(site_url, delay=0).run()
    titles = {p.url: p.title for p in result.pages}
    assert titles[site_url + "blog/post.html"] == "Bir Yazı"


def test_max_depth_and_max_pages(site_url):
    shallow = Crawler(site_url, max_depth=1, delay=0).run()
    assert all(p.depth <= 1 for p in shallow.pages)
    assert site_url + "blog/post.html" not in {p.url for p in shallow.pages}

    limited = Crawler(site_url, max_pages=2, delay=0).run()
    assert len(limited.pages) == 2


def test_audit_reports_expected_issues(site_url):
    result = Crawler(site_url, delay=0).run()
    issues = audit(result)

    missing = [i for i in issues if i.kind == "broken_page"]
    assert [i.url for i in missing] == [site_url + "missing.html"]
    assert missing[0].detail == "HTTP 404"
    assert missing[0].referrers == [site_url]

    assert "duplicate_title" in kinds_for(issues, "about.html")
    assert "missing_description" in kinds_for(issues, "about.html")
    assert "multiple_h1" in kinds_for(issues, "about.html")
    assert "missing_h1" in kinds_for(issues, "blog/")
    assert 0 <= health_score(result, issues) < 100


def test_external_links_checked(site_url):
    result = Crawler(site_url, delay=0, timeout=2, check_external=True).run()
    assert [c.url for c in result.external] == ["https://external.invalid/page"]
    issues = audit(result)
    assert any(i.kind == "broken_external" for i in issues)


def test_cli_writes_reports(site_url, tmp_path):
    html_path = tmp_path / "r.html"
    json_path = tmp_path / "r.json"
    code = main([site_url, "--delay", "0", "-q", "--html", str(html_path),
                 "--json", str(json_path), "--fail-on-error"])
    assert code == 1  # the fixture site has a 404
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["summary"]["broken_pages"] == 1
    assert "Site Denetim Raporu" in html_path.read_text(encoding="utf-8")
