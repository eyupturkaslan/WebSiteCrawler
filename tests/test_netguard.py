import socket

import pytest

from sitecrawler.crawler import Crawler
from sitecrawler.netguard import BlockedURL, URLGuard


def fake_resolver(mapping):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (mapping[host], port))]
    return resolve


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata endpoint
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
])
def test_blocks_private_addresses(url):
    with pytest.raises(BlockedURL):
        URLGuard().check(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://example.com/",
    "http://user:pass@example.com/",
    "http://example.com:22/",
])
def test_blocks_bad_scheme_credentials_and_ports(url):
    guard = URLGuard(resolver=fake_resolver({"example.com": "93.184.216.34"}))
    with pytest.raises(BlockedURL):
        guard.check(url)


def test_allows_public_address():
    guard = URLGuard(resolver=fake_resolver({"example.com": "93.184.216.34"}))
    guard.check("https://example.com/page")


def test_crawler_blocks_private_start_url(site_url):
    result = Crawler(site_url, delay=0, guard=URLGuard(allowed_ports=None)).run()
    assert len(result.pages) == 1
    assert result.pages[0].error.startswith("Engellendi")


def test_crawler_blocks_redirect_to_private_address(site_url):
    # Pretend 127.0.0.1 is a public server, while "localhost" is (correctly) internal.
    guard = URLGuard(allowed_ports=None, resolver=fake_resolver({"127.0.0.1": "93.184.216.34",
                                                                  "localhost": "127.0.0.1"}))
    result = Crawler(site_url + "go-internal", delay=0, respect_robots=False, guard=guard).run()
    page = result.pages[0]
    assert page.status is None
    assert "localhost" in page.error


def test_response_size_is_capped(site_url):
    result = Crawler(site_url, delay=0, max_bytes=200).run()
    home = result.pages[0]
    # The home page links appear after the first 200 bytes, so none are discovered.
    assert home.ok and home.internal_links < 4
