"""Lobbi va tezkor juftlash: seeklar, bir vaqtda qo'shilish, muddat, bekor qilish, qo'l siqish, obuna farqlari."""
import asyncio
import json
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import config
from app.db import Database
from app.hub import DuelHub
from app.server import create_app
from test_hub import Conn, FakeClock

QS = [{"text": f"Savol {i}", "options": ["A", "B", "C", "D"], "correct": i % 4} for i in range(20)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COUNTDOWN", 3.0)
    db = Database(tmp_path / "l.db")
    users = {}
    for name in ("ali", "vali", "soli", "gani", "hasan"):
        uid = db.create_user(name, "x", False)
        users[name] = {"id": uid, "login": name}
    topics = [db.create_topic(name, QS, False, None, None) for name in ("Tarix", "Fizika", "Kimyo")]
    clock = FakeClock()
    clock.t = 1000.0
    yield SimpleNamespace(db=db, clock=clock, hub=DuelHub(db, clock), users=users, topics=topics)
    db.close()


def online(env, name, ip="10.0.0.1"):
    c = Conn(env, env.users[name])
    c.ip = ip
    env.hub.connect(env.users[name], c)
    return c


def act(env, name, conn, t, **d):
    env.hub.handle(env.users[name]["id"], conn, t, d)


def seek(env, name, conn, topic=None):
    act(env, name, conn, "seek:create", topicId=topic)


def errors(conn):
    return [d for t, d in conn.msgs if t == "error"]


def test_two_joins_on_one_seek_exactly_one_wins(env):
    t = env.topics[0]
    a, v, s = online(env, "ali"), online(env, "vali"), online(env, "soli")
    seek(env, "ali", a, t)
    sid = a.last("queue")["seekId"]
    act(env, "vali", v, "seek:join", seekId=sid)
    act(env, "soli", s, "seek:join", seekId=sid)  # bir vaqtda bosgan ikkinchi o'yinchi
    assert v.last("duel:start")["opp"]["login"] == "ali" and a.last("duel:start")["opp"]["login"] == "vali"
    assert s.last("duel:start") is None
    err = errors(s)[-1]
    assert err["code"] == "taken" and err["seekId"] == sid and "allaqachon" in err["message"]
    assert len(env.hub.duels) == 1 and env.hub.stats["joinRaces"] == 1


def test_quick_pairing_on_topic(env):
    t = env.topics[1]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    assert a.last("queue")["topicId"] == t and not env.hub.duels  # hech kim kutmayapti — seek yaratildi
    seek(env, "vali", v, t)                                         # kutayotgan bor — darhol duel
    assert v.last("duel:start")["topicId"] == t and not env.hub.seeks


def finished_duel(env, topic, p1, p2):
    u1, u2 = env.users[p1], env.users[p2]
    env.db.save_duel(topic_id=topic, topic_name="x", p1={"id": u1["id"], "login": p1, "correct": 1, "time_ms": 1},
                     p2={"id": u2["id"], "login": p2, "correct": 0, "time_ms": 1}, total=3, winner=1, reason="score",
                     started_at=1, finished_at=2)


def test_any_topic_prefers_recent_topics_then_longest_waiting(env):
    t1, t2, t3 = env.topics
    a, v, s, g, hs = (online(env, n) for n in ("ali", "vali", "soli", "gani", "hasan"))
    finished_duel(env, t2, "gani", "soli")  # gani yaqinda t2 ni o'ynagan
    seek(env, "ali", a, t1)
    env.clock.t += 1
    seek(env, "vali", v, t2)
    env.clock.t += 1
    seek(env, "hasan", hs, t3)
    seek(env, "gani", g)                  # istalgan mavzu: o'zi yaqinda o'ynagan t2 — vali (ali uzoqroq kutgan bo'lsa ham)
    assert g.last("duel:start")["topicId"] == t2 and g.last("duel:start")["opp"]["login"] == "vali"
    env.hub.handle(env.users["soli"]["id"], s, "seek:create", {})  # soli ham t2 ni o'ynagan, lekin t2 da kutuvchi yo'q
    assert s.last("duel:start")["opp"]["login"] == "ali"           # — eng uzoq kutgan raqib
    uid = env.db.create_user("zafar", "x", False)
    env.users["zafar"] = {"id": uid, "login": "zafar"}
    z = online(env, "zafar")
    seek(env, "zafar", z)  # tarixi yo'q — yagona kutayotgan hasan (t3) bilan
    assert z.last("duel:start")["topicId"] == t3 and z.last("duel:start")["opp"]["login"] == "hasan"


def test_topic_seeker_meets_any_topic_seeker(env):
    t3 = env.topics[2]
    a, hs = online(env, "ali"), online(env, "hasan")
    seek(env, "hasan", hs)                           # hech kim kutmayapti — "istalgan mavzu" seeki
    assert hs.last("queue")["topicId"] is None and hs.last("queue")["topicName"] is None
    seek(env, "ali", a, t3)                          # mavzu bo'yicha kutuvchi "istalgan" kutuvchini topadi
    assert a.last("duel:start")["topicId"] == t3 and a.last("duel:start")["opp"]["login"] == "hasan"


def test_any_plus_any_plays_the_hottest_topic(env):
    t1, t2, _ = env.topics
    for _ in range(3):
        env.db.record_duel_start(t2, [env.users["soli"]["id"], env.users["gani"]["id"]])
    env.db.record_duel_start(t1, [env.users["soli"]["id"], env.users["gani"]["id"]])
    env.hub.catalog.topics_changed()
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a)
    seek(env, "vali", v)
    assert v.last("duel:start")["topicId"] == t2


def test_no_self_join_and_one_seek_per_user(env):
    t1, t2, _ = env.topics
    a = online(env, "ali")
    seek(env, "ali", a, t1)
    first = a.last("queue")["seekId"]
    act(env, "ali", a, "seek:join", seekId=first)
    assert errors(a)[-1]["code"] == "own" and not env.hub.duels
    seek(env, "ali", a, t2)  # yangisi eskisini almashtiradi
    assert first not in env.hub.seeks and len(env.hub.seeks) == 1 and a.last("queue")["topicId"] == t2


def test_cancel_and_forged_ids(env):
    t = env.topics[0]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    sid = a.last("queue")["seekId"]
    act(env, "vali", v, "seek:cancel", seekId=sid)  # boshqaning seekini bekor qilib bo'lmaydi
    assert errors(v)[-1]["code"] == "forbidden" and sid in env.hub.seeks
    for bad in ("x" * 16, "0" * 15, 123, None, {"id": sid}):
        act(env, "vali", v, "seek:join", seekId=bad)
        assert errors(v)[-1]["code"] == "taken"
    for bad_topic in ("abc", -5, 0, 10**30, True, 9999):
        act(env, "vali", v, "seek:create", topicId=bad_topic)
        assert errors(v)[-1]["code"] == "topic", bad_topic
    act(env, "ali", a, "seek:cancel", seekId=sid)
    assert not env.hub.seeks and a.last("queue") is None


def test_no_seek_or_join_while_in_a_duel(env):
    t = env.topics[0]
    a, v, s = online(env, "ali"), online(env, "vali"), online(env, "soli")
    seek(env, "ali", a, t)
    seek(env, "vali", v, t)
    assert env.hub.duels
    seek(env, "soli", s, t)
    sid = s.last("queue")["seekId"]
    seek(env, "ali", a, t)
    act(env, "vali", v, "seek:join", seekId=sid)
    assert errors(a)[-1]["code"] == "busy" and errors(v)[-1]["code"] == "busy" and sid in env.hub.seeks


def test_disconnect_and_expiry_leave_no_ghosts(env):
    t = env.topics[0]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    env.hub.disconnect(env.users["ali"]["id"], a)
    assert not env.hub.seeks and env.hub.topic_live(t) == (0, 0)
    seek(env, "vali", v, t)
    env.hub.conns.pop(env.users["vali"]["id"])  # aloqa "jim" uzildi (disconnect hodisasisiz)
    env.clock.advance(11)                       # zaxira tozalash
    assert not env.hub.seeks


def test_deactivated_topic_cancels_its_seeks(env):
    t = env.topics[0]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    sid = a.last("queue")["seekId"]
    env.db.update_topic(t, active=False)
    env.hub.topic_removed(t, "Siz kutayotgan mavzu yopildi")
    assert not env.hub.seeks and a.last("queue") is None and "yopildi" in a.last("notice")["message"]
    seek(env, "vali", v, t)
    act(env, "vali", v, "seek:join", seekId=sid)
    assert [e["code"] for e in errors(v)] == ["topic", "taken"]


def test_handshake_disconnect_cancels_duel_cleanly(env):
    t = env.topics[0]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    seek(env, "vali", v, t)
    assert env.hub.topic_live(t) == (0, 1)
    env.hub.disconnect(env.users["vali"]["id"], v)  # sanoq paytida aloqa uzildi
    assert "uzildi" in a.last("duel:cancel")["message"]
    assert not env.hub.duels and not env.hub.user_duel and env.hub.topic_live(t) == (0, 0)
    env.clock.advance(30)
    assert env.db._scalar("SELECT COUNT(*) FROM duels") == 0
    assert env.db.get_topic(t)["total_duels"] == 0  # boshlanmagan duel faollik sifatida yozilmaydi
    seek(env, "ali", a, t)                           # "kutish" holatida qotib qolmaydi
    assert a.last("queue")["topicId"] == t


def test_activity_recorded_when_duel_starts(env):
    t = env.topics[2]
    a, v = online(env, "ali"), online(env, "vali")
    seek(env, "ali", a, t)
    seek(env, "vali", v, t)
    assert env.db.get_topic(t)["total_duels"] == 0
    env.clock.advance(config.COUNTDOWN)  # sanoq tugadi — duel boshlandi
    topic = env.db.get_topic(t)
    assert topic["total_duels"] == 1 and topic["last_played_at"]
    row = env.db._one("SELECT duels_started, unique_players FROM topic_activity_daily WHERE topic_id = ?", (t,))
    assert row == {"duels_started": 1, "unique_players": 2}
    env.hub.handle(env.users["vali"]["id"], v, "duel:leave", {})
    assert env.hub.topic_live(t) == (0, 0) and env.db._scalar("SELECT COUNT(*) FROM duels") == 1


def test_avoids_same_opponent_twice_in_a_row(env):
    t1, t2, _ = env.topics
    a, v, s = online(env, "ali"), online(env, "vali"), online(env, "soli")
    seek(env, "ali", a, t1)
    seek(env, "vali", v, t1)
    env.clock.advance(config.COUNTDOWN)
    env.hub.handle(env.users["vali"]["id"], v, "duel:leave", {})
    seek(env, "ali", a, t1)       # oxirgi raqib, yaqinda o'ynalgan mavzuda va eng uzoq kutmoqda
    env.clock.t += 1
    seek(env, "soli", s, t2)
    seek(env, "vali", v)          # istalgan mavzu: ali emas, soli bilan juftlanadi
    assert v.last("duel:start")["opp"]["login"] == "soli"


def test_lobby_subscription_sends_throttled_diffs(env):
    t = env.topics[0]
    watcher, a, v = online(env, "soli"), online(env, "ali"), online(env, "vali")
    act(env, "soli", watcher, "lobby:sub", watch=[t, env.topics[1]])
    assert watcher.last("lobby")["seeks"] == []
    seek(env, "ali", a, t)
    seek(env, "vali", v, env.topics[1])
    env.hub.handle(env.users["vali"]["id"], v, "seek:cancel", {})
    assert not [d for k, d in watcher.msgs if k == "lobby:diff"]  # hali yuborilmagan (sekundiga bir marta)
    env.clock.advance(1.0)
    diffs = [d for k, d in watcher.msgs if k == "lobby:diff"]
    assert len(diffs) == 1
    assert [s["login"] for s in diffs[0]["add"]] == ["ali"] and diffs[0]["del"] == []
    assert diffs[0]["counts"] == {str(t): [1, 0]} and diffs[0]["live"][0][:3] == [t, "Tarix", 1]
    env.clock.advance(5)
    assert len([d for k, d in watcher.msgs if k == "lobby:diff"]) == 1  # o'zgarish yo'q — xabar yo'q
    act(env, "soli", watcher, "lobby:unsub")
    seek(env, "vali", v, t)
    env.clock.advance(2)
    assert len([d for k, d in watcher.msgs if k == "lobby:diff"]) == 1  # obuna bekor — yuborilmaydi


def test_lobby_list_is_capped_and_filterable(env, monkeypatch):
    monkeypatch.setattr(config, "LOBBY_LIMIT", 3)
    topics = [env.db.create_topic(f"Mavzu {i}", QS, False, None, None) for i in range(5)]
    for i, tid in enumerate(topics):
        uid = env.db.create_user(f"kutuvchi{i}", "x", False)
        user = {"id": uid, "login": f"kutuvchi{i}"}
        c = Conn(env, user)
        c.ip = "10.0.0.2"
        env.hub.connect(user, c)
        env.hub.handle(uid, c, "seek:create", {"topicId": tid})
    w = online(env, "ali")
    act(env, "ali", w, "lobby:sub")
    snap = w.last("lobby")
    assert [s["login"] for s in snap["seeks"]] == ["kutuvchi4", "kutuvchi3", "kutuvchi2"] and snap["waiting"] == 5  # eng yangilari
    act(env, "ali", w, "lobby:sub", topicId=topics[1])
    assert [s["login"] for s in w.last("lobby")["seeks"]] == ["kutuvchi1"]


def test_rate_limit_per_user(env):
    a = online(env, "ali")
    for _ in range(15):
        seek(env, "ali", a, env.topics[0])
        act(env, "ali", a, "seek:cancel")
    assert not [e for e in errors(a) if e.get("code") == "rate"]
    seek(env, "ali", a, env.topics[0])
    assert errors(a)[-1]["code"] == "rate"


# ===================================================== haqiqiy WebSocket orqali
SAMPLE = "\n++++\n".join(f"Savol {i}?\n====\n#Ha {i}\n====\nYo'q {i}" for i in range(5))


async def _recv(ws, t, timeout=5.0):
    async def inner():
        while True:
            msg = await ws.receive()
            if msg.type != aiohttp.WSMsgType.TEXT:
                return None
            data = json.loads(msg.data)
            if data["t"] == t:
                return data["d"]
    return await asyncio.wait_for(inner(), timeout)


def test_simultaneous_joins_over_websocket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COUNTDOWN", 0.2)
    monkeypatch.setattr(config, "RANKING_REFRESH", 0.0)

    async def body():
        server = TestServer(create_app(db_path=tmp_path / "w.db"))
        await server.start_server()
        clients = [TestClient(server) for _ in range(4)]
        try:
            for i, c in enumerate(clients):
                await c.start_server()
                assert (await c.post("/api/auth/register", json={"login": f"user{i}", "password": "1234"})).status == 200
            r = await clients[0].post("/api/admin/topics", json={"name": "Tarix", "content": SAMPLE})
            tid = (await r.json())["topic"]["id"]
            host, b, c, watcher = [await cl.ws_connect("/ws") for cl in clients]
            for ws in (host, b, c, watcher):
                await _recv(ws, "hello")
            await watcher.send_json({"t": "lobby:sub", "d": {"watch": [tid]}})
            await _recv(watcher, "lobby")
            await host.send_json({"t": "seek:create", "d": {"topicId": tid}})
            sid = (await _recv(host, "queue"))["seekId"]
            diff = await _recv(watcher, "lobby:diff")  # yangi seek jonli ko'rindi
            assert diff["add"][0]["id"] == sid and diff["add"][0]["login"] == "user0"
            await asyncio.gather(b.send_json({"t": "seek:join", "d": {"seekId": sid}}),
                                 c.send_json({"t": "seek:join", "d": {"seekId": sid}}))

            async def outcome(ws):
                while True:
                    msg = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
                    if msg["t"] in ("duel:start", "error"):
                        return msg

            results = [await outcome(b), await outcome(c)]
            kinds = sorted(m["t"] for m in results)
            assert kinds == ["duel:start", "error"]
            assert next(m for m in results if m["t"] == "error")["d"]["code"] == "taken"
            assert (await _recv(host, "duel:start"))["opp"]["login"] in ("user1", "user2")
            gone = await _recv(watcher, "lobby:diff")
            assert gone["del"] == [sid] and gone["counts"] == {str(tid): [0, 1]}
            await asyncio.sleep(0.4)  # sanoq tugadi — faollik yozildi
            browse = await (await clients[3].get("/api/topics/browse?period=today")).json()
            assert browse["items"][0]["id"] == tid and browse["items"][0]["today"] == 1 and browse["items"][0]["playing"] == 1
        finally:
            for cl in clients:
                await cl.close()
            await server.close()

    asyncio.run(body())
