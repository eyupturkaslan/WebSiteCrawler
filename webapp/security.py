import base64
import functools
import hashlib
import hmac
import secrets
import time

from flask import abort, current_app, g, redirect, request, session, url_for

from sitecrawler.report import REPORT_CSS, REPORT_JS

from .db import get_db

COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456789", "1234567890", "qwertyuiop",
    "iloveyou", "sifre1234", "parola1234", "1q2w3e4r5t", "qwerty1234", "admin12345",
}

APP_CSP = ("default-src 'self'; script-src 'none'; object-src 'none'; base-uri 'none'; "
           "form-action 'self'; frame-ancestors 'none'; img-src 'self'")


def _sha256_source(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


# Reports are generated HTML containing text scraped from arbitrary websites. They are
# escaped when rendered, and as a second line of defence the only inline code the browser
# will run is the exact stylesheet and script shipped with the report template.
REPORT_CSP = (f"default-src 'none'; style-src {_sha256_source(REPORT_CSS)}; "
              f"script-src {_sha256_source(REPORT_JS)}; base-uri 'none'; form-action 'none'; "
              "frame-ancestors 'none'; sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox")


# --- passwords ---------------------------------------------------------------------------

def password_problem(password, username=""):
    """Return a Turkish error message if the password is too weak, else None."""
    if len(password) < 10:
        return "Parola en az 10 karakter olmalı."
    if len(password) > 128:
        return "Parola en fazla 128 karakter olabilir."
    if password.lower() in COMMON_PASSWORDS or len(set(password)) < 5:
        return "Bu parola çok kolay tahmin edilir."
    if username and username.lower() in password.lower():
        return "Parola kullanıcı adını içermemeli."
    return None


# --- CSRF -------------------------------------------------------------------------------

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = session.get("csrf")
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, "Geçersiz veya eksik CSRF anahtarı. Sayfayı yenileyip tekrar deneyin.")


# --- session / login ----------------------------------------------------------------------

def load_user():
    g.user = None
    uid = session.get("uid")
    if uid is None:
        return
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None or user["session_version"] != session.get("ver"):
        session.clear()
        return
    g.user = user


def login_user(user):
    # Fresh session on login: prevents session fixation and rotates the CSRF token.
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["ver"] = user["session_version"]
    csrf_token()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target):
    """Only allow local redirect targets after login (no open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("crawls.dashboard")


# --- brute-force protection ----------------------------------------------------------------

def record_auth_event(kind, username=None):
    db = get_db()
    db.execute("INSERT INTO auth_events (kind, username, ip, ts) VALUES (?, ?, ?, ?)",
               (kind, username, request.remote_addr, time.time()))
    db.commit()


def _count(kind, column, value, window):
    return get_db().execute(
        f"SELECT COUNT(*) FROM auth_events WHERE kind = ? AND {column} = ? AND ts > ?",
        (kind, value, time.time() - window),
    ).fetchone()[0]


def login_locked(username):
    cfg = current_app.config
    window = cfg["LOCKOUT_WINDOW"]
    return (_count("login_fail", "username", username.lower(), window) >= cfg["MAX_FAILS_PER_USER"]
            or _count("login_fail", "ip", request.remote_addr, window) >= cfg["MAX_FAILS_PER_IP"])


def signup_limited():
    return _count("signup", "ip", request.remote_addr, 3600) >= current_app.config["MAX_SIGNUPS_PER_IP_HOUR"]


def prune_auth_events():
    db = get_db()
    db.execute("DELETE FROM auth_events WHERE ts < ?", (time.time() - 30 * 86400,))
    db.commit()


# --- response headers -----------------------------------------------------------------------

def set_security_headers(response):
    headers = response.headers
    headers.setdefault("Content-Security-Policy", APP_CSP)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "no-referrer")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if current_app.config["SESSION_COOKIE_SECURE"]:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if g.get("user") is not None or request.endpoint in ("auth.login", "auth.register"):
        headers["Cache-Control"] = "no-store"
    return response
