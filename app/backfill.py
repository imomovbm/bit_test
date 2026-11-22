"""Mavzular faolligini (oxirgi o'yin, duellar soni, kunlik yig'indi) duellar tarixidan qayta hisoblash.

    python -m app.backfill --db data/testduel.db --dry-run     # bazaning nusxasida hisoblaydi, asl faylga tegmaydi
    python -m app.backfill --db nusxa.db                        # berilgan bazaga yozadi (avval nusxa oling)

Odatda kerak emas: ustunlar birinchi marta qo'shilganda (yangilangan ilova ishga tushganda) to'ldirish avtomatik
bajariladi. Hisob idempotent — necha marta ishga tushirilsa ham natija bir xil, bitta tranzaksiyada yoziladi.
Tarixda faqat tugagan duellar bor, shuning uchun skriptni duellar o'ynalmayotgan paytda ishga tushirgan ma'qul.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from . import config
from .db import Database


def copy_database(src: Path, dst: Path) -> None:
    """SQLite'ning backup API si bilan izchil nusxa (ilova ishlab turgan bo'lsa ham)."""
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dst) as target:
        source.backup(target)


def run(path: Path) -> dict:
    db = Database(path)
    try:
        started = time.perf_counter()
        summary = db.backfill_activity()
        summary["seconds"] = round(time.perf_counter() - started, 2)
        summary["top"] = db._all("SELECT name, total_duels, last_played_at FROM topics ORDER BY total_duels DESC LIMIT 5")
    finally:
        db.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mavzular faolligini duellar tarixidan qayta hisoblash")
    parser.add_argument("--db", default=str(config.DB_PATH), help="SQLite baza fayli")
    parser.add_argument("--dry-run", action="store_true", help="vaqtinchalik nusxada hisoblash (asl faylga yozilmaydi)")
    args = parser.parse_args(argv)
    src = Path(args.db)
    if not src.exists():
        print(f"Baza topilmadi: {src}", file=sys.stderr)
        return 1
    if args.dry_run:
        tmp = Path(tempfile.mkdtemp(prefix="td-backfill-"))
        try:
            copy = tmp / "copy.db"
            copy_database(src, copy)
            summary = run(copy)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("Sinov (nusxada, asl baza o'zgarmadi):")
    else:
        summary = run(src)
        print(f"Yozildi: {src}")
    print(f"  duellar: {summary['duels']}, o'ynalgan mavzular: {summary['topicsPlayed']}, kunlar: {summary['days']}, "
          f"kunlik qatorlar: {summary['dailyRows']}, vaqt: {summary['seconds']} s")
    for t in summary["top"]:
        print(f"  {t['total_duels']:>7}  {t['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
