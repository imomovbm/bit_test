"""Mavzular va savollarni qo'lda boshqarish, faol/nofaol mavzular va xavfsizlik tekshiruvlari."""
import asyncio

from aiohttp.test_utils import TestClient, TestServer

from app.server import create_app

FILE = "\n++++\n".join(f"Fayl savoli {i}?\n====\n#Ha {i}\n====\nYo'q {i}" for i in range(3))
OTHER = "\n++++\n".join(f"Boshqa savol {i}?\n====\n#Ha {i}\n====\nYo'q {i}" for i in range(2))


def test_topics_questions_and_security(tmp_path):
    asyncio.run(_flow(tmp_path))


async def _flow(tmp_path):
    server = TestServer(create_app(db_path=tmp_path / "t.db"))
    await server.start_server()
    admin, user = TestClient(server), TestClient(server)
    try:
        for c in (admin, user):
            await c.start_server()

        async def call(client, method, path, body=None, **kw):
            r = await client.request(method, path, json=body, **kw)
            data = await r.json() if r.content_type == "application/json" else await r.text()
            return r.status, data

        await call(admin, "POST", "/api/auth/register", {"login": "admin", "password": "1234"})
        # --- ro'yxatdan o'tishda o'zini admin qilib bo'lmaydi
        status, data = await call(user, "POST", "/api/auth/register", {"login": "talaba", "password": "1234", "isAdmin": True, "is_admin": 1, "isSuperadmin": True})
        assert status == 200 and data["user"]["isAdmin"] is False and data["user"]["isSuperadmin"] is False

        # --- bo'sh mavzu yaratish
        status, data = await call(admin, "POST", "/api/admin/topics", {"name": "Qo'lda mavzu"})
        assert status == 201 and data["topic"]["questionCount"] == 0 and data["topic"]["active"] is True
        tid = data["topic"]["id"]
        assert (await call(admin, "POST", "/api/admin/topics", {"name": "  qo'lda   MAVZU "}))[0] == 409
        assert (await call(user, "GET", "/api/topics"))[1]["topics"] == []  # savolsiz mavzu ko'rinmaydi

        # --- savol qo'shish / tahrirlash / o'chirish
        q = {"text": "2 + 2 = ?", "options": ["3", "4", "5"], "correct": 1}
        for bad in [
            {**q, "options": ["4"]},
            {**q, "correct": 3},
            {**q, "correct": "1"},
            {**q, "text": "   "},
            {**q, "options": ["4", "4 "]},
            {**q, "text": "a ==== b"},
            {**q, "options": ["a", {"x": 1}]},
            {**q, "options": [str(i) for i in range(11)]},
        ]:
            assert (await call(admin, "POST", f"/api/admin/topics/{tid}/questions", bad))[0] == 400, bad
        status, data = await call(admin, "POST", f"/api/admin/topics/{tid}/questions", q)
        assert status == 201 and data["topic"]["questionCount"] == 1
        qid = data["question"]["id"]
        status, data = await call(admin, "PUT", f"/api/admin/topics/{tid}/questions/{qid}", {**q, "text": "2 + 3 = ?", "correct": 2})
        assert status == 200 and data["question"] == {"id": qid, "text": "2 + 3 = ?", "options": ["3", "4", "5"], "correct": 2}
        assert (await call(admin, "PUT", f"/api/admin/topics/{tid}/questions/99999", q))[0] == 404
        assert (await call(admin, "POST", "/api/admin/topics/99999/questions", q))[0] == 404

        # --- fayldan qo'shish (mavjud mavzu oxiriga)
        assert (await call(admin, "POST", f"/api/admin/topics/{tid}/append", {"content": "buzuq"}))[0] == 400
        status, data = await call(admin, "POST", f"/api/admin/topics/{tid}/append", {"content": FILE, "fileName": "q.txt"})
        assert status == 200 and data["added"] == 3 and data["topic"]["questionCount"] == 4
        status, data = await call(admin, "GET", f"/api/admin/topics/{tid}/questions")
        assert [x["text"] for x in data["questions"]] == ["2 + 3 = ?", "Fayl savoli 0?", "Fayl savoli 1?", "Fayl savoli 2?"]
        status, data = await call(admin, "DELETE", f"/api/admin/topics/{tid}/questions/{qid}")
        assert status == 200 and data["topic"]["questionCount"] == 3
        assert (await call(admin, "DELETE", f"/api/admin/topics/{tid}/questions/{qid}"))[0] == 404

        # --- boshqa mavzuning savolini shu mavzu orqali o'zgartirib bo'lmaydi
        status, other = await call(admin, "POST", "/api/admin/topics", {"name": "Boshqa", "content": OTHER})
        oid = other["topic"]["id"]
        other_q = (await call(admin, "GET", f"/api/admin/topics/{oid}/questions"))[1]["questions"][0]["id"]
        assert (await call(admin, "PUT", f"/api/admin/topics/{tid}/questions/{other_q}", q))[0] == 404
        assert (await call(admin, "DELETE", f"/api/admin/topics/{tid}/questions/{other_q}"))[0] == 404

        # --- faol/nofaol: nofaol mavzu foydalanuvchilarga ko'rinmaydi va o'ynab bo'lmaydi
        assert {t["id"] for t in (await call(user, "GET", "/api/topics"))[1]["topics"]} == {tid, oid}
        status, data = await call(admin, "PATCH", f"/api/admin/topics/{tid}", {"active": False})
        assert status == 200 and data["topic"]["active"] is False
        assert {t["id"] for t in (await call(user, "GET", "/api/topics"))[1]["topics"]} == {oid}
        assert (await call(user, "GET", f"/api/topics/{tid}/practice?count=all"))[0] == 404
        teams = [{"name": "A", "color": "red"}, {"name": "B", "color": "blue"}]
        assert (await call(admin, "POST", "/api/balloon/games", {"topicId": tid, "teams": teams, "balloons": 10}))[0] == 404
        ws = await user.ws_connect("/ws")
        await ws.receive_json(timeout=3)
        await ws.send_json({"t": "queue:join", "d": {"topicId": tid}})
        while True:
            msg = await ws.receive_json(timeout=3)
            if msg["t"] == "error":
                break
        assert "yopilgan" in msg["d"]["message"]
        await ws.close()
        admin_topics = (await call(admin, "GET", "/api/admin/topics"))[1]["topics"]
        assert [t["active"] for t in admin_topics if t["id"] == tid] == [False]  # admin barchasini ko'radi
        await call(admin, "PATCH", f"/api/admin/topics/{tid}", {"active": True})
        assert (await call(user, "GET", f"/api/topics/{tid}/practice?count=all"))[0] == 200

        # --- oddiy foydalanuvchi yangi amallarning hech birini bajara olmaydi
        for method, path, body in [
            ("POST", "/api/admin/topics", {"name": "X"}),
            ("PATCH", f"/api/admin/topics/{tid}", {"active": False}),
            ("POST", f"/api/admin/topics/{tid}/questions", q),
            ("PUT", f"/api/admin/topics/{tid}/questions/{other_q}", q),
            ("DELETE", f"/api/admin/topics/{tid}/questions/{other_q}", None),
            ("POST", f"/api/admin/topics/{tid}/append", {"content": FILE}),
            ("PATCH", "/api/admin/users/2", {"isAdmin": True}),
            ("PATCH", "/api/admin/settings", {"registrationOpen": True}),
        ]:
            assert (await call(user, method, path, body))[0] == 403, (method, path)
        assert (await call(user, "GET", "/api/auth/me"))[1]["user"]["isAdmin"] is False

        # --- boshqa saytdan yuborilgan so'rovlar rad etiladi
        evil = {"Origin": "https://evil.example"}
        status, _ = await call(admin, "POST", "/api/admin/topics", {"name": "CSRF"}, headers=evil)
        assert status == 403
        r = await admin.post("/api/admin/topics", data='{"name": "Forma"}', headers={"Content-Type": "text/plain"})
        assert r.status == 415  # oddiy HTML forma JSON yubora olmaydi
        own = {"Origin": f"http://{server.host}:{server.port}"}
        assert (await call(admin, "POST", "/api/admin/topics", {"name": "Oʻz saytimdan"}, headers=own))[0] == 201
        # --- egasiga o'xshatilgan login va katta so'rovlar
        for fake in ("аdmin", "ADMIN", "adm1n", "admln", "a.dmin", "ad-min"):
            assert (await call(user, "POST", "/api/auth/register", {"login": fake, "password": "1234"}))[0] == 409, fake
        assert (await call(user, "POST", "/api/auth/register", {"login": "administrator", "password": "1234"}))[0] == 200
        r = await user.post("/api/practice/results", data=b"{" + b" " * 300_000 + b"}", headers={"Content-Type": "application/json"})
        assert r.status == 413
        r = await user.get("/ws", headers={**evil, "Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        assert r.status == 403
    finally:
        await admin.close()
        await user.close()
        await server.close()


def test_bank_api(tmp_path):
    asyncio.run(_bank_flow(tmp_path))


async def _bank_flow(tmp_path):
    server = TestServer(create_app(db_path=tmp_path / "b.db"))
    await server.start_server()
    admin, user = TestClient(server), TestClient(server)
    try:
        for c in (admin, user):
            await c.start_server()

        async def call(client, method, path, body=None):
            r = await client.request(method, path, json=body)
            return r.status, await r.json()

        await call(admin, "POST", "/api/auth/register", {"login": "admin", "password": "1234"})
        await call(user, "POST", "/api/auth/register", {"login": "talaba", "password": "1234"})
        # --- fayldan bankka (mavzusiz), qayta yuklash takrorlamaydi
        status, data = await call(admin, "POST", "/api/admin/bank/upload", {"content": FILE, "fileName": "bank.txt"})
        assert status == 200 and data == {"created": 3, "reused": 0, "skipped": 0}
        assert (await call(admin, "POST", "/api/admin/bank/upload", {"content": FILE}))[1]["reused"] == 3
        status, data = await call(admin, "POST", "/api/admin/bank", {"text": "Qo'lda?", "options": ["a", "b"], "correct": 0})
        assert status == 201
        manual = data["question"]["id"]
        status, page = await call(admin, "GET", "/api/admin/bank?per=10&page=1")
        assert page["total"] == 4 and len(page["questions"]) == 4 and page["questions"][0]["id"] == manual
        assert (await call(admin, "GET", "/api/admin/bank?topic=none"))[1]["total"] == 4
        assert (await call(admin, "GET", "/api/admin/bank?search=fayl%20savoli"))[1]["total"] == 3
        assert (await call(admin, "GET", "/api/admin/bank?page=x"))[0] == 400
        # juda katta sonlar 500 emas, oddiy xato qaytaradi
        big = "9" * 25
        assert (await call(admin, "GET", f"/api/admin/bank?page={big}"))[0] == 200
        assert (await call(admin, "GET", f"/api/admin/bank?topic={big}"))[0] == 400
        assert (await call(admin, "GET", f"/api/admin/topics/{big}/questions"))[0] == 404
        assert (await call(admin, "PATCH", f"/api/admin/users/{big}", {"blocked": True}))[0] == 404
        assert (await call(admin, "POST", "/api/admin/bank/delete", {"questionIds": [10**30]}))[0] == 400
        assert (await call(admin, "POST", "/api/admin/bank", {"text": "x", "options": ["a", "b"], "correct": 0, "topicIds": [10**30]}))[0] == 400

        # --- tanlangan savollardan yangi aralash mavzu
        ids = (await call(admin, "GET", "/api/admin/bank/ids?search=savoli"))[1]["ids"]
        assert len(ids) == 3
        tid = (await call(admin, "POST", "/api/admin/topics", {"name": "Aralash"}))[1]["topic"]["id"]
        status, data = await call(admin, "POST", f"/api/admin/topics/{tid}/link", {"questionIds": ids[:2] + [manual]})
        assert status == 200 and data["linked"] == 3 and data["topic"]["questionCount"] == 3
        assert (await call(admin, "POST", f"/api/admin/topics/{tid}/link", {"questionIds": ids}))[1]["linked"] == 1
        for bad in ([], ["1"], [True], [0], list(range(1, 5003))):
            assert (await call(admin, "POST", f"/api/admin/topics/{tid}/link", {"questionIds": bad}))[0] == 400
        page = (await call(admin, "GET", f"/api/admin/bank?topic={tid}"))[1]
        assert page["total"] == 4 and all({"id": tid, "name": "Aralash"} in q["topics"] for q in page["questions"])
        assert (await call(admin, "GET", "/api/admin/bank?topic=none"))[1]["total"] == 0
        # mavzudan olib tashlash — bankda qoladi; bankdan o'chirish — mavzudan ham
        assert (await call(admin, "DELETE", f"/api/admin/topics/{tid}/questions/{manual}"))[1]["topic"]["questionCount"] == 3
        assert (await call(admin, "GET", "/api/admin/bank"))[1]["total"] == 4
        status, data = await call(admin, "DELETE", f"/api/admin/bank/{ids[0]}")
        assert status == 200 and data["topics"] == 1
        assert (await call(admin, "GET", f"/api/admin/topics/{tid}/questions"))[1]["topic"]["questionCount"] == 2
        assert (await call(admin, "PUT", f"/api/admin/bank/{manual}", {"text": "Tahrir", "options": ["a", "b"], "correct": 1}))[0] == 200
        assert (await call(admin, "DELETE", f"/api/admin/bank/{ids[0]}"))[0] == 404
        # bir nechtasini birdan o'chirish
        extra = (await call(admin, "POST", "/api/admin/bank", {"text": "Ortiqcha?", "options": ["a", "b"], "correct": 0, "topicIds": [tid]}))[1]["question"]["id"]
        status, data = await call(admin, "POST", "/api/admin/bank/delete", {"questionIds": [extra, extra, 999999]})
        assert status == 200 and data == {"deleted": 1, "topics": 1}
        assert (await call(admin, "POST", "/api/admin/bank/delete", {"questionIds": "1"}))[0] == 400
        assert (await call(admin, "POST", "/api/admin/bank", {"text": "x", "options": ["a", "b"], "correct": 0, "topicIds": [99999]}))[0] == 404
        # mavzu o'chirilsa savollar bankda qoladi
        await call(admin, "DELETE", f"/api/admin/topics/{tid}")
        assert (await call(admin, "GET", "/api/admin/bank?topic=none"))[1]["total"] == 3
        # oddiy foydalanuvchi bankka kira olmaydi
        for method, path, body in [
            ("GET", "/api/admin/bank", None), ("GET", "/api/admin/bank/ids", None),
            ("POST", "/api/admin/bank", {"text": "x", "options": ["a", "b"], "correct": 0}),
            ("POST", "/api/admin/bank/upload", {"content": FILE}), ("PUT", f"/api/admin/bank/{manual}", {}),
            ("DELETE", f"/api/admin/bank/{manual}", None), ("POST", "/api/admin/bank/delete", {"questionIds": [manual]}),
            ("POST", "/api/admin/topics/1/link", {"questionIds": [1]}),
        ]:
            assert (await call(user, method, path, body))[0] == 403, (method, path)
    finally:
        await admin.close()
        await user.close()
        await server.close()
