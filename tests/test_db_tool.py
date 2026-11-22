"""scripts/db_tool.py: onlayn zaxira (server ishlab turganda ham) va nusxada migratsiya + butunlik tekshiruvi."""
import subprocess
import sys
from pathlib import Path

from app.db import Database

ROOT = Path(__file__).resolve().parent.parent


def tool(*args):
    return subprocess.run([sys.executable, "scripts/db_tool.py", *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=60)


def test_backup_while_open_and_check_the_copy(tmp_path):
    live = Database(tmp_path / "live.db")          # server ishlab turibdi: ulanish ochiq, WAL rejimi
    uid = live.create_user("ali", "x", True)
    live.create_topic("Informatika", [{"text": "Savol?", "options": ["a", "b"], "correct": 0}], True, None, uid)
    copy = tmp_path / "zaxira" / "copy.db"
    r = tool("backup", tmp_path / "live.db", copy)
    assert r.returncode == 0 and copy.exists() and oct(copy.stat().st_mode & 0o777) == "0o600"
    r = tool("check", copy)
    assert r.returncode == 0 and "integrity_check: ok" in r.stdout and "foreign_key_check: 0" in r.stdout
    assert any(line.split()[:2] == ["users", "1"] for line in r.stdout.splitlines())
    assert tool("backup", tmp_path / "live.db", copy).returncode != 0   # mavjud zaxira ustiga yozilmaydi
    assert tool("check", tmp_path / "yoq.db").returncode != 0
    live.close()
