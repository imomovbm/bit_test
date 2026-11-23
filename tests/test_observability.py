"""Kuzatuv va ishlatish: ko'rsatkichlar, tuzilgan jurnal, xatolar ilgagi, /healthz, /metrics, brauzer xatolari,
to'xtash rejimi va jurnalda shaxsiy ma'lumot yo'qligi (haqiqiy o'yin davomida)."""
import asyncio
import json
import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import config, ops
from app.keys import ASSETS, LIFECYCLE
from app.observability import ERRORS, METRICS, JsonFormatter, Metrics
from app.server import create_app
from test_octagon_api import QUESTIONS, call, recv, recv_state
from app.octagon import PROTOCOL_VERSION as PV  # noqa: E402


@pytest.fixture(autouse=True)
def quick_phases(monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 0.05)
    monkeypatch.setattr(config, "OCTAGON_READ", 0.05)


def run(tmp_path, body):
    async def main():
        server = TestServer(create_app(db_path=tmp_path / "o.db"))
        client = TestClient(server)
        await client.start_server()
        try:
            await body(client, server.app)
        finally:
            await client.close()
    asyncio.run(main())


# ----------------------------------------------------------------- ko'rsatkichlar
def test_metrics_counters_latency_window_and_prometheus_text():
    t = [100.0]
    m = Metrics(clock=lambda: t[0])
    m.inc("requests_total", area="api", status="2xx")
    m.inc("requests_total", 2, area="api", status="2xx")
    m.inc("plain_total")
    assert m.count("requests_total", area="api", status="2xx") == 3
    for ms in range(1, 101):
        m.observe("api_ms", float(ms))
    assert m.percentiles("api_ms") == {"n": 100, "p50": 50.0, "p95": 95.0, "p99": 99.0, "max": 100.0}
    t[0] += 301  # 5 daqiqalik oynadan chiqdi
    assert m.percentiles("api_ms") is None
    m.observe("api_ms", 7.0)
    m.gauge("games", lambda: 3)
    m.gauge("broken", lambda: 1 / 0)  # ko'rsatkich xatosi xizmatni buzmaydi
    text = m.prometheus()
    assert 'testduel_requests_total{area="api",status="2xx"} 3' in text and "testduel_plain_total 1" in text
    assert "testduel_games 3" in text and "testduel_broken NaN" in text
    assert 'testduel_latency_ms{metric="api_ms",quantile="0.95"} 7.0' in text
    snap = m.snapshot()
    assert snap["counters"]["requests_total"] == {"area=api,status=2xx": 3} and snap["gauges"]["games"] == 3


def test_json_log_lines_are_valid_json_with_fields():
    record = logging.LogRecord("testduel.x", logging.WARNING, __file__, 1, "Octagon %s yopildi", ("123456",), None)
    record.fields = {"kind": "demo", "pin": "123456"}
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "Octagon 123456 yopildi" and line["level"] == "WARNING" and line["kind"] == "demo"
    assert line["ts"].endswith("Z")


def test_error_hook_counts_logs_and_rate_limits_the_webhook(caplog, monkeypatch):
    sent = []

    async def fake_post(url, payload):
        sent.append((url, payload))

    async def body():
        monkeypatch.setattr(ERRORS, "post", fake_post)
        monkeypatch.setattr(ERRORS, "sent", {})
        ERRORS.configure(url="https://hook.example/x", release="abc123")
        before = METRICS.count("errors_total", kind="test_kind")
        for _ in range(3):
            ERRORS.report("test_kind", "nimadir buzildi", route="/api/x/{id}")
        await asyncio.sleep(0)
        assert METRICS.count("errors_total", kind="test_kind") == before + 3
        assert len(sent) == 1 and sent[0][1]["kind"] == "test_kind" and sent[0][1]["release"] == "abc123"
        assert sent[0][1]["fields"] == {"route": "/api/x/{id}"}
        ERRORS.configure(url="", release="")
    caplog.set_level(logging.ERROR, logger="testduel.errors")
    asyncio.run(body())
    assert "test_kind: nimadir buzildi" in caplog.text


# ------------------------------------------------------------------ marshrutlar
def test_healthz_reports_ok_and_draining(tmp_path):
    async def body(client, app):
        r = await client.get("/healthz")
        data = await r.json()
        assert r.status == 200 and data["status"] == "ok" and data["release"] == app[ASSETS].release
        assert r.headers["Cache-Control"] == "no-store"
        app[LIFECYCLE].draining = True
        r = await client.get("/healthz")
        assert r.status == 503 and (await r.json())["status"] == "draining"
        app[LIFECYCLE].draining = False
    run(tmp_path, body)


def test_metrics_endpoint_needs_the_token(tmp_path, monkeypatch):
    async def body(client, app):
        assert (await client.get("/metrics")).status == 401  # token sozlanmagan — ochiq emas
        monkeypatch.setattr(config, "METRICS_TOKEN", "s3cret-token")
        assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status == 401
        r = await client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
        text = await r.text()
        assert r.status == 200 and "testduel_octagon_games 0" in text and "testduel_ws_open" in text
        assert r.headers["Cache-Control"] == "no-store"
    run(tmp_path, body)


def test_admin_metrics_json_for_admins_only(tmp_path):
    async def body(client, app):
        assert (await call(client, "POST", "/api/auth/register", {"login": "admin", "password": "1234"}))[0] == 200
        status, data = await call(client, "GET", "/api/admin/metrics")
        assert status == 200 and "octagon_games" in data["gauges"] and "uptimeS" in data
        user = TestClient(client.server)
        await user.start_server()
        await call(user, "POST", "/api/auth/register", {"login": "oddiy", "password": "1234"})
        assert (await call(user, "GET", "/api/admin/metrics"))[0] == 403
        await user.close()
    run(tmp_path, body)


def test_client_error_reports_are_trimmed_and_rate_limited(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(config, "CLIENT_ERROR_LIMIT", 3)
    monkeypatch.setattr(ops, "_client_errors", ops.RateLimiter(limit=3, window=600))
    caplog.set_level(logging.WARNING, logger="testduel.errors")

    async def body(client, app):
        before = METRICS.count("errors_total", kind="client")
        r = await client.post("/api/client-errors", json={"m": "TypeError: x is null " + "y" * 900, "s": "/assets/abc/js/play.js?v=1#f",
                                                          "l": 42, "p": "play", "extra": "ignored"})
        assert r.status == 200
        await client.post("/api/client-errors", json={"m": "boshqa", "p": "<script>"})
        await client.post("/api/client-errors", json={"m": "uchinchi", "p": "app", "l": "x"})
        assert (await client.post("/api/client-errors", json={"m": "ortiqcha"})).status == 429
        assert METRICS.count("errors_total", kind="client") == before + 3
        assert (await client.post("/api/client-errors", data="not json", headers={"Content-Type": "text/plain"})).status in (415, 429)
    run(tmp_path, body)
    assert "y" * 301 not in caplog.text and "?v=1" not in caplog.text and "ortiqcha" not in caplog.text


def test_api_responses_carry_the_release_for_reload_prompts(tmp_path):
    async def body(client, app):
        r = await client.get("/api/auth/me")
        assert r.headers["X-Release"] == app[ASSETS].release
    run(tmp_path, body)


def test_new_games_are_refused_while_draining(tmp_path):
    async def body(client, app):
        await call(client, "POST", "/api/auth/register", {"login": "admin", "password": "1234"})
        tid = (await call(client, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS}))[1]["topic"]["id"]
        app[LIFECYCLE].draining = True
        status, data = await call(client, "POST", "/api/octagon/games", {"topicId": tid})
        assert status == 503 and "yangilanmoqda" in data["error"]
        app[LIFECYCLE].draining = False
        assert (await call(client, "POST", "/api/octagon/games", {"topicId": tid}))[0] == 201
    run(tmp_path, body)


def test_full_game_is_measured_and_logs_hold_no_personal_data(tmp_path, caplog):
    """Butun o'yin davomida barcha jurnallar (DEBUG darajasigacha): o'quvchi ismi, o'qituvchi logini, tokenlar,
    savol matni yo'q. Ko'rsatkichlar to'planadi (qo'shilish, javob, kechikishlar)."""
    caplog.set_level(logging.DEBUG)

    async def body(client, app):
        await call(client, "POST", "/api/auth/register", {"login": "ustoz_karimova", "password": "1234"})
        tid = (await call(client, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS}))[1]["topic"]["id"]
        before = {k: METRICS.count(k) for k in ("octagon_joins_total", "octagon_answers_total", "octagon_games_finished_total")}
        pin = (await call(client, "POST", "/api/octagon/games", {"topicId": tid, "questionCount": 1}))[1]["game"]["pin"]
        phone_client = TestClient(client.server)
        await phone_client.start_server()
        phone = await phone_client.ws_connect("/ws/octagon")
        await phone.send_json({"t": "join", "d": {"v": PV, "pin": pin, "nick": "Zulfiya Karimova", "av": 1}})
        me = await recv(phone, "w")
        host = await client.ws_connect("/ws/octagon")
        await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
        await recv(host, "h")
        await host.send_json({"t": "start", "d": {}})
        s = await recv_state(phone, "question_active")
        await phone.send_json({"t": "a", "d": {"q": s["q"], "o": 1}})
        await recv_state(phone, "question_result")
        await host.send_json({"t": "next", "d": {}})   # oxirgi savol -> yakuniy ochilish
        await recv_state(phone, "podium_intro")
        await host.send_json({"t": "skip", "d": {}})   # ochilishni o'tkazib yuborish -> natijalar
        await recv_state(phone, "final_results")
        await host.send_json({"t": "close", "d": {}})
        await phone.close()
        await host.close()
        await phone_client.close()
        assert METRICS.count("octagon_joins_total") == before["octagon_joins_total"] + 1
        assert METRICS.count("octagon_answers_total") == before["octagon_answers_total"] + 1
        assert METRICS.count("octagon_games_finished_total") == before["octagon_games_finished_total"] + 1
        for name in ("octagon_handle_ms", "octagon_broadcast_ms", "http_api_ms"):
            assert METRICS.percentiles(name), name
        text = caplog.text
        assert pin in text
        for secret in ("Zulfiya", "Karimova", "ustoz_karimova", me["tok"], "Savol matni", "Variant"):
            assert secret not in text, secret
    run(tmp_path, body)
