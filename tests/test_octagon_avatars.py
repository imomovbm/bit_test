"""Octagon avatarlari: qat'iy ro'yxat (server), simda faqat indeks, tekshiruv, lobbida almashtirish, qayta ulanishda
saqlanishi va hamma ekranlarga (o'qituvchi holati, reyting, podium, o'quvchi xabarlari) yetib borishi."""
import json
import re
import unicodedata
from pathlib import Path

import pytest

from app import config, octagon
from app.octagon import AVATARS, OctagonError, clean_avatar
from test_octagon import PV, FakeConn, act, answer, finish_reveal, join, make_game, ph, to_question
from test_octagon import octagon_env

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


def test_allowlist_is_simple_single_codepoint_emoji():
    assert 30 <= len(AVATARS) <= 48 and len(set(AVATARS)) == len(AVATARS)
    for a in AVATARS:
        assert len(a) == 1, a                               # bitta kod nuqtasi: ZWJ ketma-ketligi, VS16, teri rangi yo'q
        cp = ord(a)
        assert not 0x1F1E6 <= cp <= 0x1F1FF, a              # bayroq harflari emas
        assert not 0x1F3FB <= cp <= 0x1F3FF, a              # teri rangi modifikatorlari emas
        assert unicodedata.category(a) == "So", a
        # Unicode 6.0 (2010) va undan oldingilar: eski telefonlarda ham bir xil ko'rinadi
        assert cp <= 0x1F6FF or cp in (0x26BD, 0x2B50), a


def test_client_list_matches_server_list_in_order():
    js = (ROOT / "static/js/octagon/common.js").read_text(encoding="utf-8")
    block = re.search(r"export const AVATARS = \[(.*?)\];", js, re.S).group(1)
    assert re.findall(r"'([^']+)'", block) == list(AVATARS)


@pytest.mark.parametrize("bad", [-1, len(AVATARS), 10**9, 1.0, "1", "🐶", True, False, None, [0], {"i": 0}])
def test_invalid_avatar_values_are_rejected(bad):
    with pytest.raises(OctagonError) as e:
        clean_avatar(bad)
    assert e.value.code == "avatar"


def test_join_requires_a_valid_avatar_index_and_never_trusts_strings(env):
    game = make_game(env)
    for bad in (None, "🐶", "<img src=x onerror=alert(1)>", len(AVATARS), -1, 2.0, True):
        c = FakeConn()
        data = {"v": PV, "pin": game.pin, "nick": "Ali"}
        if bad is not None:
            data["av"] = bad
        env.hub.handle(c, "join", data)
        assert c.errors()[-1]["c"] == "avatar", bad
    assert not game.players
    ok = join(env, game, "Ali", av=len(AVATARS) - 1)
    assert ok.last("w")["av"] == len(AVATARS) - 1 and isinstance(ok.last("w")["av"], int)


def test_avatar_changes_only_in_lobby_and_persists_across_reconnect(env):
    game = make_game(env, questionCount=2, timeLimit=5)
    a = join(env, game, "Ali", av=2)
    b = join(env, game, "Vali", av=2)  # bir xil avatar ikki o'yinchida — ruxsat etilgan
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    env.hub.handle(a, "av", {"i": 9})
    assert a.last("w")["av"] == 9 and "tok" not in a.last("w")
    env.clock.advance(1)
    assert [(p["nick"], p["av"]) for p in host.last("h")["players"]] == [("Ali", 9), ("Vali", 2)]
    for bad in ("🐱", 99, None):
        env.hub.handle(a, "av", {"i": bad})
        assert a.errors()[-1]["c"] == "avatar"
    act(env, game, "start")
    env.hub.handle(a, "av", {"i": 4})
    assert a.errors()[-1]["c"] == "started" and next(p for p in game.players.values() if p.nick == "Ali").avatar == 9
    w = next(d for t, d in a.msgs if t == "w" and "tok" in d)  # token faqat qo'shilishdagi birinchi "w" da
    env.hub.disconnect(a)
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert a2.last("w")["av"] == 9
    to_question(env, game)
    answer(env, a2, 0, 0)
    answer(env, b, 0, 1)
    act(env, game, "next")
    board = host.last("h")["leaderboard"]
    assert [(r["nick"], r["av"]) for r in board] == [("Ali", 9), ("Vali", 2)]
    act(env, game, "next")
    to_question(env, game)
    act(env, game, "skip")
    act(env, game, "next")   # oxirgi savol -> yakuniy ochilish: avatar podiumda ham
    env.clock.advance(config.OCTAGON_PODIUM_INTRO)
    assert [(r["place"], r["nick"], r["av"]) for r in host.last("h")["podium"]] == [(2, "Vali", 2)]
    finish_reveal(env, game)
    h = host.last("h")
    assert h["phase"] == "final_results" and [(r["nick"], r["av"]) for r in h["ranking"]] == [("Ali", 9), ("Vali", 2)]
    assert [(r["place"], r["av"]) for r in h["podium"]] == [(1, 9), (2, 2)]
    s = b.last("s")
    assert ph(s) == "final_results" and s["top"] == [[1, "Ali", 1000, 9], [2, "Vali", 0, 2]]


def test_avatar_message_needs_a_joined_player(env):
    make_game(env)
    c = FakeConn()
    env.hub.handle(c, "av", {"i": 1})
    assert c.errors()[-1]["c"] == "bad"


def test_only_indexes_go_over_the_wire_to_students(env):
    game = make_game(env, questionCount=1, timeLimit=5)
    a = join(env, game, "Ali", av=5)
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 0)
    act(env, game, "next")
    act(env, game, "next")
    blob = json.dumps(a.msgs, ensure_ascii=False)
    assert not any(emoji in blob for emoji in AVATARS)  # emoji matni simda yo'q — faqat indeks
    assert octagon.AVATARS[5] not in json.dumps(env.hub.host_state(game), ensure_ascii=False)
