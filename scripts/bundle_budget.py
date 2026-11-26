"""JS/CSS hajmi byudjeti (gzip): oshib ketsa — CI yiqiladi.

    python3 scripts/bundle_budget.py            # jadval va tekshiruv (0 — hammasi byudjet ichida, 1 — oshgan)

Har bir sahifa uchun birinchi yuklanishdagi JS (kirish moduli + uning statik importlari, app/assets.py bilan bir xil
hisob) va CSS, kechiktirib yuklanadigan har bir ko'rinish moduli alohida. Bundan tashqari o'quvchi sahifasi hech qachon
o'qituvchi/administrator kodini yuklamasligi tekshiriladi. Byudjetlar joriy hajmdan ~25% ortiq; spetsifikatsiyadagi
qat'iy chegara: o'quvchi sahifasi JS ≤ 100 KB (gzip). Byudjetni oshirish — ongli qaror (bu faylda, sabab bilan).
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.assets import MODULE_SCRIPT_RE, AssetStore  # noqa: E402

KB = 1024
PAGES = {  # sahifa: (JS byudjeti, CSS byudjeti) — gzip baytlarda
    "play.html": (20 * KB, 10 * KB),     # o'quvchi (telefon, sekin tarmoq) — spetsifikatsiya: ≤ 100 KB
    "index.html": (56 * KB, 34 * KB),    # asosiy ilova (kirish, duel, mashq, reyting)
}
STUDENT_HARD_LIMIT = 100 * KB
LAZY = {  # kerak bo'lganda yuklanadigan ko'rinishlar (faqat o'z hajmi)
    "js/views/octagon.js": 19 * KB,      # 16 -> 19: ovoz boshqaruvi (tugma, slayder, sozlash, «Ovozni yoqish»), 15,0 -> 16,9 KB
    "js/octagon/audio.js": 13 * KB,      # ovoz (sintez + 5 trek): faqat o'qituvchining Octagon sahifasida, import() bilan
    "js/views/admin.js": 28 * KB,
    "js/views/balloon.js": 18 * KB,
    "js/views/games.js": 4 * KB,
}
STUDENT_FORBIDDEN = re.compile(r"^js/(views/|octagon/audio\.js|app\.js|api\.js|lib\.js|live\.js|topic-browser\.js|balloon-scene\.js)")


def gz(store: AssetStore, rels: list[str]) -> int:
    return sum(len(gzip.compress(store.files[r].body, 9, mtime=0)) for r in rels)


def main() -> int:
    store = AssetStore(ROOT / "static")
    rows, failed = [], []
    for page, (js_budget, css_budget) in PAGES.items():
        html = (ROOT / "static" / page).read_text(encoding="utf-8")
        entry = "js/" + MODULE_SCRIPT_RE.search(html).group(1)
        js = [entry, *store.static_imports(entry)]
        css = ["css/" + c for c in re.findall(r'href="/css/([^"]+)"', html)]
        rows.append((f"{page} JS ({len(js)} fayl)", gz(store, js), js_budget))
        rows.append((f"{page} CSS", gz(store, css), css_budget))
        if page == "play.html":
            bad = [r for r in js if STUDENT_FORBIDDEN.match(r)]
            if bad:
                failed.append(f"o'quvchi sahifasi o'qituvchi/ilova kodini yuklaydi: {bad}")
            if gz(store, js) > STUDENT_HARD_LIMIT:
                failed.append("o'quvchi sahifasi JS > 100 KB (gzip)")
    for rel, budget in LAZY.items():
        rows.append((rel, gz(store, [rel]), budget))
    width = max(len(r[0]) for r in rows)
    for name, size, budget in rows:
        mark = "OK " if size <= budget else "OSHDI"
        print(f"  {mark} {name:<{width}}  {size / KB:6.1f} KB  (byudjet {budget / KB:.0f} KB)")
        if size > budget:
            failed.append(f"{name}: {size / KB:.1f} KB > {budget / KB:.0f} KB")
    if failed:
        print("\nByudjet buzildi:\n  - " + "\n  - ".join(failed))
        return 1
    print("\nHammasi byudjet ichida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
