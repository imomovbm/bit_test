"""Octagon: rollar va huquqlar (REST + WebSocket), ommaviy /play sahifasi va haqiqiy WebSocket orqali to'liq o'yin."""
import asyncio
import json
import time

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from app import config
from app import octagon_flow as flow
from app.server import create_app
from app.octagon import PROTOCOL_VERSION as PV  # noqa: E402

QUESTIONS = "\n++++\n".join(
    f"Savol matni {i}?\n====\n{'#' if i % 4 == 0 else ''}Variant A {i}\n====\n{'#' if i % 4 == 1 else ''}Variant B {i}\n"
    f"====\n{'#' if i % 4 == 2 else ''}Variant C {i}\n====\n{'#' if i % 4 == 3 else ''}Variant D {i}"
    for i in range(6)
)
TEXTS = [f"Savol matni {i}" for i in range(6)] + [f"Variant {x} {i}" for i in range(6) for x in "ABCD"]


def test_roles_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 0.05)
    monkeypatch.setattr(config, "OCTAGON_READ", 0.05)
    asyncio.run(_roles(tmp_path))


def test_live_game_over_websocket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 0.05)
    monkeypatch.setattr(config, "OCTAGON_READ", 0.05)
    asyncio.run(_live(tmp_path))


async def _clients(server, n):
    clients = [TestClient(server) for _ in range(n)]
    for c in clients:
        await c.start_server()
    return clients


async def call(client, method, path, body=None):
    r = await client.request(method, path, json=body)
    try:
        data = await r.json()
    except Exception:
        data = None
    return r.status, data


async def recv(ws, t, timeout=5.0, sink=None):
    """Kerakli turdagi xabargacha o'qiydi (oradagilar sink'ga yig'iladi)."""
    async def inner():
        while True:
            msg = await ws.receive()
            if msg.type != aiohttp.WSMsgType.TEXT:
                return {"__closed__": ws.close_code}
            data = json.loads(msg.data)
            if sink is not None:
                sink.append(msg.data)
            if data["t"] == t:
                return data["d"]
    return await asyncio.wait_for(inner(), timeout)


async def recv_state(ws, phase, sink=None, timeout=5.0):
    while True:
        d = await recv(ws, "s", timeout, sink)
        if "__closed__" in d or flow.PHASES[d["p"]] == phase:  # simda bosqich indeksi
            return d


async def _setup(server):
    owner, admin2, teacher, student, guest = await _clients(server, 5)
    assert (await call(owner, "POST", "/api/auth/register", {"login": "admin", "password": "1234"}))[0] == 200
    for c, login in ((admin2, "zam"), (teacher, "ustoz"), (student, "talaba")):
        assert (await call(c, "POST", "/api/auth/register", {"login": login, "password": "1234"}))[0] == 200
    status, data = await call(owner, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS})
    assert status == 201
    return owner, admin2, teacher, student, guest, data["topic"]["id"]


async def _roles(tmp_path):
    server = TestServer(create_app(db_path=tmp_path / "r.db", lan_url="http://192.168.1.20:8080"))
    await server.start_server()
    owner, admin2, teacher, student, guest, tid = await _setup(server)
    try:
        # --- rollar: faqat bosh administrator o'qituvchi tayinlaydi
        assert (await call(owner, "PATCH", "/api/admin/users/2", {"isAdmin": True}))[0] == 200  # zam — admin
        assert (await call(admin2, "PATCH", "/api/admin/users/3", {"isTeacher": True}))[0] == 403
        me = (await call(teacher, "GET", "/api/auth/me"))[1]["user"]
        assert me["isTeacher"] is False
        status, data = await call(owner, "PATCH", "/api/admin/users/3", {"isTeacher": True})
        assert status == 200 and data["user"]["isTeacher"] is True and data["user"]["isAdmin"] is False
        assert (await call(teacher, "GET", "/api/auth/me"))[1]["user"]["isTeacher"] is True
        assert (await call(admin2, "GET", "/api/auth/me"))[1]["user"]["isTeacher"] is True   # admin — o'qituvchi huquqi bor
        assert (await call(student, "GET", "/api/auth/me"))[1]["user"]["isTeacher"] is False
        users = {u["login"]: u for u in (await call(owner, "GET", "/api/admin/users"))[1]["users"]}
        assert users["ustoz"]["isTeacher"] is True and users["talaba"]["isTeacher"] is False
        # yaratishda ham rol berish mumkin
        status, data = await call(owner, "POST", "/api/admin/users", {"login": "yangi_ustoz", "password": "1234", "isTeacher": True})
        assert status == 201 and data["user"]["isTeacher"] is True

        # --- oddiy foydalanuvchi: REST — 403, mehmon — 401
        body = {"topicId": tid, "timeLimit": 20, "questionCount": 3}
        status, game = await call(teacher, "POST", "/api/octagon/games", body)
        assert status == 201
        pin = game["game"]["pin"]
        assert game["game"]["joinUrl"] == f"http://{server.host}:{server.port}/play/{pin}" or game["game"]["joinUrl"].endswith(f"/play/{pin}")
        endpoints = [
            ("GET", "/api/octagon/topics", None),
            ("POST", "/api/octagon/games", body),
            ("GET", "/api/octagon/games", None),
            ("GET", f"/api/octagon/games/{pin}", None),
            ("POST", f"/api/octagon/games/{pin}/action", {"action": "start"}),
            ("POST", f"/api/octagon/games/{pin}/action", {"action": "next"}),
            ("POST", f"/api/octagon/games/{pin}/action", {"action": "end"}),
            ("DELETE", f"/api/octagon/games/{pin}", None),
            ("GET", "/api/balloon/games", None),
            ("POST", "/api/balloon/games", {"topicId": tid}),
        ]
        for method, path, payload in endpoints:
            assert (await call(student, method, path, payload))[0] == 403, (method, path)
            assert (await call(guest, method, path, payload))[0] == 401, (method, path)
        # administrator — o'qituvchi huquqlari bor (o'yin yaratadi va boshlaydi); boshqa o'qituvchining o'yini ko'rinmaydi (404)
        assert (await call(admin2, "GET", "/api/octagon/topics"))[0] == 200
        assert (await call(admin2, "GET", f"/api/octagon/games/{pin}"))[0] == 404
        status, data = await call(admin2, "POST", "/api/octagon/games", body)
        assert status == 201
        admin_pin = data["game"]["pin"]
        phone = await guest.ws_connect("/ws/octagon")
        await phone.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": admin_pin, "nick": "Talaba"}})
        assert (await recv(phone, "w"))["nick"] == "Talaba"
        status, data = await call(admin2, "POST", f"/api/octagon/games/{admin_pin}/action", {"action": "start"})
        assert status == 200 and data["game"]["phase"] == "topic_intro"
        status, data = await call(admin2, "POST", f"/api/octagon/games/{admin_pin}/action", {"action": "end"})
        # hech kim ball olmagan muddatidan oldingi tugash — ochilishsiz, darhol yakuniy natijalar
        assert status == 200 and data["game"]["phase"] == "final_results" and data["game"]["endedEarly"] is True
        await phone.close()
        status, data = await call(owner, "POST", "/api/octagon/games", body)
        assert status == 201

        # --- WebSocket: oddiy foydalanuvchi va mehmon o'yinni boshqara olmaydi
        for client in (student, guest):
            ws = await client.ws_connect("/ws/octagon")
            await ws.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
            err = await recv(ws, "e")
            assert err["status"] == 403
            for action in ("start", "next", "skip", "end", "kick", "settings", "close"):
                await ws.send_json({"t": action, "d": {}})
                assert (await recv(ws, "e"))["status"] == 403
            await ws.close()

        # --- ommaviy /play sahifasi: kirmasdan ochiladi, asosiy ilova yuklanmaydi
        for path in ("/play", f"/play/{pin}"):
            r = await guest.get(path)
            html = await r.text()
            assert r.status == 200 and "/js/play.js" in html and "/js/app.js" not in html

        # --- boshqa saytdan WebSocket ulanishi rad etiladi
        r = await guest.get("/ws/octagon", headers={"Origin": "https://evil.example", "Upgrade": "websocket", "Connection": "Upgrade",
                                                    "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        assert r.status == 403

        # --- sozlamalar: noto'g'ri vaqt rad etiladi; o'yin boshlangach — qulflanadi
        for bad in (4, 121, "20", 7.5, None):
            assert (await call(teacher, "POST", "/api/octagon/games", {**body, "timeLimit": bad}))[0] == 400, bad
        assert (await call(teacher, "POST", f"/api/octagon/games/{pin}/action", {"action": "settings", "timeLimit": 30}))[0] == 200
        assert (await call(teacher, "POST", f"/api/octagon/games/{pin}/action", {"action": "start"}))[0] == 409  # o'yinchi yo'q

        # --- o'qituvchi roli olib qo'yilsa: menyu yangilanadi, o'yinlari yopiladi, API — 403
        assert (await call(owner, "PATCH", "/api/admin/users/3", {"isTeacher": False}))[0] == 200
        assert (await call(teacher, "GET", "/api/octagon/games"))[0] == 403
        assert (await call(owner, "GET", "/api/octagon/games"))[0] == 200
    finally:
        for c in (owner, admin2, teacher, student, guest):
            await c.close()
        await server.close()


async def _live(tmp_path):
    server = TestServer(create_app(db_path=tmp_path / "l.db", lan_url="http://192.168.1.20:8080"))
    await server.start_server()
    owner, admin2, teacher, student, guest, tid = await _setup(server)
    phones = await _clients(server, 4)
    sink: dict[str, list] = {"ali": [], "vali": [], "olim": [], "late": []}
    try:
        await call(owner, "PATCH", "/api/admin/users/3", {"isTeacher": True})
        status, data = await call(teacher, "POST", "/api/octagon/games",
                                  {"topicId": tid, "timeLimit": 5, "questionCount": 3, "shuffleQuestions": False, "shuffleAnswers": False})
        assert status == 201
        pin = data["game"]["pin"]
        assert data["game"]["qr"]["path"] and data["game"]["phase"] == "lobby"

        host = await teacher.ws_connect("/ws/octagon")
        await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
        h = await recv(host, "h")
        assert h["pin"] == pin and h["phase"] == "lobby" and h["players"] == []

        # --- o'quvchilar: PIN tekshiruvi, qo'shilish, band ism
        socks = {}
        ids = {}
        for phone, nick in zip(phones[:3], ("ali", "vali", "olim")):
            ws = await phone.ws_connect("/ws/octagon")
            await ws.send_json({"t": "check", "d": {"v": PV, "pin": "000000"}})
            assert (await recv(ws, "e", sink=sink[nick]))["c"] == "pin"
            await ws.send_json({"t": "check", "d": {"v": PV, "pin": pin}})
            assert (await recv(ws, "c", sink=sink[nick]))["pin"] == pin
            await ws.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": nick.title()}})
            ids[nick] = await recv(ws, "w", sink=sink[nick])
            assert ids[nick]["av"] == 0 and ids[nick]["tn"] == "Informatika" and ids[nick]["n"] >= 1  # o'zgarmas ma'lumot — bir marta
            assert (await recv_state(ws, "lobby", sink[nick]))["sc"] == 0
            socks[nick] = ws
        dup = await phones[3].ws_connect("/ws/octagon")
        await dup.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "ALI"}})
        assert (await recv(dup, "e"))["c"] == "taken"
        await dup.close()

        # o'qituvchi «Boshlash»ni bosmaguncha o'yin boshlanmaydi
        await asyncio.sleep(0.3)
        h = (await call(teacher, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
        assert h["phase"] == "lobby" and [p["nick"] for p in h["players"]] == ["Ali", "Vali", "Olim"]

        await host.send_json({"t": "start", "d": {"phase": "lobby"}})
        for nick in socks:
            s = await recv_state(socks[nick], "question_active", sink[nick])
            assert s["q"] == 0 and s["o"] == 4 and s["pe"] - s["ps"] == 5000 and 0 < s["pe"] - time.time() * 1000 <= 5000
        # Q0: to'g'ri javob A (0). Ali va Vali to'g'ri, Olim xato
        await socks["ali"].send_json({"t": "a", "d": {"q": 0, "o": 0}})
        assert (await recv_state(socks["ali"], "question_active", sink["ali"]))["a"] == 0
        await socks["vali"].send_json({"t": "a", "d": {"q": 0, "o": 0}})
        await socks["olim"].send_json({"t": "a", "d": {"q": 0, "o": 3}})
        results = {n: await recv_state(socks[n], "question_result", sink[n]) for n in socks}
        assert results["ali"]["res"]["ok"] is True and results["olim"]["res"] == {"ok": False, "pts": 0, "co": 0}
        assert 500 <= results["ali"]["res"]["pts"] <= 1000 and results["ali"]["sc"] == results["ali"]["res"]["pts"]
        assert sorted(r["k"] for r in results.values()) == [1, 2, 3]

        # --- o'quvchi sahifani yangiladi: o'sha o'yinchi, o'sha ball, dublikatsiz
        before = results["vali"]["sc"]
        await socks["vali"].close()
        vali2 = await phones[1].ws_connect("/ws/octagon")
        await vali2.send_json({"t": "resume", "d": {"v": PV, "pin": pin, "id": ids["vali"]["id"], "tok": ids["vali"]["tok"]}})
        w = await recv(vali2, "w", sink=sink["vali"])
        s = await recv(vali2, "s", sink=sink["vali"])
        assert w["id"] == ids["vali"]["id"] and w["nick"] == "Vali" and "tok" not in w
        assert flow.PHASES[s["p"]] == "question_result" and s["sc"] == before and s["res"]["ok"] is True
        socks["vali"] = vali2
        # --- o'sha token ikkinchi oynada: yangi ulanish eskisini almashtiradi
        tab2 = await phones[3].ws_connect("/ws/octagon")
        await tab2.send_json({"t": "resume", "d": {"v": PV, "pin": pin, "id": ids["vali"]["id"], "tok": ids["vali"]["tok"]}})
        await recv(tab2, "w")
        kicked = await recv(vali2, "k", sink=sink["vali"])
        assert kicked == {"r": "replaced"}
        while (await vali2.receive()).type == aiohttp.WSMsgType.TEXT:
            pass
        assert vali2.close_code == 4001
        socks["vali"] = tab2
        h = (await call(teacher, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
        assert h["playerCount"] == 3 and h["connectedCount"] == 3

        # --- o'qituvchi sahifani yangiladi: boshqaruv saqlanadi
        await host.close()
        host = await teacher.ws_connect("/ws/octagon")
        await host.send_json({"t": "host", "d": {"v": PV, "pin": pin}})
        h = await recv(host, "h")
        assert h["phase"] == "question_result" and h["counts"] == [2, 0, 0, 1] and h["question"]["correct"] == 0
        await host.send_json({"t": "next", "d": {"phase": "question_result", "q": 0}})
        h = await recv(host, "h")
        assert h["phase"] == "leaderboard" and [r["nick"] for r in h["leaderboard"]][2] == "Olim"
        await host.send_json({"t": "next", "d": {"phase": "leaderboard", "q": 0}})
        for n in socks:
            await recv_state(socks[n], "question_active", sink[n])

        # --- kech qo'shilgan o'quvchi (o'yin o'rtasida)
        late = await phones[2].ws_connect("/ws/octagon")  # boshqa telefon
        await late.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "Kechikkan"}})
        await recv(late, "w", sink=sink["late"])
        s = await recv(late, "s", sink=sink["late"])
        assert flow.PHASES[s["p"]] == "question_active" and s["q"] == 1 and s["sc"] == 0
        # Q1: to'g'ri — B (1)
        for n, o in (("ali", 1), ("vali", 1), ("olim", 1)):
            await socks[n].send_json({"t": "a", "d": {"q": 1, "o": o}})
        await late.send_json({"t": "a", "d": {"q": 1, "o": 2}})
        s = await recv_state(late, "question_result", sink["late"])
        assert s["res"] == {"ok": False, "pts": 0, "co": 1} and s["k"] == 4
        # PIN noto'g'ri bo'lgan ikkinchi qo'shilish — o'sha ulanishda rad
        await late.send_json({"t": "a", "d": {"q": 1, "o": 1}})
        assert (await recv(late, "e", sink=sink["late"]))["c"] == "late"

        # --- 3-savol, so'ng yakuniy ochilish (o'qituvchi «O'tkazib yuborish» bilan natijalarga o'tadi)
        await host.send_json({"t": "next", "d": {"phase": "question_result"}})
        await host.send_json({"t": "next", "d": {"phase": "leaderboard"}})
        for n in socks:
            await recv_state(socks[n], "question_active", sink[n])
        await recv_state(late, "question_active", sink["late"])
        await host.send_json({"t": "skip", "d": {}})  # vaqtni kutmasdan yakunlash
        await recv_state(late, "question_result", sink["late"])
        await host.send_json({"t": "next", "d": {"phase": "question_result"}})
        await host.send_json({"t": "next", "d": {"phase": "leaderboard"}})   # eskirgan (reyting ko'rsatilmadi) — e'tiborsiz
        intro = await recv_state(late, "podium_intro", sink["late"])
        assert "k" not in intro and intro["top"] == []
        await host.send_json({"t": "skip", "d": {"phase": "podium_intro"}})
        final = await recv_state(late, "final_results", sink["late"])
        assert final["k"] == 4 and len(final["top"]) == 3
        h = (await call(teacher, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
        ranking = h["ranking"]
        assert h["phase"] == "final_results" and len(ranking) == 4 and ranking[-1]["nick"] == "Kechikkan"
        assert [r["score"] for r in ranking] == sorted((r["score"] for r in ranking), reverse=True)
        for n in socks:
            s = await recv_state(socks[n], "final_results", sink[n])
            assert s["sc"] == next(r["score"] for r in ranking if r["nick"].lower() == n)

        # --- o'quvchilarga hech qachon savol/variant matni yoki oldindan to'g'ri javob yuborilmagan
        for nick, raw_msgs in sink.items():
            blob = "".join(raw_msgs)
            assert raw_msgs and not any(t in blob for t in TEXTS), nick
            for raw in raw_msgs:
                assert len(raw.encode()) < 300, raw
                msg = json.loads(raw)
                if msg["t"] == "s" and flow.PHASES[msg["d"]["p"]] in ("lobby", "topic_intro", "question_read", "question_active"):
                    assert "res" not in msg["d"]

        # --- o'yin tugadi: yangi qo'shilish rad etiladi; o'qituvchi o'yinni yopadi
        extra = await phones[3].ws_connect("/ws/octagon")
        await extra.send_json({"t": "join", "d": {"v": PV, "av": 0, "pin": pin, "nick": "Yangi"}})
        assert (await recv(extra, "e"))["c"] == "ended"
        await host.send_json({"t": "close", "d": {}})
        assert (await recv(host, "closed"))["pin"] == pin
        assert (await recv(late, "k")) == {"r": "ended"}
        while (await late.receive()).type == aiohttp.WSMsgType.TEXT:
            pass
        assert late.close_code == 4003
    finally:
        for c in (owner, admin2, teacher, student, guest, *phones):
            await c.close()
        await server.close()
