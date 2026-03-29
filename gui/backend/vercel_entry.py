"""
Vercel Python service entrypoint for Cricket Metrics API.

When using Vercel Services with ``routePrefix: /api``, the platform forwards
requests to this ASGI app with the ``/api`` segment removed (e.g. ``/search``
instead of ``/api/search``). Our FastAPI routes are registered under ``/api``,
so this wrapper prepends ``/api`` back onto HTTP paths before delegating.

The exposed ASGI application must be named ``app`` for Vercel detection.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

# ASGI types (avoid importing starlette before deps are installed)
Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Ensure sibling ``app.py`` is importable when the service cwd differs.
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


class _RestoreApiPrefix:
    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if path not in ("", "/") and not path.startswith("/api"):
                scope = dict(scope)
                scope["path"] = f"/api{path}" if path.startswith("/") else f"/api/{path}"
                scope["raw_path"] = scope["path"].encode("utf-8")
        await self.app(scope, receive, send)


import app as _app_module  # noqa: E402

app = _RestoreApiPrefix(_app_module.app)
