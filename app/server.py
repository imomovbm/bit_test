"""aiohttp ilovasini yig'ish va ishga tushirish."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html
import logging
import mimetypes
import re
import socket
import sys
import time
from pathlib import Path

from aiohttp import WSCloseCode, web

from . import config
from .api import ensure_superadmin, error_middleware, guard_middleware, routes, session_middleware
from .assets import REVALIDATE, AssetStore, accepts_gzip, not_modified, respond
from .db import Database
from .hub import DuelHub, LoopClock
from .keys import ASSETS, CSP, DB, HUB, LIFECYCLE, OCTAGON, SOCKETS
from .observability import ERRORS, METRICS, install_loop_handler, setup_logging
from .octagon import OctagonHub
from .ops import Lifecycle, client_error, healthz, load_snapshot, metrics, register_gauges, save_snapshot, snapshot_path
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


def content_security_policy(*inline_scripts: str) -> str:
    """Brauzer uchun xavfsizlik siyosati: skriptlar faqat shu saytdan (va sanab o'tilgan ichki skriptlar — xesh orqali),
    boshqa saytlar sahifani <iframe> ichiga ololmaydi, plaginlar va <base> o'zgartirish taqiqlangan."""
    hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()}'" for code in inline_scripts)
    return "; ".join((
        "default-src 'self'",
        f"script-src 'self' {hashes}".strip(),
        "style-src 'self'",  # uslublar faqat .css fayllardan (JS dan CSSOM orqali — ruxsat etilgan)
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "media-src 'self' data: blob:",
        "connect-src 'self' ws: wss:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ))


def inline_scripts(page: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", page, re.S)


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
    # index.html dagi kichik ichki skript (mavzuni tiklash) CSP da xeshi bilan ruxsat etilgan
    store = request.app[ASSETS]
    return store_page(request, store, "index.html", {"Content-Security-Policy": request.app[CSP]})


async def play_page(request: web.Request) -> web.StreamResponse:
    """O'quvchilar sahifasi (/play, /play/PIN): ro'yxatdan o'tmasdan, alohida yengil sahifa (asosiy ilova yuklanmaydi)."""
    return store_page(request, request.app[ASSETS], "play.html")


def store_page(request: web.Request, store: AssetStore, name: str, headers: dict | None = None) -> web.Response:
    """HTML qobiq: har doim qayta tekshiriladi (no-cache + ETag/304) — yangi versiya darhol ko'rinadi."""
    return respond(request, store.page(name), REVALIDATE, headers)


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
    csp = content_security_policy(*inline_scripts(body))
    return web.Response(text=body, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store", "Content-Security-Policy": csp})


DEFAULT_CSP = content_security_policy()

# Hamma foydalanuvchiga bir xil, shaxsiy ma'lumotsiz ro'yxatlar: brauzer saqlashi mumkin, lekin har safar qayta
# tekshiradi (ETag -> 304, tana qayta yuborilmaydi). Umumiy (CDN/proksi) kesh saqlamaydi: private.
SHARED_LISTS = frozenset({"/api/topics", "/api/topics/browse", "/api/octagon/topics", "/api/stats/leaderboard"})
API_PRIVATE = "private, no-store"
API_SHARED = "private, no-cache"
GZIP_MIN = 1024  # bundan kichik javoblarni siqish foyda bermaydi


@web.middleware
async def metrics_middleware(request: web.Request, handler):
    """So'rovlar soni (bo'lim va holat sinfi bo'yicha) va API javob vaqti (p50/p95 — /metrics)."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await handler(request)
    t0 = time.perf_counter()
    status = 500
    try:
        response = await handler(request)
        status = response.status
        return response
    except web.HTTPException as e:
        status = e.status
        raise
    finally:
        path = request.path
        area = ("api" if path.startswith("/api/") else "asset" if path.startswith(("/assets/", "/js/", "/css/", "/img/"))
                else "page" if path == "/" or path.startswith("/play") else "other")
        METRICS.inc("http_requests_total", area=area, status=f"{status // 100}xx")
        if area == "api":
            METRICS.observe("http_api_ms", (time.perf_counter() - t0) * 1000)


@web.middleware
async def http_cache_middleware(request: web.Request, handler):
    """API javoblari: kesh sarlavhasi, umumiy ro'yxatlar uchun ETag/304, katta javoblar uchun gzip."""
    response = await handler(request)
    if not request.path.startswith("/api/") or type(response) is not web.Response:
        return response
    body = response.body if isinstance(response.body, bytes) else None
    if request.method == "GET" and request.path in SHARED_LISTS and response.status == 200 and body is not None:
        etag = f'W/"{hashlib.sha256(body).hexdigest()[:20]}"'
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = API_SHARED
        if not_modified(request, etag):
            return web.Response(status=304, headers={"ETag": etag, "Cache-Control": API_SHARED, "Vary": "Accept-Encoding"})
    response.headers.setdefault("Cache-Control", API_PRIVATE)
    if body is not None and len(body) >= GZIP_MIN and accepts_gzip(request) and "Content-Encoding" not in response.headers:
        response.enable_compression(web.ContentCoding.gzip)
        response.headers["Vary"] = "Accept-Encoding"
    return response


async def _response_headers(request: web.Request, response: web.StreamResponse) -> None:
    """Kesh va xavfsizlik sarlavhalari (barcha javoblarga)."""
    headers = response.headers
    if request.path.startswith("/api/"):
        headers.setdefault("Cache-Control", API_PRIVATE)  # foydalanuvchiga xos javob hech qayerda saqlanmasin
        # ilova versiyasi: eski ochiq sahifa (boshqa versiya) foydalanuvchiga «sahifani yangilang» deb ko'rsatadi
        headers.setdefault("X-Release", request.app[ASSETS].release)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "same-origin")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    if headers.get("Content-Type", response.content_type or "").startswith("text/html"):
        headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
    if request.secure or (config.TRUST_PROXY and request.headers.get("X-Forwarded-Proto", "").startswith("https")):
        headers.setdefault("Strict-Transport-Security", "max-age=15552000")


async def _on_startup(app: web.Application) -> None:
    install_loop_handler(asyncio.get_running_loop())
    app[DB].purge_sessions()
    ensure_superadmin(app[DB])
    life = app[LIFECYCLE]
    if life.snapshot_path is not None:
        data = load_snapshot(life.snapshot_path, config.OCTAGON_RESTORE_MAX_AGE)
        if data:
            app[OCTAGON].restore(data)


async def _on_shutdown(app: web.Application) -> None:
    """To'xtash: yangi o'yinlar qabul qilinmaydi, Octagon o'yinlari diskka yoziladi, mijozlar qayta ulanadi (1012)."""
    life = app[LIFECYCLE]
    life.draining = True
    try:
        data = app[OCTAGON].shutdown()
        if life.snapshot_path is not None and config.OCTAGON_RESTORE_MAX_AGE > 0:
            saved = save_snapshot(life.snapshot_path, data)
            if saved:
                log.info("Octagon: %d ta o'yin saqlandi — qayta ishga tushganda davom etadi", saved)
    except Exception:
        ERRORS.report("shutdown", "Octagon o'yinlarini saqlab bo'lmadi", exc=True)
    await asyncio.sleep(0.1)  # Octagon ulanishlariga 1012 yopilish kadrlari yetib borsin
    for ws in list(app[SOCKETS]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")


async def _on_cleanup(app: web.Application) -> None:
    app[DB].close()


def create_app(db_path: Path | str | None = None, lan_url: str | None = None, clock=None) -> web.Application:
    app = web.Application(
        middlewares=[metrics_middleware, http_cache_middleware, error_middleware, guard_middleware, session_middleware],
        client_max_size=config.MAX_UPLOAD_CHARS * 4 + 1024 * 1024,
    )
    db = Database(db_path or config.DB_PATH)
    app[DB] = db
    clock = clock or LoopClock()
    app[HUB] = DuelHub(db, clock, lan_url=lan_url)
    app[OCTAGON] = OctagonHub(db, clock)
    app[SOCKETS] = set()
    app[ASSETS] = AssetStore(config.STATIC_DIR, dev=config.DEV)
    app[LIFECYCLE] = Lifecycle(release=app[ASSETS].release, snapshot_path=snapshot_path(db_path or config.DB_PATH))
    ERRORS.configure(url=config.ERROR_WEBHOOK, release=app[ASSETS].release)
    register_gauges(app)
    app[CSP] = content_security_policy(*inline_scripts((config.STATIC_DIR / "index.html").read_text(encoding="utf-8")))
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
    app.on_cleanup.append(_on_cleanup)
    app.on_response_prepare.append(_response_headers)
    app.add_routes(routes)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/ws/octagon", octagon_ws_handler)
    app.router.add_get("/", index)
    app.router.add_get("/play", play_page)
    app.router.add_get("/play/{pin}", play_page)
    app.router.add_get("/d/{code}", invite_page)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics)
    app.router.add_post("/api/client-errors", client_error)
    app[ASSETS].add_routes(app)
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TestDuel serveri")
    parser.add_argument("--host", default=config.HOST, help="tinglanadigan manzil (standart: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.PORT, help="port (standart: 8080)")
    parser.add_argument("--db", default=str(config.DB_PATH), help="SQLite baza fayli yo'li")
    parser.add_argument("--check-config", action="store_true", help="sozlamalarni tekshirib, joriy qiymatlarni chiqarish")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    problems = config.validate()
    if args.check_config:
        for env, value, doc in config.describe():
            print(f"  {env:36s} {value:28s} {doc}")
        print("\n" + ("Sozlamalarda xato:\n  - " + "\n  - ".join(problems) if problems else "Sozlamalar to'g'ri."))
        sys.exit(2 if problems else 0)
    if problems:
        print("Sozlamalarda xato — server ishga tushirilmadi:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        sys.exit(2)
    setup_logging(config.LOG_FORMAT, config.LOG_LEVEL)
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
    # access_log=None: so'rovlar jurnali (IP, URL dagi PIN) yozilmaydi; ko'rsatkichlar — /metrics
    web.run_app(app, host=args.host, port=args.port, print=None, access_log=None, shutdown_timeout=config.SHUTDOWN_GRACE)
