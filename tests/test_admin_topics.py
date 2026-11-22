"""Boshqaruv: mavzular faolligi ro'yxati (ustunlar, filtrlar, saralash), o'chirishga tavsiya, ommaviy yopish/ochish,
jurnal, avtomatik yopish sozlamasi va huquqlar (faqat administratorlar)."""
import asyncio
import json
import time

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from app import config
from app.keys import DB, HUB
from app.server import create_app

DAY = 86_400_000
CONTENT = "Savol?\n====\n#Ha\n====\nYo'q"


def now_ms():
    return int(time.time() * 1000)


async def call(client, method, path, body=None):
    r = await client.request(method, path, json=body)
    try:
        data = await r.json()
    except Exception:
        data = None
    return r.status, data


async def setup(tmp_path):
    server = TestServer(create_app(db_path=tmp_path / "adm.db"))
    await server.start_server()
    admin, member, guest = TestClient(server), TestClient(server), TestClient(server)
    for c in (admin, member, guest):
        await c.start_server()
    assert (await call(admin, "POST", "/api/auth/register", {"login": "admin", "password": "1234"}))[0] == 200
    assert (await call(member, "POST", "/api/auth/register", {"login": "talaba", "password": "1234"}))[0] == 200
    db = server.app[DB]
    users = [db.create_user(f"o{i}", "x", False) for i in range(2)]
    ids = {}
    # nomi -> (oxirgi o'yin necha kun oldin yoki None, yaratilgan necha kun oldin, duellar soni)
    plan = {"Yangi faol": (1, 400, 3), "Oylik": (45, 400, 2), "Choraklik": (100, 400, 1), "Yillik": (200, 400, 4),
            "Hech o'ynalmagan eski": (None, 400, 0), "Hech o'ynalmagan yangi": (None, 1, 0)}
    for name, (played, created, n) in plan.items():
        status, data = await call(admin, "POST", "/api/admin/topics", {"name": name, "content": CONTENT})
        assert status == 201
        tid = ids[name] = data["topic"]["id"]
        db.conn.execute("UPDATE topics SET created_at = ? WHERE id = ?", (now_ms() - created * DAY, tid))
        for k in range(n):
            db.record_duel_start(tid, users, now_ms() - played * DAY - k * 1000)
    server.app[HUB].catalog.topics_changed()
    return server, admin, member, guest, ids


def run(coro_fn, tmp_path):
    async def body():
        server, admin, member, guest, ids = await setup(tmp_path)
        try:
            await coro_fn(server, admin, member, guest, ids)
        finally:
            for c in (admin, member, guest):
                await c.close()
            await server.close()
    asyncio.run(body())


def test_columns_filters_sorting_and_pagination(tmp_path):
    async def body(server, admin, member, guest, ids):
        status, data = await call(admin, "GET", "/api/admin/topic-activity?sort=name")
        assert status == 200 and data["total"] == 6 and data["counts"] == {"active": 6, "inactive": 0}
        row = next(t for t in data["items"] if t["name"] == "Yillik")
        assert row["totalDuels"] == 4 and row["duels30"] == 0 and row["active"] is True and row["lastPlayedAt"] < now_ms() - 199 * DAY
        assert next(t for t in data["items"] if t["name"] == "Yangi faol")["duels30"] == 3
        assert data["settings"] == {"autoDeactivateDays": 0, "suggestDays": config.SUGGEST_IDLE_DAYS}

        async def names(query):
            st, d = await call(admin, "GET", f"/api/admin/topic-activity?{query}")
            assert st == 200, (query, d)
            return [t["name"] for t in d["items"]]

        # "N kundan beri o'ynalmagan" (hech o'ynalmagan — yaratilgan paytdan)
        assert set(await names("idle=30")) == {"Oylik", "Choraklik", "Yillik", "Hech o'ynalmagan eski"}
        assert set(await names("idle=90")) == {"Choraklik", "Yillik", "Hech o'ynalmagan eski"}
        assert set(await names("idle=180")) == {"Yillik", "Hech o'ynalmagan eski"}
        assert await names("q=ynalmagan&sort=name") == ["Hech o'ynalmagan eski", "Hech o'ynalmagan yangi"]
        assert (await names("sort=total&dir=desc"))[:2] == ["Yillik", "Yangi faol"]
        assert (await names("sort=recent&dir=desc"))[0] == "Yangi faol"
        assert (await names("sort=lastPlayed&dir=desc"))[:4] == ["Yangi faol", "Oylik", "Choraklik", "Yillik"]
        st, page2 = await call(admin, "GET", "/api/admin/topic-activity?sort=name&per=5&page=2")
        assert page2["pages"] == 2 and len(page2["items"]) == 1
        for bad in ("sort=hack", "status=x", "idle=-1", "per=1000", "page=0", "dir=up"):
            assert (await call(admin, "GET", f"/api/admin/topic-activity?{bad}"))[0] == 400, bad

    run(body, tmp_path)


def test_suggested_bulk_deactivate_reactivate_and_audit_log(tmp_path):
    async def body(server, admin, member, guest, ids):
        st, sug = await call(admin, "GET", "/api/admin/topic-activity/suggested")
        assert st == 200 and sug["days"] == 90
        assert [t["name"] for t in sug["items"]] == ["Hech o'ynalmagan eski", "Yillik", "Choraklik"]  # eng uzoq o'ynalmagani oldin
        st, sid = await call(admin, "GET", "/api/admin/topic-activity/suggested/ids?days=150")
        assert set(sid["ids"]) == {ids["Yillik"], ids["Hech o'ynalmagan eski"]}

        # kimdir "Yillik" mavzusini lobbida kutmoqda — yopilganda seeki bekor qilinadi
        ws = await member.ws_connect("/ws")
        await ws.receive()
        await ws.send_json({"t": "seek:create", "d": {"topicId": ids["Yillik"]}})
        while json.loads((await asyncio.wait_for(ws.receive(), 3)).data)["t"] != "queue":
            pass
        assert server.app[HUB].topic_live(ids["Yillik"]) == (1, 0)
        db = server.app[DB]
        duel_rows = db._scalar("SELECT COUNT(*) FROM topic_activity_daily WHERE topic_id = ?", (ids["Yillik"],))
        st, res = await call(admin, "POST", "/api/admin/topic-activity/status",
                             {"ids": sid["ids"] + [999_999], "active": False, "source": "suggested"})
        assert st == 200 and res["changed"] == 2  # mavjud bo'lmagan id e'tiborsiz
        notices = []
        while True:
            msg = await asyncio.wait_for(ws.receive(), 3)
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            data = json.loads(msg.data)
            notices.append(data)
            if data["t"] == "notice":
                break
        assert any(m["t"] == "notice" and "yopildi" in m["d"]["message"] for m in notices)
        assert server.app[HUB].topic_live(ids["Yillik"]) == (0, 0)
        # bosh sahifadan va lobbidan yo'qoldi, tarix saqlandi
        st, browse = await call(member, "GET", "/api/topics/browse?period=all&limit=60")
        assert ids["Yillik"] not in [t["id"] for t in browse["items"]] and browse["total"] == 4
        await ws.send_json({"t": "seek:create", "d": {"topicId": ids["Yillik"]}})
        err = None
        while err is None:
            data = json.loads((await asyncio.wait_for(ws.receive(), 3)).data)
            err = data["d"] if data["t"] == "error" else None
        assert err["code"] == "topic"
        assert db.get_topic(ids["Yillik"])["total_duels"] == 4
        assert db._scalar("SELECT COUNT(*) FROM topic_activity_daily WHERE topic_id = ?", (ids["Yillik"],)) == duel_rows
        st, lst = await call(admin, "GET", "/api/admin/topic-activity?status=inactive")
        assert {t["name"] for t in lst["items"]} == {"Yillik", "Hech o'ynalmagan eski"} and lst["counts"]["inactive"] == 2

        # bittasini qayta ochish (mavjud tugma — PATCH) ham jurnalga yoziladi
        assert (await call(admin, "PATCH", f"/api/admin/topics/{ids['Yillik']}", {"active": True}))[0] == 200
        st, browse = await call(member, "GET", "/api/topics/browse?period=all&limit=60")
        assert ids["Yillik"] in [t["id"] for t in browse["items"]]
        st, logs = await call(admin, "GET", "/api/admin/topic-activity/log")
        assert logs["total"] == 3
        first = logs["items"][0]
        assert first["topicName"] == "Yillik" and first["active"] is True and first["by"] == "admin" and first["reason"] == "manual"
        assert {(e["topicName"], e["active"], e["reason"]) for e in logs["items"][1:]} == {
            ("Yillik", False, "suggested"), ("Hech o'ynalmagan eski", False, "suggested")}
        await ws.close()

    run(body, tmp_path)


def test_auto_deactivate_is_off_by_default_and_logged(tmp_path):
    async def body(server, admin, member, guest, ids):
        hub = server.app[HUB]
        hub.maintenance()
        assert all(server.app[DB].get_topic(t)["active"] for t in ids.values())  # standart — o'chiq
        for bad in (3, -1, 4000, "30", True):
            assert (await call(admin, "PATCH", "/api/admin/topic-activity/settings", {"autoDeactivateDays": bad}))[0] == 400
        st, res = await call(admin, "PATCH", "/api/admin/topic-activity/settings", {"autoDeactivateDays": 150, "suggestDays": 60})
        assert st == 200 and res["settings"] == {"autoDeactivateDays": 150, "suggestDays": 60}
        hub.maintenance()
        inactive = {n for n, t in ids.items() if not server.app[DB].get_topic(t)["active"]}
        assert inactive == {"Yillik", "Hech o'ynalmagan eski"}
        st, logs = await call(admin, "GET", "/api/admin/topic-activity/log")
        assert {e["reason"] for e in logs["items"]} == {"auto:150"} and {e["by"] for e in logs["items"]} == {None}
        assert (await call(admin, "GET", "/api/admin/topic-activity/suggested"))[1]["days"] == 60

    run(body, tmp_path)


def test_only_admins_can_use_topic_activity_tools(tmp_path):
    async def body(server, admin, member, guest, ids):
        endpoints = [
            ("GET", "/api/admin/topic-activity", None),
            ("GET", "/api/admin/topic-activity/suggested", None),
            ("GET", "/api/admin/topic-activity/suggested/ids", None),
            ("POST", "/api/admin/topic-activity/status", {"ids": [ids["Oylik"]], "active": False}),
            ("GET", "/api/admin/topic-activity/log", None),
            ("PATCH", "/api/admin/topic-activity/settings", {"autoDeactivateDays": 30}),
            ("PATCH", f"/api/admin/topics/{ids['Oylik']}", {"active": False}),
        ]
        for method, path, payload in endpoints:
            assert (await call(member, method, path, payload))[0] == 403, path
            assert (await call(guest, method, path, payload))[0] == 401, path
        assert server.app[DB].get_topic(ids["Oylik"])["active"] == 1
        for bad in ({"ids": "1", "active": False}, {"ids": [], "active": False}, {"ids": [True], "active": False},
                    {"ids": [1], "active": "no"}, {"ids": list(range(1, 2003)), "active": False}):
            assert (await call(admin, "POST", "/api/admin/topic-activity/status", bad))[0] == 400, bad

    run(body, tmp_path)
