import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).parent / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/go-internal":
            # Simulates a public page that redirects the crawler to an internal address.
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_address[1]}/about.html")
            self.end_headers()
            return
        super().do_GET()


@pytest.fixture(scope="session")
def site_url():
    handler = functools.partial(QuietHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    # The local test server must not be reached through any configured HTTP proxy.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
