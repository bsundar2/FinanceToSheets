"""Serves the P&L tracker (Swing Trading) at / behind a password, on Render:

    uvicorn --factory src.dashboard_server:create_app --host 0.0.0.0 --port $PORT

The password is FINANCE_TOKEN. PasswordGate below is used instead of marimo's
own login (`--token-password`) so the same gate code serves the P&L tracker
and the Yearly Overview / Net Worth site (FinanceDashboards), which keeps a
copy: one signed cookie valid for every path, and websockets without it are
closed."""

import asyncio
import hashlib
import hmac
import html
import os
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote

import marimo
from itsdangerous import BadSignature, TimestampSigner

_SRC = Path(__file__).parent
PASSWORD_ENV_VAR = "FINANCE_TOKEN"
COOKIE_NAME = "dashboard_session"
# Log in again daily; checked on the server too, not only by the browser
COOKIE_MAX_AGE = 24 * 60 * 60
LOGIN_PATH = "/login"
# Slows down guessing; a person barely notices it on a typo
FAILED_LOGIN_DELAY_SECONDS = 1.0

_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finance dashboards</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #0a0c0f; color: #c8d0e0; font-family: 'IBM Plex Mono', monospace; }}
  form {{ display: grid; gap: 0.8rem; width: min(22rem, 100% - 2rem); }}
  h1 {{ font-size: 1rem; letter-spacing: 0.14em; text-transform: uppercase; color: #e8edf5; margin: 0; }}
  input, button {{ font: inherit; padding: 0.6rem 0.8rem; border-radius: 3px; }}
  input {{ background: #111318; color: #e8edf5; border: 1px solid #1e2330; }}
  button {{ background: #E8890C; color: #0a0c0f; border: 0; cursor: pointer; }}
  .error {{ color: #ff4d6a; font-size: 0.85rem; }}
</style></head>
<body><form method="post" action="{action}">
  <h1>⬡ Finance dashboards</h1>
  <input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
  {error}
  <button type="submit">Log in</button>
</form></body></html>"""


def _safe_next(target: str) -> str:
    """Only same-site paths, so the login page can't be used to redirect
    someone to another site."""
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


class PasswordGate:
    """ASGI middleware: every HTTP request and websocket needs a cookie
    signed with a key derived from the password (so changing the password
    logs everyone out), except the login page itself."""

    def __init__(self, app, password: str):
        self.app = app
        self.password = password.encode()
        key = hashlib.sha256(b"dashboard-cookie:" + self.password).hexdigest()
        self.signer = TimestampSigner(key)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"] == LOGIN_PATH:
            await self._login(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        target = scope["path"] + (
            "?" + scope["query_string"].decode() if scope["query_string"] else ""
        )
        await self._respond(
            send,
            303,
            headers=[(b"location", f"{LOGIN_PATH}?next={quote(target)}".encode())],
        )

    def _authorized(self, scope) -> bool:
        cookie = SimpleCookie(_header(scope, b"cookie"))
        if COOKIE_NAME not in cookie:
            return False
        try:
            self.signer.unsign(cookie[COOKIE_NAME].value, max_age=COOKIE_MAX_AGE)
            return True
        except BadSignature:
            return False

    async def _login(self, scope, receive, send):
        query = parse_qs(scope["query_string"].decode())
        target = _safe_next(query.get("next", ["/"])[0])
        action = f"{LOGIN_PATH}?next={quote(target)}"
        if scope["method"] != "POST":
            await self._page(send, action)
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        password = parse_qs(body.decode()).get("password", [""])[0].encode()
        if not hmac.compare_digest(password, self.password):
            await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
            await self._page(send, action, error="Wrong password")
            return
        cookie = (
            f"{COOKIE_NAME}={self.signer.sign(b'ok').decode()}; Path=/; "
            f"Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax"
        )
        # Render terminates TLS in front of the app, so look at the header it
        # forwards rather than the (plain HTTP) connection itself
        if _header(scope, b"x-forwarded-proto") == "https":
            cookie += "; Secure"
        await self._respond(
            send, 303,
            headers=[(b"location", target.encode()), (b"set-cookie", cookie.encode())],
        )  # fmt: skip

    async def _page(self, send, action: str, error: str = ""):
        page = _LOGIN_PAGE.format(
            action=html.escape(action),
            error=f'<div class="error">{error}</div>' if error else "",
        )
        await self._respond(
            send, 401 if error else 200, page.encode(),
            [(b"content-type", b"text/html; charset=utf-8")],
        )  # fmt: skip

    @staticmethod
    async def _respond(send, status: int, body: bytes = b"", headers=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", str(len(body)).encode()), *headers]})  # fmt: skip
        await send({"type": "http.response.body", "body": body})


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def create_app():
    """The ASGI app uvicorn serves (with --factory, so importing this module
    doesn't need the password set)."""
    password = os.environ.get(PASSWORD_ENV_VAR)
    if not password:
        # Refuse to serve personal finances without a password
        raise RuntimeError(f"Set {PASSWORD_ENV_VAR} to the dashboards' password")
    dashboards = (
        marimo.create_asgi_app()
        .with_app(path="", root=str(_SRC / "pnl_tracker.py"))
        .build()
    )
    return PasswordGate(dashboards, password)
