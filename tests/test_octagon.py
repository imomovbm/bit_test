"""Octagon (jonli viktorina): ball hisoblash, ismlar va o'yin dvigateli (soxta soat bilan — haqiqiy kutishsiz)."""
import heapq
import json

import pytest

from app import config, octagon, security
from app import octagon_flow as flow
from app.db import Database
from app.octagon import OctagonError, OctagonHub, calculate_score, clean_nickname, nickname_key

PV = octagon.PROTOCOL_VERSION


def ph(state):
    """O'quvchi holatidagi bosqich kodi -> nomi (simda indeks yuboriladi)."""
    return flow.PHASES[state["p"]]


# ============================================================ ball hisoblash
@pytest.mark.parametrize("ms", [0, 1, 250, 499])
def test_score_under_half_second_is_full(ms):
    assert calculate_score(True, ms, 20_000) == 1000
    assert calculate_score(True, ms, 10_000) == 1000
    assert calculate_score(True, ms, 60_000) == 1000


def test_score_exactly_half_second_is_full():
    for timer in (5_000, 10_000, 20_000, 30_000, 60_000, 120_000):
        assert calculate_score(True, 500, timer) == 1000


def test_score_half_timer_750_and_full_timer_500():
    for timer in (10_000, 20_000, 60_000):
        assert calculate_score(True, timer // 2, timer) == 750
        assert calculate_score(True, timer, timer) == 500


def test_score_wrong_or_unanswered_is_zero():
    assert calculate_score(False, 100, 20_000) == 0
    assert calculate_score(False, 20_000, 20_000) == 0


def test_score_over_timer_is_clamped_but_game_rejects_it():
    # funksiya himoya uchun vaqtni chegaralaydi; o'yinning o'zi kech javobni qabul qilmaydi (pastdagi testlar)
    assert calculate_score(True, 25_000, 20_000) == 500


@pytest.mark.parametrize("timer,ms,expected", [
    (10_000, 2_500, 875),     # 1 - 0.25/2
    (20_000, 5_000, 875),
    (60_000, 15_000, 875),
    (10_000, 7_500, 625),
    (60_000, 45_000, 625),
    (20_000, 1_000, 975),
])
def test_score_different_timers(timer, ms, expected):
    assert calculate_score(True, ms, timer) == expected


@pytest.mark.parametrize("timer,ms,expected", [
    (20_000, 501, 987),       # 987.475
    (20_000, 520, 987),       # aniq 987
    (20_000, 540, 987),       # 986.5 -> yuqoriga (Python round() 986 berardi)
    (20_000, 19_980, 501),    # 500.5 -> 501 (suzuvchi nuqtada 500.4999... chiqadi)
    (20_000, 19_999, 500),    # 500.025
    (20_000, 19_979, 501),    # 500.525
    (30_000, 630, 990),       # 989.5
    (10_000, 1_010, 950),     # 949.5
    (10_000, 1_011, 949),     # 949.45
    (60_000, 1_001, 992),     # 991.658...
])
def test_score_one_millisecond_rounding_edges(timer, ms, expected):
    assert calculate_score(True, ms, timer) == expected


def test_score_is_int_and_never_increases_with_time():
    for timer in (10_000, 20_000, 60_000):
        prev = 1000
        for ms in range(0, timer + 1, 7):
            score = calculate_score(True, ms, timer)
            assert isinstance(score, int) and 500 <= score <= prev
            prev = score


# =================================================================== ismlar
@pytest.mark.parametrize("raw,expected", [
    ("  Ali   Valiyev  ", "Ali Valiyev"),
    ("Oʻgʻiloy", "Oʻgʻiloy"),
    ("O'tkir", "O'tkir"),
    ("Алишер", "Алишер"),
    ("<b>Ali</b>", "Ali"),
    ("<script>alert(1)</script>Vali", "alert(1)Vali"),
    ("A​li\u0000", "Ali"),
    ("Ali😀🔥", "Ali"),
    ("Nodira\n\tA.", "Nodira A."),
    ("12345678901234567890", "12345678901234567890"),
])
def test_clean_nickname(raw, expected):
    assert clean_nickname(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "!!!", "😀😀", None, 42, "x" * 21, "fuck", "F.U.C.K", "s u k a", "Dalbayob", "сука"])
def test_bad_nicknames_rejected(raw):
    with pytest.raises(octagon.NicknameError):
        clean_nickname(raw)


def test_nickname_key_ignores_case_spaces_and_lookalikes():
    assert nickname_key("Ali") == nickname_key("ALI") == nickname_key("A li") == nickname_key("Аli")  # kirillcha А
    assert nickname_key("Ali") != nickname_key("Vali")


# ============================================================ o'yin dvigateli
class FakeHandle:
    def __init__(self, when, cb, args):
        self.when, self.cb, self.args, self.cancelled = when, cb, args, False

    def cancel(self):
        self.cancelled = True


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.seq = 0
        self.heap = []

    def now(self):
        return self.t

    def call_later(self, delay, cb, *args):
        h = FakeHandle(self.t + delay, cb, args)
        heapq.heappush(self.heap, (h.when, self.seq, h))
        self.seq += 1
        return h

    def advance(self, dt):
        end = self.t + dt
        while self.heap and self.heap[0][0] <= end:
            when, _, h = heapq.heappop(self.heap)
            self.t = max(self.t, when)
            if not h.cancelled:
                h.cb(*h.args)
        self.t = end


class FakeConn:
    def __init__(self, ip="10.0.0.1"):
        self.ip = ip
        self.msgs = []
        self.closed = None

    def send(self, t, d):
        json.dumps(d)  # yuboriladigan hamma narsa JSON bo'lishi kerak
        self.msgs.append((t, d))

    def close(self, reason, code=4401):
        self.closed = (code, reason)

    def last(self, t):
        return next(d for tt, d in reversed(self.msgs) if tt == t)

    def errors(self):
        return [d for t, d in self.msgs if t == "e"]


QUESTIONS = [
    {"text": f"Savol matni {i}?", "options": [f"Javob A{i}", f"Javob B{i}", f"Javob C{i}", f"Javob D{i}"], "correct": i % 4}
    for i in range(5)
] + [{"text": "Besh variantli savol?", "options": ["Besh A", "Besh B", "Besh C", "Besh D", "Besh E"], "correct": 4}]
# Eslatma: barcha matnlarda bo'shliq bor — tasodifiy tokenlar (A-Z, a-z, 0-9, _ -) ichida uchramaydi.


def octagon_env(tmp_path, monkeypatch):
    """Soxta soatli Octagon muhiti (boshqa test modullari ham o'z env fixture'ida ishlatadi)."""
    monkeypatch.setattr(config, "OCTAGON_INTRO", 5.0)
    monkeypatch.setattr(config, "OCTAGON_READ", 5.0)
    monkeypatch.setattr(config, "OCTAGON_PODIUM_INTRO", 3.0)
    monkeypatch.setattr(config, "OCTAGON_REVEAL_STEP", 3.5)
    monkeypatch.setattr(config, "OCTAGON_REVEAL_WINNER", 6.0)
    db = Database(tmp_path / "oct.db")
    owner_id = db.create_user("ustoz", "x", False, True)
    student_id = db.create_user("talaba", "x", False, False)
    tid = db.create_topic("Mavzu", QUESTIONS, False, None, owner_id)
    clock = FakeClock()
    hub = OctagonHub(db, clock)

    class Env:
        pass

    e = Env()
    e.db, e.clock, e.hub = db, clock, hub
    e.owner = db.user_by_id(owner_id)
    e.student_user = db.user_by_id(student_id)
    e.topic = db.get_topic(tid)
    e.rows = db.topic_questions(tid)
    yield e
    db.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


def make_game(env, **overrides):
    settings = octagon.clean_settings({"timeLimit": 20, "questionCount": 5, "shuffleQuestions": False, "shuffleAnswers": False, **overrides})
    return env.hub.create_game(env.owner, env.topic, env.rows, settings, "http://192.168.1.5:8080")


def join(env, game, nick, ip="10.0.0.1", av=0):
    conn = FakeConn(ip)
    env.hub.handle(conn, "join", {"v": PV, "pin": game.pin, "nick": nick, "av": av})
    assert not conn.errors(), conn.errors()
    return conn


def act(env, game, action, **data):
    return env.hub.host_action(env.owner, game.pin, action, data)


def answer(env, conn, q, o):
    env.hub.handle(conn, "a", {"q": q, "o": o})


def to_question(env, game):
    """Mavzu kirishi (faqat 1-savoldan oldin) va o'qish vaqtidan o'tib, savol faol bo'lguncha."""
    if game.phase == flow.INTRO:
        env.clock.advance(config.OCTAGON_INTRO)
    assert game.phase == flow.READ, game.phase
    env.clock.advance(config.OCTAGON_READ)
    assert game.phase == flow.ACTIVE


def finish_reveal(env, game):
    """Yakuniy ochilish (podium_intro -> 3-, 2-, 1-o'rin) taymerlari bilan oxirigacha — final_results."""
    env.clock.advance(config.OCTAGON_PODIUM_INTRO + 2 * config.OCTAGON_REVEAL_STEP + config.OCTAGON_REVEAL_WINNER)
    assert game.phase == flow.FINAL, game.phase


def next_question(env, game):
    """Natijadan keyingi savolga (reyting orqali); oxirgi savoldan keyin — yakuniy ochilish boshlanadi."""
    act(env, game, "next")
    if game.phase == flow.BOARD:
        act(env, game, "next")


def reach_phase(env, game, players, phase):
    """O'yinni berilgan bosqichga olib boradi (yakuniy ochilish — 1-savoldan keyin «Tugatish» bilan, 3 o'yinchi)."""
    order = list(flow.PHASES)
    if phase == "lobby":
        return
    act(env, game, "start")
    if order.index(phase) >= order.index("question_read"):
        env.clock.advance(config.OCTAGON_INTRO)
    if order.index(phase) >= order.index("question_active"):
        env.clock.advance(config.OCTAGON_READ)
    if order.index(phase) >= order.index("question_result"):
        for c in players:
            answer(env, c, 0, 0)
    if phase == "leaderboard":
        act(env, game, "next")
    if order.index(phase) >= order.index("podium_intro"):
        act(env, game, "end")
    for later, wait in (("reveal_3rd", config.OCTAGON_PODIUM_INTRO), ("reveal_2nd", config.OCTAGON_REVEAL_STEP),
                        ("reveal_1st", config.OCTAGON_REVEAL_STEP), ("final_results", config.OCTAGON_REVEAL_WINNER)):
        if order.index(phase) >= order.index(later):
            env.clock.advance(wait)
    assert game.phase == phase


def left_ms(env, s):
    """Bosqich tugashiga qolgan vaqt (ms) — serverning mutlaq vaqtlari bo'yicha."""
    return s["pe"] - env.hub.wall_ms()


def test_game_waits_in_lobby_until_teacher_starts(env):
    game = make_game(env)
    assert octagon.PIN_RE.fullmatch(game.pin) and game.join_url == f"http://192.168.1.5:8080/play/{game.pin}"
    assert game.qr["size"] > 21 and game.qr["path"].startswith("M")
    a = join(env, game, "Ali")
    env.clock.advance(3600)
    assert game.phase == "lobby" and ph(a.last("s")) == "lobby"
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    assert host.last("h")["phase"] == "lobby" and host.last("h")["players"] == [{"id": a.last("w")["id"], "nick": "Ali", "av": 0, "online": True}]
    # oddiy foydalanuvchi va o'quvchi o'yinni boshlay olmaydi
    with pytest.raises(OctagonError) as e:
        env.hub.host_action(env.student_user, game.pin, "start")
    assert e.value.status == 403
    env.hub.handle(a, "start", {})
    assert a.errors()[-1]["status"] == 403 and game.phase == "lobby"
    act(env, game, "start")
    assert game.phase == "topic_intro"


def test_cannot_start_empty_lobby(env):
    game = make_game(env)
    with pytest.raises(OctagonError) as e:
        act(env, game, "start")
    assert e.value.status == 409


def test_full_game_scores_ranks_and_podium(env):
    game = make_game(env, questionCount=2, timeLimit=10)
    ali, vali, olim = join(env, game, "Ali"), join(env, game, "Vali"), join(env, game, "Olim")
    act(env, game, "start")
    s = ali.last("s")  # avval mavzu nomi (topic_intro, 5 s) — savol hali yo'q
    assert ph(s) == "topic_intro" and "q" not in s and s["pe"] - s["ps"] == 5000
    env.clock.advance(5)
    s = ali.last("s")  # savolni o'qish (5 s): variantlar soni ma'lum, javob tugmalari yopiq
    assert ph(s) == "question_read" and s["q"] == 0 and s["o"] == 4 and s["pe"] - s["ps"] == 5000
    to_question(env, game)
    s = ali.last("s")
    assert ph(s) == "question_active" and s["pe"] - s["ps"] == 10_000 and left_ms(env, s) == 10_000
    # Q0: to'g'ri javob — 0 (A). Ali 0.4 s da to'g'ri, Vali 5 s da to'g'ri, Olim xato
    env.clock.advance(0.4)
    answer(env, ali, 0, 0)
    assert ali.last("s")["a"] == 0
    env.clock.advance(4.6)
    answer(env, vali, 0, 0)
    answer(env, olim, 0, 2)  # hamma javob berdi -> savol darhol yopiladi
    assert game.phase == "question_result"
    assert ali.last("s")["res"] == {"ok": True, "pts": 1000, "co": 0}
    assert vali.last("s")["res"] == {"ok": True, "pts": 750, "co": 0}
    assert olim.last("s")["res"] == {"ok": False, "pts": 0, "co": 0}
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    h = host.last("h")
    assert h["counts"] == [2, 0, 1, 0] and h["question"]["correct"] == 0 and h["answered"] == 3 and h["correctCount"] == 2
    act(env, game, "next")
    assert game.phase == "leaderboard"
    board = host.last("h")["leaderboard"]
    assert [(r["nick"], r["score"], r["rank"]) for r in board] == [("Ali", 1000, 1), ("Vali", 750, 2), ("Olim", 0, 3)]
    act(env, game, "next")
    to_question(env, game)
    # Q1: to'g'ri — 1 (B). Olim 1 s da to'g'ri, Ali javob bermaydi, Vali xato; vaqt tugaydi
    env.clock.advance(1.0)
    answer(env, olim, 1, 1)
    answer(env, vali, 1, 3)
    env.clock.advance(9.0)
    assert game.phase == "question_result"
    assert ali.last("s")["res"] == {"ok": None, "pts": 0, "co": 1}
    assert olim.last("s")["res"]["pts"] == calculate_score(True, 1000, 10_000) == 950
    act(env, game, "next")  # oxirgi savol natijasidan — reytingsiz, to'g'ridan-to'g'ri yakuniy ochilishga
    assert game.phase == "podium_intro"
    finish_reveal(env, game)
    final = host.last("h")
    assert [(r["nick"], r["score"]) for r in final["ranking"]] == [("Ali", 1000), ("Olim", 950), ("Vali", 750)]
    s = olim.last("s")
    assert ph(s) == "final_results" and s["k"] == 2 and s["sc"] == 950 and s["top"][0] == [1, "Ali", 1000, 0]


def test_configured_timer_is_used(env):
    game = make_game(env, timeLimit=7)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(6.999)
    s = a.last("s")
    assert game.phase == "question_active" and s["pe"] - s["ps"] == 7000
    env.clock.advance(0.002)
    assert game.phase == "question_result"


def test_answer_after_deadline_is_rejected_by_server_time(env):
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    env.clock.t += 10.001  # javob server muddatidan 1 ms keyin keldi (taymer hali ishlamagan bo'lsa ham)
    answer(env, a, 0, 0)
    assert a.errors()[-1]["c"] == "late" and 0 not in game.players[a.last("w")["id"]].answers
    env.clock.advance(1)
    assert a.last("s")["res"] == {"ok": None, "pts": 0, "co": 0}
    # aynan muddatda kelgan javob qabul qilinadi (500 ball)
    act(env, game, "next")
    act(env, game, "next")
    to_question(env, game)
    env.clock.t += 10.0
    answer(env, a, 1, 1)
    assert a.last("s")["res"] == {"ok": True, "pts": 500, "co": 1}


def test_one_answer_per_question_first_wins(env):
    game = make_game(env)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 3)
    answer(env, a, 0, 0)
    answer(env, a, 5, 0)
    pid = a.last("w")["id"]
    assert game.players[pid].answers == {0: (3, 0)}
    assert a.errors()[-1]["c"] == "late"  # boshqa savol indeksi
    env.hub.handle(b, "a", {"q": 0, "o": 9})
    env.hub.handle(b, "a", {"q": 0, "o": "1"})
    assert [e["c"] for e in b.errors()] == ["bad", "bad"] and game.phase == "question_active"


def test_late_joiner_mid_game(env):
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 0)  # yagona o'yinchi javob berdi -> reveal
    act(env, game, "next")
    act(env, game, "next")
    to_question(env, game)
    env.clock.advance(2)
    late = join(env, game, "Kechikkan")
    s = late.last("s")
    assert ph(s) == "question_active" and s["q"] == 1 and s["o"] == 4 and left_ms(env, s) == 8000 and s["sc"] == 0
    assert late.last("w")["n"] == len(game.questions) and late.last("w")["tn"] == "Mavzu"
    answer(env, late, 1, 1)
    env.clock.advance(8)
    assert late.last("s")["res"]["ok"] is True and late.last("s")["res"]["pts"] == calculate_score(True, 2000, 10_000)
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    act(env, game, "next")
    assert "Kechikkan" in [r["nick"] for r in host.last("h")["leaderboard"]]


def test_reconnect_resumes_same_player_without_duplicates(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    w = a.last("w")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(1)
    answer(env, a, 0, 0)
    env.hub.disconnect(a)
    assert game.players[w["id"]].conn is None and game.phase == "question_result"
    score = game.players[w["id"]].score
    # sahifa yangilandi: token bilan qaytadi
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert a2.last("w") == {"v": PV, "pin": game.pin, "id": w["id"], "nick": "Ali", "av": 0, "tn": "Mavzu", "n": len(game.questions)}
    s = a2.last("s")
    assert ph(s) == "question_result" and s["sc"] == score > 0 and s["a"] == 0 and s["res"]["ok"] is True
    assert len(game.players) == 1 and list(game.keys) == [nickname_key("Ali")]
    # token yoki PIN noto'g'ri — qabul qilinmaydi
    bad = FakeConn()
    env.hub.handle(bad, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": "x" + w["tok"]})
    env.hub.handle(bad, "resume", {"v": PV, "pin": "999999", "id": w["id"], "tok": w["tok"]})
    assert [e["c"] for e in bad.errors()] == ["gone", "gone"] and len(game.players) == 1


def test_same_token_in_second_tab_takes_over(env):
    game = make_game(env)
    first = join(env, game, "Ali")
    w = first.last("w")
    second = FakeConn()
    env.hub.handle(second, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert first.last("k") == {"r": "replaced"} and first.closed == (4001, "replaced")
    assert game.players[w["id"]].conn is second and len(game.players) == 1
    env.hub.disconnect(first)  # eski oyna yopilganda yangi ulanish saqlanib qoladi
    assert game.players[w["id"]].conn is second


def test_duplicate_nickname_rejected_even_for_disconnected_player(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    for nick in ("Ali", "ALI", "a li", "Аli"):  # oxirgisi — kirillcha "А"
        c = FakeConn()
        env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game.pin, "nick": nick})
        assert c.errors()[-1]["c"] == "taken", nick
    env.hub.disconnect(a)
    c = FakeConn()
    env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game.pin, "nick": "Ali"})
    assert c.errors()[-1]["c"] == "taken" and len(game.players) == 1


def test_student_messages_never_contain_question_or_answer_text(env):
    game = make_game(env, questionCount=6, timeLimit=5)  # 5 variantli savol ham bor (qisqartiriladi)
    conns = [join(env, game, n) for n in ("Ali", "Vali", "Olim")]
    texts = [q["text"] for q in QUESTIONS] + [o for q in QUESTIONS for o in q["options"]]
    act(env, game, "start")
    for i in range(len(game.questions)):
        to_question(env, game)
        for j, c in enumerate(conns[:2]):
            answer(env, c, i, j)
        env.clock.advance(5)
        next_question(env, game)
    finish_reveal(env, game)
    for c in conns:
        raw = json.dumps(c.msgs, ensure_ascii=False)
        assert not any(t in raw for t in texts)
        for t, d in c.msgs:
            assert len(json.dumps(d, ensure_ascii=False, separators=(",", ":"))) < 200
            if t == "s" and ph(d) in ("lobby", "topic_intro", "question_read", "question_active"):
                assert "res" not in d and "co" not in json.dumps(d)
            if t == "s":
                assert set(d) <= {"p", "q", "o", "ps", "pe", "a", "sc", "k", "pl", "res", "top", "dk", "nw", "bh", "nc"}


def test_long_option_questions_trimmed_or_skipped(env):
    game = make_game(env, questionCount=6)
    q = game.questions[5]
    assert len(q["options"]) == 4 and q["options"][q["correct"]] == "Besh E" and game.trimmed == 1
    game2 = make_game(env, questionCount=6, longOptions="skip")
    assert len(game2.questions) == 5 and all(len(q["options"]) == 4 for q in game2.questions)


def test_two_option_question(env):
    rows = [{"id": 1, "text": "Rostmi?", "options": ["Ha", "Yo'q"], "correct": 1}]
    settings = octagon.clean_settings({"questionCount": 5})
    game = env.hub.create_game(env.owner, env.topic, rows, settings, "http://x")
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    assert a.last("s")["o"] == 2
    answer(env, a, 0, 2)
    assert a.errors()[-1]["c"] == "bad"
    correct = game.questions[0]["correct"]  # variantlar aralashtirilgan (standart sozlama)
    assert game.questions[0]["options"][correct] == "Yo'q"
    answer(env, a, 0, correct)
    assert a.last("s")["res"]["ok"] is True


def test_ties_broken_by_total_response_time_then_nickname(env):
    game = make_game(env, questionCount=1, timeLimit=10)
    b, a, c = join(env, game, "Bobur"), join(env, game, "Anvar"), join(env, game, "Charos")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(0.2)
    answer(env, b, 0, 1)   # hammasi xato: 0 ball; Bobur 0.2 s
    env.clock.advance(0.3)
    answer(env, a, 0, 1)   # Anvar 0.5 s
    answer(env, c, 0, 1)   # Charos 0.5 s
    ranking = [p.nick for p in env.hub.standings(game)]
    assert ranking == ["Bobur", "Anvar", "Charos"]


def test_settings_locked_after_start(env):
    game = make_game(env)
    join(env, game, "Ali")
    act(env, game, "settings", timeLimit=30)
    assert game.time_limit_ms == 30_000
    for bad in (4, 121, 12.5, "20", True):
        with pytest.raises(OctagonError):
            act(env, game, "settings", timeLimit=bad)
    act(env, game, "start")
    with pytest.raises(OctagonError) as e:
        act(env, game, "settings", timeLimit=10)
    assert e.value.status == 409 and game.time_limit_ms == 30_000


@pytest.mark.parametrize("data", [{"timeLimit": 4}, {"timeLimit": 121}, {"timeLimit": "20"}, {"timeLimit": 20.0},
                                  {"questionCount": 0}, {"longOptions": "x"}])
def test_clean_settings_validation(data):
    with pytest.raises(OctagonError):
        octagon.clean_settings(data)


def test_end_early_and_cancel_in_lobby(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    answer(env, a, 0, 0)
    act(env, game, "next")
    act(env, game, "next")  # 2-savol: tayyorlaning
    act(env, game, "end")  # 1-savolda ball olingan — yakuniy ochilish shu ballar bilan
    assert game.phase == "podium_intro" and game.ended_early and len(game.stats) == 1 and ph(a.last("s")) == "podium_intro"
    assert game.podium == [a.last("w")["id"]]
    # lobbida "tugatish" — o'yin bekor qilinadi
    game2 = make_game(env)
    b = join(env, game2, "Vali")
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game2.pin}, env.owner)
    assert act(env, game2, "end") is None
    assert game2.pin not in env.hub.games and b.closed == (4003, "ended") and host.last("closed")["pin"] == game2.pin


def test_kick_player(env):
    game = make_game(env)
    a = join(env, game, "Yomon")
    pid = a.last("w")["id"]
    act(env, game, "kick", id=pid)
    assert a.closed == (4002, "kicked") and pid not in game.players
    c = FakeConn()
    env.hub.handle(c, "resume", {"v": PV, "pin": game.pin, "id": pid, "tok": a.last("w")["tok"]})
    assert c.errors()[-1]["c"] == "gone"
    join(env, game, "Yaxshi")  # boshqa ism bilan qaytishi mumkin (o'sha ism band — audit testiga qarang)


def test_stale_host_action_is_ignored(env):
    game = make_game(env)
    join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    act(env, game, "next", phase="question_active", q=0)
    assert game.phase == "question_result"
    act(env, game, "next", phase="question_active", q=0)  # ikkinchi oynadan kechikkan bosish — e'tiborsiz
    assert game.phase == "question_result"


def test_host_reconnect_resumes_control(env):
    game = make_game(env)
    join(env, game, "Ali")
    h1 = FakeConn()
    env.hub.handle(h1, "host", {"v": PV, "pin": game.pin}, env.owner)
    env.hub.handle(h1, "start", {}, env.owner)
    assert game.phase == "topic_intro"
    env.hub.disconnect(h1)
    env.clock.advance(10)  # mavzu (5 s) + o'qish (5 s)
    h2 = FakeConn()
    env.hub.handle(h2, "host", {"v": PV, "pin": game.pin}, env.owner)
    h = h2.last("h")
    assert h["phase"] == "question_active" and h["question"]["text"] == "Savol matni 0?" and h["phaseEnd"] - env.hub.wall_ms() == 20_000
    env.hub.handle(h2, "skip", {}, env.owner)
    assert game.phase == "question_result"
    # boshqa o'qituvchi bu o'yinni boshqara olmaydi
    other_id = env.db.create_user("boshqa", "x", False, True)
    other = FakeConn()
    env.hub.handle(other, "host", {"v": PV, "pin": game.pin}, env.db.user_by_id(other_id))
    assert other.errors()[-1]["status"] == 404


def test_role_revoked_mid_game_blocks_control(env):
    game = make_game(env)
    join(env, game, "Ali")
    env.db.set_teacher(env.owner["id"], False)
    with pytest.raises(OctagonError) as e:
        act(env, game, "start")
    assert e.value.status == 403


def test_unknown_pin_and_rate_limit(env):
    game = make_game(env)
    c = FakeConn(ip="10.9.9.9")
    for _ in range(octagon.FAIL_LIMIT):
        env.hub.handle(c, "check", {"v": PV, "pin": "123456" if game.pin != "123456" else "654321"})
    assert all(e["c"] == "pin" for e in c.errors())
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.errors()[-1]["c"] == "rate"  # to'g'ri PIN ham — IP vaqtincha bloklangan
    other = FakeConn(ip="10.9.9.10")
    env.hub.handle(other, "check", {"v": PV, "pin": game.pin})
    assert other.last("c") == {"pin": game.pin}
    for bad in ("12345", "abcdef", "0123456", None, 123):
        env.hub.handle(other, "check", {"v": PV, "pin": bad})
    assert len(other.errors()) == 5


def test_pins_are_unique_six_digits(env, monkeypatch):
    values = iter([111111 - 100000, 111111 - 100000, 222222 - 100000])
    monkeypatch.setattr(octagon.secrets, "randbelow", lambda n: next(values))
    g1, g2 = make_game(env), make_game(env)
    assert (g1.pin, g2.pin) == ("111111", "222222")


def test_inactive_games_are_cleaned_up(env, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_TTL", 7200.0)
    game = make_game(env)
    a = join(env, game, "Ali")
    env.clock.advance(7100)
    assert game.pin in env.hub.games
    env.clock.advance(200)
    assert game.pin not in env.hub.games and a.closed == (4003, "ended")


def test_teacher_game_limit(env):
    for _ in range(octagon.MAX_GAMES_PER_OWNER):
        make_game(env)
    with pytest.raises(OctagonError) as e:
        make_game(env)
    assert e.value.status == 409


# ============================================ xavfsizlik auditi (docs/octagon-audit.md)
def test_forged_answer_fields_are_ignored(env):
    """Javob vaqti, to'g'riligi va ball faqat serverda aniqlanadi — mijoz yuborgan qo'shimcha maydonlar e'tiborsiz."""
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(4)
    env.hub.handle(a, "a", {"q": 0, "o": 1, "ms": 0, "t": 0, "time": 1, "score": 99999, "pts": 1000, "ok": True, "correct": 1})
    p = next(iter(game.players.values()))
    assert p.answers == {0: (1, 4000)}
    env.clock.advance(6)
    assert a.last("s")["res"] == {"ok": False, "pts": 0, "co": 0} and p.score == 0


@pytest.mark.parametrize("bad", [
    {"q": 0, "o": -1}, {"q": 0, "o": 4}, {"q": 0, "o": 10**30}, {"q": 0, "o": 1.0}, {"q": 0, "o": "1"}, {"q": 0, "o": True},
    {"q": 0, "o": None}, {"q": 0, "o": [1]}, {"q": True, "o": 1}, {"q": "0", "o": 1}, {"q": -1, "o": 1}, {"q": 1, "o": 1},
    {"o": 1}, {},
])
def test_malformed_answers_rejected(env, bad):
    game = make_game(env)
    a = join(env, game, "Ali")
    join(env, game, "Vali")
    act(env, game, "start")
    to_question(env, game)
    env.hub.handle(a, "a", bad)
    assert a.errors() and all(not p.answers for p in game.players.values()) and game.phase == "question_active"


def test_answer_before_question_opens_is_rejected(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    act(env, game, "start")  # mavzu kirishi — savol hali ochilmagan
    env.hub.handle(a, "a", {"q": 0, "o": 0})
    assert a.errors()[-1]["c"] == "early" and not game.players[a.last("w")["id"]].answers
    env.clock.advance(config.OCTAGON_INTRO)  # o'qish bosqichi — savol matni faqat o'qituvchida, javob hali qabul qilinmaydi
    env.hub.handle(a, "a", {"q": 0, "o": 0})
    assert a.errors()[-1]["c"] == "early" and not game.players[a.last("w")["id"]].answers
    to_question(env, game)
    answer(env, a, 0, 0)
    assert a.last("s")["res"]["ok"] is True


def test_player_tokens_never_reach_host_or_other_players(env):
    game = make_game(env, questionCount=2, timeLimit=5)
    conns = [join(env, game, n) for n in ("Ali", "Vali", "Olim")]
    tokens = [c.last("w")["tok"] for c in conns]
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    env.hub.disconnect(conns[1])
    again = FakeConn()
    env.hub.handle(again, "resume", {"v": PV, "pin": game.pin, "id": conns[1].last("w")["id"], "tok": tokens[1]})
    act(env, game, "start")
    for i in range(2):
        to_question(env, game)
        answer(env, conns[0], i, 0)
        env.clock.advance(5)
        next_question(env, game)
    finish_reveal(env, game)
    host_blob = json.dumps([host.msgs, env.hub.host_state(game), env.hub.game_summary(game)])
    for i, tok in enumerate(tokens):
        assert len(tok) >= 32 and tok not in host_blob
        for c in conns + [again]:
            if c is not conns[i]:  # token faqat o'ziga, birinchi "w" xabarida yuboriladi
                assert tok not in json.dumps(c.msgs)
    assert all(p.token_hash not in tokens for p in game.players.values())


def test_resume_cannot_impersonate_another_player(env):
    game = make_game(env)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    wa, wb = a.last("w"), b.last("w")
    attempts = [
        {"id": wb["id"], "tok": wa["tok"]},   # boshqa o'yinchining ID si + o'z tokeni
        {"id": wb["id"]},                     # tokensiz (faqat ID ni bilish yetmaydi)
        {"id": wb["id"], "tok": None},
        {"id": wb["id"], "tok": "\ud800"},    # UTF-8 ga o'tmaydigan satr
        {"id": wb["id"], "tok": 12345},
        {"id": "Vali", "tok": wb["tok"]},     # ism bilan
    ]
    for data in attempts:
        c = FakeConn(ip="10.1.1.1")
        env.hub.handle(c, "resume", {"v": PV, "pin": game.pin, **data})
        assert c.errors() and c.errors()[-1]["c"] == "gone", data
    assert game.players[wb["id"]].conn is b and len(game.players) == 2
    assert env.hub.failed.count("10.1.1.1") == len(attempts)  # har bir urinish hisoblanadi


def test_join_at_start_and_reconnect_during_question_change(env):
    game = make_game(env, timeLimit=10)
    a = join(env, game, "Ali")
    act(env, game, "start")
    b = join(env, game, "Vali")  # aynan «Boshlash» paytida
    assert ph(b.last("s")) == "topic_intro" and b.last("w")["tn"] == "Mavzu"
    to_question(env, game)
    answer(env, b, 0, 0)
    wa = a.last("w")
    env.hub.disconnect(a)        # savol almashayotganda aloqa uzildi
    env.clock.advance(10)
    act(env, game, "next")
    act(env, game, "next")
    to_question(env, game)
    env.clock.advance(1.5)
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"v": PV, "pin": game.pin, "id": wa["id"], "tok": wa["tok"]})
    s = a2.last("s")
    assert ph(s) == "question_active" and s["q"] == 1 and left_ms(env, s) == 8500 and s["a"] is None
    answer(env, a2, 0, 0)        # oldingi savolga kechikkan javob
    assert a2.errors()[-1]["c"] == "late"
    answer(env, a2, 1, 1)
    assert game.players[wa["id"]].answers == {1: (1, 1500)} and len(game.players) == 2


def test_ended_game_pin_checks_count_as_failed_attempts(env):
    game = make_game(env)
    join(env, game, "Ali")
    act(env, game, "start")
    act(env, game, "end")
    c = FakeConn(ip="10.2.2.2")
    for _ in range(octagon.FAIL_LIMIT):
        env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert {e["c"] for e in c.errors()} == {"ended"}
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.errors()[-1]["c"] == "rate"


def test_global_failure_surge_tightens_per_ip_limit(env, monkeypatch):
    game = make_game(env)
    wrong = "123456" if game.pin != "123456" else "654321"
    t = [5000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: t[0])
    for i in range(octagon.GLOBAL_FAIL_LIMIT):  # ko'p IP dan PIN taxmin qilish (botnet)
        env.hub.handle(FakeConn(ip=f"10.50.{i // 200}.{i % 200}"), "check", {"v": PV, "pin": wrong})
    c = FakeConn(ip="10.60.0.1")
    for _ in range(octagon.SURGE_FAIL_LIMIT):
        env.hub.handle(c, "check", {"v": PV, "pin": wrong})
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.errors()[-1]["c"] == "rate"  # odatda FAIL_LIMIT (20) tagacha ruxsat bor
    fresh = FakeConn(ip="10.60.0.2")      # xato qilmagan IP (masalan, boshqa sinf) qo'shila oladi
    env.hub.handle(fresh, "check", {"v": PV, "pin": game.pin})
    assert fresh.last("c") == {"pin": game.pin}
    t[0] += octagon.GLOBAL_FAIL_WINDOW + 1  # hujum to'xtadi — oddiy chegara qaytadi
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    assert c.last("c") == {"pin": game.pin}


def test_kicked_nickname_stays_reserved_and_join_lock(env):
    game = make_game(env)
    a = join(env, game, "Yomon")
    act(env, game, "kick", id=a.last("w")["id"])
    for nick in ("Yomon", "YOMON", "yo mon"):
        c = FakeConn()
        env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game.pin, "nick": nick})
        assert c.errors() and c.errors()[-1]["c"] == "banned", nick
    b = join(env, game, "Boshqa")  # boshqa ism bilan — mumkin
    act(env, game, "lock", locked=True)
    assert env.hub.host_state(game)["locked"] is True
    c = FakeConn()
    env.hub.handle(c, "check", {"v": PV, "pin": game.pin})
    env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game.pin, "nick": "Yangi"})
    assert [e["c"] for e in c.errors()] == ["locked", "locked"] and len(game.players) == 1
    wb = b.last("w")
    env.hub.disconnect(b)
    b2 = FakeConn()
    env.hub.handle(b2, "resume", {"v": PV, "pin": game.pin, "id": wb["id"], "tok": wb["tok"]})  # qayta ulanishga qulf ta'sir qilmaydi
    assert b2.last("w")["id"] == wb["id"]
    act(env, game, "lock", locked=False)
    join(env, game, "Yangi")


def test_finished_games_do_not_exhaust_server_capacity(env, monkeypatch):
    monkeypatch.setattr(octagon, "MAX_GAMES", 8)
    for _ in range(12):  # o'qituvchi o'yin ochib, tugatib turadi
        g = make_game(env)
        join(env, g, "Ali")
        act(env, g, "start")
        act(env, g, "end")
    assert len(env.hub.games_of(env.owner["id"])) <= octagon.MAX_FINISHED_PER_OWNER
    other = env.db.user_by_id(env.db.create_user("boshqa", "x", False, True))
    settings = octagon.clean_settings({"timeLimit": 20, "questionCount": 5})
    for _ in range(octagon.MAX_GAMES_PER_OWNER):
        env.hub.create_game(other, env.topic, env.rows, settings, "http://x")
    assert len(env.hub.games) <= octagon.MAX_GAMES


def test_sweep_keeps_running_after_an_error(env, monkeypatch):
    g1, g2 = make_game(env), make_game(env)
    real = env.hub.close_game

    def flaky(pin, reason="closed"):
        if pin == g1.pin:
            raise RuntimeError("boom")
        real(pin, reason)

    monkeypatch.setattr(env.hub, "close_game", flaky)
    env.clock.advance(config.OCTAGON_TTL + 120)
    assert g2.pin not in env.hub.games  # bitta o'yindagi xato boshqalarini tozalashga to'sqinlik qilmaydi
    monkeypatch.setattr(env.hub, "close_game", real)
    env.clock.advance(120)
    assert not env.hub.games


def test_no_state_left_after_game_closed(env):
    game = make_game(env, questionCount=1, timeLimit=5)
    conns = [join(env, game, n) for n in ("Ali", "Vali")]
    host = FakeConn()
    env.hub.handle(host, "host", {"v": PV, "pin": game.pin}, env.owner)
    act(env, game, "start")
    to_question(env, game)
    answer(env, conns[0], 0, 0)
    env.clock.advance(5)
    act(env, game, "next")
    act(env, game, "next")
    for c in conns:
        env.hub.disconnect(c)
    act(env, game, "close")
    assert not env.hub.games and not env.hub.conn_info and not env.hub.sockets
    live = [h for *_, h in env.clock.heap if not h.cancelled]
    assert len(live) <= 1  # faqat umumiy tozalash taymeri
    env.hub.disconnect(host)
    assert not env.hub.conn_info


def test_player_cap_and_join_flood_limit(env, monkeypatch):
    monkeypatch.setattr(octagon, "MAX_PLAYERS", 3)
    game = make_game(env)
    for n in ("Ali", "Vali", "Olim"):
        join(env, game, n, ip="10.3.3.3")
    c = FakeConn(ip="10.3.3.4")
    env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game.pin, "nick": "Toshmat"})
    assert c.errors()[-1]["c"] == "full"
    monkeypatch.setattr(octagon, "MAX_PLAYERS", 1000)
    game2 = make_game(env)
    for i in range(octagon.JOIN_LIMIT):  # bitta IP ortida butun maktab bo'lishi mumkin — chegara keng
        join(env, game2, f"Bot {i}", ip="10.4.4.4")
    c = FakeConn(ip="10.4.4.4")
    env.hub.handle(c, "join", {"v": PV, "av": 0, "pin": game2.pin, "nick": "Yana"})
    assert c.errors()[-1]["c"] == "rate"
