from collections import defaultdict
from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"
INFO = "info"
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

TITLE_MAX = 60
DESCRIPTION_MAX = 160
THIN_CONTENT_WORDS = 100

# kind -> (severity, Turkish label shown in reports)
KINDS = {
    "broken_page": (ERROR, "Kırık sayfa"),
    "broken_external": (ERROR, "Kırık dış link"),
    "missing_title": (ERROR, "Başlık (title) eksik"),
    "duplicate_title": (WARNING, "Tekrar eden başlık"),
    "missing_description": (WARNING, "Meta açıklama eksik"),
    "duplicate_description": (WARNING, "Tekrar eden meta açıklama"),
    "missing_h1": (WARNING, "H1 eksik"),
    "slow_page": (WARNING, "Yavaş sayfa"),
    "long_title": (INFO, "Başlık çok uzun"),
    "long_description": (INFO, "Meta açıklama çok uzun"),
    "multiple_h1": (INFO, "Birden fazla H1"),
    "thin_content": (INFO, "Az içerik"),
    "redirect": (INFO, "Yönlendirme"),
}


@dataclass
class Issue:
    kind: str
    url: str
    detail: str = ""
    referrers: list[str] = field(default_factory=list)

    @property
    def severity(self):
        return KINDS[self.kind][0]

    @property
    def label(self):
        return KINDS[self.kind][1]


def audit(result, slow_ms=1500):
    """Inspect a CrawlResult and return a list of Issues, most severe first."""
    issues = []

    def add(kind, url, detail=""):
        issues.append(Issue(kind, url, detail, sorted(result.referrers.get(url, ()))))

    titles = defaultdict(list)
    descriptions = defaultdict(list)

    for page in result.pages:
        if not page.ok:
            add("broken_page", page.url, page.error or f"HTTP {page.status}")
            continue
        if page.redirected:
            add("redirect", page.url, f"→ {page.final_url}")
        if page.elapsed_ms > slow_ms:
            add("slow_page", page.url, f"{page.elapsed_ms} ms")
        if not page.is_html:
            continue

        if not page.title:
            add("missing_title", page.url)
        else:
            titles[page.title].append(page.url)
            if len(page.title) > TITLE_MAX:
                add("long_title", page.url, f"{len(page.title)} karakter")

        if not page.meta_description:
            add("missing_description", page.url)
        else:
            descriptions[page.meta_description].append(page.url)
            if len(page.meta_description) > DESCRIPTION_MAX:
                add("long_description", page.url, f"{len(page.meta_description)} karakter")

        if page.h1_count == 0:
            add("missing_h1", page.url)
        elif page.h1_count > 1:
            add("multiple_h1", page.url, f"{page.h1_count} adet")

        if page.word_count < THIN_CONTENT_WORDS:
            add("thin_content", page.url, f"{page.word_count} kelime")

    for kind, groups in (("duplicate_title", titles), ("duplicate_description", descriptions)):
        for text, urls in groups.items():
            if len(urls) > 1:
                for url in urls:
                    add(kind, url, f"“{text}” — {len(urls)} sayfada")

    for check in result.external:
        if not check.ok:
            add("broken_external", check.url, check.error or f"HTTP {check.status}")

    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.kind, i.url))
    return issues


def health_score(result, issues):
    """0-100 score: starts at 100, errors cost more than warnings; scaled by site size."""
    if not result.pages:
        return 0
    penalty = sum({ERROR: 10, WARNING: 3, INFO: 0.5}[i.severity] for i in issues)
    return max(0, round(100 - penalty / len(result.pages) * 5))
