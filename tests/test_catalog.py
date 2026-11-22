"""Bosh sahifa reytingi: davrlar (bugun/hafta/oy/hamma vaqt), "qizg'in" ball, qidiruv, sahifalash va kesh."""
import asyncio
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import catalog, config
from app.catalog import TopicCatalog, hot_score, hot_weight
from app.db import Database
from app.server import create_app
from test_hub import FakeClock

QS = [{"text": "Savol", "options": ["A", "B"], "correct": 0}]
DAY = 86_400_000


def now_ms():
    return int(time.time() * 1000)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TZ_OFFSET_HOURS", 5.0)
    monkeypatch.setattr(config, "HOT_HALF_LIFE_DAYS", 2.0)
    monkeypatch.setattr(config, "HOT_WINDOW_DAYS", 14)
    monkeypatch.setattr(config, "HOT_LIVE_WEIGHT", 3.0)
    db = Database(tmp_path / "c.db")
    live = {}
    clock = FakeClock()
    clock.t = 100.0
    cat = TopicCatalog(db, clock, lambda tid: live.get(tid, (0, 0)))
    u = [db.create_user(f"u{i}", "x", False) for i in range(2)]
    yield db, cat, clock, live, u
    db.close()


def topic(db, name, questions=QS):
    return db.create_topic(name, questions, False, None, None)


def play(db, tid, players, days_ago=0, n=1):
    for _ in range(n):
        db.record_duel_start(tid, players, now_ms() - days_ago * DAY)


def names(cat, period, **kw):
    return [item["name"] for item in cat.browse(period, **kw)["items"]]


def test_hot_score_formula():
    assert hot_weight(0) == 1.0 and hot_weight(2) == 0.5 and hot_weight(4) == 0.25
    assert hot_weight(14) == 0.0 and hot_weight(-1) == 0.0
    assert hot_score({0: 4, 2: 4}) == 6.0          # bugun 4 + 2 kun oldin 4·0.5
    assert hot_score({0: 1}, live=2) == 1 + 3.0 * 2
    assert hot_score({20: 100}) == 0.0              # 14 kundan eski faollik hisobga olinmaydi


def test_periods_rank_by_activity_in_that_period(env):
    db, cat, _, _, u = env
    today, week, month, old = (topic(db, n) for n in ("Bugungi", "Haftalik", "Oylik", "Eski"))
    play(db, today, u, 0, n=2)
    play(db, week, u, 3, n=5)
    play(db, month, u, 20, n=8)
    play(db, old, u, 100, n=20)
    assert names(cat, "today")[:1] == ["Bugungi"]
    assert names(cat, "week")[:2] == ["Haftalik", "Bugungi"]
    assert names(cat, "month")[:3] == ["Oylik", "Haftalik", "Bugungi"]
    assert names(cat, "all") == ["Eski", "Oylik", "Haftalik", "Bugungi"]
    # qizg'in: yaqindagi faollik eski jami sondan ustun (bugun 2 > 3 kun oldin 5·0.35 = 1.77)
    assert names(cat, "hot")[:3] == ["Bugungi", "Haftalik", "Oylik"]
    page = cat.browse("today")
    assert page["items"][0]["today"] == 2 and page["items"][0]["periodCount"] == 2


def test_quiet_topics_follow_active_ones_by_recency_then_name(env):
    db, cat, _, _, u = env
    busy, played_long_ago, never_b, never_a = (topic(db, n) for n in ("Faol", "Avval", "B mavzu", "A mavzu"))
    play(db, busy, u, 0)
    play(db, played_long_ago, u, 60)
    assert names(cat, "today") == ["Faol", "Avval", "A mavzu", "B mavzu"]


def test_inactive_and_empty_topics_are_hidden(env):
    db, cat, _, _, u = env
    visible = topic(db, "Ochiq")
    closed = topic(db, "Yopiq")
    topic(db, "Bo'sh", questions=[])
    play(db, closed, u, 0, n=9)
    db.update_topic(closed, active=False)
    cat.topics_changed()
    assert names(cat, "today") == ["Ochiq"] and names(cat, "all") == ["Ochiq"]
    assert cat.month_all[closed] == 9  # tarix saqlanadi (boshqaruv paneli uchun)
    assert cat.is_playable(visible) and not cat.is_playable(closed)


def test_search_and_pagination(env):
    db, cat, _, _, u = env
    for i in range(30):
        topic(db, f"Matematika {i:02d}")
    topic(db, "Tarix")
    play(db, db.get_topic(1)["id"], u, 0, n=3)
    page1 = cat.browse("hot", limit=24)
    assert page1["total"] == 31 and len(page1["items"]) == 24 and page1["nextOffset"] == 24
    page2 = cat.browse("hot", offset=24, limit=24)
    assert len(page2["items"]) == 7 and page2["nextOffset"] is None
    found = cat.browse("today", query="  MATEMATIKA  0", limit=60)
    assert found["total"] == 10 and found["items"][0]["name"] == "Matematika 00"  # faoli birinchi
    assert cat.browse("today", query="yo'q mavzu")["total"] == 0


def test_cache_rebuilds_on_topic_change_activity_and_ttl(env, monkeypatch):
    monkeypatch.setattr(config, "RANKING_TTL", 30.0)
    monkeypatch.setattr(config, "RANKING_REFRESH", 5.0)
    db, cat, clock, _, u = env
    a = topic(db, "Alfa")
    cat.browse("today")
    built = cat.rebuilds
    play(db, a, u, 0)
    cat.activity_changed()
    clock.t += 2
    assert cat.browse("today")["items"][0]["today"] == 0 and cat.rebuilds == built  # hali eski (≤ 5 s)
    clock.t += 3
    assert cat.browse("today")["items"][0]["today"] == 1 and cat.rebuilds == built + 1
    topic(db, "Beta")
    cat.topics_changed()  # mavzular o'zgarsa — darhol
    assert cat.browse("today")["total"] == 2 and cat.rebuilds == built + 2
    clock.t += 29
    cat.browse("today")
    assert cat.rebuilds == built + 2
    clock.t += 1
    cat.browse("today")
    assert cat.rebuilds == built + 3  # TTL


def test_live_activity_boosts_hot_ranking(env):
    db, cat, _, live, u = env
    a, b = topic(db, "Alfa"), topic(db, "Beta")
    play(db, a, u, 0)
    live[b] = (1, 1)  # hozir 1 kutmoqda va 1 duel ketmoqda
    cat.topics_changed()
    assert names(cat, "hot") == ["Beta", "Alfa"]
    card = cat.browse("hot")["items"][0]
    assert card["waiting"] == 1 and card["playing"] == 1 and card["periodCount"] is None


def test_browse_api_validates_and_requires_login(tmp_path):
    async def body():
        server = TestServer(create_app(db_path=tmp_path / "b.db"))
        await server.start_server()
        user, guest = TestClient(server), TestClient(server)
        try:
            for c in (user, guest):
                await c.start_server()
            await user.post("/api/auth/register", json={"login": "admin", "password": "1234"})
            await user.post("/api/admin/topics", json={"name": "Tarix", "content": "Savol?\n====\n#Ha\n====\nYo'q"})
            assert (await guest.get("/api/topics/browse")).status == 401
            r = await user.get("/api/topics/browse?period=week&q=tar")
            data = await r.json()
            assert r.status == 200 and data["total"] == 1 and data["items"][0]["name"] == "Tarix"
            for bad in ("period=year", "offset=-1", "limit=0", "limit=61", "offset=abc"):
                assert (await user.get(f"/api/topics/browse?{bad}")).status == 400, bad
            assert catalog.PERIODS == ("hot", "today", "week", "month", "all")
        finally:
            await user.close()
            await guest.close()
            await server.close()

    asyncio.run(body())
