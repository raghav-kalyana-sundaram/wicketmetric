"""
Vercel Python service entrypoint for Cricket Metrics API.

When using Vercel Services with ``routePrefix: /api``, the platform forwards
requests to this ASGI app with the ``/api`` segment removed (e.g. ``/search``
instead of ``/api/search``). Our FastAPI routes are registered under ``/api``,
so this wrapper prepends ``/api`` back onto HTTP paths before delegating.

The exposed ASGI application must be named ``app`` for Vercel detection.
"""

from __future__ import annotations

import json
import os
import sys
import time
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


def _normalize_api_path(path: str) -> str:
    """Ensure ASGI path matches FastAPI routes under ``/api/…``.

    Vercel Services (``routePrefix: /api``) usually strips ``/api`` so we see
    ``/meta`` or ``/search``. Some stacks send ``api/meta`` without a leading
    slash; the old logic turned that into ``/api/api/meta`` (404).
    """
    if path in ("", "/"):
        return path
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    if not path.startswith("/api"):
        path = f"/api{path}"
    return path


class _RestoreApiPrefix:
    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            orig = scope.get("path") or ""
            path = _normalize_api_path(orig)
            # #region agent log
            _risky = orig not in ("", "/") and not orig.startswith("/")
            if _risky or os.environ.get("CM_DEBUG_ASGI_PATH") == "1":
                payload = {
                    "sessionId": "06591a",
                    "location": "vercel_entry.py:_RestoreApiPrefix",
                    "message": "asgi_path_rewrite",
                    "data": {"orig": orig, "normalized": path, "risky_leading_slash": _risky},
                    "timestamp": int(time.time() * 1000),
                    "hypothesisId": "H_path",
                }
                _repo = Path(__file__).resolve().parents[2]
                try:
                    with open(
                        _repo / ".cursor" / "debug-06591a.log",
                        "a",
                        encoding="utf-8",
                    ) as f:
                        f.write(json.dumps(payload) + "\n")
                except OSError:
                    pass
                if os.environ.get("CM_DEBUG_ASGI_PATH") == "1":
                    print(
                        json.dumps({"cm_asgi_path": payload["data"]}),
                        file=sys.stderr,
                        flush=True,
                    )
            # #endregion
            if path != orig:
                scope = dict(scope)
                scope["path"] = path
                scope["raw_path"] = path.encode("utf-8")
        await self.app(scope, receive, send)


import app as _app_module  # noqa: E402

app = _RestoreApiPrefix(_app_module.app)
