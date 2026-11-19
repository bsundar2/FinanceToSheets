import pytest

pytest.importorskip("httpx")  # starlette's TestClient needs it

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src import dashboard_server as ds


async def _websocket(websocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()


_DASHBOARDS = Starlette(
    routes=[
        Route("/", lambda request: PlainTextResponse("finance")),
        Route("/pnl/", lambda request: PlainTextResponse("pnl")),
        WebSocketRoute("/ws", _websocket),
    ]
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ds, "FAILED_LOGIN_DELAY_SECONDS", 0)
    return TestClient(ds.PasswordGate(_DASHBOARDS, "s3cret"), follow_redirects=False)


def _log_in(client, password="s3cret", target="/pnl/"):
    return client.post(f"/login?next={target}", data={"password": password})


class TestPasswordGate:
    def test_every_path_redirects_to_login_without_the_cookie(self, client):
        for path in ("/", "/pnl/"):
            response = client.get(path)
            assert response.status_code == 303
            assert response.headers["location"] == f"/login?next={path}"

    def test_login_page_is_served_without_the_cookie(self, client):
        response = client.get("/login?next=/pnl/")
        assert response.status_code == 200
        assert 'type="password"' in response.text
        assert 'action="/login?next=/pnl/"' in response.text

    def test_wrong_password_is_refused(self, client):
        response = _log_in(client, "nope")
        assert response.status_code == 401
        assert "Wrong password" in response.text
        assert ds.COOKIE_NAME not in response.cookies

    def test_one_login_covers_every_dashboard(self, client):
        response = _log_in(client)
        assert response.status_code == 303
        assert response.headers["location"] == "/pnl/"
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/pnl/").text == "pnl"
        assert client.get("/").text == "finance"

    def test_login_lasts_a_day(self, client):
        assert "Max-Age=86400" in _log_in(client).headers["set-cookie"]

    def test_expired_cookie_is_rejected_even_if_the_browser_keeps_it(
        self, client, monkeypatch
    ):
        _log_in(client)
        monkeypatch.setattr(ds, "COOKIE_MAX_AGE", -1)
        assert client.get("/").status_code == 303

    def test_cookie_is_secure_behind_https(self, client):
        response = client.post(
            "/login?next=/", data={"password": "s3cret"},
            headers={"x-forwarded-proto": "https"},
        )  # fmt: skip
        assert "Secure" in response.headers["set-cookie"]

    def test_only_same_site_redirects_after_login(self, client):
        for target in ("//evil.example", "https://evil.example", "/\\evil.example"):
            assert _log_in(client, target=target).headers["location"] == "/"

    def test_a_cookie_signed_for_another_password_is_rejected(self, client):
        other = TestClient(
            ds.PasswordGate(_DASHBOARDS, "different"), follow_redirects=False
        )
        _log_in(other, "different")
        client.cookies.set(ds.COOKIE_NAME, other.cookies[ds.COOKIE_NAME])
        assert client.get("/").status_code == 303

    def test_websockets_need_the_cookie_too(self, client):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws") as ws:
                ws.receive_text()
        assert closed.value.code == 1008

        _log_in(client)
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_text() == "hello"


class TestCreateApp:
    def test_refuses_to_start_without_a_password(self, monkeypatch):
        monkeypatch.delenv(ds.PASSWORD_ENV_VAR, raising=False)
        with pytest.raises(RuntimeError, match=ds.PASSWORD_ENV_VAR):
            ds.create_app()

    def test_mounts_the_p_and_l_tracker_behind_the_gate(self, monkeypatch):
        monkeypatch.setenv(ds.PASSWORD_ENV_VAR, "s3cret")
        client = TestClient(ds.create_app(), follow_redirects=False)
        assert client.get("/").headers["location"] == "/login?next=/"
