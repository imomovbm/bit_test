"""Duel dvigateli testlari (soxta soat bilan — haqiqiy kutishsiz)."""
import heapq
from types import SimpleNamespace

import pytest

from app import config
from app.db import Database
from app.hub import DuelHub, afk_timeouts


class FakeHandle:
    def __init__(self, when, cb, args):
        self.when, self.cb, self.args, self.cancelled = when, cb, args, False

    def cancel(self):
        self.cancelled = True


class FakeClock:
    def __init__(self):
        self.t = 0.0
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


class Conn:
    """Soxta ulanish. `bot` berilsa, savollarga avtomatik javob beradi."""

    def __init__(self, env=None, user=None, delay=1.0, correct=True, silent=True):
        self.msgs = []
        self.closed = False
        self.env, self.user, self.delay, self.correct, self.silent = env, user, delay, correct, silent

    def send(self, t, d):
        self.msgs.append((t, d))
        if t == "duel:question" and not self.silent:
            self.env.clock.call_later(self.delay, self._answer, d["duelId"], d["index"])

    def _answer(self, duel_id, index):
        duel = self.env.hub.duels.get(duel_id)
        if not duel:
            return
        q = duel.questions[index]
        ok = self.correct(index) if callable(self.correct) else self.correct
        choice = q["correct"] if ok else (q["correct"] + 1) % len(q["options"])
        self.env.hub.handle(self.user["id"], self, "duel:answer", {"duelId": duel_id, "index": index, "choice": choice})

    def close(self, reason="closed"):
        self.closed = True
        self.close_reason = reason

    def of(self, t):
        return [d for mt, d in self.msgs if mt == t]

    def last(self, t):
        items = self.of(t)
        return items[-1] if items else None


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "t.db")
    users = {}
    for name in ("ali", "vali", "soli"):
        uid = db.create_user(name, "x", False)
        users[name] = {"id": uid, "login": name, "is_admin": 0}
    qs = [{"text": f"Savol {i}", "options": ["A", "B", "C", "D"], "correct": i % 4} for i in range(20)]
    topic = db.create_topic("Mavzu", qs, shuffle=True, source_file=None, user_id=None)
    clock = FakeClock()
    yield SimpleNamespace(db=db, hub=DuelHub(db, clock), clock=clock, users=users, topic=topic)
    db.close()


def bot(env, name, **kw):
    kw.setdefault("silent", False)
    conn = Conn(env, env.users[name], **kw)
    env.hub.connect(env.users[name], conn)
    return conn


def join(env, name, conn):
    env.hub.handle(env.users[name]["id"], conn, "queue:join", {"topicId": env.topic})


def start(env, a_kw=None, b_kw=None):
    a = bot(env, "ali", **(a_kw or {}))
    b = bot(env, "vali", **(b_kw or {}))
    join(env, "ali", a)
    assert a.last("queue")["topicId"] == env.topic
    assert a.last("duel:start") is None
    join(env, "vali", b)
    assert a.last("duel:start")["opp"]["login"] == "vali"
    assert b.last("duel:start")["opp"]["login"] == "ali"
    return a, b


def test_both_get_same_15_questions_without_answers(env):
    a, b = start(env)
    env.clock.advance(config.COUNTDOWN + 0.01)
    qa, qb = a.last("duel:question"), b.last("duel:question")
    assert qa["total"] == 15 == config.DUEL_QUESTIONS
    assert qa["text"] == qb["text"] and qa["options"] == qb["options"]
    assert "correct" not in qa and "correctIndex" not in qa


def test_more_correct_answers_wins(env):
    a, b = start(env, b_kw={"correct": lambda i: i % 2 == 0})
    env.clock.advance(600)
    ra, rb = a.last("duel:end"), b.last("duel:end")
    assert ra["result"] == "win" and ra["reason"] == "score"
    assert rb["result"] == "lose"
    assert ra["me"]["correct"] == 15 and rb["me"]["correct"] == 8
    assert len(ra["review"]) == 15
    assert env.db.leaderboard()[0]["login"] == "ali"


def test_tie_is_broken_by_time(env):
    a, b = start(env, a_kw={"delay": 3.0}, b_kw={"delay": 1.5})
    env.clock.advance(600)
    ra, rb = a.last("duel:end"), b.last("duel:end")
    assert ra["me"]["correct"] == rb["me"]["correct"] == 15
    assert rb["result"] == "win" and rb["reason"] == "time"
    assert ra["result"] == "lose"
    assert rb["me"]["timeMs"] < ra["me"]["timeMs"]


def test_exact_tie_is_draw(env):
    a, b = start(env)
    env.clock.advance(600)
    assert a.last("duel:end")["result"] == b.last("duel:end")["result"] == "draw"


def test_silent_player_loses_after_30_seconds(env):
    assert afk_timeouts() == 2
    a, b = start(env, b_kw={"silent": True})
    env.clock.advance(config.COUNTDOWN + config.QUESTION_TIME + config.ANSWER_GRACE + 0.1)
    assert b.last("duel:feedback")["timedOut"] is True
    assert a.last("duel:end") is None  # bitta savolni o'tkazib yuborish hali mag'lubiyat emas
    env.clock.advance(config.FEEDBACK_DELAY + config.QUESTION_TIME + config.ANSWER_GRACE + 0.1)
    ra, rb = a.last("duel:end"), b.last("duel:end")
    assert ra["result"] == "win" and ra["reason"] == "afk"
    assert rb["result"] == "lose"


def test_answering_resets_afk_counter(env):
    # vali har ikkinchi savolga javob bermaydi — ketma-ket emas, shuning uchun mag'lub bo'lmaydi
    a, b = start(env, b_kw={"delay": 16.5})  # 16.5 s > 15 s: javob kechikadi = vaqt tugaydi
    b.silent = True
    env.clock.advance(config.COUNTDOWN + config.QUESTION_TIME + config.ANSWER_GRACE + 0.1)
    b.silent = False
    b.delay = 1.0
    env.clock.advance(600)
    rb = b.last("duel:end")
    assert rb["reason"] in ("score", "time")
    assert rb["me"]["correct"] == 14


def test_leaving_duel_gives_win_to_opponent(env):
    a, b = start(env)
    env.clock.advance(5)
    env.hub.handle(env.users["vali"]["id"], b, "duel:leave", {})
    assert a.last("duel:end")["result"] == "win"
    assert a.last("duel:end")["reason"] == "left"
    assert b.last("duel:end")["result"] == "lose"


def test_disconnect_then_reconnect_continues_duel(env):
    a, b = start(env)
    env.clock.advance(4)
    env.hub.disconnect(env.users["vali"]["id"], b)
    assert a.last("duel:opp")["connected"] is False
    env.clock.advance(config.DISCONNECT_GRACE - 2)
    b2 = bot(env, "vali")
    hello = b2.last("hello")
    assert hello["duel"] is not None and hello["duel"]["opp"]["login"] == "ali"
    assert a.last("duel:opp")["connected"] is True
    env.clock.advance(600)
    assert a.last("duel:end")["reason"] in ("score", "time", "draw")


def test_disconnect_without_return_loses(env):
    a, b = start(env)
    env.clock.advance(4)
    env.hub.disconnect(env.users["vali"]["id"], b)
    env.clock.advance(config.DISCONNECT_GRACE + 0.1)
    ra = a.last("duel:end")
    assert ra["result"] == "win" and ra["reason"] == "left"
    assert env.users["vali"]["id"] not in env.hub.user_duel


def test_finished_player_may_leave_and_gets_result_later(env):
    a, b = start(env, a_kw={"delay": 0.5}, b_kw={"delay": 5.0})
    env.clock.advance(40)  # ali tugatdi, vali hali davom etmoqda
    assert a.last("duel:done") is not None and b.last("duel:end") is None
    env.hub.disconnect(env.users["ali"]["id"], a)
    env.clock.advance(200)
    assert b.last("duel:end")["result"] == "lose"  # ikkalasi 15/15, ali tezroq
    a2 = Conn()
    env.hub.connect(env.users["ali"], a2)
    assert a2.last("duel:end")["result"] == "win"


def test_invite_link_creates_duel_with_host(env):
    a = bot(env, "ali")
    s = bot(env, "soli")
    v = bot(env, "vali")
    join(env, "ali", a)
    code = a.last("queue")["code"]
    assert code and env.hub.invite_info(code)["valid"] is True
    env.hub.handle(env.users["vali"]["id"], v, "invite:accept", {"code": code.lower()})
    assert v.last("duel:start")["opp"]["login"] == "ali"
    assert s.last("duel:start") is None
    assert env.hub.invite_info(code)["reason"] == "busy"


def test_invite_errors(env):
    a = bot(env, "ali")
    v = bot(env, "vali")
    env.hub.handle(env.users["vali"]["id"], v, "invite:accept", {"code": "NOPE1234"})
    assert "noto'g'ri" in v.last("error")["message"]
    join(env, "ali", a)
    code = a.last("queue")["code"]
    env.hub.handle(env.users["ali"]["id"], a, "invite:accept", {"code": code})
    assert "o'zingizning" in a.last("error")["message"]
    env.hub.handle(env.users["ali"]["id"], a, "queue:leave", {})
    env.hub.handle(env.users["vali"]["id"], v, "invite:accept", {"code": code})
    assert "kutmayapti" in v.last("error")["message"]


def test_invitee_waits_for_offline_host(env):
    a = bot(env, "ali")
    v = bot(env, "vali")
    join(env, "ali", a)
    code = a.last("queue")["code"]
    env.hub.disconnect(env.users["ali"]["id"], a)  # masalan, Telegram'ga havola yuborish uchun chiqdi
    env.hub.handle(env.users["vali"]["id"], v, "invite:accept", {"code": code})
    assert v.last("queue")["inviteFor"]["online"] is False
    assert v.last("duel:start") is None
    a2 = bot(env, "ali")
    assert a2.last("hello")["queue"]["code"] == code
    assert v.last("duel:start")["opp"]["login"] == "ali"
    assert a2.last("duel:start")["opp"]["login"] == "vali"


def test_same_user_is_not_matched_with_self(env):
    a1, a2 = bot(env, "ali"), bot(env, "ali")
    join(env, "ali", a1)
    join(env, "ali", a2)
    assert not env.hub.duels


def test_waiting_survives_short_disconnect_but_expires(env):
    a = bot(env, "ali")
    join(env, "ali", a)
    env.hub.disconnect(env.users["ali"]["id"], a)
    env.clock.advance(config.WAITING_TTL - 5)
    assert env.users["ali"]["id"] in env.hub.waiting
    env.clock.advance(10)
    assert env.users["ali"]["id"] not in env.hub.waiting


def test_presence_reports_online_users_and_waiting(env):
    a = bot(env, "ali")
    bot(env, "vali")
    join(env, "ali", a)
    env.clock.advance(1)
    p = a.last("presence")
    assert p["online"] == 2
    assert p["waiting"] == {str(env.topic): 1}
    assert {u["login"]: u["status"] for u in p["users"]} == {"ali": "waiting", "vali": "idle"}
