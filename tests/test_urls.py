from sitecrawler.urls import normalize_url, resolve_link, same_site


def test_normalize_strips_fragment_and_default_port():
    assert normalize_url("HTTP://Example.COM:80/a#top") == "http://example.com/a"
    assert normalize_url("https://example.com:443") == "https://example.com/"
    assert normalize_url("http://example.com:8080/x?q=1#f") == "http://example.com:8080/x?q=1"


def test_resolve_link_skips_non_http_and_fragments():
    base = "http://example.com/dir/page.html"
    assert resolve_link(base, "#section") is None
    assert resolve_link(base, "mailto:a@b.com") is None
    assert resolve_link(base, "JavaScript:void(0)") is None
    assert resolve_link(base, "") is None
    assert resolve_link(base, "other.html#x") == "http://example.com/dir/other.html"
    assert resolve_link(base, "/root") == "http://example.com/root"


def test_same_site_ignores_www():
    assert same_site("http://www.example.com/a", "https://example.com/b")
    assert not same_site("http://example.com", "http://example.org")
    assert not same_site("http://example.com:8080", "http://example.com")
