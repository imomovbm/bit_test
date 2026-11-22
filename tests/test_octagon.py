"""Octagon (jonli viktorina): ball hisoblash, ismlar va o'yin dvigateli (soxta soat bilan — haqiqiy kutishsiz)."""
import heapq
import json

import pytest

from app import config, octagon
from app.db import Database
from app.octagon import OctagonError, OctagonHub, calculate_score, clean_nickname, nickname_key


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


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_READY", 3.0)
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


def make_game(env, **overrides):
    settings = octagon.clean_settings({"timeLimit": 20, "questionCount": 5, "shuffleQuestions": False, "shuffleAnswers": False, **overrides})
    return env.hub.create_game(env.owner, env.topic, env.rows, settings, "http://192.168.1.5:8080")


def join(env, game, nick, ip="10.0.0.1"):
    conn = FakeConn(ip)
    env.hub.handle(conn, "join", {"pin": game.pin, "nick": nick})
    assert not conn.errors(), conn.errors()
    return conn


def act(env, game, action, **data):
    return env.hub.host_action(env.owner, game.pin, action, data)


def answer(env, conn, q, o):
    env.hub.handle(conn, "a", {"q": q, "o": o})


def to_question(env, game):
    env.clock.advance(config.OCTAGON_READY)
    assert game.phase == "question"


def test_game_waits_in_lobby_until_teacher_starts(env):
    game = make_game(env)
    assert octagon.PIN_RE.fullmatch(game.pin) and game.join_url == f"http://192.168.1.5:8080/play/{game.pin}"
    assert game.qr["size"] > 21 and game.qr["path"].startswith("M")
    a = join(env, game, "Ali")
    env.clock.advance(3600)
    assert game.phase == "lobby" and a.last("s")["p"] == "lobby"
    host = FakeConn()
    env.hub.handle(host, "host", {"pin": game.pin}, env.owner)
    assert host.last("h")["phase"] == "lobby" and host.last("h")["players"] == [{"id": a.last("w")["id"], "nick": "Ali", "online": True}]
    # oddiy foydalanuvchi va o'quvchi o'yinni boshlay olmaydi
    with pytest.raises(OctagonError) as e:
        env.hub.host_action(env.student_user, game.pin, "start")
    assert e.value.status == 403
    env.hub.handle(a, "start", {})
    assert a.errors()[-1]["status"] == 403 and game.phase == "lobby"
    act(env, game, "start")
    assert game.phase == "ready"


def test_cannot_start_empty_lobby(env):
    game = make_game(env)
    with pytest.raises(OctagonError) as e:
        act(env, game, "start")
    assert e.value.status == 409


def test_full_game_scores_ranks_and_podium(env):
    game = make_game(env, questionCount=2, timeLimit=10)
    ali, vali, olim = join(env, game, "Ali"), join(env, game, "Vali"), join(env, game, "Olim")
    act(env, game, "start")
    s = ali.last("s")
    assert s["p"] == "ready" and s["q"] == 0 and s["o"] == 4 and s["r"] == 3000 and s["t"] == 10_000
    to_question(env, game)
    assert ali.last("s")["p"] == "question" and ali.last("s")["r"] == 10_000
    # Q0: to'g'ri javob — 0 (A). Ali 0.4 s da to'g'ri, Vali 5 s da to'g'ri, Olim xato
    env.clock.advance(0.4)
    answer(env, ali, 0, 0)
    assert ali.last("s")["a"] == 0
    env.clock.advance(4.6)
    answer(env, vali, 0, 0)
    answer(env, olim, 0, 2)  # hamma javob berdi -> savol darhol yopiladi
    assert game.phase == "reveal"
    assert ali.last("s")["res"] == {"ok": True, "pts": 1000, "co": 0}
    assert vali.last("s")["res"] == {"ok": True, "pts": 750, "co": 0}
    assert olim.last("s")["res"] == {"ok": False, "pts": 0, "co": 0}
    host = FakeConn()
    env.hub.handle(host, "host", {"pin": game.pin}, env.owner)
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
    assert game.phase == "reveal"
    assert ali.last("s")["res"] == {"ok": None, "pts": 0, "co": 1}
    assert olim.last("s")["res"]["pts"] == calculate_score(True, 1000, 10_000) == 950
    act(env, game, "next")
    act(env, game, "next")  # oxirgi savol -> podium
    assert game.phase == "podium"
    final = host.last("h")
    assert [(r["nick"], r["score"]) for r in final["ranking"]] == [("Ali", 1000), ("Olim", 950), ("Vali", 750)]
    s = olim.last("s")
    assert s["p"] == "podium" and s["k"] == 2 and s["sc"] == 950 and s["top"][0] == ["Ali", 1000]


def test_configured_timer_is_used(env):
    game = make_game(env, timeLimit=7)
    a = join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(6.999)
    assert game.phase == "question" and a.last("s")["t"] == 7000
    env.clock.advance(0.002)
    assert game.phase == "reveal"


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
    assert [e["c"] for e in b.errors()] == ["bad", "bad"] and game.phase == "question"


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
    assert s["p"] == "question" and s["q"] == 1 and s["o"] == 4 and s["r"] == 8000 and s["sc"] == 0 and s["k"] == 2 and s["pl"] == 2
    answer(env, late, 1, 1)
    env.clock.advance(8)
    assert late.last("s")["res"]["ok"] is True and late.last("s")["res"]["pts"] == calculate_score(True, 2000, 10_000)
    host = FakeConn()
    env.hub.handle(host, "host", {"pin": game.pin}, env.owner)
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
    assert game.players[w["id"]].conn is None and game.phase == "reveal"
    score = game.players[w["id"]].score
    # sahifa yangilandi: token bilan qaytadi
    a2 = FakeConn()
    env.hub.handle(a2, "resume", {"pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert a2.last("w") == {"pin": game.pin, "id": w["id"], "nick": "Ali"}
    s = a2.last("s")
    assert s["p"] == "reveal" and s["sc"] == score > 0 and s["a"] == 0 and s["res"]["ok"] is True
    assert len(game.players) == 1 and list(game.keys) == [nickname_key("Ali")]
    # token yoki PIN noto'g'ri — qabul qilinmaydi
    bad = FakeConn()
    env.hub.handle(bad, "resume", {"pin": game.pin, "id": w["id"], "tok": "x" + w["tok"]})
    env.hub.handle(bad, "resume", {"pin": "999999", "id": w["id"], "tok": w["tok"]})
    assert [e["c"] for e in bad.errors()] == ["gone", "gone"] and len(game.players) == 1


def test_same_token_in_second_tab_takes_over(env):
    game = make_game(env)
    first = join(env, game, "Ali")
    w = first.last("w")
    second = FakeConn()
    env.hub.handle(second, "resume", {"pin": game.pin, "id": w["id"], "tok": w["tok"]})
    assert first.last("k") == {"r": "replaced"} and first.closed == (4001, "replaced")
    assert game.players[w["id"]].conn is second and len(game.players) == 1
    env.hub.disconnect(first)  # eski oyna yopilganda yangi ulanish saqlanib qoladi
    assert game.players[w["id"]].conn is second


def test_duplicate_nickname_rejected_even_for_disconnected_player(env):
    game = make_game(env)
    a = join(env, game, "Ali")
    for nick in ("Ali", "ALI", "a li", "Аli"):  # oxirgisi — kirillcha "А"
        c = FakeConn()
        env.hub.handle(c, "join", {"pin": game.pin, "nick": nick})
        assert c.errors()[-1]["c"] == "taken", nick
    env.hub.disconnect(a)
    c = FakeConn()
    env.hub.handle(c, "join", {"pin": game.pin, "nick": "Ali"})
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
        act(env, game, "next")
        act(env, game, "next")
    assert game.phase == "podium"
    for c in conns:
        raw = json.dumps(c.msgs, ensure_ascii=False)
        assert not any(t in raw for t in texts)
        for t, d in c.msgs:
            assert len(json.dumps(d, ensure_ascii=False, separators=(",", ":"))) < 200
            if t == "s" and d["p"] in ("lobby", "ready", "question"):
                assert "res" not in d and "co" not in json.dumps(d)
            if t == "s":
                assert set(d) <= {"p", "q", "n", "o", "r", "t", "a", "sc", "k", "pl", "res", "top"}


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
    act(env, game, "end")
    assert game.phase == "podium" and game.ended_early and len(game.stats) == 1 and a.last("s")["p"] == "podium"
    # lobbida "tugatish" — o'yin bekor qilinadi
    game2 = make_game(env)
    b = join(env, game2, "Vali")
    host = FakeConn()
    env.hub.handle(host, "host", {"pin": game2.pin}, env.owner)
    assert act(env, game2, "end") is None
    assert game2.pin not in env.hub.games and b.closed == (4003, "ended") and host.last("closed")["pin"] == game2.pin


def test_kick_player(env):
    game = make_game(env)
    a = join(env, game, "Yomon")
    pid = a.last("w")["id"]
    act(env, game, "kick", id=pid)
    assert a.closed == (4002, "kicked") and pid not in game.players
    c = FakeConn()
    env.hub.handle(c, "resume", {"pin": game.pin, "id": pid, "tok": a.last("w")["tok"]})
    assert c.errors()[-1]["c"] == "gone"
    join(env, game, "Yomon")  # ism bo'shadi


def test_stale_host_action_is_ignored(env):
    game = make_game(env)
    join(env, game, "Ali")
    act(env, game, "start")
    to_question(env, game)
    act(env, game, "next", phase="question", q=0)
    assert game.phase == "reveal"
    act(env, game, "next", phase="question", q=0)  # ikkinchi oynadan kechikkan bosish — e'tiborsiz
    assert game.phase == "reveal"


def test_host_reconnect_resumes_control(env):
    game = make_game(env)
    join(env, game, "Ali")
    h1 = FakeConn()
    env.hub.handle(h1, "host", {"pin": game.pin}, env.owner)
    env.hub.handle(h1, "start", {}, env.owner)
    assert game.phase == "ready"
    env.hub.disconnect(h1)
    env.clock.advance(3)
    h2 = FakeConn()
    env.hub.handle(h2, "host", {"pin": game.pin}, env.owner)
    h = h2.last("h")
    assert h["phase"] == "question" and h["question"]["text"] == "Savol matni 0?" and h["remainingMs"] == 20_000
    env.hub.handle(h2, "skip", {}, env.owner)
    assert game.phase == "reveal"
    # boshqa o'qituvchi bu o'yinni boshqara olmaydi
    other_id = env.db.create_user("boshqa", "x", False, True)
    other = FakeConn()
    env.hub.handle(other, "host", {"pin": game.pin}, env.db.user_by_id(other_id))
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
    for _ in range(20):
        env.hub.handle(c, "check", {"pin": "123456" if game.pin != "123456" else "654321"})
    assert all(e["c"] == "pin" for e in c.errors())
    env.hub.handle(c, "check", {"pin": game.pin})
    assert c.errors()[-1]["c"] == "rate"  # to'g'ri PIN ham — IP vaqtincha bloklangan
    other = FakeConn(ip="10.9.9.10")
    env.hub.handle(other, "check", {"pin": game.pin})
    assert other.last("c") == {"pin": game.pin}
    for bad in ("12345", "abcdef", "0123456", None, 123):
        env.hub.handle(other, "check", {"pin": bad})
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
