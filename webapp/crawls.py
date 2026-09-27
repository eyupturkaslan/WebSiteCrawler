import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request,
                   url_for)

from sitecrawler.audit import audit
from sitecrawler.crawler import Crawler
from sitecrawler.netguard import BlockedURL, URLGuard
from sitecrawler.report import build_summary, render_html, to_dict

from .db import connect, get_db
from .security import REPORT_CSP, login_required

bp = Blueprint("crawls", __name__)
log = logging.getLogger("webapp.crawls")

_executor = None


def _get_executor(app):
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=app.config["CRAWL_WORKERS"], thread_name_prefix="crawl")
    return _executor


def _guard(app):
    return None if app.config["ALLOW_PRIVATE_TARGETS"] else URLGuard()


def _int_field(name, default, low, high):
    try:
        value = int(request.form.get(name, default))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _get_own_crawl(crawl_id):
    # Always scoped to the logged-in user: other users' crawls are indistinguishable from missing ones.
    crawl = get_db().execute(
        "SELECT * FROM crawls WHERE id = ? AND user_id = ?", (crawl_id, g.user["id"])
    ).fetchone()
    if crawl is None:
        abort(404)
    return crawl


@bp.get("/")
@login_required
def dashboard():
    crawls = get_db().execute(
        "SELECT id, url, status, error, pages_crawled, health_score, errors, warnings, created_at "
        "FROM crawls WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
        (g.user["id"],),
    ).fetchall()
    return render_template("dashboard.html", crawls=crawls, limits=current_app.config)


@bp.post("/crawls")
@login_required
def start():
    cfg = current_app.config
    url = request.form.get("url", "").strip()
    if "://" not in url:
        url = "https://" + url
    if len(url) > 2048:
        flash("Adres çok uzun.", "error")
        return redirect(url_for(".dashboard"))
    guard = _guard(current_app)
    if guard is not None:
        try:
            guard.check(url)
        except BlockedURL as exc:
            flash(f"Bu adres taranamaz: {exc}", "error")
            return redirect(url_for(".dashboard"))

    db = get_db()
    uid = g.user["id"]
    # Take the write lock before counting so parallel requests can't both slip under the limits.
    db.execute("BEGIN IMMEDIATE")
    active = db.execute(
        "SELECT COUNT(*) FROM crawls WHERE user_id = ? AND status IN ('queued', 'running')", (uid,)
    ).fetchone()[0]
    if active >= cfg["MAX_ACTIVE_CRAWLS_PER_USER"]:
        flash("Zaten devam eden bir taramanız var; bitmesini bekleyin.", "error")
        return redirect(url_for(".dashboard"))
    today = db.execute(
        "SELECT COUNT(*) FROM crawls WHERE user_id = ? AND created_at > ?", (uid, time.time() - 86400)
    ).fetchone()[0]
    if today >= cfg["MAX_CRAWLS_PER_DAY"]:
        flash(f"Günlük tarama sınırına ({cfg['MAX_CRAWLS_PER_DAY']}) ulaştınız.", "error")
        return redirect(url_for(".dashboard"))

    options = {
        "max_pages": _int_field("max_pages", 100, 1, cfg["MAX_PAGES_LIMIT"]),
        "max_depth": _int_field("max_depth", 5, 0, 10),
        "check_external": request.form.get("check_external") == "on",
    }
    crawl_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO crawls (id, user_id, url, options, status, created_at) VALUES (?, ?, ?, ?, 'queued', ?)",
        (crawl_id, uid, url, json.dumps(options), time.time()),
    )
    db.commit()
    log.info("crawl queued id=%s user=%s url=%s", crawl_id, g.user["username"], url)

    app = current_app._get_current_object()
    if cfg["CRAWL_SYNC"]:
        run_crawl(app, crawl_id)
    else:
        _get_executor(app).submit(run_crawl, app, crawl_id)
    return redirect(url_for(".detail", crawl_id=crawl_id))


def run_crawl(app, crawl_id):
    conn = connect(app.config["DATABASE"])
    try:
        row = conn.execute("SELECT url, options FROM crawls WHERE id = ?", (crawl_id,)).fetchone()
        if row is None:
            return
        conn.execute("UPDATE crawls SET status = 'running' WHERE id = ?", (crawl_id,))
        conn.commit()
        options = json.loads(row["options"])
        crawler = Crawler(
            row["url"],
            max_pages=options["max_pages"],
            max_depth=options["max_depth"],
            check_external=options["check_external"],
            delay=app.config["CRAWL_DELAY"],
            timeout=10,
            guard=_guard(app),
        )
        result = crawler.run()
        issues = audit(result)
        summary = build_summary(result, issues)
        conn.execute(
            "UPDATE crawls SET status = 'done', pages_crawled = ?, health_score = ?, errors = ?, "
            "warnings = ?, report_html = ?, report_json = ?, finished_at = ? WHERE id = ?",
            (summary["pages_crawled"], summary["health_score"], summary["errors"], summary["warnings"],
             render_html(result, issues), json.dumps(to_dict(result, issues), ensure_ascii=False),
             time.time(), crawl_id),
        )
        conn.commit()
    except Exception:
        log.exception("crawl failed id=%s", crawl_id)
        # Don't leak internals to the user; details are in the server log.
        conn.execute(
            "UPDATE crawls SET status = 'failed', error = 'Beklenmeyen bir hata oluştu', finished_at = ? "
            "WHERE id = ?",
            (time.time(), crawl_id),
        )
        conn.commit()
    finally:
        conn.close()


@bp.get("/crawls/<crawl_id>")
@login_required
def detail(crawl_id):
    crawl = _get_own_crawl(crawl_id)
    return render_template("crawl.html", crawl=crawl, options=json.loads(crawl["options"]))


@bp.get("/crawls/<crawl_id>/report")
@login_required
def report(crawl_id):
    crawl = _get_own_crawl(crawl_id)
    if crawl["status"] != "done":
        abort(404)
    response = Response(crawl["report_html"], mimetype="text/html")
    response.headers["Content-Security-Policy"] = REPORT_CSP
    return response


@bp.get("/crawls/<crawl_id>/report.json")
@login_required
def report_json(crawl_id):
    crawl = _get_own_crawl(crawl_id)
    if crawl["status"] != "done":
        abort(404)
    response = Response(crawl["report_json"], mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="rapor-{crawl_id[:8]}.json"'
    return response


@bp.post("/crawls/<crawl_id>/delete")
@login_required
def delete(crawl_id):
    crawl = _get_own_crawl(crawl_id)
    if crawl["status"] in ("queued", "running"):
        flash("Devam eden bir tarama silinemez.", "error")
        return redirect(url_for(".detail", crawl_id=crawl_id))
    db = get_db()
    db.execute("DELETE FROM crawls WHERE id = ? AND user_id = ?", (crawl_id, g.user["id"]))
    db.commit()
    flash("Tarama silindi.", "info")
    return redirect(url_for(".dashboard"))
