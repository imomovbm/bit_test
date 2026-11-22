"""Octagon v2: bosqichlar mashinasi (sof qoidalar + dvigatelda), mutlaq vaqtlar, protokol versiyasi, soat sinxronlash,
o'tkazib yuborish, kech qo'shilish va qayta ulanish har bir bosqichda."""
import pytest

from app import config, octagon
from app import octagon_flow as flow
from test_octagon import PV, FakeConn, act, answer, join, left_ms, make_game, ph, to_question
from test_octagon import octagon_env

ALL = flow.PHASES


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


# ============================================================ sof qoidalar
def test_phase_list_order_matches_wire_codes():
    assert ALL == ("lobby", "topic_intro", "question_read", "question_active", "question_result", "leaderboard", "podium")
    assert all(flow.CODE[name] == i for i, name in enumerate(ALL))
    assert set(flow.TRANSITIONS) == set(ALL)


@pytest.mark.parametrize("src", ALL)
@pytest.mark.parametrize("dst", ALL)
def test_every_transition_is_either_allowed_or_rejected(src, dst):
    allowed = {
        ("lobby", "topic_intro"),
        ("topic_intro", "question_read"), ("topic_intro", "podium"),
        ("question_read", "question_active"), ("question_read", "podium"),
        ("question_active", "question_result"),
        ("question_result", "leaderboard"), ("question_result", "podium"),
        ("leaderboard", "question_read"), ("leaderboard", "podium"),
    }
    if (src, dst) in allowed:
        flow.check(src, dst)
    else:
        with pytest.raises(flow.IllegalTransition):
            flow.check(src, dst)


def test_durations_come_from_config_values():
    assert flow.duration(flow.INTRO, 20, 5, 5) == 5
    assert flow.duration(flow.READ, 20, 5, 7) == 7
    assert flow.duration(flow.ACTIVE, 20, 5, 5) == 20
    for phase in (flow.LOBBY, flow.RESULT, flow.BOARD, flow.PODIUM):
        assert flow.duration(phase, 20, 5, 5) is None
    assert flow.TIMED == {flow.INTRO, flow.READ, flow.ACTIVE}


def test_timer_next_and_skip_rules():
    assert [flow.after_timer(p) for p in (flow.INTRO, flow.READ, flow.ACTIVE)] == [flow.READ, flow.ACTIVE, flow.RESULT]
    for p in (flow.LOBBY, flow.RESULT, flow.BOARD, flow.PODIUM):
        with pytest.raises(flow.IllegalTransition):
            flow.after_timer(p)
    assert flow.on_next(flow.ACTIVE, True) == flow.RESULT
    assert flow.on_next(flow.RESULT, True) == flow.BOARD
    assert flow.on_next(flow.BOARD, True) == flow.READ and flow.on_next(flow.BOARD, False) == flow.PODIUM
    for p in (flow.LOBBY, flow.INTRO, flow.READ, flow.PODIUM):  # «Keyingi» bu bosqichlarni sakratib yubormaydi
        assert flow.on_next(p, True) is None
    assert [flow.on_skip(p) for p in ALL] == [None, flow.READ, flow.ACTIVE, flow.RESULT, None, None, None]
    assert [p for p in ALL if flow.can_answer(p)] == [flow.ACTIVE]
    assert [p for p in ALL if not flow.can_join(p)] == [flow.PODIUM]


# ============================================================ dvigatelda
def test_full_flow_uses_configured_timings(env, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 4.0)
    monkeypatch.setattr(config, "OCTAGON_READ", 6.0)
    game = make_game(env, questionCount=2, timeLimit=8)
    a = join(env, game, "Ali", av=7)
    act(env, game, "start")
    s = a.last("s")
    assert ph(s) == "topic_intro" and s["pe"] - s["ps"] == 4000 and s["ps"] == env.hub.wall_ms()
    env.clock.advance(3.999)
    assert game.phase == "topic_intro"
    env.clock.advance(0.002)
    s = a.last("s")
    assert ph(s) == "question_read" and s["q"] == 0 and s["pe"] - s["ps"] == 6000
    env.clock.advance(6.0)
    s = a.last("s")
    assert ph(s) == "question_active" and s["pe"] - s["ps"] == 8000
    env.clock.advance(8.0)
    assert ph(a.last("s")) == "question_result" and "ps" not in a.last("s")
    act(env, game, "next")
    act(env, game, "next")
    assert game.phase == "question_read" and game.index == 1  # mavzu kirishi faqat bir marta — 2-savoldan oldin yo'q


def test_answer_timing_starts_at_active_not_at_reading(env):
    """Javob vaqti question_active boshlanishidan o'lchanadi (o'qish vaqti va mavzu kirishi hisobga kirmaydi)."""
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    env.clock.advance(config.OCTAGON_INTRO + config.OCTAGON_READ)  # 10 s o'tdi, lekin savol hozirgina ochildi
    assert game.phase == "question_active"
    env.clock.advance(0.3)
    answer(env, a, 0, 0)
    assert next(iter(game.players.values())).answers == {0: (0, 300)} and a.last("s")["res"]["pts"] == 1000


def test_skip_intro_and_reading_and_active(env):
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    act(env, game, "skip")
    assert game.phase == "question_read" and game.index == 0
    act(env, game, "skip")
    assert game.phase == "question_active" and ph(a.last("s")) == "question_active"
    env.clock.advance(1.5)
    act(env, game, "skip")  # savolni muddatidan oldin yopish
    assert game.phase == "question_result" and a.last("s")["res"]["ok"] is None
    for _ in range(3):
        act(env, game, "skip")  # natija/reytingda «o'tkazib yuborish» hech narsa qilmaydi
    assert game.phase == "question_result"
    env.clock.advance(60)  # bekor qilingan taymerlar hech narsa qilmaydi
    assert game.phase == "question_result"


def test_double_skip_or_next_from_two_windows_never_double_advances(env):
    game = make_game(env)
    join(env, game, "Ali")
    act(env, game, "start")
    act(env, game, "skip", phase="topic_intro", q=-1)
    act(env, game, "skip", phase="topic_intro", q=-1)  # ikkinchi oynadan bir xil bosish — e'tiborsiz
    assert game.phase == "question_read" and game.index == 0
    for _ in range(3):
        act(env, game, "next")  # o'qish paytida «Keyingi» — hech narsa
    assert game.phase == "question_read"
    act(env, game, "skip", phase="question_read", q=0)
    act(env, game, "skip", phase="question_read", q=0)
    assert game.phase == "question_active" and game.index == 0


def test_end_during_intro_or_reading_plays_no_unopened_question(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    act(env, game, "start")
    act(env, game, "end")
    assert game.phase == "podium" and game.stats == [] and ph(a.last("s")) == "podium" and a.last("s")["top"] == [["Ali", 0, 0]]
    env.clock.advance(60)  # eski kirish taymeri ishlamaydi
    assert game.phase == "podium"
    game2 = make_game(env)
    join(env, game2, "Vali")
    act(env, game2, "start")
    env.clock.advance(config.OCTAGON_INTRO)
    act(env, game2, "end")
    assert game2.phase == "podium" and game2.stats == [] and env.hub.host_state(game2)["played"] == 0


def test_illegal_transition_is_a_bug_not_silently_accepted(env):
    game = make_game(env)
    join(env, game, "Ali")
    with pytest.raises(flow.IllegalTransition):
        env.hub._set_phase(game, flow.ACTIVE)  # lobbidan to'g'ri savolga — mumkin emas
    assert game.phase == "lobby"


@pytest.mark.parametrize("phase", ["topic_intro", "question_read", "question_active"])
def test_late_join_and_reconnect_in_each_timed_phase_land_in_the_right_place(env, phase):
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali", av=3)
    act(env, game, "start")
    if phase != "topic_intro":
        env.clock.advance(config.OCTAGON_INTRO)
    if phase == "question_active":
        env.clock.advance(config.OCTAGON_READ)
    env.clock.advance(1.25)
    assert game.phase == phase
    late = join(env, game, "Kechikkan", ip="10.0.0.9", av=11)
    s = late.last("s")
    assert ph(s) == phase and left_ms(env, s) == game_duration(phase) - 1250
    w = a.last("w")
    env.hub.disconnect(a)
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert ph(a2.last("s")) == phase and left_ms(env, a2.last("s")) == game_duration(phase) - 1250
    assert a2.last("w")["av"] == 3 and a2.last("w")["id"] == w["id"] and len(game.players) == 2
    to = None if phase == "question_active" else game  # o'qish paytida kirganlar savol ochilganda javob bera oladi
    if to is not None:
        to_question(env, game)
    answer(env, late, 0, 0)
    answer(env, a2, 0, 0)
    res = late.last("s")["res"]
    assert res["ok"] is True and a2.last("s")["res"]["ok"] is True
    assert {p.nick: p.avatar for p in game.players.values()} == {"Ali": 3, "Kechikkan": 11}


def game_duration(phase):
    return {"topic_intro": int(config.OCTAGON_INTRO * 1000), "question_read": int(config.OCTAGON_READ * 1000), "question_active": 10_000}[phase]


# ===================================================== protokol va soat
@pytest.mark.parametrize("msg", ["check", "join", "resume", "host"])
@pytest.mark.parametrize("version", [None, 1, 3, "2"])
def test_old_or_unknown_protocol_version_gets_reload_not_silent_breakage(env, msg, version):
    game = make_game(env)
    c = FakeConn()
    data = {"pin": game.pin, "nick": "Ali", "av": 0, "id": "x", "tok": "y" * 20}
    if version is not None:
        data["v"] = version
    env.hub.handle(c, msg, data, env.owner)
    assert c.msgs == [("reload", {"v": PV})] and not game.players and not game.hosts


def test_unknown_message_types_are_ignored_safely(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    for t in ("hack", "", None, 42, "__proto__", "constructor"):
        env.hub.handle(a, t, {"x": 1})
    assert all(e["c"] == "bad" for e in a.errors()) and game.phase == "lobby" and len(game.players) == 1


def test_clock_sync_returns_server_time_and_echo(env):
    c = FakeConn()
    env.hub.handle(c, "sync", {"c": 1234.5})
    assert c.last("sync") == {"c": 1234.5, "s": env.hub.wall_ms()}
    for bad in ("x", True, None, [1]):
        env.hub.handle(c, "sync", {"c": bad})
        assert c.last("sync")["c"] is None
    env.clock.advance(2.5)
    env.hub.handle(c, "sync", {})
    assert c.last("sync")["s"] == env.hub.wall_ms() and env.hub.wall_ms() - c.msgs[0][1]["s"] == 2500


def test_host_state_carries_absolute_phase_times_and_version(env):
    game = make_game(env, timeLimit=12)
    join(env, game, "Ali")
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    assert host.last("h")["v"] == PV and "phaseEnd" not in host.last("h")
    act(env, game, "start")
    h = host.last("h")
    assert h["phase"] == "topic_intro" and h["topicName"] == "Mavzu" and h["phaseEnd"] - h["phaseStart"] == int(config.OCTAGON_INTRO * 1000)
    assert "question" not in h  # mavzu kirishida savol hali ko'rsatilmaydi
    env.clock.advance(config.OCTAGON_INTRO)
    h = host.last("h")
    assert h["phase"] == "question_read" and h["question"]["text"] == "Savol matni 0?" and h["phaseEnd"] - h["phaseStart"] == int(config.OCTAGON_READ * 1000)
    env.clock.advance(config.OCTAGON_READ)
    h = host.last("h")
    assert h["phase"] == "question_active" and h["phaseEnd"] - h["phaseStart"] == 12_000 and h["answered"] == 0


def test_answer_exactly_at_timer_end_is_accepted_one_ms_later_rejected(env):
    game = make_game(env, timeLimit=10)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    to_question(env, game)
    env.clock.t += 10.0  # aynan chegarada (taymer hali ishlamagan)
    answer(env, a, 0, 0)
    env.clock.t += 0.001
    answer(env, b, 0, 0)
    assert next(p for p in game.players.values() if p.nick == "Ali").answers == {0: (0, 10_000)}
    assert b.errors()[-1]["c"] == "late" and not next(p for p in game.players.values() if p.nick == "Vali").answers
    env.clock.advance(0)
    assert octagon.calculate_score(True, 10_000, 10_000) == 500


def test_app_can_be_created_outside_a_running_event_loop(tmp_path):
    """Ishlab chiqarishda ilova hodisalar tsikli ishga tushishidan oldin yig'iladi (web.run_app) — hub loop soatini
    konstruktorda o'qimasligi kerak (v2 dagi xato: server umuman ishga tushmagan)."""
    from app.server import create_app
    app = create_app(db_path=tmp_path / "boot.db")
    assert app is not None
