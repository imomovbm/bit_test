"""Octagon: savoldan keyingi o'rin o'zgarishi va podium tanlash — sof funksiyalar (app/octagon_scoring.py) hamda
yakuniy ochilish bosqichlari (app/octagon_flow.py): qaysi bosqichda qaysi o'rinlar ochiq."""
import random

import pytest

from app import octagon_flow as flow
from app.octagon_scoring import biggest_jump, podium, rank_changes, rank_order, standing_key


def row(pid, score=0, ms=0, key=None):
    return (pid, score, ms, key or pid)


# ======================================================= o'rin o'zgarishi
def test_first_question_has_no_previous_ranking():
    """1-savoldan keyin oldingi reyting yo'q: hech kimda strelka yo'q (delta None), lekin yangi o'rinlar bor."""
    out = rank_changes(None, [row("a", 500), row("b", 900), row("c", 0)])
    assert out == {"b": (None, 1, None), "a": (None, 2, None), "c": (None, 3, None)}


def test_moving_up_down_and_staying():
    before = [row("a", 1000), row("b", 900), row("c", 800), row("d", 700)]
    after = [row("a", 1000), row("b", 1800), row("c", 800), row("d", 1700)]   # b +900, d +1000
    out = rank_changes(before, after)
    assert out["b"] == (2, 1, 1)      # 2 -> 1: bitta yuqoriga
    assert out["d"] == (4, 2, 2)      # 4 -> 2: ikkita yuqoriga
    assert out["a"] == (1, 3, -2)     # 1 -> 3: ikkita pastga
    assert out["c"] == (3, 4, -1)
    assert sum(d for _, _, d in out.values()) == 0  # yopiq ro'yxatda siljishlar yig'indisi nol


def test_unchanged_rank_is_zero_not_none():
    before = [row("a", 900), row("b", 500)]
    after = [row("a", 1900), row("b", 1400)]
    assert rank_changes(before, after) == {"a": (1, 1, 0), "b": (2, 2, 0)}


def test_tie_break_order_score_then_time_then_name():
    """Ball teng — umumiy javob vaqti kam bo'lgan yuqorida; u ham teng — ism (alifbo), keyin id."""
    after = [row("x", 1000, 9000, "zarina"), row("y", 1000, 4000, "yusuf"), row("z", 1000, 4000, "anvar"), row("w", 2000, 99_000, "bek")]
    assert rank_order(after) == ["w", "z", "y", "x"]
    same = [row("p2", 0, 0, "ali"), row("p1", 0, 0, "ali")]   # ism kaliti ham bir xil: id hal qiladi, o'rin takrorlanmaydi
    assert rank_order(same) == ["p1", "p2"]
    out = rank_changes(same, same)
    assert sorted(v[1] for v in out.values()) == [1, 2]


def test_order_is_the_same_as_the_existing_standing_key():
    rng = random.Random(7)
    rows = [row(f"p{i}", rng.choice([0, 500, 750, 1000, 1500]), rng.choice([0, 3000, 3000, 20_000]), rng.choice(["ali", "vali", "olim"]))
            for i in range(60)]
    expected = [r[0] for r in sorted(rows, key=lambda r: standing_key(r[1], r[2], r[3], r[0]))]
    assert rank_order(rows) == expected
    assert [pid for pid, _ in sorted(rank_changes(None, rows).items(), key=lambda kv: kv[1][1])] == expected


def test_all_zero_scores_are_ordered_by_tie_break_without_duplicates():
    before = [row(c, 0, 20_000) for c in "edcba"]
    after = [row("e", 0, 20_000 + 1500), row("d", 0, 20_000 + 900), row("c", 0, 40_000), row("b", 0, 40_000), row("a", 0, 40_000)]
    out = rank_changes(before, after)
    assert [pid for pid in rank_order(after)] == ["d", "e", "a", "b", "c"]
    assert sorted(v[1] for v in out.values()) == [1, 2, 3, 4, 5]
    assert out["d"] == (4, 1, 3) and out["a"] == (1, 3, -2)


def test_late_joiner_has_no_previous_rank_then_normal_deltas():
    """Kech qo'shilgan o'yinchi oldingi reytingda yo'q: delta None (ekranda «YANGI»), keyingi savoldan — oddiy."""
    before = [row("a", 1000), row("b", 500)]
    after = [row("a", 1000), row("late", 900), row("b", 500)]
    out = rank_changes(before, after)
    assert out["late"] == (None, 2, None)
    assert out["b"] == (2, 3, -1)   # yangi o'yinchi o'zib ketdi — b bitta pastga tushdi
    nxt = rank_changes(after, [row("a", 1000), row("late", 1900), row("b", 500)])
    assert nxt["late"] == (2, 1, 1) and nxt["a"] == (1, 2, -1)


def test_players_gone_since_the_previous_ranking_are_ignored():
    """O'yindan chiqarilgan o'yinchi yangi reytingda yo'q — natijada ham yo'q, xato bermaydi."""
    out = rank_changes([row("a", 900), row("gone", 800), row("b", 700)], [row("a", 900), row("b", 1700)])
    assert set(out) == {"a", "b"} and out["b"] == (3, 1, 2)


def test_big_jump_from_last_to_first():
    before = [row(f"p{i}", 1000 - i * 10) for i in range(10)]
    after = [*before[:9], row("p9", 5000)]
    out = rank_changes(before, after)
    assert out["p9"] == (10, 1, 9)
    assert all(out[f"p{i}"][2] == -1 for i in range(9))


def test_non_answerers_drop_like_everyone_else():
    """Javob bermagan o'yinchi 0 ball oladi va boshqalar o'zib ketsa — pastga tushadi."""
    before = [row("idle", 900, 1000), row("fast", 800, 1000)]
    after = [row("idle", 900, 21_000), row("fast", 1800, 1500)]
    assert rank_changes(before, after)["idle"] == (1, 2, -1)


def test_biggest_jump_needs_at_least_two_places():
    assert biggest_jump({"a": (2, 1, 1), "b": (1, 2, -1)}) is None
    assert biggest_jump({"a": (None, 1, None)}) is None
    assert biggest_jump({}) is None
    assert biggest_jump({"a": (5, 3, 2), "b": (9, 4, 5), "c": (3, 1, 2)}) == ("b", 5)


def test_biggest_jump_tie_goes_to_the_better_new_rank():
    assert biggest_jump({"x": (8, 5, 3), "y": (6, 3, 3), "z": (7, 4, 3)}) == ("y", 3)


# ============================================================ podium tanlash
@pytest.mark.parametrize("n, expected", [(0, []), (1, ["p0"]), (2, ["p0", "p1"]), (3, ["p0", "p1", "p2"]), (30, ["p0", "p1", "p2"])])
def test_podium_for_0_1_2_3_and_many_players(n, expected):
    ranked = [f"p{i}" for i in range(n)]
    assert podium(ranked, has_points=True, ended_early=False) == expected
    assert podium(ranked, has_points=True, ended_early=True) == expected


def test_all_zero_scores_still_get_a_podium_by_tie_break_at_the_normal_end():
    assert podium(["a", "b", "c", "d"], has_points=False, ended_early=False) == ["a", "b", "c"]


def test_early_end_without_points_skips_the_reveal():
    assert podium(["a", "b"], has_points=False, ended_early=True) == []


# ============================================================ ochilish bosqichlari
def test_reveal_steps_follow_the_number_of_places():
    assert flow.reveal_steps(3) == (flow.REVEAL_3, flow.REVEAL_2, flow.REVEAL_1)
    assert flow.reveal_steps(2) == (flow.REVEAL_2, flow.REVEAL_1)
    assert flow.reveal_steps(1) == (flow.REVEAL_1,)
    assert flow.reveal_steps(0) == ()
    assert flow.reveal_steps(30) == flow.reveal_steps(3)


@pytest.mark.parametrize("places", [0, 1, 2, 3])
def test_reveal_runs_in_order_then_final_results(places):
    phase = flow.finish_phase(places)
    seen = [phase]
    while phase != flow.FINAL:
        phase = flow.after_timer(phase, places)
        seen.append(phase)
    expected = ([flow.PODIUM_INTRO] if places else []) + list(flow.reveal_steps(places)) + [flow.FINAL]
    assert seen == expected
    for a, b in zip(seen, seen[1:]):
        flow.check(a, b)   # har bir qadam — ruxsat etilgan o'tish


def test_revealed_places_never_run_ahead_of_the_step():
    """Ochilmagan o'rin ma'lumoti hech qaysi bosqichda yuborilmaydi: 3-o'rin — reveal_3rd dan, 2-o'rin — reveal_2nd dan,
    1-o'rin — reveal_1st dan boshlab; podium_intro va undan oldingi bosqichlarda — hech narsa."""
    for phase in (flow.LOBBY, flow.INTRO, flow.READ, flow.ACTIVE, flow.RESULT, flow.BOARD, flow.PODIUM_INTRO):
        assert all(flow.revealed_places(phase, n) == () for n in range(4))
    assert flow.revealed_places(flow.REVEAL_3, 3) == (3,)
    assert flow.revealed_places(flow.REVEAL_2, 3) == (3, 2)
    assert flow.revealed_places(flow.REVEAL_1, 3) == (3, 2, 1)
    assert flow.revealed_places(flow.FINAL, 3) == (3, 2, 1)
    assert flow.revealed_places(flow.REVEAL_2, 2) == (2,)
    assert flow.revealed_places(flow.REVEAL_1, 2) == (2, 1)
    assert flow.revealed_places(flow.REVEAL_1, 1) == (1,)
    assert flow.revealed_places(flow.FINAL, 0) == ()
    for places in range(4):  # har bir qadamda: oldingi qadamdagilar + aynan bitta yangi o'rin
        shown: tuple = ()
        for step in flow.reveal_steps(places):
            now = flow.revealed_places(step, places)
            assert now[:-1] == shown and len(now) == len(shown) + 1 and now[-1] == flow.PLACE[step]
            shown = now
