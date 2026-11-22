"""Matnlar jadvali (i18n): ilova bitta tilda (o'zbekcha), har bir modulning `T` jadvali — uning yagona manbai.
Tekshiruv: kodda ishlatilgan har bir `T.kalit` jadvalda bor (ekranda "undefined" chiqmaydi), hech bir matn bo'sh emas,
avatar nomlari soni avatarlar soniga teng. Yangi til qo'shilsa, shu test har bir jadval uchun takrorlanadi."""
import re
from pathlib import Path

import pytest

from app.octagon import AVATARS

ROOT = Path(__file__).resolve().parent.parent
MODULES = ["static/js/play.js", "static/js/views/octagon.js", "static/js/views/games.js"]


def table(src: str) -> tuple[str, str]:
    start = src.index("\nconst T = {\n") + 1
    end = src.index("\n};\n", start)
    return src[start:end], src[:start] + src[end:]


def top_level_keys(block: str) -> set[str]:
    return set(re.findall(r"^  ([A-Za-z_$][\w$]*):", block, re.M))


@pytest.mark.parametrize("module", MODULES)
def test_every_used_string_key_exists(module):
    src = (ROOT / module).read_text(encoding="utf-8")
    block, rest = table(src)
    keys = top_level_keys(block)
    used = set(re.findall(r"(?<![\w$.])T\.([A-Za-z_$][\w$]*)", rest))
    assert used, module
    assert not used - keys, f"{module}: jadvalda yo'q: {sorted(used - keys)}"


@pytest.mark.parametrize("module", MODULES)
def test_no_empty_strings(module):
    block, _ = table((ROOT / module).read_text(encoding="utf-8"))
    assert not re.search(r":\s*(''|\"\"|``)\s*,", block), module


def test_avatar_names_cover_every_avatar():
    block, _ = table((ROOT / "static/js/play.js").read_text(encoding="utf-8"))
    names = re.search(r"avatarNames: \[(.*?)\]", block, re.S).group(1)
    assert len(re.findall(r"'([^']+)'", names)) == len(AVATARS)


def test_games_panel_names_every_octagon_phase():
    """«Davom etayotgan o'yinlar» ro'yxati bosqich nomini ko'rsatadi: serverdagi har bir bosqich uchun matn bo'lishi
    kerak (aks holda ekranda "question_read" kabi ichki nom chiqadi; audit V2-F11)."""
    from app.octagon_flow import PHASES

    block, _ = table((ROOT / "static/js/views/games.js").read_text(encoding="utf-8"))
    labels = re.search(r"phase: \{(.*?)\}", block, re.S).group(1)
    named = set(re.findall(r"(\w+):\s*'[^']+'", labels))
    assert not set(PHASES) - named, sorted(set(PHASES) - named)
