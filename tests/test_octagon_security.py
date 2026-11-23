"""Octagon xavfsizlik auditi (docs/octagon-audit.md): HTTP va WebSocket darajasidagi regressiya testlari.

Har bir test audit hisobotidagi bitta bandga mos keladi: topilgan muammo (avval yiqilgan test -> tuzatish) yoki
tekshirilib, muammo topilmagan holat (keyinchalik buzilib qolmasligi uchun).
"""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import config, octagon
from app import ws as ws_mod
from app.keys import DB, OCTAGON
from app.server import create_app
from test_octagon_api import QUESTIONS, call, recv, recv_state
from app.octagon import PROTOCOL_VERSION as PV  # noqa: E402

EVIL = "https://evil.example"


@asynccontextmanager
async def world(tmp_path, name="s.db"):
    """Ega (admin), ikki o'qituvchi, oddiy foydalanuvchi, mehmon va bitta mavzu."""
    server = TestServer(create_app(db_path=tmp_path / name, lan_url="http://192.168.1.20:8080"))
    await server.start_server()
    clients = []

    async def client(login=None):
        c = TestClient(server)
        await c.start_server()
        clients.append(c)
        if login:
            assert (await call(c, "POST", "/api/auth/register", {"login": login, "password": "1234"}))[0] == 200
        return c

    w = SimpleNamespace(server=server, client=client)
    w.owner = await client("admin")
    w.a = await client("ustoz_a")
    w.b = await client("ustoz_b")
    w.student = await client("talaba")
    w.guest = await client()
    for uid in (2, 3):
        assert (await call(w.owner, "PATCH", f"/api/admin/users/{uid}", {"isTeacher": True}))[0] == 200
    status, data = await call(w.owner, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS})
    assert status == 201
    w.tid = data["topic"]["id"]

    async def game(teacher=None, **settings):
        body = {"topicId": w.tid, "timeLimit": 20, "questionCount": 3, "shuffleQuestions": False, "shuffleAnswers": False, **settings}
        status, data = await call(teacher or w.a, "POST", "/api/octagon/games", body)
        assert status == 201, data
        return data["game"]["pin"]

    w.game = game
    try:
        yield w
    finally:
        for c in clients:
            await c.close()
        await server.close()


async def drain(ws, timeout=0.5):
    """Ulanish yopilguncha o'qiydi: yopilish kodi yoki (hali ochiq bo'lsa) None."""
    try:
        while True:
            msg = await asyncio.wait_for(ws.receive(), timeout)
            if msg.type != aiohttp.WSMsgType.TEXT:
                return ws.close_code
    except asyncio.TimeoutError:
        return None


# ============================================================ huquqlar va rollar
def test_roles_cannot_be_self_assigned(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            hacker = await w.client()
            status, data = await call(hacker, "POST", "/api/auth/register", {
                "login": "hacker", "password": "1234", "isAdmin": True, "isTeacher": True, "is_admin": 1, "is_teacher": 1, "role": "teacher",
            })
            assert status == 200 and data["user"]["isAdmin"] is False and data["user"]["isTeacher"] is False
            assert (await call(hacker, "GET", "/api/auth/me"))[1]["user"]["isTeacher"] is False
            for c in (hacker, w.a):  # oddiy foydalanuvchi ham, o'qituvchi ham o'ziga rol bera olmaydi
                own = (await call(c, "GET", "/api/auth/me"))[1]["user"]["id"]
                assert (await call(c, "PATCH", f"/api/admin/users/{own}", {"isTeacher": True, "isAdmin": True}))[0] == 403
                assert (await call(c, "POST", "/api/admin/users", {"login": f"yangi{own}", "password": "1234", "isTeacher": True}))[0] == 403
            assert (await call(hacker, "POST", "/api/octagon/games", {"topicId": w.tid}))[0] == 403
            # rol cookie yoki mijozda saqlanmaydi: soxta sessiya cookie si — mehmon
            r = await w.guest.get("/api/octagon/games", headers={"Cookie": f"{config.SESSION_COOKIE}={'x' * 43}"})
            assert r.status == 401
            # bosh administrator ham o'z huquqlarini o'zgartira olmaydi
            assert (await call(w.owner, "PATCH", "/api/admin/users/1", {"isTeacher": False}))[0] == 400

    asyncio.run(body())


def test_teacher_cannot_control_another_teachers_game(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            phone = await w.guest.ws_connect("/ws/octagon")
            await phone.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "Ali"}})
            assert (await recv(phone, "w"))["nick"] == "Ali"
            zam = await w.client("zam")  # oddiy administrator (bosh administrator emas)
            assert (await call(w.owner, "PATCH", "/api/admin/users/5", {"isAdmin": True}))[0] == 200
            for intruder in (w.b, zam):
                assert (await call(intruder, "GET", f"/api/octagon/games/{pin}"))[0] == 404
                for action in ("start", "next", "skip", "end", "settings", "close", "lock", "kick"):
                    payload = {"action": action, "timeLimit": 30, "id": "x", "locked": True}
                    assert (await call(intruder, "POST", f"/api/octagon/games/{pin}/action", payload))[0] == 404, action
                assert (await call(intruder, "DELETE", f"/api/octagon/games/{pin}"))[0] == 404
                assert pin not in [g["pin"] for g in (await call(intruder, "GET", "/api/octagon/games"))[1]["games"]]
                ws = await intruder.ws_connect("/ws/octagon")
                await ws.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
                assert (await recv(ws, "e"))["status"] == 404
                for action in ("start", "next", "end", "close"):
                    await ws.send_json({"t": action, "d": {}})
                    assert (await recv(ws, "e"))["status"] == 403
                await ws.close()
            state = (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
            assert state["phase"] == "lobby" and state["timeLimit"] == 20 and state["playerCount"] == 1
            await phone.close()

    asyncio.run(body())


def test_player_socket_cannot_send_host_messages(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            for c, nick in ((w.guest, "Mehmon"), (w.student, "Talaba")):  # mehmon telefoni va akkaunti bor o'quvchi
                ws = await c.ws_connect("/ws/octagon")
                await ws.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": nick}})
                await recv(ws, "w")
                for t, d in (("host", {"v": PV, "pin": pin}), ("start", {}), ("next", {}), ("skip", {}), ("end", {}), ("kick", {"id": "x"}),
                             ("settings", {"timeLimit": 5}), ("close", {}), ("lock", {"locked": True})):
                    await ws.send_json({"t": t, "d": d})
                    assert (await recv(ws, "e"))["status"] == 403, t
                await ws.close()
            state = (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
            assert state["phase"] == "lobby" and state["timeLimit"] == 20 and state["playerCount"] == 2 and not state.get("locked")

    asyncio.run(body())


def test_host_socket_loses_control_after_logout_or_password_reset(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            game = w.server.app[OCTAGON].games[pin]
            phone = await w.guest.ws_connect("/ws/octagon")
            await phone.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "Ali"}})
            await recv(phone, "w")
            # 1) o'qituvchi boshqa oynada tizimdan chiqdi — ochiq boshqaruv ulanishi yopiladi
            host = await w.a.ws_connect("/ws/octagon")
            await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
            assert (await recv(host, "h"))["phase"] == "lobby"
            assert (await call(w.a, "POST", "/api/auth/logout"))[0] == 200
            assert await drain(host, 3) == 4401
            # 2) bosh administrator parolni tikladi — eski sessiyalardagi boshqaruv ulanishlari yopiladi
            assert (await call(w.a, "POST", "/api/auth/login", {"login": "ustoz_a", "password": "1234"}))[0] == 200
            host = await w.a.ws_connect("/ws/octagon")
            await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
            await recv(host, "h")
            assert (await call(w.owner, "PATCH", "/api/admin/users/2", {"password": "yangi-parol"}))[0] == 200
            assert await drain(host, 3) == 4401
            # 3) sessiya boshqa sabab bilan tugagan bo'lsa ham — har bir boshqaruv amali sessiyani qayta tekshiradi
            assert (await call(w.a, "POST", "/api/auth/login", {"login": "ustoz_a", "password": "yangi-parol"}))[0] == 200
            host = await w.a.ws_connect("/ws/octagon")
            await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
            await recv(host, "h")
            w.server.app[DB].conn.execute("DELETE FROM sessions")
            await host.send_json({"t": "start", "d": {}})
            assert (await recv(host, "e"))["status"] == 403
            assert await drain(host, 3) == 4401
            assert game.phase == "lobby" and not game.hosts

    asyncio.run(body())


# ===================================================== CSRF, CORS, sarlavhalar
def test_csrf_and_cors_on_teacher_endpoints(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            create = {"topicId": w.tid, "timeLimit": 20}
            for client, method, path, payload in (
                (w.a, "POST", "/api/octagon/games", create),
                (w.a, "POST", f"/api/octagon/games/{pin}/action", {"action": "close"}),
                (w.a, "DELETE", f"/api/octagon/games/{pin}", None),
                (w.owner, "PATCH", "/api/admin/users/4", {"isTeacher": True}),
            ):
                r = await client.request(method, path, json=payload, headers={"Origin": EVIL})
                assert r.status == 403 and "Access-Control-Allow-Origin" not in r.headers, (method, path)
            r = await w.a.post("/api/octagon/games", data=json.dumps(create), headers={"Content-Type": "text/plain"})
            assert r.status == 415  # oddiy HTML forma bilan (preflight'siz) yuborib bo'lmaydi
            r = await w.a.options("/api/octagon/games", headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"})
            assert "Access-Control-Allow-Origin" not in r.headers
            for path in ("/api/auth/me", "/api/octagon/games", f"/api/octagon/games/{pin}", "/play", "/"):
                r = await w.a.get(path, headers={"Origin": EVIL})
                assert "Access-Control-Allow-Origin" not in r.headers and "Access-Control-Allow-Credentials" not in r.headers
            assert (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[1]["game"]["phase"] == "lobby"
            users = {u["login"]: u for u in (await call(w.owner, "GET", "/api/admin/users"))[1]["users"]}
            assert users["talaba"]["isTeacher"] is False

    asyncio.run(body())


def test_security_headers(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            for path in ("/", "/play", "/play/123456", "/api/auth/me", "/js/play.js", "/css/play.css", "/d/ABCDEF"):
                r = await w.guest.get(path)
                assert r.headers.get("X-Content-Type-Options") == "nosniff", path
                assert r.headers.get("X-Frame-Options") == "DENY", path
                assert r.headers.get("Referrer-Policy") == "same-origin", path
            for path in ("/", "/play", "/play/123456", "/d/ABCDEF"):
                csp = (await w.guest.get(path)).headers.get("Content-Security-Policy", "")
                rules = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
                assert rules.get("frame-ancestors") == ["'none'"], path
                assert rules.get("object-src") == ["'none'"] and rules.get("base-uri") == ["'self'"], path
                script = rules.get("script-src", ["'unsafe-inline'"])
                assert "'self'" in script and "'unsafe-inline'" not in script and "'unsafe-eval'" not in script, path

    asyncio.run(body())


# ======================================================= cheklovlar va chidamlilik
def test_ws_message_size_and_flood_limits(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            hub = w.server.app[OCTAGON]
            ws = await w.guest.ws_connect("/ws/octagon")
            await ws.send_str("x" * 5000)
            assert await drain(ws, 3) == 1009  # juda katta xabar
            ws = await w.guest.ws_connect("/ws/octagon")
            for _ in range(ws_mod.FLOOD_LIMIT + 5):
                await ws.send_json({"t": "ping", "d": {}})
            assert await drain(ws, 3) == 4008  # xabarlar oqimi
            ws = await w.guest.ws_connect("/ws/octagon")  # server ishlashda davom etadi
            await ws.send_json({"t": "ping", "d": {}})
            assert await recv(ws, "pong") == {}
            await ws.close()
            await asyncio.sleep(0.2)
            assert not hub.sockets  # ochiq ulanishlar hisobi to'g'ri kamayadi

    asyncio.run(body())


def test_socket_caps_per_ip_and_global(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    monkeypatch.setattr(octagon, "MAX_SOCKETS_PER_IP", 2)
    monkeypatch.setattr(octagon, "MAX_SOCKETS", 4)

    async def body():
        async with world(tmp_path) as w:
            opened = []

            async def connect(ip):
                opened.append(await w.guest.ws_connect("/ws/octagon", headers={"X-Forwarded-For": ip}))

            await connect("10.0.0.1")
            await connect("10.0.0.1")
            with pytest.raises(aiohttp.WSServerHandshakeError) as e:
                await connect("10.0.0.1")  # bitta IP chegarasi
            assert e.value.status == 429
            await connect("10.0.0.2")
            await connect("10.0.0.3")
            with pytest.raises(aiohttp.WSServerHandshakeError) as e:
                await connect("10.0.0.4")  # jami chegara (ko'p IP dan hujum)
            assert e.value.status == 429
            for ws in opened:
                await ws.close()
            await asyncio.sleep(0.2)
            await connect("10.0.0.4")

    asyncio.run(body())


def test_deeply_nested_json_is_ignored(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            ws = await w.student.ws_connect("/ws")  # duel kanali (16 KB gacha xabar)
            await recv(ws, "hello")
            await ws.send_str("[" * 8000 + "]" * 8000)  # chegaraga yaqin chuqur JSON — e'tiborsiz, ulanish yashaydi
            await ws.send_json({"t": "ping", "d": {}})
            assert await recv(ws, "pong") == {}
            await ws.send_str("[" * 30000 + "]" * 30000)  # RecursionError chuqurligi — hajm chegarasida to'xtaydi
            assert await drain(ws, 3) == 1009
            ws = await w.student.ws_connect("/ws")  # server ishlashda davom etadi
            assert (await recv(ws, "hello"))["rules"]
            ows = await w.guest.ws_connect("/ws/octagon")
            await ows.send_str("[" * 2040 + "]" * 2040)
            await ows.send_json({"t": "ping", "d": {}})
            assert await recv(ows, "pong") == {}

    asyncio.run(body())


def test_concurrent_join_same_nick_and_concurrent_resume(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            s1 = await w.guest.ws_connect("/ws/octagon")
            s2 = await w.student.ws_connect("/ws/octagon")
            await asyncio.gather(s1.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "Ali"}}),
                                 s2.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "ali"}}))
            first = [json.loads((await s.receive()).data) for s in (s1, s2)]
            assert sorted(m["t"] for m in first) == ["e", "w"]
            loser = next(m for m in first if m["t"] == "e")
            assert loser["d"]["c"] == "taken"
            winner = s1 if first[0]["t"] == "w" else s2
            me = next(m for m in first if m["t"] == "w")["d"]
            tabs = [await w.guest.ws_connect("/ws/octagon") for _ in range(3)]
            await asyncio.gather(*(t.send_json({"t": "resume", "d": {"v": PV, "pin": pin, "id": me["id"], "tok": me["tok"]}}) for t in tabs))
            codes = [await drain(t) for t in (winner, *tabs)]
            game = w.server.app[OCTAGON].games[pin]
            assert len(game.players) == 1 and game.players[me["id"]].conn is not None  # dublikat yo'q
            assert codes.count(None) == 1 and codes.count(4001) == 3  # eng yangi ulanish qoladi

    asyncio.run(body())


async def _restart_scenario(tmp_path, keep):
    """Server ishlayotgan o'yin paytida to'xtaydi va qayta ishga tushadi (o'sha baza)."""
    server = TestServer(create_app(db_path=tmp_path / "restart.db"))
    await server.start_server()
    owner, phone_client = TestClient(server), TestClient(server)
    for c in (owner, phone_client):
        await c.start_server()
    await call(owner, "POST", "/api/auth/register", {"login": "admin", "password": "1234"})
    tid = (await call(owner, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS}))[1]["topic"]["id"]
    body = {"topicId": tid, "timeLimit": 20, "shuffleQuestions": False, "shuffleAnswers": False}  # 1-savol: to'g'risi A
    pin = (await call(owner, "POST", "/api/octagon/games", body))[1]["game"]["pin"]
    phone = await phone_client.ws_connect("/ws/octagon")
    await phone.send_json({"t": "join", "d": {"v": PV, "av": 7, "pin": pin, "nick": "Ali"}})
    me = await recv(phone, "w")
    host = await owner.ws_connect("/ws/octagon")
    await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
    await recv(host, "h")
    await host.send_json({"t": "start", "d": {}})
    s = await recv_state(phone, "question_active")
    await phone.send_json({"t": "a", "d": {"q": s["q"], "o": 0}})
    res = await recv_state(phone, "question_result")
    assert res["sc"] > 0
    closing = asyncio.ensure_future(drain(phone, 5))
    await server.close()
    code = await closing
    await owner.close()
    await phone_client.close()
    snapshot = tmp_path / "restart.octagon.json"
    assert snapshot.exists() == keep and (not keep or oct(snapshot.stat().st_mode & 0o777) == "0o600")

    server = TestServer(create_app(db_path=tmp_path / "restart.db"))
    await server.start_server()
    owner, phone_client = TestClient(server), TestClient(server)
    try:
        for c in (owner, phone_client):
            await c.start_server()
        assert not snapshot.exists()  # bir marta tiklanadi — fayl o'chiriladi
        assert (await call(owner, "POST", "/api/auth/login", {"login": "admin", "password": "1234"}))[0] == 200
        games = (await call(owner, "GET", "/api/octagon/games"))[1]["games"]
        host = await owner.ws_connect("/ws/octagon")
        await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
        phone = await phone_client.ws_connect("/ws/octagon")
        await phone.send_json({"t": "resume", "d": {"v": PV, "pin": pin, "id": me["id"], "tok": me["tok"]}})
        return code, games, host, phone, me, res["sc"]
    except Exception:
        await owner.close()
        await phone_client.close()
        await server.close()
        raise


@pytest.fixture
def quick_phases(monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 0.05)
    monkeypatch.setattr(config, "OCTAGON_READ", 0.05)


def test_server_restart_keeps_running_games(tmp_path, quick_phases):
    """To'xtashda o'yinlar diskka yoziladi va qayta ishga tushganda tiklanadi: o'qituvchi va o'quvchi avtomatik qayta
    ulanib, o'sha bosqich, ism, avatar va ball bilan davom etadi (docs/runbook.md)."""
    async def body():
        code, games, host, phone, me, score = await _restart_scenario(tmp_path, keep=True)
        try:
            assert code == 1012  # "xizmat qayta ishga tushmoqda" — mijozlar qayta ulanadi
            assert [g["phase"] for g in games] == ["question_result"]
            h = await recv(host, "h")
            assert h["phase"] == "question_result" and h["playerCount"] == 1 and h["qr"]
            w = await recv(phone, "w")
            s = await recv(phone, "s")
            assert (w["id"], w["nick"], w["av"]) == (me["id"], "Ali", 7) and s["sc"] == score
            await host.send_json({"t": "next", "d": {}})   # o'yin davom etadi
            assert (await recv_state(phone, "leaderboard"))["sc"] == score
        finally:
            await host.close()
            await phone.close()
    asyncio.run(body())


def test_server_restart_without_saved_state_loses_games_cleanly(tmp_path, monkeypatch, quick_phases):
    """Tiklash o'chirilgan (TD_OCTAGON_RESTORE_MAX_AGE=0) yoki fayl eskirgan: o'yinlar yo'qoladi, lekin hamma tushunarli
    xabar oladi (o'qituvchi — «o'yin topilmadi», o'quvchi — PIN ni qayta tekshiradi)."""
    monkeypatch.setattr(config, "OCTAGON_RESTORE_MAX_AGE", 0.0)

    async def body():
        code, games, host, phone, _, _ = await _restart_scenario(tmp_path, keep=False)
        try:
            assert code == 1012 and games == []
            assert (await recv(host, "e"))["c"] == "notfound"
            assert (await recv(phone, "e"))["c"] == "gone"
        finally:
            await host.close()
            await phone.close()
    asyncio.run(body())


# ============================================================= havolalar va PIN
def test_join_url_setting_and_host_header_validation(tmp_path, monkeypatch):
    async def body():
        async with world(tmp_path) as w:
            create = {"topicId": w.tid, "timeLimit": 20}
            r = await w.a.post("/api/octagon/games", json=create, headers={"Host": "evil.example/x?y="})
            data = await r.json()
            assert r.status == 201 and data["game"]["joinUrl"].startswith("http://192.168.1.20:8080/play/")
            monkeypatch.setattr(config, "PUBLIC_URL", "https://quiz.example.uz")
            status, data = await call(w.a, "POST", "/api/octagon/games", create)
            assert status == 201 and data["game"]["joinUrl"] == f"https://quiz.example.uz/play/{data['game']['pin']}"

    asyncio.run(body())


def test_pin_parameters_validated_and_no_open_redirect(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            for path in ("/play/123456?next=https://evil.example", "/play/%2e%2e%2f%2e%2e", "/play/%3Cscript%3E", "/play?pin=https://evil.example"):
                r = await w.guest.get(path, allow_redirects=False)
                assert r.status in (200, 404) and "Location" not in r.headers, path
                if r.status == 200:
                    page = await r.text()
                    assert "evil.example" not in page and page.count("<script") == 1, path  # statik sahifa: hech narsa qaytarilmaydi
            for pin in ("abc", "0123456", "12345", "1234567", "%00", "123456%20"):
                assert (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[0] == 404, pin

    asyncio.run(body())
