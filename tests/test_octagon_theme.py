"""Octagon mavzusi: ranglar bitta faylda (static/css/octagon-theme.css), kontrast WCAG AA talablariga mos,
javob shakllari to'rt xil va har biri rang + shakl + nom bilan."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
THEME = (ROOT / "static/css/octagon-theme.css").read_text(encoding="utf-8")
VARS = dict(re.findall(r"(--oc-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", THEME))
ANSWERS = ("red", "blue", "yellow", "green")


def rgb(name: str) -> tuple[float, float, float]:
    value = VARS[name].lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def luminance(c) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def darken(c, alpha):
    return tuple(v * (1 - alpha) for v in c)


@pytest.mark.parametrize("color", ANSWERS)
def test_answer_colours_meet_wcag_aa(color):
    base, ink, lo, hi = (rgb(f"--oc-{color}{s}") for s in ("", "-ink", "-lo", "-hi"))
    bg = rgb("--oc-bg")
    assert contrast(base, ink) >= 4.5           # shakl va proyektordagi variant matni
    assert contrast(darken(base, 0.24), ink) >= 4.5  # .oc-fill naqshi va gradienti eng to'q joyda (jami ~24%)
    assert contrast(lo, ink) >= 4.5             # natija ekranidagi xiralashtirilgan variant
    assert contrast(base, bg) >= 3              # tugma to'q fonda ko'rinadi (WCAG 1.4.11)
    assert contrast(hi, bg) >= 3                # tugmaning yorug' chegarasi


def test_answer_colours_are_distinct():
    colours = [rgb(f"--oc-{c}") for c in ANSWERS]
    for i, a in enumerate(colours):
        for b in colours[i + 1:]:
            assert sum(abs(x - y) for x, y in zip(a, b)) > 120


@pytest.mark.parametrize("fg,bgs,minimum", [
    ("--oc-ink", ("--oc-bg", "--oc-surface", "--oc-surface-2"), 7),
    ("--oc-ink-2", ("--oc-bg", "--oc-surface", "--oc-surface-2"), 4.5),
    ("--oc-ink-3", ("--oc-bg", "--oc-surface"), 4.5),
    ("--oc-accent-ink", ("--oc-accent", "--oc-accent-lo"), 4.5),
    ("--oc-medal-ink", ("--oc-gold", "--oc-silver", "--oc-bronze"), 4.5),
    ("--oc-warn-ink", ("--oc-warn",), 4.5),
    ("--oc-red-hi", ("--oc-surface",), 4.5),     # xato matni kartochkada
    ("--oc-green-hi", ("--oc-surface",), 4.5),   # reytingdagi "+ball"
    ("--oc-qr-dark", ("--oc-qr-light",), 15),
])
def test_text_contrast(fg, bgs, minimum):
    for bg in bgs:
        assert contrast(rgb(fg), rgb(bg)) >= minimum, (fg, bg)


def test_colours_live_only_in_the_theme_file():
    hexes = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")
    for path in ("static/js/octagon/common.js", "static/js/play.js", "static/js/views/octagon.js", "static/js/views/games.js",
                 "static/css/play.css"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert not hexes.findall(re.sub(r"https?://\S+", "", text)), path
    for color in ANSWERS:
        assert f".oc-c{ANSWERS.index(color)} {{ --c: var(--oc-{color});" in THEME


def test_four_distinct_shapes_with_accessible_names():
    common = (ROOT / "static/js/octagon/common.js").read_text(encoding="utf-8")
    shapes = re.findall(r"\{ id: '([a-z]+)', name: '([^']+)', path: '([^']+)' \}", common)
    assert [s[0] for s in shapes] == ["octagon", "drop", "star", "plus"]
    assert [s[1] for s in shapes] == ["Qizil sakkizburchak", "Koʻk tomchi", "Sariq yulduz", "Yashil plyus"]
    assert len({s[2] for s in shapes}) == 4
