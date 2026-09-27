import getpass
import logging
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import click
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import auth, crawls
from .db import close_db, init_db
from .security import check_csrf, csrf_token, load_user, prune_auth_events, set_security_headers


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _secret_key(instance_path):
    """SITECRAWLER_SECRET_KEY, or a random key persisted (mode 0600) in the instance folder."""
    key = os.environ.get("SITECRAWLER_SECRET_KEY")
    if key:
        return key
    path = Path(instance_path) / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        DATABASE=os.environ.get("SITECRAWLER_DATABASE", str(Path(app.instance_path) / "sitecrawler.db")),
        # Cookies: not readable from JS, not sent on cross-site POSTs, HTTPS-only when enabled.
        SESSION_COOKIE_NAME="sc_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_bool("SITECRAWLER_COOKIE_SECURE", False),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=64 * 1024,
        ALLOW_SIGNUP=_env_bool("SITECRAWLER_ALLOW_SIGNUP", False),
        # Only for local development: lets the panel crawl localhost / private networks.
        ALLOW_PRIVATE_TARGETS=_env_bool("SITECRAWLER_ALLOW_PRIVATE_TARGETS", False),
        TRUST_PROXY=_env_bool("SITECRAWLER_TRUST_PROXY", False),
        LOCKOUT_WINDOW=15 * 60,
        MAX_FAILS_PER_USER=5,
        MAX_FAILS_PER_IP=20,
        MAX_SIGNUPS_PER_IP_HOUR=5,
        MAX_PAGES_LIMIT=500,
        MAX_ACTIVE_CRAWLS_PER_USER=1,
        MAX_CRAWLS_PER_DAY=20,
        CRAWL_WORKERS=2,
        CRAWL_DELAY=0.3,
        CRAWL_SYNC=False,
    )
    if test_config:
        app.config.update(test_config)
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or _secret_key(app.instance_path)

    if app.config["TRUST_PROXY"]:
        # Behind exactly one reverse proxy: take client IP/scheme from its headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db(app.config["DATABASE"])

    app.register_blueprint(auth.bp)
    app.register_blueprint(crawls.bp)
    app.teardown_appcontext(close_db)
    app.before_request(load_user)
    app.before_request(check_csrf)
    app.after_request(set_security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.filters["datetime"] = lambda ts: datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")

    for code in (400, 403, 404, 405, 413, 429, 500):
        app.register_error_handler(code, _error_page)

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--admin", is_flag=True, help="Yönetici olarak işaretle.")
    def create_user_command(username, admin):
        """Yeni bir kullanıcı oluşturur (parola gizli olarak sorulur)."""
        password = getpass.getpass("Parola: ")
        if password != getpass.getpass("Parola (tekrar): "):
            raise click.ClickException("Parolalar eşleşmiyor.")
        error = auth.create_user(username, password, is_admin=admin)
        if error:
            raise click.ClickException(error)
        click.echo(f"Kullanıcı oluşturuldu: {username}")

    @app.cli.command("prune")
    def prune_command():
        """30 günden eski giriş kayıtlarını siler."""
        prune_auth_events()
        click.echo("Eski giriş kayıtları silindi.")

    return app


def _error_page(err):
    code = getattr(err, "code", 500) or 500
    # Only our own 400s (e.g. CSRF) carry a user-facing Turkish message.
    message = getattr(err, "description", None) if code == 400 else None
    return render_template("error.html", code=code, message=message), code
