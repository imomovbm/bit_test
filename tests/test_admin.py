"""Boshqaruv paneli API: huquqlar, foydalanuvchilarni boshqarish, bloklash, sozlamalar, mavzular."""
import asyncio

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from app import config
from app.parser import parse_questions
from app.server import create_app

SAMPLE = "\n++++\n".join(f"Savol {i}?\n====\n#Toʻgʻri {i}\n====\nNotoʻgʻri {i}\n====\nBoshqa {i}" for i in range(6))
SAMPLE2 = "Yangi savol?\n====\nA\n====\n#B\n++++\nYana bir savol?\n====\n#\\#teg emas\n====\n\\#teg"


def test_admin_api(tmp_path):
    asyncio.run(_flow(tmp_path))


async def _flow(tmp_path):
    app = create_app(db_path=tmp_path / "admin.db")
    server = TestServer(app)
    await server.start_server()
    clients = [TestClient(server) for _ in range(5)]
    admin, student, guest, created, extra = clients
    try:
        for c in clients:
            await c.start_server()

        async def call(client, method, path, body=None):
            r = await client.request(method, path, json=body)
            data = await r.json() if r.content_type == "application/json" else await r.text()
            return r.status, data

        # --- birinchi foydalanuvchi "admin" — bosh administrator (tizim egasi)
        assert (await call(guest, "GET", "/api/auth/me"))[1]["registrationOpen"] is True
        status, data = await call(admin, "POST", "/api/auth/register", {"login": "admin", "password": "1234"})
        assert status == 200 and data["user"]["isAdmin"] is True and data["user"]["isSuperadmin"] is True
        status, data = await call(student, "POST", "/api/auth/register", {"login": "talaba", "password": "1234"})
        assert status == 200 and data["user"]["isAdmin"] is False and data["user"]["isSuperadmin"] is False
        # "admin" logini band: katta-kichik harf farqsiz qayta ro'yxatdan o'tib bo'lmaydi
        assert (await call(guest, "POST", "/api/auth/register", {"login": "ADMIN", "password": "1234"}))[0] == 409
        status, topic = await call(admin, "POST", "/api/admin/topics", {"name": "Sinov", "content": SAMPLE})
        assert status == 201
        tid = topic["topic"]["id"]

        # --- oddiy foydalanuvchi va mehmon boshqaruv API'siga kira olmaydi
        admin_calls = [
            ("GET", "/api/admin/overview", None),
            ("GET", "/api/admin/settings", None),
            ("PATCH", "/api/admin/settings", {"registrationOpen": False}),
            ("GET", "/api/admin/users", None),
            ("POST", "/api/admin/users", {"login": "xaker", "password": "1234"}),
            ("PATCH", "/api/admin/users/1", {"isAdmin": False}),
            ("DELETE", "/api/admin/users/1", None),
            ("GET", "/api/admin/topics", None),
            ("POST", "/api/admin/topics/parse", {"content": SAMPLE}),
            ("POST", "/api/admin/topics", {"name": "X", "content": SAMPLE}),
            ("PATCH", f"/api/admin/topics/{tid}", {"name": "Y"}),
            ("PUT", f"/api/admin/topics/{tid}/content", {"content": SAMPLE2}),
            ("GET", f"/api/admin/topics/{tid}/export", None),
            ("GET", f"/api/admin/topics/{tid}/questions", None),
            ("DELETE", f"/api/admin/topics/{tid}", None),
        ]
        for method, path, body in admin_calls:
            assert (await call(student, method, path, body))[0] == 403, (method, path)
            assert (await call(guest, method, path, body))[0] == 401, (method, path)

        # --- umumiy statistika
        status, ov = await call(admin, "GET", "/api/admin/overview")
        assert status == 200
        assert ov["stats"]["users"]["total"] == 2 and ov["stats"]["users"]["admins"] == 1
        assert ov["stats"]["topics"] == {"total": 1, "questions": 6}
        assert [u["login"] for u in ov["recentUsers"]] == ["talaba", "admin"]
        assert [u["isSuperadmin"] for u in ov["recentUsers"]] == [False, True]
        assert ov["settings"] == {"registrationOpen": True}

        # --- administrator foydalanuvchi yaratadi
        status, data = await call(admin, "POST", "/api/admin/users", {"login": "a b", "password": "1234"})
        assert status == 400
        status, data = await call(admin, "POST", "/api/admin/users", {"login": "TALABA", "password": "1234"})
        assert status == 409
        status, data = await call(admin, "POST", "/api/admin/users", {"login": "sardor", "password": "12"})
        assert status == 400
        status, data = await call(admin, "POST", "/api/admin/users", {"login": "sardor", "password": "sardor1"})
        assert status == 201 and data["user"]["isAdmin"] is False and data["user"]["blocked"] is False
        sardor = data["user"]["id"]
        status, data = await call(created, "POST", "/api/auth/login", {"login": "sardor", "password": "sardor1"})
        assert status == 200

        # --- bloklash: sessiya bekor qilinadi, ochiq oyna yopiladi, kirish taqiqlanadi
        ws = await created.ws_connect("/ws")
        hello = await ws.receive_json(timeout=3)
        assert hello["t"] == "hello"
        status, data = await call(admin, "PATCH", f"/api/admin/users/{sardor}", {"blocked": True})
        assert status == 200 and data["user"]["blocked"] is True
        msg = await ws.receive(timeout=3)
        while msg.type == WSMsgType.TEXT:
            msg = await ws.receive(timeout=3)
        assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
        assert ws.close_code == 4401 and msg.extra == "blocked"
        assert (await call(created, "GET", "/api/auth/me"))[1]["user"] is None
        status, data = await call(created, "POST", "/api/auth/login", {"login": "sardor", "password": "sardor1"})
        assert status == 403 and "bloklangan" in data["error"]
        status, data = await call(created, "POST", "/api/auth/login", {"login": "sardor", "password": "xato"})
        assert status == 401  # parol noto'g'ri bo'lsa — bloklangani aytilmaydi
        status, data = await call(admin, "PATCH", f"/api/admin/users/{sardor}", {"blocked": False})
        assert data["user"]["blocked"] is False
        assert (await call(created, "POST", "/api/auth/login", {"login": "sardor", "password": "sardor1"}))[0] == 200

        # --- o'z huquqlarini o'zgartirib bo'lmaydi
        assert (await call(admin, "PATCH", "/api/admin/users/1", {"blocked": True}))[0] == 400
        assert (await call(admin, "PATCH", "/api/admin/users/1", {"isAdmin": False}))[0] == 400
        assert (await call(admin, "DELETE", "/api/admin/users/1"))[0] == 400
        assert (await call(admin, "PATCH", "/api/admin/users/999", {"blocked": True}))[0] == 404

        # --- admin huquqi: foydalanuvchi oynasiga xabar boradi
        ws = await student.ws_connect("/ws")
        await ws.receive_json(timeout=3)
        status, data = await call(admin, "PATCH", "/api/admin/users/2", {"isAdmin": True})
        assert data["user"]["isAdmin"] is True
        while True:
            msg = await ws.receive_json(timeout=3)
            if msg["t"] == "account":
                break
        assert msg["d"] == {"isAdmin": True}
        await ws.close()
        assert (await call(student, "GET", "/api/admin/overview"))[0] == 200
        # oddiy administrator: mavzularni boshqaradi, foydalanuvchilarni faqat ko'radi
        status, data = await call(student, "GET", "/api/admin/users")
        assert status == 200 and [u["isSuperadmin"] for u in data["users"] if u["login"] == "admin"] == [True]
        assert (await call(student, "POST", "/api/admin/topics", {"name": "Talaba mavzusi", "content": SAMPLE}))[0] == 201
        for method, path, body in [
            ("POST", "/api/admin/users", {"login": "boshqa", "password": "1234"}),
            ("PATCH", f"/api/admin/users/{sardor}", {"blocked": True}),
            ("PATCH", f"/api/admin/users/{sardor}", {"password": "1111"}),
            ("PATCH", f"/api/admin/users/{sardor}", {"isAdmin": True}),
            ("PATCH", "/api/admin/users/1", {"blocked": True}),
            ("DELETE", f"/api/admin/users/{sardor}", None),
            ("PATCH", "/api/admin/settings", {"registrationOpen": False}),
        ]:
            status, data = await call(student, method, path, body)
            assert status == 403 and "bosh administrator" in data["error"], (method, path)
        assert (await call(student, "GET", "/api/admin/settings"))[0] == 200
        await call(admin, "PATCH", "/api/admin/users/2", {"isAdmin": False})
        assert (await call(student, "GET", "/api/admin/overview"))[0] == 403

        # --- parolni tiklash: foydalanuvchi hamma joydan chiqariladi; admin o'zinikini o'zgartirsa — tizimda qoladi
        assert (await call(admin, "PATCH", "/api/admin/users/2", {"password": "yangi1"}))[0] == 200
        assert (await call(student, "GET", "/api/auth/me"))[1]["user"] is None
        assert (await call(student, "POST", "/api/auth/login", {"login": "talaba", "password": "yangi1"}))[0] == 200
        assert (await call(admin, "PATCH", "/api/admin/users/1", {"password": "boshqa1"}))[0] == 200
        assert (await call(admin, "GET", "/api/auth/me"))[1]["user"]["login"] == "admin"
        assert (await call(extra, "POST", "/api/auth/login", {"login": "admin", "password": "boshqa1"}))[0] == 200

        # --- ro'yxatdan o'tishni yopish
        status, data = await call(admin, "PATCH", "/api/admin/settings", {"registrationOpen": False})
        assert data["settings"]["registrationOpen"] is False
        assert (await call(guest, "GET", "/api/auth/me"))[1]["registrationOpen"] is False
        status, data = await call(guest, "POST", "/api/auth/register", {"login": "yangi", "password": "1234"})
        assert status == 403
        assert (await call(admin, "POST", "/api/admin/users", {"login": "yangi", "password": "1234"}))[0] == 201
        await call(admin, "PATCH", "/api/admin/settings", {"registrationOpen": True})
        assert (await call(guest, "POST", "/api/auth/register", {"login": "mehmon", "password": "1234"}))[0] == 200

        # --- mavzuni yangi fayl bilan almashtirish va yuklab olish
        assert (await call(admin, "PUT", f"/api/admin/topics/{tid}/content", {"content": "buzuq fayl"}))[0] == 400
        assert (await call(admin, "PUT", "/api/admin/topics/999/content", {"content": SAMPLE2}))[0] == 404
        status, data = await call(admin, "PUT", f"/api/admin/topics/{tid}/content", {"content": SAMPLE2, "fileName": "v2.txt"})
        assert status == 200 and data["topic"]["questionCount"] == 2 and data["topic"]["name"] == "Sinov"
        assert data["topic"]["sourceFile"] == "v2.txt"
        r = await admin.get(f"/api/admin/topics/{tid}/export")
        assert r.status == 200 and r.content_type == "text/plain"
        assert "attachment" in r.headers["Content-Disposition"] and "Sinov.txt" in r.headers["Content-Disposition"]
        exported = parse_questions(await r.text())["questions"]
        status, data = await call(admin, "GET", f"/api/admin/topics/{tid}/questions")
        assert exported == [{k: q[k] for k in ("text", "options", "correct")} for q in data["questions"]]
        assert exported[1]["options"] == ["#teg emas", "#teg"] and exported[1]["correct"] == 0

        # --- foydalanuvchini o'chirish
        status, users = await call(admin, "GET", "/api/admin/users")
        assert {u["login"] for u in users["users"]} == {"admin", "talaba", "sardor", "yangi", "mehmon"}
        assert all("lastSeenAt" in u and "balloonGames" in u for u in users["users"])
        assert (await call(admin, "DELETE", f"/api/admin/users/{sardor}"))[0] == 200
        assert (await call(created, "GET", "/api/auth/me"))[1]["user"] is None
    finally:
        for c in clients:
            await c.close()
        await server.close()


def test_superadmin_login_reserved_and_bootstrap(tmp_path, monkeypatch):
    asyncio.run(_superadmin_flow(tmp_path, monkeypatch))


async def _start(path):
    server = TestServer(create_app(db_path=path))
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    return server, client


async def _superadmin_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "owner.db"
    # 1) birinchi foydalanuvchi boshqa login bilan — u admin, lekin bosh administrator emas; "admin" band
    server, c = await _start(db_path)
    try:
        r = await c.post("/api/auth/register", json={"login": "ustoz", "password": "1234"})
        user = (await r.json())["user"]
        assert user["isAdmin"] is True and user["isSuperadmin"] is False
        assert (await c.post("/api/admin/users", json={"login": "x1", "password": "1234"})).status == 403
        guest = TestClient(server)
        await guest.start_server()
        r = await guest.post("/api/auth/register", json={"login": "Admin", "password": "1234"})
        assert r.status == 409  # band login — hech kim egallay olmaydi
        await guest.close()
    finally:
        await c.close()
        await server.close()

    # 2) TD_SUPERADMIN_PASSWORD: ishga tushishda bosh administrator yaratiladi
    monkeypatch.setattr(config, "SUPERADMIN_PASSWORD", "sirli-parol")
    server, c = await _start(db_path)
    try:
        r = await c.post("/api/auth/login", json={"login": "admin", "password": "sirli-parol"})
        assert r.status == 200 and (await r.json())["user"]["isSuperadmin"] is True
        assert (await c.post("/api/admin/users", json={"login": "oquvchi", "password": "1234"})).status == 201
        users = (await (await c.get("/api/admin/users")).json())["users"]
        assert {u["login"]: u["isSuperadmin"] for u in users} == {"ustoz": False, "admin": True, "oquvchi": False}
    finally:
        await c.close()
        await server.close()

    # 3) parol unutilsa: boshqa TD_SUPERADMIN_PASSWORD bilan qayta ishga tushirish parolni tiklaydi
    monkeypatch.setattr(config, "SUPERADMIN_PASSWORD", "yangi-parol")
    server, c = await _start(db_path)
    try:
        assert (await c.post("/api/auth/login", json={"login": "admin", "password": "sirli-parol"})).status == 401
        assert (await c.post("/api/auth/login", json={"login": "admin", "password": "yangi-parol"})).status == 200
    finally:
        await c.close()
        await server.close()

    # 4) parolsiz ishga tushganda ham bosh administrator doim admin va bloklanmagan bo'ladi
    monkeypatch.setattr(config, "SUPERADMIN_PASSWORD", None)
    from app.db import Database
    db = Database(db_path)
    owner = db.user_by_login("admin")
    db.set_admin(owner["id"], False)
    db.set_blocked(owner["id"], True)
    db.close()
    server, c = await _start(db_path)
    try:
        r = await c.post("/api/auth/login", json={"login": "admin", "password": "yangi-parol"})
        assert r.status == 200 and (await r.json())["user"]["isAdmin"] is True
    finally:
        await c.close()
        await server.close()
