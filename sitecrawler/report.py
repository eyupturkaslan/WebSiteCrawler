import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from html import escape

from .audit import ERROR, INFO, WARNING, health_score

SEVERITY_LABELS = {ERROR: "Hata", WARNING: "Uyarı", INFO: "Bilgi"}

# Kept as constants so a server can allow exactly these inline blocks via CSP hashes.
REPORT_CSS = """:root { --bg:#f7f7f8; --fg:#1b1b1f; --muted:#66666e; --card:#fff; --line:#e3e3e8;
  --err:#c62828; --warn:#b26a00; --info:#1565c0; --good:#2e7d32; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141417; --fg:#ececf1; --muted:#9a9aa3; --card:#1e1e23; --line:#2e2e35;
    --err:#ef6b6b; --warn:#f0a940; --info:#6aa8f0; --good:#5cc26a; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1200px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 12px; }
.meta { color:var(--muted); font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
.card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.card .v { font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; }
.score.good { color:var(--good); } .score.mid { color:var(--warn); } .score.bad { color:var(--err); }
ul.breakdown { list-style:none; padding:0; margin:0; display:flex; flex-wrap:wrap; gap:8px; }
ul.breakdown li { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:6px 10px; }
.sev { font-size:11px; font-weight:600; padding:2px 6px; border-radius:4px; color:#fff; }
.sev.error { background:var(--err); } .sev.warning { background:var(--warn); } .sev.info { background:var(--info); }
.filters { display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
.filters button { border:1px solid var(--line); background:var(--card); color:var(--fg);
  border-radius:6px; padding:4px 10px; cursor:pointer; font:inherit; font-size:13px; }
.filters button.on { border-color:var(--fg); }
.table-wrap { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--card); }
td.url, td.refs { word-break:break-all; min-width:220px; }
a { color:var(--info); text-decoration:none; } a:hover { text-decoration:underline; }
"""

REPORT_JS = """document.querySelectorAll('.filters button').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.filters button').forEach(b => b.classList.toggle('on', b === btn));
  const f = btn.dataset.f;
  document.querySelectorAll('#issues tbody tr').forEach(tr => {
    tr.style.display = (f === 'all' || tr.dataset.sev === f) ? '' : 'none';
  });
}));
"""


def build_summary(result, issues):
    by_severity = Counter(i.severity for i in issues)
    ok_pages = [p for p in result.pages if p.ok]
    avg_ms = round(sum(p.elapsed_ms for p in ok_pages) / len(ok_pages)) if ok_pages else 0
    return {
        "start_url": result.start_url,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "duration_s": round(result.duration_s, 2),
        "pages_crawled": len(result.pages),
        "broken_pages": sum(1 for p in result.pages if not p.ok),
        "external_checked": len(result.external),
        "blocked_by_robots": len(result.blocked_by_robots),
        "avg_response_ms": avg_ms,
        "errors": by_severity[ERROR],
        "warnings": by_severity[WARNING],
        "infos": by_severity[INFO],
        "health_score": health_score(result, issues),
    }


def to_dict(result, issues):
    return {
        "summary": build_summary(result, issues),
        "issues": [
            {"severity": i.severity, "kind": i.kind, "label": i.label, "url": i.url,
             "detail": i.detail, "referrers": i.referrers}
            for i in issues
        ],
        "pages": [asdict(p) for p in result.pages],
        "external": [asdict(c) for c in result.external],
        "blocked_by_robots": result.blocked_by_robots,
    }


def write_json(path, result, issues):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_dict(result, issues), fh, ensure_ascii=False, indent=2)


def write_html(path, result, issues):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(result, issues))


def _link(url):
    u = escape(url)
    return f'<a href="{u}" target="_blank" rel="noopener">{u}</a>'


def render_html(result, issues):
    s = build_summary(result, issues)
    score = s["health_score"]
    score_class = "good" if score >= 80 else "mid" if score >= 50 else "bad"

    cards = [
        ("Sağlık puanı", f'<span class="score {score_class}">{score}</span>'),
        ("Taranan sayfa", s["pages_crawled"]),
        ("Kırık sayfa", s["broken_pages"]),
        ("Hata", s["errors"]),
        ("Uyarı", s["warnings"]),
        ("Ort. yanıt", f'{s["avg_response_ms"]} ms'),
    ]
    cards_html = "".join(
        f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in cards
    )

    kind_counts = Counter((i.severity, i.label) for i in issues)
    breakdown = "".join(
        f'<li><span class="sev {sev}">{SEVERITY_LABELS[sev]}</span> {escape(label)} '
        f'<b>{n}</b></li>'
        for (sev, label), n in sorted(kind_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ) or "<li>Sorun bulunamadı 🎉</li>"

    issue_rows = "".join(
        f'<tr data-sev="{i.severity}"><td><span class="sev {i.severity}">'
        f'{SEVERITY_LABELS[i.severity]}</span></td><td>{escape(i.label)}</td>'
        f'<td class="url">{_link(i.url)}</td><td>{escape(i.detail)}</td>'
        f'<td class="refs">{"<br>".join(_link(r) for r in i.referrers[:5])}'
        f'{f"<br>+{len(i.referrers) - 5} daha" if len(i.referrers) > 5 else ""}</td></tr>'
        for i in issues
    )

    page_rows = "".join(
        f'<tr><td class="url">{_link(p.url)}</td><td>{p.status or escape(p.error or "")}</td>'
        f'<td>{p.depth}</td><td>{p.elapsed_ms}</td><td>{escape(p.title or "—")}</td>'
        f'<td>{p.word_count}</td><td>{p.internal_links}/{p.external_links}</td></tr>'
        for p in result.pages
    )

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Site Denetim Raporu — {escape(result.start_url)}</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<main>
<h1>Site Denetim Raporu</h1>
<div class="meta">{_link(result.start_url)} · {s["generated_at"]} · {s["duration_s"]} sn ·
robots.txt ile engellenen: {s["blocked_by_robots"]} · kontrol edilen dış link: {s["external_checked"]}</div>
<div class="cards">{cards_html}</div>

<h2>Sorun dağılımı</h2>
<ul class="breakdown">{breakdown}</ul>

<h2>Sorunlar ({len(issues)})</h2>
<div class="filters">
  <button class="on" data-f="all">Tümü</button>
  <button data-f="error">Hatalar</button>
  <button data-f="warning">Uyarılar</button>
  <button data-f="info">Bilgi</button>
</div>
<div class="table-wrap"><table id="issues">
<thead><tr><th>Seviye</th><th>Tür</th><th>URL</th><th>Detay</th><th>Link veren sayfalar</th></tr></thead>
<tbody>{issue_rows}</tbody></table></div>

<h2>Sayfalar ({len(result.pages)})</h2>
<div class="table-wrap"><table>
<thead><tr><th>URL</th><th>Durum</th><th>Derinlik</th><th>ms</th><th>Başlık</th><th>Kelime</th><th>İç/Dış link</th></tr></thead>
<tbody>{page_rows}</tbody></table></div>
</main>
<script>{REPORT_JS}</script>
</body>
</html>
"""
