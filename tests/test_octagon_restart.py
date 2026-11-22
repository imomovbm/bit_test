"""Server qayta ishga tushganda Octagon o'yinlari saqlanadi va tiklanadi (app/octagon.py: snapshot/restore/shutdown,
app/ops.py: fayl). Server to'xtab turgan vaqt o'yinga pauza: savol vaqti yeyilmaydi."""
import json
import os
import time

import pytest

from app import config, octagon, ops
from app.octagon import OctagonHub
from test_octagon import PV, FakeClock, FakeConn, act, answer, join, make_game, octagon_env, ph, to_question


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


def restart(env, data, downtime=0.0):
    """Yangi jarayon: yangi soat (boshqa monoton vaqt) va yangi hub; holat JSON orqali o'tadi (diskdagidek)."""
    clock = FakeClock()
    clock.t = 50_000.0
    hub = OctagonHub(env.db, clock)
    hub._epoch0 = env.hub.wall_ms() + downtime * 1000 - clock.t * 1000  # Unix vaqti: to'xtab turgan vaqt o'tdi
    restored = hub.restore(json.loads(json.dumps(data)))
    env.hub, env.clock = hub, clock
    return restored


def resume(env, game_pin, w):
    c = FakeConn()
    env.hub.handle(c, "resume", {"v": PV, "pin": game_pin, "id": w["id"], "tok": w["tok"]})
    return c


@pytest.mark.parametrize("phase", ["lobby", "topic_intro", "question_read", "question_active", "question_result", "leaderboard", "podium"])
def test_every_phase_survives_a_restart(env, phase):
    game = make_game(env, questionCount=2, timeLimit=20)
    a, b = join(env, game, "Ali", av=5), join(env, game, "Vali", av=6)
    wa, wb = a.last("w"), b.last("w")
    if phase != "lobby":
        act(env, game, "start")
    if phase in ("question_read", "question_active", "question_result", "leaderboard"):
        env.clock.advance(config.OCTAGON_INTRO)
    if phase in ("question_active", "question_result", "leaderboard"):
        env.clock.advance(config.OCTAGON_READ)
    if phase in ("question_result", "leaderboard"):
        answer(env, a, 0, 0)
        answer(env, b, 0, 1)
    if phase == "leaderboard":
        act(env, game, "next")
    if phase == "podium":
        act(env, game, "end")
    assert game.phase == phase
    before = {p.id: (p.nick, p.avatar, p.score, dict(p.answers)) for p in game.players.values()}
    data = env.hub.shutdown()
    assert a.closed == (1012, "restart") and b.closed == (1012, "restart")
    assert restart(env, data, downtime=30) == 1
    g2 = env.hub.games[game.pin]
    assert g2.phase == phase and g2.index == game.index
    assert {p.id: (p.nick, p.avatar, p.score, dict(p.answers)) for p in g2.players.values()} == before
    a2 = resume(env, game.pin, wa)
    assert ph(a2.last("s")) == phase and a2.last("w")["nick"] == "Ali" and a2.last("w")["av"] == 5
    b2 = resume(env, game.pin, wb)
    assert b2.last("w")["id"] == wb["id"] and b2.last("s")["sc"] == before[wb["id"]][2] and len(g2.players) == 2
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    assert host.last("h")["phase"] == phase and host.last("h")["qr"]


def test_downtime_is_a_pause_not_lost_answer_time(env):
    game = make_game(env, timeLimit=20)
    a = join(env, game, "Ali")
    wa = a.last("w")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(3)                                  # savolning 3-soniyasida server to'xtadi
    data = env.hub.shutdown()
    restart(env, data, downtime=60)                       # bir daqiqa ishlamadi
    a2 = resume(env, game.pin, wa)
    s = a2.last("s")
    assert ph(s) == "question_active" and s["pe"] - s["ps"] == 20_000
    assert round((s["pe"] - env.hub.wall_ms()) / 1000) == 17   # 17 soniya qoldi — to'xtab turgan vaqt hisoblanmadi
    env.clock.advance(2)
    env.hub.handle(a2, "a", {"q": 0, "o": 0})
    p = env.hub.games[game.pin].players[wa["id"]]
    assert p.answers[0] == (0, 5000)                      # javob vaqti: 3 + 2 soniya (server soati)
    env.clock.advance(14.9)
    assert env.hub.games[game.pin].phase == "question_result"  # hamma javob berdi — savol yopildi


def test_timers_resume_with_the_remaining_time(env):
    game = make_game(env, timeLimit=20)
    join(env, game, "Ali")
    act(env, game, "start")
    env.clock.advance(config.OCTAGON_INTRO - 1)          # kirishning oxirgi soniyasi
    data = env.hub.shutdown()
    restart(env, data, downtime=10)
    g2 = env.hub.games[game.pin]
    env.clock.advance(0.9)
    assert g2.phase == "topic_intro"
    env.clock.advance(0.2)
    assert g2.phase == "question_read"
    env.clock.advance(config.OCTAGON_READ)
    assert g2.phase == "question_active"


def test_shutdown_freezes_the_game(env):
    game = make_game(env, timeLimit=20)
    a = join(env, game, "Ali")
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    act(env, game, "start")
    to_question(env, game)
    env.hub.shutdown()
    assert host.closed == (1012, "restart") and a.closed == (1012, "restart")
    sent = len(a.msgs)
    env.clock.advance(3600)                               # taymerlar to'xtatilgan: hech narsa o'zgarmaydi
    assert game.phase == "question_active" and len(a.msgs) == sent


def test_snapshot_holds_token_hashes_not_tokens(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    tok = a.last("w")["tok"]
    blob = json.dumps(env.hub.snapshot())
    assert tok not in blob and next(iter(game.players.values())).token_hash in blob


def test_bad_or_foreign_snapshots_are_ignored(env):
    game = make_game(env)
    join(env, game, "Ali")
    data = env.hub.snapshot()
    assert restart(env, {**data, "v": 999}) == 0
    assert restart(env, "garbage") == 0
    broken = json.loads(json.dumps(data))
    broken["games"].append({"pin": "abc"})               # buzilgan yozuv — o'tkazib yuboriladi, qolganlari tiklanadi
    broken["games"].append({**broken["games"][0], "pin": "999999", "phase": "nonsense"})
    assert restart(env, broken) == 1 and list(env.hub.games) == [game.pin]


def test_snapshot_file_is_private_single_use_and_expires(tmp_path):
    path = ops.snapshot_path(tmp_path / "baza.db")
    assert path.name == "baza.octagon.json"
    now = int(time.time() * 1000)
    assert ops.save_snapshot(path, {"v": 1, "savedAt": now, "games": []}) == 0 and not path.exists()  # bo'sh — fayl yo'q
    assert ops.save_snapshot(path, {"v": 1, "savedAt": now, "games": [{"pin": "123456"}]}) == 1
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert ops.load_snapshot(path, 600, now + 5_000)["games"] == [{"pin": "123456"}]
    assert not path.exists()                              # ikki marta tiklanmaydi
    ops.save_snapshot(path, {"v": 1, "savedAt": now, "games": [{"pin": "123456"}]})
    assert ops.load_snapshot(path, 600, now + 601_000) is None and not path.exists()   # eskirgan
    ops.save_snapshot(path, {"v": 1, "savedAt": now + 60_000, "games": [{"pin": "123456"}]})
    assert ops.load_snapshot(path, 600, now) is None      # kelajakdagi vaqt — soat buzilgan
    path.write_text("{not json", encoding="utf-8")
    assert ops.load_snapshot(path, 600, now) is None and not path.exists()
    ops.save_snapshot(path, {"v": 1, "savedAt": now, "games": [{"pin": "123456"}]})
    assert ops.load_snapshot(path, 0, now) is None and not path.exists()   # tiklash o'chirilgan


def test_restored_games_count_toward_limits_and_sweep(env, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_TTL", 7200.0)
    game = make_game(env)
    join(env, game, "Ali")
    env.clock.advance(7000)
    data = env.hub.shutdown()
    restart(env, data, downtime=300)                      # 7000 + 300 > 7200 — keyingi tozalashda yopiladi
    assert game.pin in env.hub.games
    env.clock.advance(octagon.SWEEP_EVERY + 1)
    assert game.pin not in env.hub.games
