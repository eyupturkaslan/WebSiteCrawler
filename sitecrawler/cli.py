import argparse
import sys

from .audit import ERROR, WARNING, audit
from .crawler import Crawler
from .report import build_summary, write_html, write_json


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="sitecrawler",
        description="Bir web sitesini tarar; kırık linkleri ve SEO sorunlarını raporlar.",
    )
    parser.add_argument("url", help="Taramaya başlanacak adres, ör. https://example.com")
    parser.add_argument("--max-pages", type=int, default=200, help="En fazla taranacak sayfa (varsayılan: 200)")
    parser.add_argument("--max-depth", type=int, default=5, help="Başlangıçtan en fazla link derinliği (varsayılan: 5)")
    parser.add_argument("--delay", type=float, default=0.2, help="İstekler arası bekleme, saniye (varsayılan: 0.2)")
    parser.add_argument("--timeout", type=float, default=10.0, help="İstek zaman aşımı, saniye (varsayılan: 10)")
    parser.add_argument("--slow-ms", type=int, default=1500, help="Bu süreyi aşan sayfalar yavaş sayılır (varsayılan: 1500)")
    parser.add_argument("--check-external", action="store_true", help="Dış linklerin çalışıp çalışmadığını da kontrol et")
    parser.add_argument("--ignore-robots", action="store_true", help="robots.txt kurallarını yok say")
    parser.add_argument("--html", default="report.html", help="HTML rapor dosyası (varsayılan: report.html)")
    parser.add_argument("--json", help="İsteğe bağlı JSON rapor dosyası")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="Hata seviyesinde sorun varsa çıkış kodu 1 döndür (CI için)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Taranan her sayfayı yazdırma")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    def on_page(page):
        if not args.quiet:
            status = page.status if page.status is not None else page.error
            print(f"[{status}] {page.url}", flush=True)

    crawler = Crawler(
        args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        timeout=args.timeout,
        respect_robots=not args.ignore_robots,
        check_external=args.check_external,
        on_page=on_page,
    )
    result = crawler.run()
    issues = audit(result, slow_ms=args.slow_ms)
    summary = build_summary(result, issues)

    if args.html:
        write_html(args.html, result, issues)
    if args.json:
        write_json(args.json, result, issues)

    print()
    print(f"Taranan sayfa : {summary['pages_crawled']} ({summary['duration_s']} sn)")
    print(f"Kırık sayfa   : {summary['broken_pages']}")
    print(f"Hata / Uyarı  : {summary['errors']} / {summary['warnings']}")
    print(f"Sağlık puanı  : {summary['health_score']}/100")
    for issue in [i for i in issues if i.severity in (ERROR, WARNING)][:10]:
        print(f"  - {issue.label}: {issue.url} {issue.detail}".rstrip())
    for path in (args.html, args.json):
        if path:
            print(f"Rapor yazıldı : {path}")

    if args.fail_on_error and summary["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
