"""Octagon v2 auditi (docs/octagon-v2-audit.md): har bir topilma uchun avval yiqiladigan test yozildi, so'ng tuzatildi.
Testlar topilma raqami bilan (V2-F1 …) — jadvaldagi bilan bir xil."""
import logging

import pytest

from app import config, octagon, security
from test_octagon import PV, FakeConn, act, answer, join, make_game, octagon_env, ph, to_question


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


# ------------------------------------------------------------------- V2-F1
def test_f1_full_class_behind_one_school_nat_can_join(env):
    """Bitta maktab tarmog'i (NAT) ortidagi 300 o'quvchi bitta o'yinga qo'shila olishi kerak (MAX_PLAYERS)."""
    game = make_game(env)
    for i in range(octagon.MAX_PLAYERS):
        c = FakeConn(ip="10.77.0.1")
        env.hub.handle(c, "join", {"v": PV, "pin": game.pin, "nick": f"Oquvchi {i}", "av": i % len(octagon.AVATARS)})
        assert not c.errors(), (i, c.errors())
    assert len(game.players) == octagon.MAX_PLAYERS


# ------------------------------------------------------------------- V2-F2
def test_f2_pin_typos_in_a_big_class_do_not_lock_out_the_whole_school(env):
    """Sinfdagi o'quvchilar PIN ni xato yozishi tabiiy: 5 daqiqada 40 ta xato butun maktab IP sini bloklamasin.
    PIN taxmin qilish hujumiga qarshi himoya (umumiy portlash va IP chegarasi) saqlanadi."""
    game = make_game(env)
    wrong = "123456" if game.pin != "123456" else "654321"
    for _ in range(40):
        env.hub.handle(FakeConn(ip="10.78.0.1"), "check", {"v": PV, "pin": wrong})
    c = FakeConn(ip="10.78.0.1")
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.last("c") == {"pin": game.pin}
    for _ in range(octagon.FAIL_LIMIT):  # chegara baribir bor
        env.hub.handle(c, "check", {"v": PV, "pin": wrong})
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.errors()[-1]["c"] == "rate"


# ------------------------------------------------------------------- V2-F3
def test_f3_rate_limiter_forgets_stale_keys(monkeypatch):
    """Ko'p turli IP dan so'rovlar: eskirgan yozuvlar o'chirilishi kerak (xotira o'smaydi, har chaqiruv hammasini aylanmaydi)."""
    t = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: t[0])
    rl = security.RateLimiter(limit=5, window=60)
    for i in range(25_000):
        rl.hit(f"10.{i // 65536}.{i // 256 % 256}.{i % 256}")
    t[0] += 61  # hammasi eskirdi
    rl.hit("192.168.0.1")
    rl.hit("192.168.0.2")
    assert len(rl._hits) <= 2
    assert rl.count("192.168.0.1") == 1


# ------------------------------------------------------------------- V2-F4
def test_f4_logs_contain_no_student_nicknames_or_teacher_login(env, caplog):
    caplog.set_level(logging.DEBUG, logger="testduel.octagon")
    game = make_game(env, questionCount=1, timeLimit=5)
    a = join(env, game, "Zulfiya Karimova")
    join(env, game, "Sardorbek")
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 0)
    env.clock.advance(5)
    act(env, game, "next")
    act(env, game, "next")
    act(env, game, "close")
    text = caplog.text
    assert game.pin in text  # o'yin hodisalari jurnalda bor
    for secret in ("Zulfiya", "Karimova", "Sardorbek", env.owner["login"]):
        assert secret not in text, secret


# ------------------------------------------------------------------- V2-F5
@pytest.mark.parametrize("msg", ["check", "join"])
def test_f5_v1_student_page_gets_a_visible_reload_message(env, msg):
    """Joylashtirish paytida ochiq qolgan eski (v1) sahifa "reload" xabarini tushunmaydi: unga v1 ham ko'rsatadigan
    xato (PIN maydoni ostida) yuboriladi."""
    game = make_game(env)
    c = FakeConn()
    env.hub.handle(c, msg, {"pin": game.pin, "nick": "Ali"})  # v1: versiya maydoni yo'q
    err = next(d for t, d in c.msgs if t == "e")
    assert err["c"] == "pin" and "yangilang" in err["m"] and not game.players


def test_f5_v1_teacher_page_gets_a_visible_reload_message(env):
    game = make_game(env)
    c = FakeConn()
    env.hub.handle(c, "host", {"pin": game.pin}, env.owner)
    err = next(d for t, d in c.msgs if t == "e")
    assert "yangilang" in err["m"] and err["status"] not in (403, 404) and not game.hosts


# ------------------------------------------------------------------- V2-F7
def test_f7_kicking_the_last_unanswered_player_closes_the_question(env):
    game = make_game(env, timeLimit=60)
    a, b = join(env, game, "Ali"), join(env, game, "Bezori")
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 0)
    assert game.phase == "question_active"
    act(env, game, "kick", id=b.last("w")["id"])
    assert game.phase == "question_result" and ph(a.last("s")) == "question_result"


# ---------------------------------------------------- qo'shimcha tekshiruvlar
def test_two_games_at_once_do_not_interfere(env):
    g1, g2 = make_game(env, timeLimit=10), make_game(env, timeLimit=20)
    a1, a2 = join(env, g1, "Ali"), join(env, g2, "Ali")  # bir xil ism — boshqa o'yinda mumkin
    act(env, g1, "start")
    to_question(env, g1)
    act(env, g2, "start")  # birinchisida savol ochiq, ikkinchisida endi mavzu kirishi
    assert g1.phase == "question_active" and g2.phase == "topic_intro"
    answer(env, a1, 0, 0)
    env.hub.handle(a1, "a", {"q": 0, "o": 0})  # o'z o'yiniga qayta — e'tiborsiz
    assert g1.phase == "question_result" and g2.phase == "topic_intro"
    act(env, g1, "close")
    env.clock.advance(config.OCTAGON_INTRO + config.OCTAGON_READ)
    assert g2.phase == "question_active" and ph(a2.last("s")) == "question_active"  # g1 yopilishi g2 taymerlariga tegmadi
    answer(env, a2, 0, 0)
    assert a2.last("s")["res"]["ok"] is True and g1.pin not in env.hub.games


@pytest.mark.parametrize("phase", ["lobby", "topic_intro", "question_read", "question_active", "question_result", "leaderboard", "podium"])
def test_teacher_and_student_reconnect_in_every_phase(env, phase):
    game = make_game(env, questionCount=2, timeLimit=10)
    a = join(env, game, "Ali", av=4)
    w = a.last("w")
    steps = {
        "topic_intro": [("start",)],
        "question_read": [("start",), ("adv", config.OCTAGON_INTRO)],
        "question_active": [("start",), ("adv", config.OCTAGON_INTRO + config.OCTAGON_READ)],
        "question_result": [("start",), ("adv", config.OCTAGON_INTRO + config.OCTAGON_READ), ("ans",)],
        "leaderboard": [("start",), ("adv", config.OCTAGON_INTRO + config.OCTAGON_READ), ("ans",), ("next",)],
        "podium": [("start",), ("end",)],
    }.get(phase, [])
    for step in steps:
        if step[0] == "adv":
            env.clock.advance(step[1])
        elif step[0] == "ans":
            answer(env, a, 0, 0)
        else:
            act(env, game, step[0])
    assert game.phase == phase
    score = next(iter(game.players.values())).score
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    h = host.last("h")
    assert h["phase"] == phase and ("phaseEnd" in h) == (phase in ("topic_intro", "question_read", "question_active"))
    env.hub.disconnect(a)
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert ph(a2.last("s")) == phase and a2.last("s")["sc"] == score and a2.last("w")["av"] == 4 and len(game.players) == 1


@pytest.mark.parametrize("phase", ["lobby", "topic_intro", "question_read", "question_active", "question_result", "leaderboard", "podium"])
def test_closing_in_any_phase_leaves_no_timers_and_nothing_fires_later(env, phase):
    """O'qituvchi o'yinni istalgan bosqichda yopsa: o'yin, ulanishlar va taymerlar qolmaydi; keyin vaqt o'tsa
    hech narsa ishga tushmaydi (yopilgan o'yinga xabar yoki xato yo'q)."""
    baseline = sum(1 for *_, h in env.clock.heap if not h.cancelled)
    game = make_game(env, questionCount=2, timeLimit=10)
    a = join(env, game, "Ali")
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    if phase != "lobby":
        act(env, game, "start")
    if phase in ("question_read", "question_active", "question_result", "leaderboard"):
        env.clock.advance(config.OCTAGON_INTRO)
    if phase in ("question_active", "question_result", "leaderboard"):
        env.clock.advance(config.OCTAGON_READ)
    if phase in ("question_result", "leaderboard"):
        answer(env, a, 0, 0)
    if phase == "leaderboard":
        act(env, game, "next")
    if phase == "podium":
        act(env, game, "end")
    assert game.phase == phase
    act(env, game, "close")
    assert game.pin not in env.hub.games and a.closed == (4003, "ended")
    live = sum(1 for *_, h in env.clock.heap if not h.cancelled)
    assert live <= max(baseline, 1)  # faqat umumiy tozalash taymeri qolishi mumkin
    sent_a, sent_h = len(a.msgs), len(host.msgs)
    env.clock.advance(3600)
    assert len(a.msgs) == sent_a and len(host.msgs) == sent_h


def test_answers_for_previous_or_future_questions_never_count(env):
    """Oldingi savolga (keyingisining o'qish yoki javob vaqtida) yoki hali kelmagan savolga javob — rad etiladi,
    ball va javoblar o'zgarmaydi."""
    game = make_game(env, questionCount=3, timeLimit=10)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    to_question(env, game)
    env.hub.handle(a, "a", {"q": 1, "o": 0})               # kelajakdagi savol
    assert a.errors()[-1]["c"] == "late"
    answer(env, a, 0, 0)                                     # Vali javob bermaydi — savol ochiq qoladi
    act(env, game, "next")                                   # savol → natija
    act(env, game, "next")                                   # natija → reyting
    act(env, game, "next")                                   # reyting → 2-savolni o'qish
    assert game.phase == "question_read" and game.index == 1
    for q in (0, 2):
        env.hub.handle(b, "a", {"q": q, "o": 0})
        assert b.errors()[-1]["c"] == "late", q
    env.clock.advance(config.OCTAGON_READ)
    assert game.phase == "question_active"
    env.hub.handle(b, "a", {"q": 0, "o": 0})                 # 1-savolga kechikkan javob
    assert b.errors()[-1]["c"] == "late"
    pb = next(p for p in game.players.values() if p.nick == "Vali")
    assert pb.answers == {} and pb.score == 0


def test_octagon_ui_code_has_no_html_injection_sinks():
    """Ism, mavzu nomi va savol matni faqat matn tugunlari orqali chiziladi (innerHTML va shu kabilar yo'q)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "static/js"
    files = [root / "play.js", root / "views/octagon.js", root / "views/games.js", *sorted((root / "octagon").glob("*.js"))]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert sink not in src, (f.name, sink)
