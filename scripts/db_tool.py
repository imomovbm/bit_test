"""Bazani zaxiralash va nusxada tekshirish (docs/runbook.md).

    python3 scripts/db_tool.py backup data/testduel.db backups/testduel-2026-11-22.db
        — ishlab turgan server bilan ham xavfsiz (SQLite onlayn zaxira API: izchil surat, yozishlarni to'xtatmaydi)

    python3 scripts/db_tool.py check backups/testduel-2026-11-22.db
        — NUSXADA: migratsiyalarni ishga tushiradi (yangi versiya ishga tushgandagidek), butunlikni (integrity_check,
          foreign_key_check) tekshiradi va jadvallardagi yozuvlar sonini chiqaradi. Yangi versiyani joylashtirishdan
          oldin ishlab chiqarish bazasining nusxasida shu buyruqni bajaring.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def backup(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"baza topilmadi: {src}")
    if dst.exists():
        raise SystemExit(f"fayl allaqachon bor (ustiga yozilmaydi): {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dst) as target:
        source.backup(target)
    dst.chmod(0o600)
    print(f"zaxira tayyor: {dst} ({dst.stat().st_size / 1024:.0f} KB)")


def check(path: Path) -> int:
    from app.db import Database

    if not path.exists():
        raise SystemExit(f"baza topilmadi: {path}")
    db = Database(path)  # migratsiyalar shu yerda bajariladi (server ishga tushgandagidek)
    try:
        integrity = db.conn.execute("PRAGMA integrity_check").fetchone()[0]
        broken_fk = db.conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = [r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            print(f"  {t:28s} {db.conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>9}")
    finally:
        db.close()
    print(f"integrity_check: {integrity}; foreign_key_check: {len(broken_fk)} ta muammo")
    return 0 if integrity == "ok" and not broken_fk else 1


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "backup":
        backup(Path(argv[1]), Path(argv[2]))
        return 0
    if len(argv) == 2 and argv[0] == "check":
        return check(Path(argv[1]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
