"""To'liq oqim: HTTP API + WebSocket orqali haqiqiy duel (vaqtlar qisqartirilgan)."""
import asyncio

from aiohttp.test_utils import TestClient, TestServer

from app import config
from app.server import create_app

SAMPLE = "\n++++\n".join(
    f"Savol {i}?\n====\nNotoʻgʻri {i}\n====\n#Toʻgʻri {i}\n====\nYana notoʻgʻri {i}\n====\nBoshqa {i}" for i in range(25)
)


def test_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COUNTDOWN", 0.05)
    monkeypatch.setattr(config, "FEEDBACK_DELAY", 0.01)
    asyncio.run(_flow(tmp_path))


async def _next(ws, msg_type, timeout=5.0):
    async def inner():
        while True:
            msg = await ws.receive_json()
            if msg["t"] == msg_type:
                return msg["d"]

    return await asyncio.wait_for(inner(), timeout)


async def _play(ws, smart: bool):
    """Savollarga javob beradi: smart=True — to'g'ri javobni tanlaydi."""
    while True:
        msg = await asyncio.wait_for(ws.receive_json(), 10)
        if msg["t"] == "duel:question":
            d = msg["d"]
            correct = next(i for i, o in enumerate(d["options"]) if o.startswith("Toʻgʻri"))
            choice = correct if smart else (correct + 1) % len(d["options"])
            await ws.send_json({"t": "duel:answer", "d": {"duelId": d["duelId"], "index": d["index"], "choice": choice}})
        elif msg["t"] == "duel:end":
            return msg["d"]


async def _flow(tmp_path):
    app = create_app(db_path=tmp_path / "e2e.db", lan_url="http://192.168.1.10:8080")
    server = TestServer(app)
    await server.start_server()
    admin, ali, vali, guest = (TestClient(server) for _ in range(4))
    try:
        for c in (admin, ali, vali, guest):
            await c.start_server()

        # --- ro'yxatdan o'tish: birinchisi admin bo'ladi
        r = await admin.post("/api/auth/register", json={"login": "ustoz", "password": "1234"})
        assert r.status == 200 and (await r.json())["user"]["isAdmin"] is True
        r = await ali.post("/api/auth/register", json={"login": "ali", "password": "parol1"})
        assert (await r.json())["user"]["isAdmin"] is False
        r = await vali.post("/api/auth/register", json={"login": "vali", "password": "parol2"})
        assert r.status == 200
        r = await guest.post("/api/auth/register", json={"login": "ALI", "password": "boshqa"})
        assert r.status == 409  # login band (katta-kichik harf farqsiz)
        r = await guest.post("/api/auth/login", json={"login": "ali", "password": "xato"})
        assert r.status == 401
        assert (await (await guest.get("/api/auth/me")).json())["user"] is None

        # --- test yuklash faqat admin uchun
        r = await ali.post("/api/admin/topics", json={"name": "X", "content": SAMPLE})
        assert r.status == 403
        r = await admin.post("/api/admin/topics/parse", json={"content": SAMPLE + "\n++++\nBuzuq savol\n====\nA\n====\nB"})
        parsed = await r.json()
        assert parsed["count"] == 25 and parsed["errorCount"] == 1 and len(parsed["preview"]) == 5
        r = await admin.post("/api/admin/topics", json={"name": "Testlash asoslari", "content": SAMPLE, "shuffle": True, "fileName": "a.txt"})
        assert r.status == 201
        topic = (await r.json())["topic"]
        assert topic["questionCount"] == 25
        r = await admin.post("/api/admin/topics", json={"name": "  testlash   ASOSLARI ", "content": SAMPLE})
        assert r.status == 409  # nom band

        # --- o'rganish rejimi
        r = await ali.get(f"/api/topics/{topic['id']}/practice?count=10&order=random")
        practice = await r.json()
        assert len(practice["questions"]) == 10
        q = practice["questions"][0]
        assert q["options"][q["correct"]].startswith("Toʻgʻri")
        r = await ali.get(f"/api/topics/{topic['id']}/practice?count=all&order=seq")
        assert [x["text"] for x in (await r.json())["questions"]][:2] == ["Savol 0?", "Savol 1?"]
        r = await ali.post("/api/practice/results", json={"topicId": topic["id"], "total": 10, "answered": 9, "correct": 7})
        assert r.status == 200

        # --- WebSocket: avtorizatsiyasiz ulanish yopiladi
        ws_guest = await guest.ws_connect("/ws")
        msg = await ws_guest.receive()
        assert ws_guest.close_code == 4401 or msg.data == 4401

        # --- duel: ali va vali bir mavzuni tanlaydi
        wa = await ali.ws_connect("/ws")
        wv = await vali.ws_connect("/ws")
        hello = await _next(wa, "hello")
        assert hello["rules"]["duelQuestions"] == 15 and hello["rules"]["lanUrl"].startswith("http://192.168.")
        await _next(wv, "hello")
        await wa.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        queue = await _next(wa, "queue")
        assert queue["topicId"] == topic["id"] and len(queue["code"]) == 8

        # taklif sahifasi (og: teglari bilan)
        r = await guest.get(f"/d/{queue['code']}", allow_redirects=False)
        page = await r.text()
        assert r.status == 200 and "ali sizni test duelga chaqirmoqda" in page and f"/#/invite/{queue['code']}" in page
        info = await (await vali.get(f"/api/invite/{queue['code']}")).json()
        assert info["valid"] and info["host"] == "ali"

        await wv.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        start_a = await _next(wa, "duel:start")
        start_v = await _next(wv, "duel:start")
        assert start_a["opp"]["login"] == "vali" and start_v["opp"]["login"] == "ali"
        assert start_a["total"] == 15

        res_a, res_v = await asyncio.gather(_play(wa, smart=True), _play(wv, smart=False))
        assert res_a["result"] == "win" and res_a["reason"] == "score"
        assert res_v["result"] == "lose"
        assert res_a["me"]["correct"] == 15 and res_v["me"]["correct"] == 0
        assert len(res_a["review"]) == 15

        # --- statistika
        mine = await (await ali.get("/api/stats/me")).json()
        assert mine["duelSummary"]["wins"] == 1 and mine["duels"][0]["opponent"] == "vali"
        assert mine["practiceSummary"]["sessions"] == 1
        board = await (await vali.get("/api/stats/leaderboard")).json()
        assert [row["login"] for row in board["rows"]] == ["ali", "vali"]

        # --- boshlanish sanog'i paytida chiqib ketish: duel bekor qilinadi (natija yozilmaydi)
        await wa.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        await wv.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        await _next(wv, "duel:start")
        await wv.send_json({"t": "duel:leave", "d": {}})
        cancelled = await _next(wa, "duel:cancel")
        assert "bekor" in cancelled["message"]

        # --- duel boshlangandan keyin tark etish: vali chiqib ketsa, ali g'olib
        await wa.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        await wv.send_json({"t": "queue:join", "d": {"topicId": topic["id"]}})
        await _next(wv, "duel:question")
        await wv.send_json({"t": "duel:leave", "d": {}})
        end = await _next(wa, "duel:end")
        assert end["result"] == "win" and end["reason"] == "left"

        # --- boshqaruv: foydalanuvchilar ro'yxati
        users = (await (await admin.get("/api/admin/users")).json())["users"]
        assert {u["login"]: u["online"] for u in users} == {"ustoz": False, "ali": True, "vali": True}

        # --- statik fayllar va MIME turlari
        r = await guest.get("/")
        assert r.status == 200 and "TestDuel" in await r.text()
        r = await guest.get("/js/app.js")
        assert r.status == 200 and "javascript" in r.headers["Content-Type"]
        r = await guest.get("/css/app.css")
        assert r.status == 200 and "text/css" in r.headers["Content-Type"]

        await wa.close()
        await wv.close()
        await ws_guest.close()
    finally:
        for c in (admin, ali, vali, guest):
            await c.close()
        await server.close()
