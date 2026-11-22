"""aiohttp ilovasini yig'ish va ishga tushirish."""
from __future__ import annotations

import argparse
import html
import logging
import mimetypes
import re
import socket
import sys
from pathlib import Path

from aiohttp import WSCloseCode, web

from . import config
from .api import ensure_superadmin, error_middleware, guard_middleware, routes, session_middleware
from .db import Database
from .hub import DuelHub, LoopClock
from .keys import DB, HUB, OCTAGON, SOCKETS
from .octagon import OctagonHub
from .ws import octagon_ws_handler, ws_handler

log = logging.getLogger("testduel")

# Windows reyestrida noto'g'ri MIME turlari bo'lishi mumkin — aniq belgilab qo'yamiz.
for _ext, _type in (
    (".js", "text/javascript"),
    (".css", "text/css"),
    (".svg", "image/svg+xml"),
    (".json", "application/json"),
    (".webmanifest", "application/manifest+json"),
):
    mimetypes.add_type(_type, _ext)

INVITE_HTML = """<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta http-equiv="refresh" content="0; url=/#/invite/{code}">
<link rel="icon" href="/img/logo.svg" type="image/svg+xml">
</head>
<body>
<script>location.replace("/#/invite/{code}");</script>
<p><a href="/#/invite/{code}">Duelga o'tish</a></p>
</body>
</html>
"""


def detect_lan_ip() -> str | None:
    """Kompyuterning lokal tarmoqdagi IP manzilini aniqlaydi (paket yuborilmaydi)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith(("127.", "0.")):
                return ip
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return None


async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def play_page(request: web.Request) -> web.StreamResponse:
    """O'quvchilar sahifasi (/play, /play/PIN): ro'yxatdan o'tmasdan, alohida yengil sahifa (asosiy ilova yuklanmaydi)."""
    return web.FileResponse(config.STATIC_DIR / "play.html", headers={"Cache-Control": "no-cache"})


async def invite_page(request: web.Request) -> web.Response:
    """Taklif havolasi (/d/KOD): ijtimoiy tarmoqlarda chiroyli ko'rinishi uchun og: teglari bilan."""
    code = re.sub(r"[^A-Za-z0-9]", "", request.match_info["code"])[:16].upper()
    info = request.app[HUB].invite_info(code)
    if info.get("valid"):
        title = f"⚔ {info['host']} sizni test duelga chaqirmoqda!"
        desc = (
            f"Mavzu: {info['topicName']} · {info['questionCount']} ta savol · "
            f"har biriga {config.QUESTION_TIME:g} soniya"
        )
    else:
        title = "TestDuel — testlar dueli"
        desc = "Bilimingizni duelda sinang!"
    body = INVITE_HTML.format(title=html.escape(title), desc=html.escape(desc), code=code)
    return web.Response(text=body, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store"})


async def _cache_headers(request: web.Request, response: web.StreamResponse) -> None:
    if request.path.startswith(("/js/", "/css/", "/img/")):
        response.headers["Cache-Control"] = "no-cache"


async def _on_startup(app: web.Application) -> None:
    app[DB].purge_sessions()
    ensure_superadmin(app[DB])


async def _on_shutdown(app: web.Application) -> None:
    for ws in list(app[SOCKETS]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")


async def _on_cleanup(app: web.Application) -> None:
    app[DB].close()


def create_app(db_path: Path | str | None = None, lan_url: str | None = None, clock=None) -> web.Application:
    app = web.Application(
        middlewares=[error_middleware, guard_middleware, session_middleware],
        client_max_size=config.MAX_UPLOAD_CHARS * 4 + 1024 * 1024,
    )
    db = Database(db_path or config.DB_PATH)
    app[DB] = db
    clock = clock or LoopClock()
    app[HUB] = DuelHub(db, clock, lan_url=lan_url)
    app[OCTAGON] = OctagonHub(db, clock)
    app[SOCKETS] = set()
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
    app.on_cleanup.append(_on_cleanup)
    app.on_response_prepare.append(_cache_headers)
    app.add_routes(routes)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/ws/octagon", octagon_ws_handler)
    app.router.add_get("/", index)
    app.router.add_get("/play", play_page)
    app.router.add_get("/play/{pin}", play_page)
    app.router.add_get("/d/{code}", invite_page)
    for sub in ("js", "css", "img"):
        app.router.add_static(f"/{sub}", config.STATIC_DIR / sub)
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TestDuel serveri")
    parser.add_argument("--host", default=config.HOST, help="tinglanadigan manzil (standart: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.PORT, help="port (standart: 8080)")
    parser.add_argument("--db", default=str(config.DB_PATH), help="SQLite baza fayli yo'li")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    lan_ip = detect_lan_ip()
    lan_url = f"http://{lan_ip}:{args.port}" if lan_ip else None
    app = create_app(db_path=args.db, lan_url=lan_url)
    print()
    print("  TestDuel ishga tushdi!")
    print(f"  Shu kompyuterda:        http://localhost:{args.port}")
    if lan_url:
        print(f"  Tarmoqdagi qurilmalar:  {lan_url}")
    print(f"  Ma'lumotlar bazasi:     {args.db}")
    print("  To'xtatish: Ctrl+C")
    print()
    web.run_app(app, host=args.host, port=args.port, print=None, access_log=None)
