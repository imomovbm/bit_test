"""Sozlamalar (app/config.py): muhit o'zgaruvchilari, tur va oraliq tekshiruvi, zid sozlamalar, maxfiy qiymatlar."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from app import config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def reload_config(monkeypatch):
    """Muhit o'zgaruvchilari bilan config ni qayta o'qish; test oxirida toza holatga qaytariladi."""
    def load(**env):
        for k in [k for k in list(__import__("os").environ) if k.startswith("TD_") or k == "PORT"]:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(config)
    yield load
    monkeypatch.undo()
    importlib.reload(config)


def test_defaults_are_valid():
    assert config.validate() == []
    assert config.OCTAGON_INTRO == 5.0 and config.OCTAGON_READ == 5.0 and config.OCTAGON_MAX_PLAYERS == 300


def test_values_come_from_environment(reload_config):
    c = reload_config(TD_OCTAGON_INTRO="3", TD_OCTAGON_READ="7.5", TD_OCTAGON_MAX_PLAYERS="120", TD_LOG_FORMAT="json",
                      TD_LOG_LEVEL="debug", TD_DEV="1", TD_TRUST_PROXY="true")
    assert (c.OCTAGON_INTRO, c.OCTAGON_READ, c.OCTAGON_MAX_PLAYERS) == (3.0, 7.5, 120)
    assert (c.LOG_FORMAT, c.LOG_LEVEL, c.DEV, c.TRUST_PROXY) == ("json", "DEBUG", True, True)
    assert c.validate() == []


def test_legacy_names_still_work(reload_config):
    c = reload_config(TD_OCTAGON_READY="4", PORT="9123")
    assert c.OCTAGON_READ == 4.0 and c.PORT == 9123
    c = reload_config(TD_OCTAGON_READY="4", TD_OCTAGON_READ="6", PORT="9123", TD_PORT="9000")
    assert c.OCTAGON_READ == 6.0 and c.PORT == 9000  # yangi nom ustun


@pytest.mark.parametrize("env, needle", [
    ({"TD_OCTAGON_INTRO": "besh"}, "TD_OCTAGON_INTRO='besh': son"),
    ({"TD_OCTAGON_INTRO": "nan"}, "chekli son"),
    ({"TD_OCTAGON_INTRO": "-1"}, "TD_OCTAGON_INTRO='-1': 0 … 60"),
    ({"TD_OCTAGON_READ": "999"}, "TD_OCTAGON_READ='999': 0 … 60"),
    ({"TD_OCTAGON_MAX_PLAYERS": "2.5"}, "butun son"),
    ({"TD_PORT": "70000"}, "TD_PORT='70000'"),
    ({"TD_LOG_FORMAT": "xml"}, "text | json"),
    ({"TD_DEV": "maybe"}, "1/0"),
    ({"TD_PUBLIC_URL": "ftp://maktab.uz/x"}, "TD_PUBLIC_URL"),
    ({"TD_OCTAGON_MAX_PLAYERS": "1500"}, "TD_OCTAGON_JOIN_LIMIT ≥ TD_OCTAGON_MAX_PLAYERS"),
    ({"TD_OCTAGON_MAX_PLAYERS": "800"}, "TD_OCTAGON_MAX_SOCKETS_PER_IP ≥ TD_OCTAGON_MAX_PLAYERS"),
    ({"TD_OCTAGON_TIME_DEFAULT": "200"}, "TD_OCTAGON_TIME_MIN ≤ TD_OCTAGON_TIME_DEFAULT ≤ TD_OCTAGON_TIME_MAX"),
    ({"TD_OCTAGON_SURGE_FAIL_LIMIT": "100"}, "TD_OCTAGON_SURGE_FAIL_LIMIT ≤ TD_OCTAGON_FAIL_LIMIT"),
    ({"TD_OCTAGON_HOST_FLUSH": "2"}, "TD_OCTAGON_HOST_FLUSH ≤ TD_OCTAGON_HOST_FLUSH_BIG"),
])
def test_invalid_values_are_reported_not_silently_replaced(reload_config, env, needle):
    c = reload_config(**env)
    problems = c.validate()
    assert any(needle in p for p in problems), problems
    with pytest.raises(c.ConfigError):
        c.check()


def test_all_problems_are_reported_at_once(reload_config):
    c = reload_config(TD_OCTAGON_INTRO="x", TD_PORT="0", TD_LOG_LEVEL="loud")
    assert len(c.validate()) == 3


def test_secrets_are_never_shown(reload_config):
    c = reload_config(TD_SUPERADMIN_PASSWORD="juda-maxfiy", TD_METRICS_TOKEN="tok-123", TD_ERROR_WEBHOOK="https://hook.example/abc")
    shown = " ".join(f"{env} {value}" for env, value, _ in c.describe())
    for secret in ("juda-maxfiy", "tok-123", "hook.example"):
        assert secret not in shown
    assert c.SUPERADMIN_PASSWORD == "juda-maxfiy"


def test_check_config_command(tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("TD_")}
    ok = subprocess.run([sys.executable, "run.py", "--check-config"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0 and "TD_OCTAGON_INTRO" in ok.stdout and "Sozlamalar to'g'ri" in ok.stdout
    bad = subprocess.run([sys.executable, "run.py", "--check-config"], cwd=ROOT, env={**env, "TD_OCTAGON_READ": "-3"},
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2 and "TD_OCTAGON_READ" in bad.stdout
    start = subprocess.run([sys.executable, "run.py", "--port", "0", "--db", str(tmp_path / "x.db")], cwd=ROOT,
                           env={**env, "TD_OCTAGON_MAX_PLAYERS": "lots"}, capture_output=True, text=True, timeout=60)
    assert start.returncode == 2 and "server ishga tushirilmadi" in start.stderr  # noto'g'ri sozlama bilan ishga tushmaydi


def test_every_setting_is_documented_in_the_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [s.env for s in config.SETTINGS if f"`{s.env}`" not in readme]
    assert not missing, missing
