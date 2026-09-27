"""A provider's reply is read up to a bound, not to its end.

The transport used to read the whole body before parsing, so an endpoint that
kept sending could grow memory without limit inside the run.
"""
from __future__ import annotations

import http.server
import threading
import unittest
from typing import Any

from atlas_core.adapters.live_model import ProviderBadResponse, UrllibTransport


class _Reply(http.server.BaseHTTPRequestHandler):
    body: bytes

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class TestTheReplyIsBounded(unittest.TestCase):
    def serve(self, body: bytes) -> str:
        class Handler(_Reply):
            pass

        Handler.body = body
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/"

    def transport(self, limit: int) -> UrllibTransport:
        transport = UrllibTransport()
        transport.max_response_bytes = limit
        return transport

    def test_a_reply_within_the_bound_is_read(self) -> None:
        url = self.serve(b'{"ok": 1}')
        self.assertEqual(self.transport(64).post(url, {}, {}, 5), {"ok": 1})

    def test_a_reply_over_the_bound_is_refused(self) -> None:
        url = self.serve(b'{"text": "' + b"x" * 200 + b'"}')
        with self.assertRaises(ProviderBadResponse):
            self.transport(64).post(url, {}, {}, 5)

    def test_the_default_bound_is_finite(self) -> None:
        self.assertGreater(UrllibTransport.max_response_bytes, 0)
        self.assertLessEqual(UrllibTransport.max_response_bytes, 16 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
