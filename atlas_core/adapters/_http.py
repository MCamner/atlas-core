"""One opener for the adapters that send a credential.

urllib's default redirect handler copies request headers to wherever
`Location` points, `Authorization` included. A credential configured for one
origin then reaches another host, or the same host over plain HTTP. This
opener follows redirects as before but drops `Authorization` when the scheme,
host or port changes. A same-origin redirect, which GitHub uses for a renamed
repository, keeps it.
"""
from __future__ import annotations

from typing import IO, Any
from urllib.parse import urlsplit
import urllib.request


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port


class _SameOriginCredentials(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str,
        headers: Any, newurl: str,
    ) -> urllib.request.Request | None:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(new.full_url) != _origin(req.full_url):
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_SameOriginCredentials)


def urlopen(request: urllib.request.Request, *, timeout: float) -> Any:
    """`urllib.request.urlopen`, without carrying credentials across origins."""
    return _OPENER.open(request, timeout=timeout)
