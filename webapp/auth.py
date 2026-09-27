import logging
import re
import time

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import (login_locked, login_required, login_user, password_problem, record_auth_event,
                       safe_next, signup_limited)

bp = Blueprint("auth", __name__)
log = logging.getLogger("webapp.auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
# Compared against when the username does not exist, so both paths take the same time.
_DUMMY_HASH = generate_password_hash("timing-equaliser-not-a-real-password")
GENERIC_LOGIN_ERROR = "Kullanıcı adı veya parola hatalı."


def create_user(username, password, is_admin=False):
    """Validate and insert a user; returns an error message or None."""
    if not USERNAME_RE.match(username):
        return "Kullanıcı adı 3-32 karakter olmalı; harf, rakam, _ . - kullanılabilir."
    problem = password_problem(password, username)
    if problem:
        return problem
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return "Bu kullanıcı adı alınmış."
    db.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, generate_password_hash(password), int(is_admin), time.time()),
    )
    db.commit()
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("crawls.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")[:256]
        if login_locked(username):
            log.warning("login blocked (rate limit) user=%r ip=%s", username, request.remote_addr)
            flash("Çok fazla başarısız deneme. Lütfen birkaç dakika sonra tekrar deneyin.", "error")
            return render_template("login.html", username=username), 429

        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
        if user is None or not valid:
            record_auth_event("login_fail", username.lower())
            log.info("login failed user=%r ip=%s", username, request.remote_addr)
            flash(GENERIC_LOGIN_ERROR, "error")
            return render_template("login.html", username=username), 401

        record_auth_event("login_ok", username.lower())
        log.info("login ok user=%r ip=%s", username, request.remote_addr)
        login_user(user)
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", username="")


@bp.post("/logout")
def logout():
    session.clear()
    flash("Çıkış yapıldı.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config["ALLOW_SIGNUP"]:
        return render_template("signup_closed.html"), 403
    if request.method == "POST":
        if signup_limited():
            flash("Bu adresten çok fazla kayıt denemesi yapıldı. Daha sonra tekrar deneyin.", "error")
            return render_template("register.html", username=""), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if password != request.form.get("password_confirm", ""):
            error = "Parolalar eşleşmiyor."
        else:
            error = create_user(username, password)
        if error:
            flash(error, "error")
            return render_template("register.html", username=username), 400
        record_auth_event("signup", username.lower())
        flash("Hesap oluşturuldu, şimdi giriş yapabilirsiniz.", "info")
        return redirect(url_for("auth.login"))
    return render_template("register.html", username="")


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not check_password_hash(g.user["password_hash"], current):
            flash("Mevcut parola hatalı.", "error")
        elif new != request.form.get("new_password_confirm", ""):
            flash("Yeni parolalar eşleşmiyor.", "error")
        elif problem := password_problem(new, g.user["username"]):
            flash(problem, "error")
        else:
            db = get_db()
            # Bumping session_version logs out every other session of this user.
            db.execute(
                "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                (generate_password_hash(new), g.user["id"]),
            )
            db.commit()
            login_user(db.execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone())
            flash("Parola değiştirildi. Diğer tüm oturumlar kapatıldı.", "info")
            return redirect(url_for("auth.account"))
    return render_template("account.html")


@bp.post("/account/logout-all")
@login_required
def logout_all():
    db = get_db()
    db.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    flash("Tüm cihazlardaki oturumlar kapatıldı.", "info")
    return redirect(url_for("auth.login"))
