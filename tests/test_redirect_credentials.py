"""A credential goes to the origin it was configured for, not where a redirect points.

urllib's default redirect handler copies request headers, `Authorization`
included, to whatever `Location` names. Both network adapters send a bearer
credential, so a redirect to another host would hand it over.
"""
from __future__ import annotations

import http.server
import threading
import unittest
from typing import Any

from atlas_core.adapters.github_reader import GitHubRepoAdapter
from atlas_core.adapters.live_model import UrllibTransport


class _Server(http.server.BaseHTTPRequestHandler):
    """`/start` redirects to `/next` on `redirect_host` and this server's port."""

    seen: list[str | None]
    redirect_host: str
    port: int

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", f"http://{self.redirect_host}:{self.port}/next")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.seen.append(self.headers.get("Authorization"))
        body = b'{"ok": 1}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, format: str, *args: Any) -> None:
        pass


class RedirectCase(unittest.TestCase):
    def redirect_to(self, host: str) -> str:
        """A URL on 127.0.0.1 that redirects to `host` on the same port."""
        self.seen: list[str | None] = []

        class Handler(_Server):
            pass

        Handler.seen, Handler.redirect_host = self.seen, host
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        Handler.port = server.server_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/start"

    def model_post(self, url: str) -> None:
        UrllibTransport().post(url, {"x": 1}, {"Authorization": "Bearer model-key"}, 5)

    def github_get(self, url: str) -> None:
        adapter = GitHubRepoAdapter("owner/name")
        adapter.token = "github-token"
        with adapter._request(url, timeout=5) as response:
            response.read()


class TestACrossHostRedirectDropsTheCredential(RedirectCase):
    def test_model_transport(self) -> None:
        self.model_post(self.redirect_to("localhost"))
        self.assertEqual(self.seen, [None])

    def test_github_reader(self) -> None:
        self.github_get(self.redirect_to("localhost"))
        self.assertEqual(self.seen, [None])


class TestASameOriginRedirectKeepsIt(RedirectCase):
    """GitHub answers a renamed repository with a redirect on the same host."""

    def test_model_transport(self) -> None:
        self.model_post(self.redirect_to("127.0.0.1"))
        self.assertEqual(self.seen, ["Bearer model-key"])

    def test_github_reader(self) -> None:
        self.github_get(self.redirect_to("127.0.0.1"))
        self.assertEqual(self.seen, ["Bearer github-token"])


if __name__ == "__main__":
    unittest.main()
