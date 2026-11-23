"""Octagon: o'rin o'zgarishi (har savoldan keyin) va yakuniy podium ochilishi — dvigatel darajasida (soxta soat).

Tekshiriladi: o'qituvchi va o'quvchi ekranlariga boradigan ma'lumotlar (strelkalar, «YANGI», eng katta sakrash, "N ball
orqada"), ochilish tartibi va vaqtlari, 0/1/2/3/ko'p o'yinchi, tengliklar, muddatidan oldin tugatish, ochilish paytida
qo'shilish va qayta ulanish, o'qituvchi qayta ulanishi, takroriy «Keyingi»/«O'tkazib yuborish», qayta ishga tushish va
eng muhimi — hali e'lon qilinmagan o'rin hech qaysi xabarda yo'qligi.
"""
import json

import pytest

from app import config, octagon
from app import octagon_flow as flow
from app.octagon_scoring import calculate_score
from test_octagon import PV, FakeConn, act, answer, finish_reveal, join, make_game, octagon_env, ph, to_question


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield from octagon_env(tmp_path, monkeypatch)


def play(env, game, plan):
    """Savolni o'ynash: plan — [(ulanish, variant, soniya)], savol ochilgan paytdan; qolganlar javob bermaydi.
    Hamma javob bermasa — o'qituvchi savolni yopadi («O'tkazib yuborish»)."""
    to_question(env, game)
    t = 0.0
    for conn, option, at in sorted(plan, key=lambda x: x[2]):
        env.clock.advance(at - t)
        t = at
        answer(env, conn, game.index, option)
    if game.phase == flow.ACTIVE:
        act(env, game, "skip")
    assert game.phase == flow.RESULT


def ok(game):
    return game.questions[game.index]["correct"] if game.phase in (flow.ACTIVE, flow.RESULT) else None


def correct_option(i):
    return i % 4  # tests/test_octagon.QUESTIONS: aralashtirilmagan, to'g'ri javob — i % 4


def host_of(env, game):
    h = FakeConn()
    env.hub.handle(h, "host", {"v": PV, "pin": game.pin}, env.owner)
    return h


def by_nick(rows):
    return {r["nick"]: r for r in rows}


# ======================================================= o'rin o'zgarishi
def test_rank_changes_after_each_question_on_teacher_and_student_screens(env):
    game = make_game(env, questionCount=3)
    ali, vali, olim, bek, dana = (join(env, game, n) for n in ("Ali", "Vali", "Olim", "Bek", "Dana"))
    host = host_of(env, game)
    act(env, game, "start")
    # 1-savol (to'g'ri — 0): oldingi reyting yo'q — hech kimda strelka yo'q
    play(env, game, [(ali, 0, 0.4), (dana, 0, 2.0), (olim, 2, 3.0), (vali, 0, 5.0)])
    for c in (ali, vali, olim, bek, dana):
        s = c.last("s")
        assert "dk" not in s and "nw" not in s and s["pl"] == 5
    assert [ali.last("s")["k"], dana.last("s")["k"], vali.last("s")["k"], olim.last("s")["k"], bek.last("s")["k"]] == [1, 2, 3, 4, 5]
    act(env, game, "next")
    board = host.last("h")
    assert [r["nick"] for r in board["leaderboard"]] == ["Ali", "Dana", "Vali", "Olim", "Bek"]
    assert all(r["d"] is None and r["new"] is False for r in board["leaderboard"]) and board["jump"] is None
    assert [r["gained"] for r in board["leaderboard"]] == [1000, 950, 875, 0, 0]
    act(env, game, "next")
    # 2-savol (to'g'ri — 1): Bek oxirgidan birinchiga, Ali javob bermaydi
    play(env, game, [(bek, 1, 0.3), (olim, 1, 1.0), (dana, 0, 1.0), (vali, 3, 2.0)])
    expected = {"Bek": (1, 4), "Ali": (2, -1), "Olim": (3, 1), "Dana": (4, -2), "Vali": (5, -2)}
    for nick, c in (("Ali", ali), ("Vali", vali), ("Olim", olim), ("Bek", bek), ("Dana", dana)):
        s = c.last("s")
        assert (s["k"], s["dk"]) == expected[nick], nick
    # "N ball orqada": yuqoridagi o'yinchi bitta savolda quvib yetiladigan masofada bo'lsa; ball teng bo'lsa — yo'q
    assert "bh" not in bek.last("s") and "bh" not in ali.last("s")    # Ali — Bek bilan teng ball (vaqt hal qildi)
    assert olim.last("s")["bh"] == [25, "Ali"] and dana.last("s")["bh"] == [25, "Olim"] and vali.last("s")["bh"] == [75, "Dana"]
    act(env, game, "next")
    board = host.last("h")
    rows = board["leaderboard"]
    assert [(r["nick"], r["rank"], r["d"], r["gained"]) for r in rows] == [
        ("Bek", 1, 4, 1000), ("Ali", 2, -1, 0), ("Olim", 3, 1, 975), ("Dana", 4, -2, 0), ("Vali", 5, -2, 0)]
    assert board["jump"] == {"id": bek.last("w")["id"], "nick": "Bek", "av": 0, "d": 4, "rank": 1}


def test_unchanged_rank_is_sent_as_zero(env):
    game = make_game(env, questionCount=3)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 0, 5)])
    act(env, game, "next")
    act(env, game, "next")
    play(env, game, [(a, 1, 0.4), (b, 1, 5)])
    assert (a.last("s")["k"], a.last("s")["dk"]) == (1, 0) and (b.last("s")["k"], b.last("s")["dk"]) == (2, 0)
    act(env, game, "next")
    assert [r["d"] for r in env.hub.host_state(game)["leaderboard"]] == [0, 0]


def test_late_joiner_is_new_on_first_ranking_then_gets_normal_changes(env):
    game = make_game(env, questionCount=4)
    a, b, c = join(env, game, "Ali"), join(env, game, "Vali"), join(env, game, "Olim")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 0, 3), (c, 0, 6)])
    act(env, game, "next")
    act(env, game, "next")
    assert game.phase == flow.READ and game.index == 1
    late = join(env, game, "Kech", ip="10.0.0.9")         # 2-savolni o'qish paytida
    play(env, game, [(late, 1, 0.3), (b, 2, 1), (c, 2, 1)])
    s = late.last("s")
    assert s["nw"] == 1 and "dk" not in s and s["res"]["ok"] is True
    # yangi o'yinchi Alini quvib o'tdi (ball teng, umumiy vaqti 100 ms kam): Ali bitta pastga — bu ham o'zgarish
    assert a.last("s")["k"] == 2 and a.last("s")["dk"] == -1 and "nw" not in a.last("s")
    act(env, game, "next")
    rows = by_nick(env.hub.host_state(game)["leaderboard"])
    assert rows["Kech"]["new"] is True and rows["Kech"]["d"] is None and rows["Ali"]["new"] is False
    act(env, game, "next")
    play(env, game, [(late, 2, 0.3)])                        # 3-savol: endi oddiy o'zgarish
    s = late.last("s")
    assert "nw" not in s and s["dk"] == (rows["Kech"]["rank"] - s["k"])
    act(env, game, "next")
    rows = by_nick(env.hub.host_state(game)["leaderboard"])
    assert rows["Kech"]["new"] is False and rows["Kech"]["d"] == s["dk"]


def test_player_joining_during_the_result_is_new_on_that_board_only(env):
    game = make_game(env, questionCount=3)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 0, 3)])
    late = join(env, game, "Kech", ip="10.0.0.9")         # natija ko'rsatilayotganda
    s = late.last("s")
    assert ph(s) == "question_result" and "res" not in s and s["nw"] == 1 and s["k"] == 3 and s["pl"] == 3
    act(env, game, "next")
    assert by_nick(env.hub.host_state(game)["leaderboard"])["Kech"]["new"] is True
    act(env, game, "next")
    play(env, game, [(late, 1, 0.3)])
    s = late.last("s")
    assert "nw" not in s and s["dk"] == 2 and s["k"] == 1  # 3 -> 1


def test_disconnected_players_keep_their_place_and_can_drop(env):
    game = make_game(env, questionCount=3)
    a, b, c = join(env, game, "Ali"), join(env, game, "Vali"), join(env, game, "Olim")
    wa = a.last("w")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 0, 3), (c, 0, 6)])
    act(env, game, "next")
    act(env, game, "next")
    env.hub.disconnect(a)                                    # 1-o'rindagi o'quvchining aloqasi uzildi
    play(env, game, [(b, 1, 0.4), (c, 1, 0.5)])               # qolgan hammasi javob berdi — savol yopiladi
    act(env, game, "next")
    rows = by_nick(env.hub.host_state(game)["leaderboard"])
    assert len(rows) == 3 and rows["Ali"]["online"] is False and rows["Ali"]["score"] == 1000
    assert (rows["Ali"]["rank"], rows["Ali"]["d"]) == (3, -2)
    back = FakeConn()
    env.hub.handle(back, "resume", {"v": PV, "pin": game.pin, "id": wa["id"], "tok": wa["tok"]})
    s = back.last("s")
    assert (s["k"], s["dk"], s["sc"]) == (3, -2, 1000) and s["res"] == {"ok": None, "pts": 0, "co": 1}


def test_all_zero_scores_are_ranked_by_tie_break_without_shared_places(env):
    game = make_game(env, questionCount=3)
    conns = {n: join(env, game, n) for n in ("Vali", "Ali", "Bek")}
    act(env, game, "start")
    play(env, game, [(conns["Vali"], 1, 1.0), (conns["Ali"], 1, 2.0), (conns["Bek"], 1, 2.0)])   # hamma xato
    ranks = {n: c.last("s")["k"] for n, c in conns.items()}
    assert ranks == {"Vali": 1, "Ali": 2, "Bek": 3}          # vaqt, keyin ism (Ali < Bek)
    act(env, game, "next")
    assert [r["rank"] for r in env.hub.host_state(game)["leaderboard"]] == [1, 2, 3]


def test_student_gets_only_own_numbers_and_one_neighbour_name(env):
    """O'quvchi xabarida boshqalarning ro'yxati yo'q: faqat o'z o'rni/o'zgarishi/bali va (yaqin bo'lsa) yuqoridagi
    bitta o'yinchining ismi. Xabar kichik."""
    game = make_game(env, questionCount=3)
    conns = [join(env, game, f"Oquvchi{i:02d}") for i in range(30)]
    act(env, game, "start")
    play(env, game, [(c, 0, 0.5 + i * 0.1) for i, c in enumerate(conns)])
    act(env, game, "next")
    act(env, game, "next")
    play(env, game, [(c, 1, 0.5 + (29 - i) * 0.1) for i, c in enumerate(conns)])
    for c in conns:
        s = c.last("s")
        assert set(s) <= {"p", "q", "a", "sc", "res", "k", "pl", "dk", "nw", "bh"}
        others = [n for n in (f"Oquvchi{i:02d}" for i in range(30)) if n != c.last("w")["nick"]]
        assert sum(n in json.dumps(s) for n in others) <= 1
        assert len(json.dumps(s, separators=(",", ":"))) < 160


# ============================================================ yakuniy ochilish
def four_player_game(env, questions=1):
    game = make_game(env, questionCount=questions)
    p1, p2, p3, p4 = (join(env, game, n, av=i + 1) for i, n in enumerate(("Birinchi", "Ikkinchi", "Uchinchi", "Tortinchi")))
    act(env, game, "start")
    for i in range(questions):
        if i:
            act(env, game, "next")
            act(env, game, "next")
        co = correct_option(i)
        play(env, game, [(p1, co, 0.4), (p2, co, 2.0), (p3, co, 5.0), (p4, (co + 1) % 4, 1.0)])
    return game, (p1, p2, p3, p4)


def test_last_question_result_has_no_ranks_and_skips_the_leaderboard(env):
    game, players = four_player_game(env, questions=2)
    host = host_of(env, game)
    for c in players:
        s = c.last("s")
        assert ph(s) == "question_result" and s["q"] == 1 and "res" in s
        assert not {"k", "pl", "dk", "nw", "bh"} & set(s)
    assert "leaderboard" not in host.last("h") and "ranking" not in host.last("h")
    act(env, game, "next")
    assert game.phase == flow.PODIUM_INTRO
    act(env, game, "next", phase="question_result")          # eskirgan bosish — e'tiborsiz
    assert game.phase == flow.PODIUM_INTRO


def test_reveal_runs_3rd_2nd_1st_then_final_on_every_screen_with_config_timings(env):
    game, (p1, p2, p3, p4) = four_player_game(env)
    host = host_of(env, game)
    act(env, game, "next")
    ids = {c: c.last("w")["id"] for c in (p1, p2, p3, p4)}
    assert game.podium == [ids[p1], ids[p2], ids[p3]]
    steps = [("podium_intro", 3000, []), ("reveal_3rd", 3500, [3]), ("reveal_2nd", 3500, [2, 3]),
             ("reveal_1st", 6000, [1, 2, 3])]
    places = {p1: 1, p2: 2, p3: 3}
    for phase, length, shown in steps:
        h = host.last("h")
        assert h["phase"] == phase and h["places"] == 3 and h["phaseEnd"] - h["phaseStart"] == length
        assert [r["place"] for r in h["podium"]] == shown and "leaderboard" not in h and "ranking" not in h
        for c in (p1, p2, p3, p4):
            s = c.last("s")
            assert ph(s) == phase and s["pe"] - s["ps"] == length
            assert [t[0] for t in s["top"]] == shown
            mine = places.get(c)
            assert s.get("k") == (mine if mine in shown else None)
        env.clock.advance(length / 1000)
    h = host.last("h")
    assert h["phase"] == "final_results" and "phaseEnd" not in h and h["played"] == 1
    assert [(r["rank"], r["nick"]) for r in h["ranking"]] == [(1, "Birinchi"), (2, "Ikkinchi"), (3, "Uchinchi"), (4, "Tortinchi")]
    assert [(r["place"], r["nick"], r["score"]) for r in h["podium"]] == [(1, "Birinchi", 1000), (2, "Ikkinchi", 950), (3, "Uchinchi", 875)]
    for c, k in ((p1, 1), (p2, 2), (p3, 3), (p4, 4)):
        s = c.last("s")
        assert ph(s) == "final_results" and s["k"] == k and s["pl"] == 4 and s["nc"] == (0 if k == 4 else 1)
        assert s["top"] == [[1, "Birinchi", 1000, 1], [2, "Ikkinchi", 950, 2], [3, "Uchinchi", 875, 3]]


def test_reveal_timings_follow_config(env, monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_PODIUM_INTRO", 1.5)
    monkeypatch.setattr(config, "OCTAGON_REVEAL_STEP", 2.0)
    monkeypatch.setattr(config, "OCTAGON_REVEAL_WINNER", 4.0)
    game, (p1, *_) = four_player_game(env)
    act(env, game, "next")
    lengths = []
    while game.phase != flow.FINAL:
        s = p1.last("s")
        lengths.append(s["pe"] - s["ps"])
        env.clock.advance((s["pe"] - s["ps"]) / 1000)
    assert lengths == [1500, 2000, 2000, 4000]


NICKS = ("Birinchi", "Ikkinchi", "Uchinchi")


def assert_no_leak(game, conns, hosts):
    """Har bir xabar o'z bosqichiga ko'ra tekshiriladi: e'lon qilinmagan o'rin (ism, o'rin raqami) — hech qayerda yo'q.
    Oxirgi savol natijasidan boshlab (undan oldingi reytinglar — o'z vaqtidagi oraliq natijalar)."""
    last = len(game.questions) - 1
    places = len(game.podium)
    owner = {pid: i + 1 for i, pid in enumerate(game.podium)}
    nick_place = {NICKS[i]: i + 1 for i in range(places)}
    checked = 0
    for c in conns:
        me = next((d for t, d in c.msgs if t == "w"), None)
        for t, d in c.msgs:
            if t != "s":
                continue
            phase = flow.PHASES[d["p"]]
            if flow.CODE[phase] < flow.CODE[flow.RESULT] or (phase in (flow.RESULT, flow.BOARD) and d.get("q") != last):
                continue
            shown = flow.revealed_places(phase, places)
            assert all(row[0] in shown for row in d.get("top", [])), (phase, d)
            mine = owner.get(me["id"]) if me else None
            if phase == flow.FINAL:
                assert "k" in d
            elif "k" in d:
                assert phase in flow.REVEALS and mine in shown and d["k"] == mine, (phase, d)
            assert not {"dk", "bh", "nw", "pl"} & set(d) or phase == flow.FINAL, (phase, d)
            blob = json.dumps(d, ensure_ascii=False)
            for nick, place in nick_place.items():
                if place not in shown:
                    assert nick not in blob, (phase, nick, d)
            checked += 1
    for c in hosts:
        for t, d in c.msgs:
            if t != "h" or not (d["phase"] in flow.FINISHED or (d["phase"] == flow.RESULT and d["index"] == last)):
                continue
            shown = flow.revealed_places(d["phase"], places)
            assert [r["place"] for r in d.get("podium", [])] == sorted(shown), d
            assert "leaderboard" not in d and ("ranking" in d) == (d["phase"] == flow.FINAL)
            blob = json.dumps(d, ensure_ascii=False)
            for nick, place in nick_place.items():
                if place not in shown:
                    assert nick not in blob, (d["phase"], nick)
            checked += 1
    return checked


def test_no_message_ever_carries_a_place_before_its_reveal(env):
    """Sizib chiqmaslik: o'quvchilar, ikkita o'qituvchi oynasi, ochilish paytida qo'shilgan va qayta ulangan o'quvchi —
    barcha xabarlar. 3-o'rin reveal_3rd dan, 2-o'rin reveal_2nd dan, 1-o'rin reveal_1st dan oldin hech qayerda yo'q."""
    game, (p1, p2, p3, p4) = four_player_game(env, questions=2)
    host = host_of(env, game)
    conns = [p1, p2, p3, p4]
    act(env, game, "next")                                   # podium_intro
    late1 = join(env, game, "Kechikkan", ip="10.0.0.8")      # ochilish boshida qo'shildi
    conns.append(late1)
    env.clock.advance(config.OCTAGON_PODIUM_INTRO)           # reveal_3rd
    host2 = host_of(env, game)                               # ikkinchi o'qituvchi oynasi
    w1 = p1.last("w")
    env.hub.disconnect(p1)                                   # g'olib qayta ulanadi — o'z o'rni hali sir
    p1b = FakeConn()
    env.hub.handle(p1b, "resume", {"v": PV, "pin": game.pin, "id": w1["id"], "tok": w1["tok"]})
    conns.append(p1b)
    assert "k" not in p1b.last("s") and [t[0] for t in p1b.last("s")["top"]] == [3]
    env.clock.advance(config.OCTAGON_REVEAL_STEP)            # reveal_2nd
    late2 = join(env, game, "Yana", ip="10.0.0.7")
    conns.append(late2)
    env.clock.advance(config.OCTAGON_REVEAL_STEP)            # reveal_1st
    assert p1b.last("s")["k"] == 1
    env.clock.advance(config.OCTAGON_REVEAL_WINNER)          # final_results
    assert game.phase == flow.FINAL
    assert assert_no_leak(game, conns, [host, host2]) > 25
    # podium o'zgarmadi: kech qo'shilganlar reyting oxirida
    ranking = env.hub.host_state(game)["ranking"]
    assert [r["nick"] for r in ranking][:3] == list(NICKS) and {r["nick"] for r in ranking[-2:]} == {"Kechikkan", "Yana"}
    assert late2.last("s")["k"] in (5, 6) and late2.last("s")["pl"] == 6


def test_two_players_reveal_second_then_first(env):
    game = make_game(env, questionCount=1)
    a, b = join(env, game, "Birinchi"), join(env, game, "Ikkinchi")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 0, 3)])
    act(env, game, "next")
    seen = []
    while game.phase != flow.FINAL:
        seen.append((game.phase, [t[0] for t in a.last("s")["top"]]))
        env.clock.advance(game.phase_end - env.clock.now())
    assert seen == [("podium_intro", []), ("reveal_2nd", [2]), ("reveal_1st", [1, 2])]
    assert env.hub.host_state(game)["places"] == 2 and a.last("s")["k"] == 1 and b.last("s")["k"] == 2


def test_one_player_reveals_only_first_place(env):
    game = make_game(env, questionCount=1)
    a = join(env, game, "Yolgiz")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4)])
    act(env, game, "next")
    seen = []
    while game.phase != flow.FINAL:
        seen.append(game.phase)
        env.clock.advance(game.phase_end - env.clock.now())
    assert seen == ["podium_intro", "reveal_1st"] and a.last("s")["k"] == 1 and a.last("s")["top"] == [[1, "Yolgiz", 1000, 0]]


def test_no_players_left_skips_the_reveal_and_shows_an_empty_game(env):
    game = make_game(env, questionCount=2)
    a = join(env, game, "Ali")
    host = host_of(env, game)
    act(env, game, "start")
    to_question(env, game)
    act(env, game, "kick", id=a.last("w")["id"])              # hammasi chiqarildi
    act(env, game, "skip")
    act(env, game, "next")
    act(env, game, "next")
    act(env, game, "skip")
    act(env, game, "skip")
    act(env, game, "next")                                   # oxirgi savol -> tugash
    h = host.last("h")
    assert game.phase == flow.FINAL and h["places"] == 0 and h["podium"] == [] and h["ranking"] == [] and h["playerCount"] == 0


def test_all_zero_scores_still_reveal_by_tie_break_with_distinct_places(env):
    game = make_game(env, questionCount=1)
    conns = {n: join(env, game, n) for n in ("Vali", "Ali", "Bek", "Dana")}
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(1)
    for n in ("Vali", "Ali", "Bek", "Dana"):               # hamma bir paytda va xato
        answer(env, conns[n], 0, 3)
    act(env, game, "next")
    assert game.phase == flow.PODIUM_INTRO and [game.players[pid].nick for pid in game.podium] == ["Ali", "Bek", "Dana"]
    finish_reveal(env, game)
    assert sorted(c.last("s")["k"] for c in conns.values()) == [1, 2, 3, 4]


def test_early_end_reveals_the_scores_at_that_moment(env):
    game, (p1, p2, p3, p4) = four_player_game(env, questions=1)
    game2 = make_game(env, questionCount=3)
    a, b = join(env, game2, "Ali"), join(env, game2, "Vali")
    act(env, game2, "start")
    play(env, game2, [(a, 0, 0.4), (b, 0, 2)])
    act(env, game2, "next")
    act(env, game2, "next")                                  # 2-savolni o'qish — tugatish
    act(env, game2, "end")
    h = env.hub.host_state(game2)
    assert game2.phase == flow.PODIUM_INTRO and h["endedEarly"] is True and h["places"] == 2 and h["podium"] == []
    finish_reveal(env, game2)
    assert env.hub.host_state(game2)["played"] == 1 and a.last("s")["k"] == 1


def test_early_end_before_anybody_scored_shows_the_zero_case(env):
    game = make_game(env, questionCount=3)
    a, b = join(env, game, "Ali"), join(env, game, "Vali")
    act(env, game, "start")
    play(env, game, [(a, 3, 1), (b, 3, 2)])                  # ikkalasi ham xato
    act(env, game, "next")
    act(env, game, "end")
    assert game.phase == flow.FINAL and game.podium == [] and env.hub.host_state(game)["podium"] == []
    assert (a.last("s")["k"], b.last("s")["k"]) == (1, 2) and a.last("s")["top"] == []


def test_join_while_reveal_has_fewer_than_three_places_never_enters_the_podium(env):
    game = make_game(env, questionCount=1)
    a, b = join(env, game, "Birinchi"), join(env, game, "Ikkinchi")
    act(env, game, "start")
    play(env, game, [(a, 0, 0.4), (b, 3, 3)])
    act(env, game, "next")
    late = join(env, game, "Aaa", ip="10.0.0.9")            # alifbo bo'yicha oldinda, 0 ball — baribir oxirida
    finish_reveal(env, game)
    assert late.last("s")["k"] == 3 and [t[0] for t in late.last("s")["top"]] == [1, 2]
    assert [r["nick"] for r in env.hub.host_state(game)["ranking"]] == ["Birinchi", "Ikkinchi", "Aaa"]


def test_joining_after_final_results_is_rejected(env):
    game, _ = four_player_game(env)
    act(env, game, "next")
    finish_reveal(env, game)
    c = FakeConn()
    env.hub.handle(c, "join", {"v": PV, "pin": game.pin, "nick": "Kech", "av": 0})
    assert c.errors()[-1]["c"] == "ended"


@pytest.mark.parametrize("phase", ["podium_intro", "reveal_3rd", "reveal_2nd", "reveal_1st", "final_results"])
def test_student_reconnect_in_each_reveal_phase_gets_exactly_what_was_announced(env, phase):
    game, players = four_player_game(env)
    act(env, game, "next")
    while game.phase != phase:
        env.clock.advance(game.phase_end - env.clock.now())
    shown = list(reversed(flow.revealed_places(phase, 3)))
    for i, c in enumerate(players):
        w = c.last("w")
        env.hub.disconnect(c)
        back = FakeConn()
        env.hub.handle(back, "resume", {"v": PV, "pin": game.pin, "id": w["id"], "tok": w["tok"]})
        s = back.last("s")
        assert ph(s) == phase and [t[0] for t in s["top"]] == shown
        place = i + 1
        expected = place if phase == "final_results" or (place in shown and place <= 3) else None
        assert s.get("k") == expected
        assert len(game.players) == 4                       # qayta ulanish — dublikat emas


@pytest.mark.parametrize("phase", ["podium_intro", "reveal_3rd", "reveal_2nd", "reveal_1st", "final_results"])
def test_teacher_reconnect_in_each_reveal_phase_continues_from_the_right_step(env, phase):
    game, _ = four_player_game(env)
    act(env, game, "next")
    while game.phase != phase:
        env.clock.advance(game.phase_end - env.clock.now())
    env.clock.advance(0.5)                                   # qadam o'rtasida sahifa yangilandi
    host = host_of(env, game)
    h = host.last("h")
    assert h["phase"] == phase and [r["place"] for r in h["podium"]] == sorted(flow.revealed_places(phase, 3))
    assert h["qr"] and ("phaseEnd" in h) == (phase != "final_results")
    if phase != "final_results":
        assert h["phaseEnd"] - env.hub.wall_ms() == round((game.phase_end - env.clock.now()) * 1000)
        env.clock.advance(game.phase_end - env.clock.now())
        assert host.last("h")["phase"] == flow.after_timer(phase, 3)   # taymer server tomonida davom etdi


def test_repeated_next_and_skip_have_no_extra_effect(env):
    game, (p1, *_) = four_player_game(env)
    act(env, game, "next")
    act(env, game, "next", phase="podium_intro", q=0)
    act(env, game, "next", phase="podium_intro", q=0)        # ikkinchi oyna / ikki marta bosish
    assert game.phase == flow.REVEAL_3
    act(env, game, "next", phase="reveal_3rd", q=0)
    act(env, game, "next", phase="reveal_3rd", q=0)
    assert game.phase == flow.REVEAL_2
    act(env, game, "skip", phase="reveal_2nd", q=0)
    act(env, game, "skip", phase="reveal_2nd", q=0)
    assert game.phase == flow.FINAL
    sent = len(p1.msgs)
    for action in ("next", "skip", "end"):
        act(env, game, action)
    env.clock.advance(60)                                    # bekor qilingan taymerlar hech narsa qilmaydi
    assert game.phase == flow.FINAL and len(p1.msgs) == sent


def test_kicking_after_the_end_is_rejected(env):
    game, (p1, *_) = four_player_game(env)
    act(env, game, "next")
    with pytest.raises(octagon.OctagonError) as e:
        act(env, game, "kick", id=p1.last("w")["id"])
    assert e.value.status == 409 and len(game.players) == 4


@pytest.mark.parametrize("phase", ["podium_intro", "reveal_3rd", "reveal_2nd", "reveal_1st", "final_results"])
def test_restart_during_the_reveal_resumes_the_same_step_and_timer(env, phase):
    from test_octagon_restart import restart
    game, players = four_player_game(env)
    act(env, game, "next")
    while game.phase != phase:
        env.clock.advance(game.phase_end - env.clock.now())
    env.clock.advance(1.0)
    left = None if game.phase_end is None else game.phase_end - env.clock.now()
    podium = list(game.podium)
    data = env.hub.shutdown()
    assert restart(env, data, downtime=20) == 1
    g2 = env.hub.games[game.pin]
    assert g2.phase == phase and g2.podium == podium
    if left is not None:
        assert g2.phase_end - env.clock.now() == pytest.approx(left)
        env.clock.advance(left)
        assert g2.phase == flow.after_timer(phase, 3)


def test_v1_snapshot_with_a_finished_game_is_restored_as_final_results(env):
    from test_octagon_restart import restart
    game, players = four_player_game(env)
    act(env, game, "next")
    finish_reveal(env, game)
    data = env.hub.shutdown()
    data["v"] = 1                                            # eski format: bitta "podium" bosqichi, podium saqlanmagan
    for g in data["games"]:
        g["phase"] = "podium"
        del g["podium"]
        for pd in g["players"]:
            for key in ("late", "firstQ", "afterEnd"):
                del pd[key]
    assert restart(env, data) == 1
    g2 = env.hub.games[game.pin]
    assert g2.phase == flow.FINAL and [g2.players[pid].nick for pid in g2.podium] == list(NICKS)


def test_scores_used_in_the_reveal_are_server_side(env):
    """Ochilishdagi ball va o'rinlar faqat serverdagi hisobdan: mijoz yuborgan qo'shimcha maydonlar e'tiborsiz."""
    game = make_game(env, questionCount=1)
    a, b = join(env, game, "Birinchi"), join(env, game, "Ikkinchi")
    act(env, game, "start")
    to_question(env, game)
    env.clock.advance(0.4)
    env.hub.handle(b, "a", {"q": 0, "o": 0, "sc": 99999, "k": 1, "ms": 0, "pts": 1000})
    env.clock.advance(5)
    answer(env, a, 0, 0)
    act(env, game, "next")
    finish_reveal(env, game)
    assert b.last("s")["k"] == 1 and b.last("s")["sc"] == 1000 == calculate_score(True, 400, 20_000)
    assert a.last("s")["sc"] == calculate_score(True, 5400, 20_000)
