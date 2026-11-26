"""Loopback HTTP transport with a per-install bearer token.

The port is reachable by every local process, and a browser page can attempt
DNS rebinding, so requests must carry a token and a loopback Host header.
"""

from __future__ import annotations

import secrets
from typing import Any

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from ..core.config import app_home
from ..core.service import ScholarService
from ..server import build_server

TOKEN_NAME = "http-token"
# Shorter than this is not a credential, it is a placeholder that happens to be in a file.
MIN_TOKEN_CHARS = 16


def load_token() -> str:
    """The per-install bearer token, generated on first use and validated afterwards.

    An existing file was returned as-is, so an empty one became the accepted credential: every
    request that simply omitted the header compared equal to "" (audit 2026-11-26, F12). The
    transport refuses to start on an unusable token instead of serving with a guessable one.
    """

    path = app_home() / TOKEN_NAME
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < MIN_TOKEN_CHARS or any(char.isspace() for char in token):
            raise ValueError(
                f"{path} holds an unusable token ({len(token)} characters, at least "
                f"{MIN_TOKEN_CHARS} needed): delete the file to let a new one be generated"
            )
        return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed, so a crash cannot leave a half-written credential.
    temporary = path.with_name(f"{TOKEN_NAME}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(token, encoding="utf-8")
    temporary.replace(path)
    return token


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _hostname(header: str) -> str:
    value = header.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


class TokenMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        if _hostname(headers.get("host", "")).casefold() not in LOOPBACK_HOSTS:
            await self._deny(send, 403)
            return

        authorization = headers.get("authorization", "")
        if not secrets.compare_digest(authorization, f"Bearer {self.token}"):
            await self._deny(send, 401)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send: Send, status: int) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})


def serve(service: ScholarService, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = build_server(service)
    server.settings.host = host
    server.settings.port = port
    app: Any = server.streamable_http_app()
    app.add_middleware(TokenMiddleware, token=load_token())
    uvicorn.run(app, host=host, port=port, log_level="warning")


__all__ = ["TokenMiddleware", "load_token", "serve"]
