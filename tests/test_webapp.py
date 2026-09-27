import re

import pytest

from webapp import create_app
from webapp.auth import create_user
from webapp.db import get_db

PASSWORD = "dogru-at-pil-zimba"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test-secret",
        "CRAWL_SYNC": True,
        "CRAWL_DELAY": 0,
        "ALLOW_PRIVATE_TARGETS": True,
    })
    with app.app_context():
        assert create_user("ayse", PASSWORD) is None
        assert create_user("mehmet", PASSWORD) is None
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, username="ayse", password=PASSWORD):
    return client.post("/login", data={"username": username, "password": password,
                                       "csrf_token": csrf(client)})


def start_crawl(client, url, **extra):
    data = {"url": url, "max_pages": "20", "csrf_token": csrf(client, "/")}
    data.update(extra)
    return client.post("/crawls", data=data)


def test_pages_require_login(client):
    for path in ("/", "/account", "/crawls/abc"):
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")


def test_password_is_hashed(app):
    with app.app_context():
        row = get_db().execute("SELECT password_hash FROM users WHERE username = 'ayse'").fetchone()
    assert PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_login_success_and_logout(client):
    response = login(client)
    assert response.status_code == 302 and response.headers["Location"] == "/"
    assert client.get("/").status_code == 200
    client.post("/logout", data={"csrf_token": csrf(client, "/")})
    assert client.get("/").status_code == 302


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong = login(client, password="yanlis-parola-123")
    unknown = login(client, username="yok-boyle-biri")
    assert wrong.status_code == unknown.status_code == 401
    assert "Kullanıcı adı veya parola hatalı" in wrong.get_data(as_text=True)
    assert "Kullanıcı adı veya parola hatalı" in unknown.get_data(as_text=True)


def test_lockout_after_repeated_failures(client):
    for _ in range(5):
        assert login(client, password="yanlis-parola-123").status_code == 401
    # Even the correct password is refused while locked.
    assert login(client).status_code == 429


def test_post_without_csrf_is_rejected(client):
    response = client.post("/login", data={"username": "ayse", "password": PASSWORD})
    assert response.status_code == 400
    login(client)
    assert client.post("/crawls", data={"url": "https://example.com"}).status_code == 400


def test_open_redirect_after_login_is_blocked(client):
    token = csrf(client)
    response = client.post("/login?next=//evil.example/", data={
        "username": "ayse", "password": PASSWORD, "csrf_token": token})
    assert response.headers["Location"] == "/"


def test_session_cookie_flags(client):
    response = login(client)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_security_headers(client):
    headers = client.get("/login").headers
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_signup_disabled_by_default(client):
    assert client.get("/register").status_code == 403


def test_signup_enforces_password_policy(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "s.db"), "SECRET_KEY": "x", "ALLOW_SIGNUP": True})
    client = app.test_client()
    token = csrf(client, "/register")
    weak = client.post("/register", data={"username": "zeynep", "password": "kisa",
                                          "password_confirm": "kisa", "csrf_token": token})
    assert weak.status_code == 400
    ok = client.post("/register", data={"username": "zeynep", "password": PASSWORD,
                                        "password_confirm": PASSWORD, "csrf_token": token})
    assert ok.status_code == 302
    assert login(client, "zeynep").status_code == 302


def test_password_change_logs_out_other_sessions(app):
    first, second = app.test_client(), app.test_client()
    login(first)
    login(second)
    new_password = "yepyeni-bir-parola-42"
    response = first.post("/account", data={
        "current_password": PASSWORD, "new_password": new_password,
        "new_password_confirm": new_password, "csrf_token": csrf(first, "/account")})
    assert response.status_code == 302
    assert first.get("/").status_code == 200       # the session that changed it stays in
    assert second.get("/").status_code == 302      # every other session is dropped


def test_crawl_and_report_flow(client, site_url):
    login(client)
    response = start_crawl(client, site_url)
    assert response.status_code == 302
    detail_url = response.headers["Location"]
    crawl_id = detail_url.rsplit("/", 1)[-1]
    assert len(crawl_id) == 32  # random id, not a guessable counter

    page = client.get(detail_url).get_data(as_text=True)
    assert "Tamamlandı" in page

    report = client.get(f"/crawls/{crawl_id}/report")
    assert report.status_code == 200
    csp = report.headers["Content-Security-Policy"]
    assert "sandbox" in csp and "'unsafe-inline'" not in csp and "sha256-" in csp
    assert client.get(f"/crawls/{crawl_id}/report.json").json["summary"]["broken_pages"] == 1


def test_users_cannot_see_each_others_crawls(app, site_url):
    owner, other = app.test_client(), app.test_client()
    login(owner)
    crawl_id = start_crawl(owner, site_url).headers["Location"].rsplit("/", 1)[-1]
    login(other, "mehmet")
    for path in (f"/crawls/{crawl_id}", f"/crawls/{crawl_id}/report", f"/crawls/{crawl_id}/report.json"):
        assert other.get(path).status_code == 404
    delete = other.post(f"/crawls/{crawl_id}/delete", data={"csrf_token": csrf(other, "/")})
    assert delete.status_code == 404
    assert owner.get(f"/crawls/{crawl_id}").status_code == 200
    assert site_url not in other.get("/").get_data(as_text=True)


def test_private_targets_blocked_in_production_mode(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "p.db"), "SECRET_KEY": "x", "CRAWL_SYNC": True})
    with app.app_context():
        create_user("ayse", PASSWORD)
    client = app.test_client()
    login(client)
    for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.1.2.3/"):
        response = start_crawl(client, url)
        assert response.headers["Location"] == "/"
    assert "Bu adres taranamaz" in client.get("/").get_data(as_text=True)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM crawls").fetchone()[0] == 0


def test_daily_crawl_limit(app, client, site_url):
    app.config["MAX_CRAWLS_PER_DAY"] = 2
    login(client)
    start_crawl(client, site_url)
    start_crawl(client, site_url)
    response = start_crawl(client, site_url)
    assert response.headers["Location"] == "/"
    assert "Günlük tarama sınırına" in client.get("/").get_data(as_text=True)
