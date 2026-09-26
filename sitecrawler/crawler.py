import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .urls import normalize_url, resolve_link, same_site

DEFAULT_USER_AGENT = "SiteCrawler/1.0 (+https://github.com/eyupturkaslan/WebSiteCrawler)"


@dataclass
class Page:
    url: str
    depth: int
    status: int | None = None
    error: str | None = None
    final_url: str | None = None
    content_type: str = ""
    elapsed_ms: int = 0
    title: str | None = None
    meta_description: str | None = None
    h1_count: int = 0
    word_count: int = 0
    internal_links: int = 0
    external_links: int = 0

    @property
    def ok(self):
        return self.error is None and self.status is not None and self.status < 400

    @property
    def is_html(self):
        return "html" in self.content_type

    @property
    def redirected(self):
        return self.final_url is not None and self.final_url != self.url


@dataclass
class LinkCheck:
    url: str
    status: int | None = None
    error: str | None = None

    @property
    def ok(self):
        return self.error is None and self.status is not None and self.status < 400


@dataclass
class CrawlResult:
    start_url: str
    pages: list[Page] = field(default_factory=list)
    external: list[LinkCheck] = field(default_factory=list)
    # target url -> set of pages that link to it
    referrers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    blocked_by_robots: list[str] = field(default_factory=list)
    duration_s: float = 0.0


class Crawler:
    def __init__(self, start_url, max_pages=200, max_depth=5, delay=0.0, timeout=10.0,
                 respect_robots=True, check_external=False, user_agent=DEFAULT_USER_AGENT,
                 on_page=None):
        if "://" not in start_url:
            start_url = "http://" + start_url
        self.start_url = normalize_url(start_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.check_external = check_external
        self.on_page = on_page
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._robots = None

    def run(self):
        started = time.monotonic()
        result = CrawlResult(start_url=self.start_url)
        if self.respect_robots:
            self._robots = self._load_robots()

        queue = deque([(self.start_url, 0)])
        seen = {self.start_url}
        external_urls = set()

        while queue and len(result.pages) < self.max_pages:
            url, depth = queue.popleft()
            if not self._allowed(url):
                result.blocked_by_robots.append(url)
                continue
            if result.pages and self.delay:
                time.sleep(self.delay)

            page, links = self._fetch(url, depth)
            result.pages.append(page)
            if self.on_page:
                self.on_page(page)

            for link in links:
                result.referrers[link].add(url)
                if not same_site(link, self.start_url):
                    external_urls.add(link)
                elif link not in seen and depth + 1 <= self.max_depth:
                    seen.add(link)
                    queue.append((link, depth + 1))

        if self.check_external:
            result.external = [self._check_link(u) for u in sorted(external_urls)]
        result.duration_s = time.monotonic() - started
        return result

    def _fetch(self, url, depth):
        page = Page(url=url, depth=depth)
        started = time.monotonic()
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            page.error = type(exc).__name__
            page.elapsed_ms = int((time.monotonic() - started) * 1000)
            return page, []
        page.elapsed_ms = int((time.monotonic() - started) * 1000)
        page.status = response.status_code
        page.final_url = normalize_url(response.url)
        page.content_type = response.headers.get("Content-Type", "").lower()
        if not page.ok or not page.is_html:
            return page, []
        # A redirect off-site must not make us crawl the other site.
        if not same_site(page.final_url, self.start_url):
            return page, []
        # Only trust the declared encoding when the server actually sent a charset;
        # otherwise let BeautifulSoup sniff it (requests would assume ISO-8859-1).
        declared = response.encoding if "charset=" in page.content_type else None
        return page, self._parse(page, response.content, declared)

    def _parse(self, page, html, encoding=None):
        soup = BeautifulSoup(html, "html.parser", from_encoding=encoding)
        if soup.title and soup.title.string:
            page.title = " ".join(soup.title.string.split())
        meta = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
        if meta and meta.get("content", "").strip():
            page.meta_description = meta["content"].strip()
        page.h1_count = len(soup.find_all("h1"))
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        page.word_count = len(soup.get_text(" ").split())

        base = page.final_url
        base_tag = soup.find("base", href=True)
        if base_tag:
            base = urljoin(base, base_tag["href"])
        links = []
        for anchor in soup.find_all("a", href=True):
            if "nofollow" in (anchor.get("rel") or []):
                continue
            link = resolve_link(base, anchor["href"])
            if link and link not in links:
                links.append(link)
        page.internal_links = sum(1 for link in links if same_site(link, self.start_url))
        page.external_links = len(links) - page.internal_links
        return links

    def _check_link(self, url):
        check = LinkCheck(url=url)
        try:
            response = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if response.status_code in (403, 405, 501):
                # Many servers reject HEAD; confirm with a streamed GET.
                response = self.session.get(url, timeout=self.timeout, stream=True)
                response.close()
            check.status = response.status_code
        except requests.exceptions.RequestException as exc:
            check.error = type(exc).__name__
        return check

    def _load_robots(self):
        parser = robotparser.RobotFileParser()
        robots_url = urljoin(self.start_url, "/robots.txt")
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
        except requests.exceptions.RequestException:
            return None
        if response.status_code != 200:
            return None
        parser.parse(response.text.splitlines())
        return parser

    def _allowed(self, url):
        if self._robots is None:
            return True
        return self._robots.can_fetch(self.session.headers["User-Agent"], url)
