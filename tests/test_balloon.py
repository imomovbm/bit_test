"""Balloon Pop: o'yin qoidalari (dvigatel) va HTTP API testlari."""
import asyncio
import copy
import random

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import balloon
from app.balloon import GameError
from app.server import create_app


class FakeSource:
    """Savollar manbai: har bir savolda to'g'ri javob — 1-variant (indeks 0)."""

    def __init__(self, n=5):
        self.questions = {i: {"id": i, "text": f"Savol {i}?", "options": ["To'g'ri", "Xato", "Xato 2"], "correct": 0} for i in range(1, n + 1)}

    def ids(self):
        return list(self.questions)

    def load(self, qid):
        return self.questions.get(qid)


class FixedDice(random.Random):
    """Zar navbat bilan berilgan qiymatlarni qaytaradi (qolgan tasodifiy amallar — oddiy Random)."""

    def __init__(self, values):
        super().__init__(7)
        self.values = list(values)

    def randint(self, a, b):
        return self.values.pop(0)


TEAMS = [{"name": "Qizil jamoa", "color": "red"}, {"name": "Ko'k jamoa", "color": "blue"}]


def make(balloons=10, answer_time=30, dice=(), n=5):
    state = balloon.new_game(topic_id=1, topic_name="Mavzu", teams=TEAMS, balloons=balloons, answer_time=answer_time, now_ms=0)
    env = {"source": FakeSource(n), "rng": FixedDice(dice), "now": 1000}

    def act(**action):
        return balloon.apply(state, action, source=env["source"], rng=env["rng"], now_ms=env["now"])

    return state, env, act


def test_clean_settings():
    s = balloon.clean_settings({"teams": [{"name": "  A   jamoa ", "color": "red"}, {"name": "B", "color": "green"}], "balloons": 20, "answerTime": 0})
    assert s == {"teams": [{"name": "A jamoa", "color": "red"}, {"name": "B", "color": "green"}], "balloons": 20, "answer_time": 0}
    bad = [
        {"teams": [TEAMS[0]], "balloons": 20},
        {"teams": [TEAMS[0], {"name": "", "color": "blue"}], "balloons": 20},
        {"teams": [TEAMS[0], {"name": "X", "color": "red"}], "balloons": 20},
        {"teams": [TEAMS[0], {"name": "qizil JAMOA", "color": "blue"}], "balloons": 20},
        {"teams": [TEAMS[0], {"name": "X", "color": "black"}], "balloons": 20},
        {"teams": TEAMS, "balloons": 2},
        {"teams": TEAMS, "balloons": "ko'p"},
        {"teams": TEAMS, "balloons": 20, "answerTime": 3},
        {"teams": [TEAMS[0], {"name": "Y" * 31, "color": "blue"}], "balloons": 20},
    ]
    for data in bad:
        with pytest.raises(GameError):
            balloon.clean_settings(data)


def test_round_correct_answer_gives_both_teams_a_roll():
    state, env, act = make(balloons=10, dice=[4, 2])
    assert state["phase"] == "rps"
    act(type="rps", winner=0)                      # qizillar yutdi -> ko'klar savolga javob beradi
    assert state["phase"] == "question" and state["question"]["team"] == 1
    pub = balloon.public(state, 2000)
    assert "correct" not in pub["question"] and "deck" not in pub
    assert pub["question"]["remainingMs"] == 30000 - 1000
    ev = act(type="answer", choice=0)
    assert ev["correct"] is True and ev["correctIndex"] == 0
    assert state["teams"][1]["asked"] == 1 and state["teams"][1]["correct"] == 1
    assert state["phase"] == "roll" and state["turn"] == {"team": 0, "bonus": False}
    assert balloon.public(state, 2000)["question"]["correct"] == 0

    ev = act(type="roll")                          # qizillar birinchi tashlaydi: 4
    assert ev == {"type": "roll", "team": 0, "value": 4, "pending": 4}
    assert state["phase"] == "pop"
    with pytest.raises(GameError):
        act(type="roll")                           # ikki marta tashlab bo'lmaydi
    act(type="pop", balloons=[0])
    act(type="pop", balloons=[5, 7])
    with pytest.raises(GameError):
        act(type="pop", balloons=[5])              # allaqachon portlagan
    with pytest.raises(GameError):
        act(type="pop", balloons=[1, 2])           # faqat 1 ta qolgan
    act(type="pop", balloons=[9])
    assert state["teams"][1]["popped"] == [0, 5, 7, 9] and balloon.left(state, 1) == 6
    # to'g'ri javob bergan ko'klar ham tashlaydi (bonus)
    assert state["phase"] == "roll" and state["turn"] == {"team": 1, "bonus": True}
    act(type="roll")
    assert state["pending"] == 2
    ev = act(type="pop", auto=True)
    assert len(ev["popped"]) == 2 and balloon.left(state, 0) == 8
    # keyingi raund
    assert state["phase"] == "rps" and state["round"] == 2
    assert state["question"] is None and state["answer"] is None and state["dice"] is None
    assert [e["t"] for e in state["log"]] == ["rps", "answer", "roll", "roll"]
    assert state["rev"] == 8  # muvaffaqiyatli amallar soni (xato amallar hisoblanmaydi)


def test_wrong_answer_no_bonus_and_timeouts():
    state, env, act = make(balloons=10, answer_time=20, dice=[3, 5])
    act(type="rps", winner=1)
    assert state["question"]["team"] == 0
    act(type="answer", choice=2)
    assert state["answer"]["correct"] is False and state["teams"][0]["correct"] == 0
    act(type="roll")
    act(type="pop", auto=True)
    assert state["phase"] == "rps" and state["round"] == 2 and balloon.left(state, 0) == 7

    # vaqt tugadi (mijoz yuborgan)
    act(type="rps", winner=1)
    ev = act(type="answer", choice=None, timeout=True)
    assert ev["timedOut"] is True and ev["correct"] is False
    act(type="roll")
    act(type="pop", auto=True)
    assert balloon.left(state, 0) == 2

    # vaqt tugaganidan keyin kelgan javob to'g'ri bo'lsa ham hisoblanmaydi
    state2, env2, act2 = make(answer_time=20, dice=[1])
    act2(type="rps", winner=0)
    env2["now"] += 20_000 + balloon.ANSWER_GRACE_MS + 1
    ev = act2(type="answer", choice=0)
    assert ev["correct"] is False and ev["timedOut"] is True


def test_game_ends_when_balloons_run_out():
    state, env, act = make(balloons=5, dice=[6])
    act(type="rps", winner=0)
    act(type="answer", choice=0)                   # to'g'ri, lekin qizillar avval tashlaydi
    ev = act(type="roll")
    assert ev["value"] == 6 and state["pending"] == 5  # qolgan sharlardan ko'p emas
    ev = act(type="pop", balloons=[0, 1, 2, 3, 4])
    assert ev["finished"] is True
    assert state["phase"] == "finished" and state["winner"] == 0 and state["endReason"] == "popped"
    with pytest.raises(GameError):
        act(type="rps", winner=0)
    assert balloon.summary(state)["teams"][1]["left"] == 0


def test_back_skip_and_end():
    state, env, act = make(balloons=10, dice=[2], n=3)
    act(type="rps", winner=0)
    first = state["question"]["id"]
    act(type="back")                               # yutgan jamoa xato belgilangan edi
    assert state["phase"] == "rps" and state["log"] == [] and state["question"] is None
    act(type="rps", winner=1)
    assert state["question"]["id"] == first and state["question"]["team"] == 0
    act(type="skip")
    second = state["question"]["id"]
    assert second != first and state["question"]["team"] == 0
    with pytest.raises(GameError):
        act(type="answer", choice=7)
    with pytest.raises(GameError):
        act(type="dance")
    act(type="answer", choice=1)
    act(type="roll")
    act(type="pop", auto=True)                     # ko'klar: 10 - 0, qizillar: 10 - 2
    ev = act(type="end")
    assert ev["winner"] == 1 and state["endReason"] == "stopped" and state["phase"] == "finished"

    tie, _, act3 = make()
    act3(type="end")
    assert tie["winner"] is None


def test_question_deck_cycles_without_immediate_repeat():
    state, env, act = make(balloons=40, dice=[1] * 100, n=3)
    seen = []
    for _ in range(9):
        act(type="rps", winner=0)
        seen.append(state["question"]["id"])
        act(type="answer", choice=1)
        act(type="roll")
        act(type="pop", auto=True)
    assert all(a != b for a, b in zip(seen, seen[1:]))
    for i in range(0, 9, 3):
        assert sorted(seen[i:i + 3]) == [1, 2, 3]  # har bir aylanishda barcha savollar bir martadan

    empty, env2, act2 = make()
    env2["source"] = FakeSource(0)
    with pytest.raises(GameError):
        act2(type="rps", winner=0)


def test_failed_action_on_copy_keeps_state():
    state, env, act = make(n=0)
    before = copy.deepcopy(state)
    env["source"] = FakeSource(0)
    work = copy.deepcopy(state)
    with pytest.raises(GameError):
        balloon.apply(work, {"type": "rps", "winner": 0}, source=env["source"], rng=env["rng"], now_ms=5)
    assert state == before


# ===================================================================== API
SAMPLE = "\n++++\n".join(f"Savol {i}?\n====\n#Toʻgʻri {i}\n====\nNotoʻgʻri {i}\n====\nBoshqa {i}" for i in range(8))


def test_balloon_api(tmp_path):
    asyncio.run(_api_flow(tmp_path))


async def _api_flow(tmp_path):
    app = create_app(db_path=tmp_path / "bp.db")
    server = TestServer(app)
    await server.start_server()
    teacher, other = TestClient(server), TestClient(server)
    try:
        for c in (teacher, other):
            await c.start_server()
        assert (await teacher.get("/api/balloon/games")).status == 401
        await teacher.post("/api/auth/register", json={"login": "ustoz", "password": "1234"})
        await other.post("/api/auth/register", json={"login": "begona", "password": "1234"})
        r = await teacher.post("/api/admin/topics", json={"name": "Sinov", "content": SAMPLE, "shuffle": True})
        topic = (await r.json())["topic"]

        body = {"topicId": topic["id"], "teams": TEAMS, "balloons": 10, "answerTime": 30}
        r = await teacher.post("/api/balloon/games", json={**body, "topicId": 999})
        assert r.status == 404
        r = await teacher.post("/api/balloon/games", json={**body, "teams": TEAMS[:1]})
        assert r.status == 400
        r = await teacher.post("/api/balloon/games", json=body)
        assert r.status == 201
        game = (await r.json())["game"]
        gid = game["id"]
        assert game["phase"] == "rps" and game["teams"][0]["left"] == 10 and "deck" not in game

        # boshqa foydalanuvchi o'yinni ko'ra olmaydi
        assert (await other.get(f"/api/balloon/games/{gid}")).status == 404
        assert (await other.post(f"/api/balloon/games/{gid}/action", json={"type": "end"})).status == 404

        async def act(**action):
            r = await teacher.post(f"/api/balloon/games/{gid}/action", json=action)
            return r.status, await r.json()

        status, data = await act(type="rps", winner=0, rev=game["rev"])
        assert status == 200 and data["event"]["type"] == "rps"
        q = data["game"]["question"]
        assert q["team"] == 1 and "correct" not in q and 29_000 <= q["remainingMs"] <= 30_000
        status, data = await act(type="rps", winner=0, rev=game["rev"])  # eskirgan rev
        assert status == 409 and data["game"]["phase"] == "question"
        status, data = await act(type="roll")                             # hali savol bosqichi
        assert status == 409 and data["game"]["phase"] == "question"

        correct = next(i for i, o in enumerate(q["options"]) if o.startswith("Toʻgʻri"))
        status, data = await act(type="answer", choice=correct)
        assert data["event"]["correct"] is True and data["game"]["question"]["correct"] == correct
        status, data = await act(type="roll")
        value = data["event"]["value"]
        assert 1 <= value <= 6 and data["game"]["pending"] == value
        status, data = await act(type="pop", balloons=[0])
        assert data["game"]["teams"][1]["popped"] == [0]
        if value > 1:
            status, data = await act(type="pop", auto=True)
        assert data["game"]["teams"][1]["left"] == 10 - value
        assert data["game"]["phase"] == "roll" and data["game"]["turn"] == {"team": 1, "bonus": True}

        # sahifa yangilansa ham holat saqlanib qoladi
        r = await teacher.get(f"/api/balloon/games/{gid}")
        assert (await r.json())["game"]["turn"]["bonus"] is True

        status, data = await act(type="end")
        assert data["game"]["phase"] == "finished" and data["game"]["winner"] == 0
        r = await teacher.get("/api/balloon/games")
        games = (await r.json())["games"]
        assert len(games) == 1 and games[0]["phase"] == "finished" and games[0]["teams"][1]["left"] == 10 - value

        # mavzu o'chirilsa, o'yin savol ololmaydi, lekin uni yakunlash mumkin
        r = await teacher.post("/api/balloon/games", json=body)
        gid = (await r.json())["game"]["id"]
        assert (await teacher.delete(f"/api/admin/topics/{topic['id']}")).status == 200
        status, data = await act(type="rps", winner=1)
        assert status == 409 and data["game"]["phase"] == "rps"
        status, data = await act(type="end")
        assert status == 200 and data["game"]["winner"] is None

        assert (await other.delete(f"/api/balloon/games/{gid}")).status == 404
        assert (await teacher.delete(f"/api/balloon/games/{gid}")).status == 200
        r = await teacher.get("/api/balloon/games")
        assert len((await r.json())["games"]) == 1
    finally:
        await teacher.close()
        await other.close()
        await server.close()
