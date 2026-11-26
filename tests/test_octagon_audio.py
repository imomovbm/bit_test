"""Octagon ovozi — server qismi: natija ovozi uchun foizlar (haqiqiy javoblardan, serverda) va sozlamalar.

Ovozning o'zi faqat o'qituvchi ekranida (static/js/octagon/audio.js; tanlash qoidalari — tests/js/octagon-audio.test.js).
Bu yerda: foizlar va chegaralar aniq, o'quvchilarga yangi hech narsa bormaydi, eski saqlangan o'yinlar ham ishlaydi.
"""
import importlib

import pytest

from app import config, octagon
from app import octagon_flow as flow
from app.octagon_scoring import answer_shares
from test_octagon import PV, FakeConn, act, answer, join, make_game, octagon_env, to_question


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


@pytest.fixture
def reload_config(monkeypatch):
    def load(**env):
        for k in [k for k in list(__import__("os").environ) if k.startswith("TD_") or k == "PORT"]:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(config)
    yield load
    monkeypatch.undo()
    importlib.reload(config)


# ============================================================ foizlar (sof)
@pytest.mark.parametrize("answered, correct, pct", [
    (100, 29, 29), (100, 30, 30), (100, 59, 59), (100, 60, 60),   # chegaralar atrofida
    (10, 6, 60), (5, 3, 60), (3, 2, 66), (7, 2, 28), (3, 1, 33),
    (1000, 599, 59),            # 59,9 % — 60 ga yaxlitlanmaydi: «≥ 60 %» chegarasi aniq qoladi
    (1000, 299, 29),            # 29,9 % — «hmm» emas
    (1, 1, 100), (1, 0, 0),     # bitta o'yinchi
    (4, 0, 0), (4, 4, 100),
])
def test_correct_share_is_floored_so_integer_thresholds_are_exact(answered, correct, pct):
    assert answer_shares(answered, correct, answered)[0] == pct


def test_nobody_answered_has_no_correct_share():
    assert answer_shares(0, 0, 5) == (None, 0)
    assert answer_shares(0, 0, 0) == (None, 0)


@pytest.mark.parametrize("answered, players, rate", [(3, 4, 75), (0, 4, 0), (4, 4, 100), (1, 3, 33), (2, 3, 66), (0, 0, 0)])
def test_answer_rate_is_share_of_players(answered, players, rate):
    assert answer_shares(answered, 0, players)[1] == rate


def test_shares_never_leave_0_100_even_with_odd_input():
    assert answer_shares(2, 5, 1) == (100, 100)
    assert answer_shares(-1, -1, -1) == (None, 0)


# ============================================================ sozlamalar
def test_sound_defaults_and_mapping_live_in_config():
    assert (config.OCTAGON_SOUND_CHEER, config.OCTAGON_SOUND_HMM, config.OCTAGON_SOUND_NOBODY) == (60, 30, "soft")
    bands = config.OCTAGON_RESULT_SOUNDS
    assert [name for _, name in bands] == ["cheer", "hmm", "oops"]
    assert [pct for pct, _ in bands] == sorted((pct for pct, _ in bands), reverse=True) and bands[-1][0] == 0  # 0–100 to'liq
    assert octagon.sound_rules() == {"bands": [[60, "cheer"], [30, "hmm"], [0, "oops"]], "nobody": "soft"}


def test_sound_thresholds_come_from_environment(reload_config):
    c = reload_config(TD_OCTAGON_SOUND_CHEER="75", TD_OCTAGON_SOUND_HMM="40", TD_OCTAGON_SOUND_NOBODY="silent")
    assert c.validate() == []
    assert c.OCTAGON_RESULT_SOUNDS == ((75, "cheer"), (40, "hmm"), (0, "oops"))
    assert octagon.sound_rules() == {"bands": [[75, "cheer"], [40, "hmm"], [0, "oops"]], "nobody": "silent"}


@pytest.mark.parametrize("env, needle", [
    ({"TD_OCTAGON_SOUND_CHEER": "101"}, "TD_OCTAGON_SOUND_CHEER='101': 0 … 100"),
    ({"TD_OCTAGON_SOUND_HMM": "-5"}, "TD_OCTAGON_SOUND_HMM='-5': 0 … 100"),
    ({"TD_OCTAGON_SOUND_HMM": "12.5"}, "butun son"),
    ({"TD_OCTAGON_SOUND_NOBODY": "loud"}, "soft | silent"),
    ({"TD_OCTAGON_SOUND_CHEER": "40", "TD_OCTAGON_SOUND_HMM": "50"}, "TD_OCTAGON_SOUND_HMM ≤ TD_OCTAGON_SOUND_CHEER"),
])
def test_bad_sound_settings_are_reported(reload_config, env, needle):
    c = reload_config(**env)
    assert any(needle in p for p in c.validate()), c.validate()
    with pytest.raises(c.ConfigError):
        c.check()


# ============================================================ dvigatel
def host_of(env, game):
    h = FakeConn()
    env.hub.handle(h, "host", {"v": PV, "pin": game.pin}, env.owner)
    return h


def test_result_shares_are_computed_on_the_server_from_real_answers(env):
    game = make_game(env, questionCount=3)
    a, b, c, d, e = (join(env, game, n) for n in ("Ali", "Vali", "Olim", "Bek", "Dana"))
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    ok = game.questions[0]["correct"]
    for conn in (a, b, c):
        answer(env, conn, 0, ok)
    answer(env, d, 0, (ok + 1) % 4)
    answer(env, d, 0, ok)              # ikkinchi javob hisobga olinmaydi (birinchisi qoladi)
    act(env, game, "skip")             # Dana javob bermadi
    st = host.last("h")
    assert st["phase"] == "question_result"
    assert (st["answered"], st["correctCount"], st["correctPct"], st["answerRate"]) == (4, 3, 75, 80)
    # o'quvchilarga yangi hech narsa: foizlar va ovoz jadvali faqat o'qituvchida
    for conn in (a, b, c, d, e):
        s = conn.last("s")
        assert not {"correctPct", "answerRate", "sounds"} & set(s)


def test_everyone_answering_closes_the_question_with_full_shares(env):
    game = make_game(env, questionCount=3)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    ok = game.questions[0]["correct"]
    answer(env, a, 0, ok)
    answer(env, b, 0, (ok + 2) % 4)    # oxirgi javob — savol o'zi yopiladi
    assert game.phase == flow.RESULT
    st = host.last("h")
    assert (st["correctPct"], st["answerRate"]) == (50, 100)


def test_nobody_answered_round(env):
    game = make_game(env, questionCount=3)
    join(env, game, "Ali"), join(env, game, "Vali")
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(20)              # vaqt tugadi
    st = host.last("h")
    assert st["phase"] == "question_result" and st["correctPct"] is None and st["answerRate"] == 0


def test_one_player_right_and_wrong(env):
    game = make_game(env, questionCount=3)
    a = join(env, game, "Yolgiz")
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, game.questions[0]["correct"])
    assert (host.last("h")["correctPct"], host.last("h")["answerRate"]) == (100, 100)
    act(env, game, "next")
    act(env, game, "next")
    to_question(env, game)
    answer(env, a, 1, (game.questions[1]["correct"] + 1) % 4)
    assert (host.last("h")["correctPct"], host.last("h")["answerRate"]) == (0, 100)


def test_kicked_or_late_players_are_counted_as_they_were_at_close(env):
    game = make_game(env, questionCount=3)
    a, b, c = join(env, game, "Ali"), join(env, game, "Vali"), join(env, game, "Olim")
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    ok = game.questions[0]["correct"]
    answer(env, a, 0, ok)
    answer(env, c, 0, (ok + 1) % 4)
    act(env, game, "kick", id=c.last("w")["id"])  # javob bergan, lekin yopilishdan oldin chiqarilgan — hisobga olinmaydi
    join(env, game, "Kech", ip="10.0.0.7")         # savol paytida qo'shilgan — o'yinchi, javob bermagan
    act(env, game, "skip")
    st = host.last("h")
    assert (st["answered"], st["correctCount"], st["correctPct"], st["answerRate"]) == (1, 1, 100, 33)
    assert b.last("s")["p"] == flow.CODE[flow.RESULT]


def test_sound_rules_go_to_the_teacher_once_not_with_every_update(env):
    game = make_game(env, questionCount=3)
    host = host_of(env, game)
    first = host.last("h")
    assert first["sounds"] == octagon.sound_rules()
    join(env, game, "Ali")
    env.clock.advance(1)
    updates = [d for t, d in host.msgs[1:] if t == "h"]
    assert updates and all("sounds" not in d for d in updates)


def test_old_snapshot_stats_without_player_count_still_work(env):
    game = make_game(env, questionCount=3)
    a = join(env, game, "Ali")
    join(env, game, "Vali")                     # javob bermaydi
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, game.questions[0]["correct"])
    act(env, game, "skip")
    data = env.hub.snapshot()
    for g in data["games"]:
        for st in g["stats"]:
            st.pop("players")          # snapshot v2, ovozdan oldingi versiya: "players" yo'q
    hub2 = octagon.OctagonHub(env.db, env.clock)
    assert hub2.restore(data) == 1
    st = hub2.host_state(hub2.games[game.pin])
    assert (st["correctPct"], st["answerRate"]) == (100, 50)
