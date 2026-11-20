"""Balloon Pop — jamoaviy sinf o'yini.

O'yin bitta ekranda (proyektor, interaktiv doska yoki kompyuter) o'tkaziladi va uni o'qituvchi
boshqaradi. Har bir jamoaning odamchasi o'z rangidagi sharlarda akulalar ustida osilib turadi:

  1. Jamoalar sinfda tosh-qaychi-qog'oz o'ynaydi, o'qituvchi yutgan jamoani belgilaydi.
  2. Yutqazgan jamoa tanlangan mavzudan bitta savolga javob beradi.
  3. Yutgan jamoa birinchi bo'lib zar tashlaydi va raqibning tushgan son miqdoricha sharini portlatadi.
  4. Yutqazgan jamoa savolga to'g'ri javob bergan bo'lsa, u ham zar tashlaydi.
  5. Sharlari tugagan jamoa suvga tushadi — akula uni yeb qo'yadi, raqib jamoa g'olib bo'ladi.

O'yin holati oddiy JSON-lug'at bo'lib, bazada saqlanadi (sahifa yangilansa ham o'yin davom etadi).
Bu modul faqat qoidalarni bajaradi: baza va HTTP bilan ishlamaydi, shuning uchun uni oson testlash mumkin.
"""
from __future__ import annotations

from typing import Protocol

COLORS = ("red", "blue", "green", "orange", "purple", "pink", "teal", "yellow")
MIN_BALLOONS, MAX_BALLOONS = 5, 50
MAX_ANSWER_TIME = 600          # soniya; 0 — vaqt cheklanmagan
MAX_TEAM_NAME = 30
DICE_SIDES = 6
ANSWER_GRACE_MS = 3000         # tarmoq kechikishi uchun qo'shimcha vaqt
DECK_LIMIT = 300               # holatda saqlanadigan savollar navbatining eng katta uzunligi
MAX_LOG = 400

PHASES = ("rps", "question", "roll", "pop", "finished")


class GameError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato. status=409 — amal o'yinning hozirgi bosqichiga mos emas."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class QuestionSource(Protocol):
    def ids(self) -> list[int]:
        """Mavzudagi barcha savollar identifikatorlari."""

    def load(self, qid: int) -> dict | None:
        """Savol: {"id", "text", "options", "correct"} (variantlar kerak bo'lsa aralashtirilgan) yoki None."""


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


# ================================================================ yaratish
def clean_settings(data: dict) -> dict:
    """Yangi o'yin sozlamalarini tekshiradi: ikki jamoa (nom, rang), sharlar soni, javob vaqti."""
    raw_teams = data.get("teams")
    if not isinstance(raw_teams, list) or len(raw_teams) != 2:
        raise GameError("O'yinda ikkita jamoa bo'lishi kerak")
    teams = []
    for i, t in enumerate(raw_teams, 1):
        if not isinstance(t, dict):
            raise GameError("Jamoa ma'lumotlari noto'g'ri")
        name = " ".join(str(t.get("name") or "").split())
        if not name:
            raise GameError(f"{i}-jamoa nomini kiriting")
        if len(name) > MAX_TEAM_NAME:
            raise GameError(f"Jamoa nomi {MAX_TEAM_NAME} belgidan oshmasin")
        color = t.get("color")
        if color not in COLORS:
            raise GameError("Jamoa rangi noto'g'ri tanlangan")
        teams.append({"name": name, "color": color})
    if teams[0]["color"] == teams[1]["color"]:
        raise GameError("Jamoalarga turli ranglar tanlang")
    if teams[0]["name"].casefold() == teams[1]["name"].casefold():
        raise GameError("Jamoalar nomi bir xil bo'lmasin")
    balloons = _int(data.get("balloons"))
    if balloons is None or not MIN_BALLOONS <= balloons <= MAX_BALLOONS:
        raise GameError(f"Sharlar soni {MIN_BALLOONS} dan {MAX_BALLOONS} gacha bo'lishi kerak")
    answer_time = _int(data.get("answerTime", 30))
    if answer_time is None or not (answer_time == 0 or 5 <= answer_time <= MAX_ANSWER_TIME):
        raise GameError("Javob vaqti noto'g'ri")
    return {"teams": teams, "balloons": balloons, "answer_time": answer_time}


def new_game(*, topic_id: int, topic_name: str, teams: list[dict], balloons: int, answer_time: int, now_ms: int) -> dict:
    return {
        "v": 1,
        "rev": 0,
        "topicId": topic_id,
        "topicName": topic_name,
        "balloons": balloons,
        "answerTime": answer_time,
        "teams": [
            {"name": t["name"], "color": t["color"], "popped": [], "asked": 0, "correct": 0, "rolls": 0, "rolled": 0}
            for t in teams
        ],
        "round": 1,
        "phase": "rps",
        "rpsWinner": None,   # tosh-qaychi-qog'ozda yutgan jamoa (0 yoki 1)
        "question": None,    # yutqazgan jamoaga berilgan savol
        "answer": None,      # shu raunddagi javob natijasi
        "turn": None,        # zar tashlayotgan jamoa: {"team", "bonus"}
        "dice": None,        # oxirgi tashlangan zar: {"team", "value", "bonus"}
        "pending": 0,        # hali portlatilishi kerak bo'lgan sharlar
        "deck": [],
        "deckPos": 0,
        "winner": None,
        "endReason": None,   # popped (sharlari tugadi) | stopped (o'qituvchi to'xtatdi)
        "log": [],
        "createdAt": now_ms,
        "updatedAt": now_ms,
        "finishedAt": None,
    }


# ================================================================== holat
def left(state: dict, team: int) -> int:
    return state["balloons"] - len(state["teams"][team]["popped"])


def public(state: dict, now_ms: int) -> dict:
    """Mijozga yuboriladigan holat: savollar navbati va javob berilmagan savolning to'g'ri javobi yashiriladi."""
    q = state["question"]
    question = None
    if q:
        question = {"id": q["id"], "team": q["team"], "text": q["text"], "options": q["options"]}
        if state["phase"] == "question":
            limit = state["answerTime"] * 1000
            question["remainingMs"] = max(0, limit - (now_ms - q["startedAt"])) if limit else None
        else:
            question["correct"] = q["correct"]
    return {
        "rev": state["rev"],
        "topicId": state["topicId"],
        "topicName": state["topicName"],
        "balloons": state["balloons"],
        "answerTime": state["answerTime"],
        "teams": [
            {
                "name": t["name"],
                "color": t["color"],
                "popped": list(t["popped"]),
                "left": left(state, i),
                "asked": t["asked"],
                "correct": t["correct"],
                "rolls": t["rolls"],
                "rolled": t["rolled"],
            }
            for i, t in enumerate(state["teams"])
        ],
        "round": state["round"],
        "phase": state["phase"],
        "rpsWinner": state["rpsWinner"],
        "question": question,
        "answer": state["answer"],
        "turn": state["turn"],
        "dice": state["dice"],
        "pending": state["pending"],
        "winner": state["winner"],
        "endReason": state["endReason"],
        "log": state["log"],
        "createdAt": state["createdAt"],
        "updatedAt": state["updatedAt"],
        "finishedAt": state["finishedAt"],
    }


def summary(state: dict) -> dict:
    """O'yinlar ro'yxati uchun qisqa ma'lumot."""
    return {
        "topicId": state["topicId"],
        "topicName": state["topicName"],
        "balloons": state["balloons"],
        "answerTime": state["answerTime"],
        "teams": [
            {"name": t["name"], "color": t["color"], "left": left(state, i), "asked": t["asked"], "correct": t["correct"]}
            for i, t in enumerate(state["teams"])
        ],
        "round": state["round"],
        "phase": state["phase"],
        "winner": state["winner"],
        "endReason": state["endReason"],
        "createdAt": state["createdAt"],
        "updatedAt": state["updatedAt"],
        "finishedAt": state["finishedAt"],
    }


# ================================================================= amallar
def apply(state: dict, action: dict, *, source: QuestionSource, rng, now_ms: int) -> dict:
    """Amalni bajaradi (holat joyida o'zgaradi) va mijoz animatsiyasi uchun hodisani qaytaradi.

    Xato bo'lsa GameError ko'tariladi; bu holda holat qisman o'zgargan bo'lishi mumkin,
    shuning uchun chaqiruvchi amalni holatning nusxasida bajarishi kerak.
    """
    if state["phase"] == "finished":
        raise GameError("O'yin allaqachon tugagan", 409)
    handler = _ACTIONS.get(action.get("type"))
    if handler is None:
        raise GameError("Noma'lum amal")
    event = handler(state, action, source, rng, now_ms)
    state["rev"] += 1
    state["updatedAt"] = now_ms
    return event


def _expect(state: dict, phase: str) -> None:
    if state["phase"] != phase:
        raise GameError("Bu amal o'yinning hozirgi bosqichida mumkin emas", 409)


def _team_index(value) -> int:
    i = _int(value)
    if i not in (0, 1):
        raise GameError("Jamoa noto'g'ri tanlangan")
    return i


def _log(state: dict, kind: str, **data) -> None:
    state["log"].append({"r": state["round"], "t": kind, **data})
    if len(state["log"]) > MAX_LOG:
        del state["log"][: len(state["log"]) - MAX_LOG]


def _draw(state: dict, source: QuestionSource, rng) -> dict:
    """Navbatdagi savolni oladi; navbat tugasa, mavzudagi savollar qayta aralashtiriladi."""
    for _ in range(3):
        while state["deckPos"] < len(state["deck"]):
            qid = state["deck"][state["deckPos"]]
            state["deckPos"] += 1
            q = source.load(qid)
            if q:
                return q
        ids = list(source.ids())
        if not ids:
            break
        last = state["deck"][-1] if state["deck"] else None
        rng.shuffle(ids)
        ids = ids[:DECK_LIMIT]
        if len(ids) > 1 and ids[0] == last:  # oldingi savol darhol takrorlanmasin
            ids[0], ids[-1] = ids[-1], ids[0]
        state["deck"] = ids
        state["deckPos"] = 0
    raise GameError("Bu mavzuda savollar topilmadi (mavzu o'chirilgan bo'lishi mumkin). O'yinni yakunlang", 409)


def _ask(state: dict, team: int, source: QuestionSource, rng, now_ms: int) -> None:
    q = _draw(state, source, rng)
    state["question"] = {
        "id": q["id"],
        "text": q["text"],
        "options": list(q["options"]),
        "correct": int(q["correct"]),
        "team": team,
        "startedAt": now_ms,
    }


def _rps(state, action, source, rng, now_ms) -> dict:
    """Tosh-qaychi-qog'oz natijasi: yutqazgan jamoaga savol beriladi."""
    _expect(state, "rps")
    winner = _team_index(action.get("winner"))
    _ask(state, 1 - winner, source, rng, now_ms)
    state["rpsWinner"] = winner
    state["answer"] = None
    state["phase"] = "question"
    _log(state, "rps", team=winner)
    return {"type": "rps", "team": winner}


def _back(state, action, source, rng, now_ms) -> dict:
    """Tosh-qaychi-qog'oz natijasi xato belgilangan bo'lsa — savolni qaytarib, avvalgi bosqichga o'tish."""
    _expect(state, "question")
    if state["deckPos"] > 0:
        state["deckPos"] -= 1  # shu savol keyingi safar yana beriladi
    state["question"] = None
    state["rpsWinner"] = None
    state["phase"] = "rps"
    while state["log"] and state["log"][-1]["r"] == state["round"]:
        state["log"].pop()
    return {"type": "back"}


def _skip(state, action, source, rng, now_ms) -> dict:
    """Savolni boshqasiga almashtirish (masalan, savol tushunarsiz bo'lsa)."""
    _expect(state, "question")
    team = state["question"]["team"]
    _ask(state, team, source, rng, now_ms)
    _log(state, "skip", team=team)
    return {"type": "skip"}


def _answer(state, action, source, rng, now_ms) -> dict:
    _expect(state, "question")
    q = state["question"]
    choice = action.get("choice")
    if choice is not None:
        choice = _int(choice)
        if choice is None or not 0 <= choice < len(q["options"]):
            raise GameError("Javob varianti noto'g'ri")
    limit = state["answerTime"] * 1000
    elapsed = max(0, now_ms - q["startedAt"])
    timed_out = choice is None and bool(action.get("timeout")) and limit > 0
    if limit and elapsed > limit + ANSWER_GRACE_MS:
        choice, timed_out = None, True  # vaqt allaqachon tugagan edi
    correct = choice is not None and choice == q["correct"]
    team = state["teams"][q["team"]]
    team["asked"] += 1
    team["correct"] += int(correct)
    state["answer"] = {"team": q["team"], "choice": choice, "correct": correct, "timedOut": timed_out, "ms": elapsed}
    state["turn"] = {"team": state["rpsWinner"], "bonus": False}
    state["phase"] = "roll"
    _log(state, "answer", team=q["team"], ok=correct, timeout=timed_out, skipped=choice is None and not timed_out)
    return {"type": "answer", "team": q["team"], "choice": choice, "correct": correct, "correctIndex": q["correct"], "timedOut": timed_out}


def _roll(state, action, source, rng, now_ms) -> dict:
    _expect(state, "roll")
    team = state["turn"]["team"]
    bonus = state["turn"]["bonus"]
    target = 1 - team
    value = rng.randint(1, DICE_SIDES)
    state["dice"] = {"team": team, "value": value, "bonus": bonus}
    state["pending"] = min(value, left(state, target))
    state["teams"][team]["rolls"] += 1
    state["teams"][team]["rolled"] += value
    state["phase"] = "pop"
    _log(state, "roll", team=team, value=value, popped=state["pending"], bonus=bonus)
    return {"type": "roll", "team": team, "value": value, "pending": state["pending"]}


def _pop(state, action, source, rng, now_ms) -> dict:
    _expect(state, "pop")
    team = state["turn"]["team"]
    target = 1 - team
    popped = state["teams"][target]["popped"]
    gone = set(popped)
    alive = [i for i in range(state["balloons"]) if i not in gone]
    if action.get("auto"):
        picks = rng.sample(alive, min(state["pending"], len(alive)))
    else:
        raw = action.get("balloons")
        if not isinstance(raw, list) or not raw:
            raise GameError("Portlatiladigan sharni tanlang")
        picks = []
        for value in raw:
            i = _int(value)
            if i is None or i in gone or not 0 <= i < state["balloons"] or i in picks:
                raise GameError("Bu shar allaqachon portlagan", 409)
            picks.append(i)
        if len(picks) > state["pending"]:
            raise GameError(f"Faqat {state['pending']} ta shar portlatish mumkin", 409)
    popped.extend(picks)
    state["pending"] -= len(picks)
    event = {"type": "pop", "team": team, "target": target, "popped": picks, "finished": False}
    if left(state, target) == 0:
        _finish(state, team, "popped", now_ms)
        event["finished"] = True
    elif state["pending"] == 0:
        _after_turn(state)
    return event


def _after_turn(state: dict) -> None:
    ans = state["answer"]
    if not state["turn"]["bonus"] and ans and ans["correct"]:
        # savolga to'g'ri javob bergan jamoa ham zar tashlaydi
        state["turn"] = {"team": ans["team"], "bonus": True}
        state["phase"] = "roll"
        return
    state["round"] += 1
    state["phase"] = "rps"
    state["rpsWinner"] = None
    state["question"] = None
    state["answer"] = None
    state["turn"] = None
    state["dice"] = None
    state["pending"] = 0


def _end(state, action, source, rng, now_ms) -> dict:
    """O'yinni muddatidan oldin yakunlash: ko'proq shari qolgan jamoa g'olib (teng bo'lsa — durang)."""
    a, b = left(state, 0), left(state, 1)
    winner = None if a == b else (0 if a > b else 1)
    _finish(state, winner, "stopped", now_ms)
    return {"type": "end", "winner": winner}


def _finish(state: dict, winner: int | None, reason: str, now_ms: int) -> None:
    state["phase"] = "finished"
    state["winner"] = winner
    state["endReason"] = reason
    state["finishedAt"] = now_ms
    state["pending"] = 0
    _log(state, "end", team=winner, reason=reason)


_ACTIONS = {
    "rps": _rps,
    "back": _back,
    "skip": _skip,
    "answer": _answer,
    "roll": _roll,
    "pop": _pop,
    "end": _end,
}
