"""Ishlatish (operatsiyalar): sog'lik tekshiruvi, ko'rsatkichlar, brauzer xatolari, to'xtash va qayta ishga tushish.

  GET  /healthz              — ochiq: {"status": "ok"|"draining"|"db_error", "release", "uptimeS"} (200 yoki 503)
  GET  /metrics              — Prometheus matni; TD_METRICS_TOKEN berilgan bo'lsa ``Authorization: Bearer <token>``
  GET  /api/admin/metrics    — xuddi shu ko'rsatkichlar JSON da (administrator sessiyasi bilan)
  POST /api/client-errors    — brauzerdagi kutilmagan xato (xabar, fayl, qator; IP bo'yicha cheklangan)

To'xtash (SIGTERM/SIGINT): yangi o'yinlar qabul qilinmaydi, Octagon o'yinlari diskka yoziladi (<baza>.octagon.json,
faqat egasi o'qiy oladi), o'quvchi va o'qituvchi oynalari 1012 bilan yopiladi. Yangi jarayon ishga tushganda fayl
TD_OCTAGON_RESTORE_MAX_AGE dan yangi bo'lsa — o'yinlar tiklanadi va fayl o'chiriladi; mijozlar avtomatik qayta ulanadi.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web

from . import config
from .observability import ERRORS, METRICS
from .security import RateLimiter

log = logging.getLogger("testduel.ops")
CLIENT_PAGES = ("play", "app")


@dataclass
class Lifecycle:
    release: str = ""
    draining: bool = False
    started: float = field(default_factory=time.monotonic)
    snapshot_path: Path | None = None


# ------------------------------------------------------------ o'yinlar holati
def snapshot_path(db_path: Path | str) -> Path:
    db = Path(db_path)
    return db.with_name(db.stem + ".octagon.json")


def save_snapshot(path: Path, data: dict) -> int:
    """Atomik yozish (vaqtinchalik fayl + nomini almashtirish), faqat egasi o'qiy oladi (0600). Yozilgan o'yinlar soni."""
    games = len(data.get("games") or [])
    if not games:
        path.unlink(missing_ok=True)
        return 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return games


def load_snapshot(path: Path, max_age: float, now_ms: int | None = None) -> dict | None:
    """Saqlangan holat (bo'lsa va eskirmagan bo'lsa). Fayl har holda o'chiriladi — ikki marta tiklanmaydi."""
    if max_age <= 0 or not path.exists():
        path.unlink(missing_ok=True)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ERRORS.report("octagon_restore", "Saqlangan o'yinlar fayli o'qilmadi", exc=True)
        data = None
    finally:
        path.unlink(missing_ok=True)
    if not isinstance(data, dict):
        return None
    now = time.time() * 1000 if now_ms is None else now_ms
    saved = data.get("savedAt")
    if not isinstance(saved, (int, float)) or not 0 <= now - saved <= max_age * 1000:
        log.warning("Saqlangan o'yinlar eskirgan yoki vaqti noto'g'ri — tiklanmadi")
        return None
    return data


# -------------------------------------------------------------- marshrutlar
async def healthz(request: web.Request) -> web.Response:
    from .keys import DB, LIFECYCLE

    life = request.app[LIFECYCLE]
    status, code = "ok", 200
    if life.draining:
        status, code = "draining", 503
    else:
        try:
            request.app[DB].conn.execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001
            ERRORS.report("health", "Baza javob bermadi", exc=True)
            status, code = "db_error", 503
    body = {"status": status, "release": life.release, "uptimeS": round(time.monotonic() - life.started)}
    return web.json_response(body, status=code, headers={"Cache-Control": "no-store"})


def _metrics_allowed(request: web.Request) -> bool:
    token = config.METRICS_TOKEN
    header = request.headers.get("Authorization", "")
    if token and header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), token.encode()):
        return True
    return False


async def metrics(request: web.Request) -> web.Response:
    if not _metrics_allowed(request):
        return web.Response(status=401, text="unauthorized\n", headers={"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"})
    return web.Response(text=METRICS.prometheus(), content_type="text/plain", headers={"Cache-Control": "no-store"})


_client_errors = RateLimiter(limit=max(1, config.CLIENT_ERROR_LIMIT), window=600)


async def client_error(request: web.Request) -> web.Response:
    """Brauzerdagi kutilmagan xato: faqat xabar, skript fayli (so'rov qismisiz) va qator — shaxsiy ma'lumotsiz."""
    from .api import client_ip, read_json

    ip = client_ip(request)
    if config.CLIENT_ERROR_LIMIT <= 0 or _client_errors.blocked(ip):
        return web.json_response({"ok": False}, status=429)
    _client_errors.hit(ip)
    data = await read_json(request)
    page = data.get("p") if data.get("p") in CLIENT_PAGES else "other"
    message = " ".join(str(data.get("m") or "").split())[:300] or "?"
    source = str(data.get("s") or "").split("?")[0].split("#")[0][-160:]
    raw_line = data.get("l")
    line = raw_line if isinstance(raw_line, int) and not isinstance(raw_line, bool) and 0 <= raw_line < 10**7 else 0
    ERRORS.report("client", message, level=logging.WARNING, page=page, src=source, line=line)
    return web.json_response({"ok": True})


def register_gauges(app: web.Application) -> None:
    from .keys import HUB, OCTAGON, SOCKETS

    octagon = app[OCTAGON]
    METRICS.gauge("octagon_games", lambda: len(octagon.games))
    METRICS.gauge("octagon_games_running", lambda: sum(1 for g in octagon.games.values() if g.phase not in ("lobby", "podium")))
    METRICS.gauge("octagon_players", lambda: sum(len(g.players) for g in octagon.games.values()))
    METRICS.gauge("octagon_players_connected",
                  lambda: sum(1 for g in octagon.games.values() for p in g.players.values() if p.conn is not None))
    METRICS.gauge("octagon_sockets", lambda: octagon.socket_total)
    METRICS.gauge("ws_open", lambda: len(app[SOCKETS]))
    hub = app[HUB]
    METRICS.gauge("duels_active", lambda: len(hub.duels))
    METRICS.gauge("users_online", lambda: len(hub.conns))
    METRICS.gauge("duel_seeks_open", lambda: len(hub.seeks))
