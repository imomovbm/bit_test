"""REST API: ro'yxatdan o'tish, mavzular, o'rganish rejimi, Balloon Pop, statistika va boshqaruv."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re
import sqlite3
from urllib.parse import quote, urlsplit

from aiohttp import web

from . import balloon, catalog, config, octagon
from .db import now_ms
from .hub import prepare_question
from .keys import DB, HUB, OCTAGON, USER
from .parser import QuestionError, format_questions, parse_questions, validate_question
from .roles import is_superadmin, is_teacher
from .security import RateLimiter, hash_password, new_token, token_hash, verify_password

log = logging.getLogger("testduel.api")
routes = web.RouteTableDef()

LOGIN_RE = re.compile(r"^[\w.\-]{3,32}$")
login_failures = RateLimiter(limit=10, window=600)
registrations = RateLimiter(limit=100, window=600)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def ok(data: dict | None = None, status: int = 200) -> web.Response:
    return web.json_response(data if data is not None else {"ok": True}, status=status, dumps=_dumps)


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as e:
        return web.json_response({"error": e.message}, status=e.status, dumps=_dumps)
    except web.HTTPException:
        raise
    except OverflowError:  # SQLite 64-bit chegarasidan katta son — noto'g'ri so'rov
        return web.json_response({"error": "Noto'g'ri raqam"}, status=400, dumps=_dumps)
    except Exception:
        log.exception("Kutilmagan xato: %s %s", request.method, request.path)
        return web.json_response({"error": "Serverda kutilmagan xatolik yuz berdi"}, status=500, dumps=_dumps)


def same_origin(request: web.Request) -> bool:
    """Brauzer boshqa saytdan yuborgan so'rovlarni (CSRF, WebSocket o'g'irlash) rad etish uchun."""
    origin = request.headers.get("Origin")
    if not origin:
        return True  # brauzer bo'lmagan mijozlar (curl, testlar) Origin yubormaydi
    host = urlsplit(origin).netloc.lower()
    allowed = {request.host.lower()}
    if config.TRUST_PROXY and request.headers.get("X-Forwarded-Host"):
        allowed.add(request.headers["X-Forwarded-Host"].split(",")[0].strip().lower())
    return host in allowed


MAX_BODY = 256 * 1024  # oddiy so'rovlar uchun; katta fayllar faqat /api/admin/ orqali yuklanadi


@web.middleware
async def guard_middleware(request: web.Request, handler):
    """Boshqa saytdan yuborilgan so'rovlarni va boshqaruvdan tashqaridagi katta so'rovlarni rad etadi."""
    writes = request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS")
    if (writes or request.path.startswith("/ws")) and not same_origin(request):
        return web.json_response({"error": "So'rov boshqa saytdan yuborilgan"}, status=403, dumps=_dumps)
    if writes and not request.path.startswith("/api/admin/"):
        size = request.content_length
        if size is None and request.body_exists:
            return web.json_response({"error": "So'rov hajmi ko'rsatilmagan"}, status=411, dumps=_dumps)
        if size and size > MAX_BODY:
            return web.json_response({"error": "So'rov juda katta"}, status=413, dumps=_dumps)
    return await handler(request)


@web.middleware
async def session_middleware(request: web.Request, handler):
    request[USER] = None
    if request.path.startswith(("/api/", "/ws")):
        token = request.cookies.get(config.SESSION_COOKIE)
        if token:
            request[USER] = request.app[DB].session_user(token_hash(token))
    return await handler(request)


# ------------------------------------------------------------------ helpers
async def read_json(request: web.Request) -> dict:
    if request.content_type != "application/json":
        raise ApiError("So'rov JSON formatida bo'lishi kerak", 415)
    try:
        data = await request.json()
    except Exception:
        raise ApiError("So'rov noto'g'ri formatda")
    if not isinstance(data, dict):
        raise ApiError("So'rov noto'g'ri formatda")
    return data


def require_user(request: web.Request) -> dict:
    user = request.get(USER)
    if not user:
        raise ApiError("Avval tizimga kiring", 401)
    return user


def require_admin(request: web.Request) -> dict:
    user = require_user(request)
    if not (user["is_admin"] or is_superadmin(user)):
        raise ApiError("Bu amal faqat administrator uchun", 403)
    return user


def require_teacher(request: web.Request) -> dict:
    user = require_user(request)
    if not is_teacher(user):
        raise ApiError("Bu amal faqat o'qituvchi yoki administrator uchun", 403)
    return user


def require_superadmin(request: web.Request) -> dict:
    user = require_admin(request)
    if not is_superadmin(user):
        raise ApiError("Foydalanuvchilarni faqat bosh administrator boshqaradi", 403)
    return user


MAX_ID = 2**62  # SQLite INTEGER chegarasidan ancha past


def valid_id(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 < x < MAX_ID


def int_param(request: web.Request, name: str) -> int:
    try:
        value = int(request.match_info[name])
    except (KeyError, ValueError):
        raise ApiError("Noto'g'ri identifikator", 404)
    if not 0 < value < MAX_ID:
        raise ApiError("Noto'g'ri identifikator", 404)
    return value


def public_user(user: dict) -> dict:
    owner = is_superadmin(user)
    return {
        "id": user["id"],
        "login": user["login"],
        "isAdmin": bool(user["is_admin"]) or owner,
        "isSuperadmin": owner,
        "isTeacher": is_teacher(user),  # o'yinlar paneli (administratorlarda ham bor)
    }


# Lotin harflariga o'xshash kirill/yunon harflari: "аdmin" (kirillcha "а") kabi soxta loginlarni aniqlash uchun.
LOOKALIKES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "i", "l": "i", "ɑ": "a", "α": "a", "ο": "o",
    "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t", "χ": "x", "ε": "e", "μ": "m", "0": "o", "1": "i",
    "_": "", ".": "", "-": "",
})


def login_skeleton(login: str) -> str:
    return login.casefold().translate(LOOKALIKES)


def reserved_login(db, login: str) -> bool:
    """Bosh administrator logini (va unga o'xshatib yozilgan loginlar) boshqalar uchun band.

    Aynan shu login faqat birinchi foydalanuvchi sifatida ro'yxatdan o'tkazilishi mumkin.
    """
    owner = config.SUPERADMIN_LOGIN
    if login.casefold() == owner.casefold():
        return db.count_users() > 0
    return login_skeleton(login) == login_skeleton(owner)


def ensure_superadmin(db) -> None:
    """Ishga tushishda: bosh administrator doim administrator va bloklanmagan bo'lsin.

    TD_SUPERADMIN_PASSWORD berilgan bo'lsa — akkaunt bo'lmasa yaratiladi, bor bo'lsa paroli shu qiymatga tiklanadi.
    """
    login = config.SUPERADMIN_LOGIN
    password = config.SUPERADMIN_PASSWORD
    if password and len(password) < 4:
        log.warning("TD_SUPERADMIN_PASSWORD juda qisqa (kamida 4 belgi) — e'tiborga olinmadi")
        password = None
    user = db.user_by_login(login)
    if not user:
        if password:
            db.create_user(login, hash_password(password), True)
            log.info("Bosh administrator akkaunti yaratildi: %s", login)
        return
    if not user["is_admin"] or user["blocked"]:
        db.set_admin(user["id"], True)
        db.set_blocked(user["id"], False)
    if password and not verify_password(password, user["pass_hash"]):
        db.set_password(user["id"], hash_password(password))
        log.info("Bosh administrator (%s) paroli TD_SUPERADMIN_PASSWORD bo'yicha yangilandi", user["login"])


def registration_open(db) -> bool:
    return db.setting("registration_open", "1") == "1"


def validate_login(login: str) -> None:
    if not LOGIN_RE.fullmatch(login):
        raise ApiError("Login 3–32 ta harf, raqam yoki . _ - belgilaridan iborat bo'lishi kerak")


def topic_json(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "questionCount": t["question_count"],
        "shuffle": bool(t["shuffle_options"]),
        "active": bool(t.get("active", 1)),
        "sourceFile": t.get("source_file"),
        "createdAt": t["created_at"],
        "createdBy": t.get("author"),
    }


def client_ip(request: web.Request) -> str:
    if config.TRUST_PROXY:
        # proksi qo'shgan oxirgi manzil — mijoz uni soxtalashtira olmaydi
        forwarded = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
        if forwarded:
            return forwarded[-1]
    return request.remote or "?"


async def in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def validate_password(password: str) -> None:
    if len(password) < 4:
        raise ApiError("Parol kamida 4 ta belgidan iborat bo'lishi kerak")
    if len(password) > 128:
        raise ApiError("Parol juda uzun")


async def start_session(request: web.Request, user: dict) -> web.Response:
    token = new_token()
    request.app[DB].create_session(token_hash(token), user["id"], config.SESSION_DAYS)
    resp = ok({"user": public_user(user)})
    resp.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,
        samesite="Lax",
        path="/",
        secure=request.secure or (config.TRUST_PROXY and request.headers.get("X-Forwarded-Proto", "").startswith("https")),
    )
    return resp


# --------------------------------------------------------------------- auth
@routes.post("/api/auth/register")
async def register(request: web.Request):
    data = await read_json(request)
    login = str(data.get("login", "")).strip()
    password = str(data.get("password", ""))
    validate_login(login)
    validate_password(password)
    ip = client_ip(request)
    if registrations.blocked(ip):
        raise ApiError("Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring", 429)
    db = request.app[DB]
    # Birinchi foydalanuvchi (administrator) har doim ro'yxatdan o'ta oladi.
    if db.count_users() and not registration_open(db):
        raise ApiError("Ro'yxatdan o'tish yopilgan. Akkaunt olish uchun administratorga murojaat qiling", 403)
    if db.user_by_login(login) or reserved_login(db, login):
        raise ApiError("Bu login band. Boshqa login tanlang", 409)
    pass_hash = await in_thread(hash_password, password)
    is_admin = db.count_users() == 0 or login.casefold() in config.ADMIN_LOGINS
    try:
        user_id = db.create_user(login, pass_hash, is_admin)
    except sqlite3.IntegrityError:
        raise ApiError("Bu login band. Boshqa login tanlang", 409)
    registrations.hit(ip)
    log.info("Yangi foydalanuvchi: %s%s", login, " (admin)" if is_admin else "")
    return await start_session(request, db.user_by_id(user_id))


@routes.post("/api/auth/login")
async def login(request: web.Request):
    data = await read_json(request)
    login_name = str(data.get("login", "")).strip()
    password = str(data.get("password", ""))
    key = f"{client_ip(request)}|{login_name.casefold()}"
    if login_failures.blocked(key):
        raise ApiError("Juda ko'p noto'g'ri urinish. 10 daqiqadan keyin qayta urinib ko'ring", 429)
    user = request.app[DB].user_by_login(login_name) if login_name else None
    if not user or not await in_thread(verify_password, password, user["pass_hash"]):
        login_failures.hit(key)
        raise ApiError("Login yoki parol noto'g'ri", 401)
    login_failures.reset(key)
    if user["blocked"]:
        raise ApiError("Akkauntingiz bloklangan. Administratorga murojaat qiling", 403)
    request.app[DB].touch_user(user["id"])
    return await start_session(request, user)


@routes.post("/api/auth/logout")
async def logout(request: web.Request):
    token = request.cookies.get(config.SESSION_COOKIE)
    if token:
        request.app[DB].delete_session(token_hash(token))
        request.app[OCTAGON].drop_hosts(session=token_hash(token))  # shu sessiyadagi Octagon boshqaruv oynalari uziladi
    resp = ok()
    resp.del_cookie(config.SESSION_COOKIE, path="/")
    return resp


@routes.get("/api/auth/me")
async def me(request: web.Request):
    user = request.get(USER)
    db = request.app[DB]
    return ok({
        "user": public_user(user) if user else None,
        "registrationOpen": registration_open(db) or db.count_users() == 0,
    })


# ------------------------------------------------------------------- topics
@routes.get("/api/topics")
async def topics_list(request: web.Request):
    require_user(request)
    topics = [topic_json(t) for t in request.app[DB].list_topics() if t["question_count"] > 0 and t["active"]]
    return ok({"topics": topics})


@routes.get("/api/topics/browse")
async def topics_browse(request: web.Request):
    """Bosh sahifa: mavzular davr bo'yicha reytingda (hot | today | week | month | all), qidiruv va sahifalash bilan.
    Javob keshdan olinadi (app/catalog.py); kutayotgan/o'ynayotganlar soni — jonli."""
    require_user(request)
    q = request.query
    period = q.get("period", "hot")
    if period not in catalog.PERIODS:
        raise ApiError("Noto'g'ri davr")
    try:
        offset = int(q.get("offset", "0"))
        limit = int(q.get("limit", str(config.TOPICS_PAGE)))
    except ValueError:
        raise ApiError("Noto'g'ri sahifa")
    if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 60:
        raise ApiError("Noto'g'ri sahifa")
    return ok(request.app[HUB].catalog.browse(period, q.get("q", "")[:catalog.MAX_SEARCH], offset, limit))


@routes.get("/api/topics/{tid}/practice")
async def practice_questions(request: web.Request):
    require_user(request)
    db = request.app[DB]
    topic = db.get_topic(int_param(request, "tid"))
    if not topic or not topic["active"]:
        raise ApiError("Mavzu topilmadi", 404)
    if topic["question_count"] < 1:
        raise ApiError("Bu mavzuda savollar yo'q")
    count = request.query.get("count", "all")
    limit = None
    if count != "all":
        try:
            limit = max(1, min(int(count), 10_000))
        except ValueError:
            raise ApiError("Savollar soni noto'g'ri")
    random_order = request.query.get("order", "random") != "seq"
    rows = db.pick_questions(topic["id"], limit, random_order=random_order)
    questions = [prepare_question(r, bool(topic["shuffle_options"])) for r in rows]
    return ok({"topic": topic_json(topic), "questions": questions})


@routes.post("/api/practice/results")
async def practice_result(request: web.Request):
    user = require_user(request)
    data = await read_json(request)
    try:
        topic_id = int(data.get("topicId"))
        total = int(data.get("total"))
        answered = int(data.get("answered"))
        correct = int(data.get("correct"))
    except (TypeError, ValueError):
        raise ApiError("Natija ma'lumotlari noto'g'ri")
    if not (0 <= correct <= answered <= total) or total < 1 or total > 10_000:
        raise ApiError("Natija ma'lumotlari noto'g'ri")
    db = request.app[DB]
    topic = db.get_topic(topic_id)
    db.save_practice(user["id"], topic_id if topic else None, topic["name"] if topic else "—", total, answered, correct)
    return ok()


# -------------------------------------------------------------------- stats
@routes.get("/api/stats/leaderboard")
async def leaderboard(request: web.Request):
    require_user(request)
    return ok({"rows": request.app[DB].leaderboard()})


@routes.get("/api/stats/me")
async def my_stats(request: web.Request):
    user = require_user(request)
    db = request.app[DB]
    return ok({
        "duelSummary": db.duel_summary(user["id"]),
        "duels": db.user_duels(user["id"]),
        "practiceSummary": db.practice_summary(user["id"]),
        "practice": db.user_practice(user["id"]),
    })


# -------------------------------------------------------------- balloon pop
balloon_rng = random.SystemRandom()
MAX_BALLOON_GAMES = 300  # bitta foydalanuvchi uchun saqlanadigan o'yinlar


class TopicQuestions:
    """O'yin uchun savollar manbai: savollar bazadan bittadan olinadi (variantlar kerak bo'lsa aralashtiriladi)."""

    def __init__(self, db, topic_id: int | None):
        self.db = db
        self.topic_id = topic_id
        topic = db.get_topic(topic_id) if topic_id is not None else None
        self.shuffle = bool(topic["shuffle_options"]) if topic else True

    def ids(self) -> list[int]:
        return self.db.question_ids(self.topic_id) if self.topic_id is not None else []

    def load(self, qid: int) -> dict | None:
        row = self.db.question_by_id(qid, self.topic_id) if self.topic_id is not None else None
        return prepare_question(row, self.shuffle) if row else None


def balloon_json(game_id: int, state: dict) -> dict:
    return {"id": game_id, **balloon.public(state, now_ms())}


def own_balloon_game(request: web.Request) -> dict:
    user = require_teacher(request)
    game = request.app[DB].balloon_game(int_param(request, "gid"))
    if not game or game["owner_id"] != user["id"]:
        raise ApiError("O'yin topilmadi", 404)
    return game


@routes.get("/api/balloon/games")
async def balloon_list(request: web.Request):
    user = require_teacher(request)
    games = [{"id": g["id"], **balloon.summary(g["state"])} for g in request.app[DB].balloon_games(user["id"])]
    return ok({"games": games})


@routes.post("/api/balloon/games")
async def balloon_create(request: web.Request):
    user = require_teacher(request)
    data = await read_json(request)
    try:
        settings = balloon.clean_settings(data)
    except balloon.GameError as e:
        raise ApiError(str(e), e.status)
    db = request.app[DB]
    topic_id = data.get("topicId")
    topic = db.get_topic(topic_id) if isinstance(topic_id, int) and not isinstance(topic_id, bool) else None
    if not topic or not topic["active"]:
        if topic_id is None:
            raise ApiError("Mavzuni tanlang")
        raise ApiError("Mavzu topilmadi — u o'chirilgan yoki yopilgan bo'lishi mumkin", 404)
    if topic["question_count"] < 1:
        raise ApiError("Bu mavzuda savollar yo'q")
    if db.count_balloon_games(user["id"]) >= MAX_BALLOON_GAMES:
        raise ApiError(f"O'yinlar soni {MAX_BALLOON_GAMES} taga yetdi. Tarixdan eskilarini o'chiring")
    state = balloon.new_game(topic_id=topic["id"], topic_name=topic["name"], now_ms=now_ms(), **settings)
    game_id = db.create_balloon_game(user["id"], topic["id"], topic["name"], state)
    log.info("Balloon Pop #%d: %s vs %s (%s) — %s", game_id, *(t["name"] for t in settings["teams"]), topic["name"], user["login"])
    return ok({"game": balloon_json(game_id, state)}, status=201)


@routes.get("/api/balloon/games/{gid}")
async def balloon_get(request: web.Request):
    game = own_balloon_game(request)
    return ok({"game": balloon_json(game["id"], game["state"])})


@routes.post("/api/balloon/games/{gid}/action")
async def balloon_action(request: web.Request):
    # Avval so'rov tanasini o'qiymiz: shundan keyin holatni o'qish, o'zgartirish va saqlash orasida
    # `await` yo'q — bir vaqtda kelgan ikki so'rov bir-birining natijasini o'chirib yubormaydi.
    data = await read_json(request)
    game = own_balloon_game(request)
    db = request.app[DB]
    state = game["state"]
    if "rev" in data and data["rev"] != state["rev"]:
        return web.json_response(
            {"error": "O'yin holati boshqa oynada o'zgargan — yangilandi", "game": balloon_json(game["id"], state)},
            status=409,
            dumps=_dumps,
        )
    work = copy.deepcopy(state)
    try:
        event = balloon.apply(work, data, source=TopicQuestions(db, game["topic_id"]), rng=balloon_rng, now_ms=now_ms())
    except balloon.GameError as e:
        return web.json_response({"error": str(e), "game": balloon_json(game["id"], state)}, status=e.status, dumps=_dumps)
    db.save_balloon_game(game["id"], work, "finished" if work["phase"] == "finished" else "active")
    return ok({"game": balloon_json(game["id"], work), "event": event})


@routes.delete("/api/balloon/games/{gid}")
async def balloon_delete(request: web.Request):
    game = own_balloon_game(request)
    request.app[DB].delete_balloon_game(game["id"])
    return ok()


# ------------------------------------------------------------------ octagon
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:[0-9]{1,5})?$|^\[[0-9A-Fa-f:.]+\](:[0-9]{1,5})?$")


def octagon_call(fn, *args):
    try:
        return fn(*args)
    except octagon.OctagonError as e:
        raise ApiError(e.message, e.status)


def public_base_url(request: web.Request) -> str:
    """O'quvchilar qo'shiladigan sayt manzili (QR kod uchun). TD_PUBLIC_URL berilgan bo'lsa — doim shu manzil.
    Kompyuterning o'zida (localhost) ochilgan bo'lsa — tarmoqdagi manzil (LAN IP), aks holda telefonlar localhost'ga
    ulana olmaydi. Host sarlavhasi tekshiriladi: noto'g'ri qiymat QR kodga tushmaydi."""
    if config.PUBLIC_URL:
        return config.PUBLIC_URL
    secure = request.secure or (config.TRUST_PROXY and request.headers.get("X-Forwarded-Proto", "").startswith("https"))
    host = request.host
    if config.TRUST_PROXY and request.headers.get("X-Forwarded-Host"):
        host = request.headers["X-Forwarded-Host"].split(",")[0].strip()
    lan = request.app[HUB].lan_url
    if not HOST_RE.fullmatch(host or ""):
        return lan or "http://localhost"
    hostname = urlsplit(f"//{host}").hostname or ""
    if lan and (hostname in ("localhost", "::1", "0.0.0.0") or hostname.startswith("127.")):
        return lan
    return f"{'https' if secure else 'http'}://{host}"


def end_teacher_games(app: web.Application, user_id: int, reason: str = "ended") -> None:
    """O'qituvchi huquqi olib qo'yilsa, bloklansa yoki o'chirilsa — uning Octagon o'yinlari yopiladi."""
    app[OCTAGON].end_games_of(user_id, reason)


@routes.get("/api/octagon/topics")
async def octagon_topics(request: web.Request):
    """O'yin uchun mavzular: savollar soni va 4 tadan ko'p variantli savollar soni."""
    require_teacher(request)
    db = request.app[DB]
    long_counts = db.long_option_counts(octagon.MAX_OPTIONS)
    topics = [
        {**topic_json(t), "longCount": long_counts.get(t["id"], 0)}
        for t in db.list_topics()
        if t["question_count"] > 0 and t["active"]
    ]
    return ok({
        "topics": topics,
        "limits": {
            "minTime": octagon.MIN_TIME, "maxTime": octagon.MAX_TIME, "defaultTime": octagon.DEFAULT_TIME,
            "maxQuestions": octagon.MAX_QUESTIONS, "defaultQuestions": octagon.DEFAULT_QUESTIONS,
            "maxOptions": octagon.MAX_OPTIONS, "readySeconds": config.OCTAGON_READY,
        },
    })


@routes.post("/api/octagon/games")
async def octagon_create(request: web.Request):
    user = require_teacher(request)
    data = await read_json(request)
    settings = octagon_call(octagon.clean_settings, data)
    db = request.app[DB]
    topic_id = data.get("topicId")
    topic = db.get_topic(topic_id) if valid_id(topic_id) else None
    if not topic or not topic["active"]:
        if topic_id is None:
            raise ApiError("Mavzuni tanlang")
        raise ApiError("Mavzu topilmadi — u o'chirilgan yoki yopilgan bo'lishi mumkin", 404)
    if topic["question_count"] < 1:
        raise ApiError("Bu mavzuda savollar yo'q")
    hub = request.app[OCTAGON]
    rows = db.topic_questions(topic["id"])
    game = octagon_call(hub.create_game, user, topic, rows, settings, public_base_url(request))
    return ok({"game": hub.host_state(game)}, status=201)


@routes.get("/api/octagon/games")
async def octagon_list(request: web.Request):
    user = require_teacher(request)
    hub = request.app[OCTAGON]
    return ok({"games": [hub.game_summary(g) for g in hub.games_of(user["id"])]})


@routes.get("/api/octagon/games/{pin}")
async def octagon_get(request: web.Request):
    user = require_teacher(request)
    hub = request.app[OCTAGON]
    game = octagon_call(hub.owned_game, user, request.match_info["pin"])
    return ok({"game": hub.host_state(game)})


@routes.post("/api/octagon/games/{pin}/action")
async def octagon_action(request: web.Request):
    """O'qituvchi amallari: start | next | skip | end | kick {id} | settings {timeLimit} | close."""
    user = require_teacher(request)
    data = await read_json(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise ApiError("Amalni ko'rsating")
    hub = request.app[OCTAGON]
    game = octagon_call(hub.host_action, user, request.match_info["pin"], action, data)
    return ok({"game": hub.host_state(game) if game else None})


@routes.delete("/api/octagon/games/{pin}")
async def octagon_delete(request: web.Request):
    user = require_teacher(request)
    hub = request.app[OCTAGON]
    game = octagon_call(hub.owned_game, user, request.match_info["pin"])
    hub.close_game(game.pin, "closed")
    return ok()


# ------------------------------------------------------------------ invites
@routes.get("/api/invite/{code}")
async def invite_info(request: web.Request):
    require_user(request)
    return ok(request.app[HUB].invite_info(request.match_info["code"]))


# -------------------------------------------------------------------- admin
def _check_content(data: dict) -> str:
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("Fayl bo'sh yoki o'qib bo'lmadi")
    if len(content) > config.MAX_UPLOAD_CHARS:
        raise ApiError("Fayl juda katta (10 MB dan oshmasin)")
    return content


def _check_topic_name(db, name, exclude_id: int | None = None) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ApiError("Mavzu nomini kiriting")
    if len(name) > config.MAX_TOPIC_NAME:
        raise ApiError(f"Mavzu nomi {config.MAX_TOPIC_NAME} belgidan oshmasin")
    if db.topic_name_taken(name, exclude_id):
        raise ApiError("Bunday nomli mavzu allaqachon bor. Boshqa nom kiriting", 409)
    return name


@routes.post("/api/admin/topics/parse")
async def admin_parse(request: web.Request):
    require_admin(request)
    data = await read_json(request)
    parsed = parse_questions(_check_content(data))
    return ok({
        "count": len(parsed["questions"]),
        "blocks": parsed["blocks"],
        "errors": parsed["errors"][:200],
        "errorCount": len(parsed["errors"]),
        "preview": parsed["questions"][:5],
    })


@routes.post("/api/admin/topics")
async def admin_create_topic(request: web.Request):
    user = require_admin(request)
    data = await read_json(request)
    db = request.app[DB]
    name = _check_topic_name(db, data.get("name"))
    if data.get("content") is None:  # bo'sh mavzu: savollar keyin qo'lda yoki fayldan qo'shiladi
        parsed = {"questions": [], "errors": []}
    else:
        parsed = parse_questions(_check_content(data))
        if not parsed["questions"]:
            raise ApiError("Faylda yaroqli savol topilmadi. Fayl formatini tekshiring")
    source = str(data.get("fileName") or "")[:255] or None
    try:
        topic_id = db.create_topic(name, parsed["questions"], bool(data.get("shuffle", True)), source, user["id"])
    except sqlite3.IntegrityError:
        raise ApiError("Bunday nomli mavzu allaqachon bor. Boshqa nom kiriting", 409)
    log.info("Yangi mavzu: %s (%d savol) — %s", name, len(parsed["questions"]), user["login"])
    request.app[HUB].topics_changed()
    return ok({"topic": topic_json(db.get_topic(topic_id)), "skipped": len(parsed["errors"])}, status=201)


@routes.get("/api/admin/topics")
async def admin_topics(request: web.Request):
    require_admin(request)
    return ok({"topics": [topic_json(t) for t in request.app[DB].list_topics()]})


@routes.get("/api/admin/topics/{tid}/questions")
async def admin_topic_questions(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    topic = db.get_topic(int_param(request, "tid"))
    if not topic:
        raise ApiError("Mavzu topilmadi", 404)
    return ok({"topic": topic_json(topic), "questions": db.topic_questions(topic["id"])})


@routes.put("/api/admin/topics/{tid}/content")
async def admin_replace_topic(request: web.Request):
    """Mavzu savollarini yangi fayl bilan almashtirish (nom, sozlamalar va tarix saqlanadi)."""
    user = require_admin(request)
    db = request.app[DB]
    tid = int_param(request, "tid")
    topic = db.get_topic(tid)
    if not topic:
        raise ApiError("Mavzu topilmadi", 404)
    data = await read_json(request)
    parsed = parse_questions(_check_content(data))
    if not parsed["questions"]:
        raise ApiError("Faylda yaroqli savol topilmadi. Fayl formatini tekshiring")
    source = str(data.get("fileName") or "")[:255] or None
    db.replace_topic_questions(tid, parsed["questions"], source, user["id"])
    log.info("Mavzu yangilandi: %s (%d savol) — %s", topic["name"], len(parsed["questions"]), user["login"])
    request.app[HUB].topics_changed()
    return ok({"topic": topic_json(db.get_topic(tid)), "skipped": len(parsed["errors"])})


@routes.get("/api/admin/topics/{tid}/export")
async def admin_export_topic(request: web.Request):
    """Mavzuni yuklash formatidagi .txt fayl sifatida qaytaradi."""
    require_admin(request)
    db = request.app[DB]
    topic = db.get_topic(int_param(request, "tid"))
    if not topic:
        raise ApiError("Mavzu topilmadi", 404)
    text = format_questions(db.topic_questions(topic["id"]))
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", topic["name"]).strip()[:100] or "mavzu"
    return web.Response(
        text=text,
        content_type="text/plain",
        charset="utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"topic-{topic['id']}.txt\"; filename*=UTF-8''{quote(name + '.txt')}",
            "Cache-Control": "no-store",
        },
    )


@routes.patch("/api/admin/topics/{tid}")
async def admin_update_topic(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    tid = int_param(request, "tid")
    if not db.get_topic(tid):
        raise ApiError("Mavzu topilmadi", 404)
    data = await read_json(request)
    name = _check_topic_name(db, data["name"], tid) if "name" in data else None
    shuffle = bool(data["shuffle"]) if "shuffle" in data else None
    active = bool(data["active"]) if "active" in data else None
    db.update_topic(tid, name=name, shuffle=shuffle)
    if active is not None:  # holat o'zgarishi jurnalga yoziladi
        db.set_topics_active([tid], active, request[USER], "manual")
    if active is False:  # yopilgan mavzuni kutayotganlarning seeklari bekor qilinadi
        request.app[HUB].topic_removed(tid, "Siz kutayotgan mavzu yopildi")
    request.app[HUB].topics_changed()
    return ok({"topic": topic_json(db.get_topic(tid))})


# ------------------------------------------- mavzular faolligi (boshqaruv)
ADMIN_TOPIC_SORTS = ("name", "lastPlayed", "total", "recent", "status", "created")
MAX_BULK = 2000


def _int_query(request: web.Request, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(request.query.get(name, str(default)))
    except ValueError:
        raise ApiError("Noto'g'ri so'rov")
    if not low <= value <= high:
        raise ApiError("Noto'g'ri so'rov")
    return value


def topic_activity_settings(db) -> dict:
    return {
        "autoDeactivateDays": int(db.setting("auto_deactivate_days", "0") or 0),
        "suggestDays": int(db.setting("suggest_idle_days", str(config.SUGGEST_IDLE_DAYS)) or config.SUGGEST_IDLE_DAYS),
    }


def admin_topic_json(t: dict, hub) -> dict:
    waiting, playing = hub.topic_live(t["id"])
    return {
        "id": t["id"],
        "name": t["name"],
        "active": bool(t["active"]),
        "questionCount": t["question_count"],
        "lastPlayedAt": t["last_played_at"],
        "totalDuels": t["total_duels"],
        "duels30": t.get("duels30", hub.catalog.month_all.get(t["id"], 0)),
        "createdAt": t["created_at"],
        "createdBy": t.get("author"),
        "sourceFile": t.get("source_file"),
        "shuffle": bool(t["shuffle_options"]),
        "waiting": waiting,
        "playing": playing,
    }


@routes.get("/api/admin/topic-activity")
async def admin_topic_activity(request: web.Request):
    """Mavzular: oxirgi o'yin, jami duellar, oxirgi 30 kun, holat — saralash, filtr va sahifalash serverda."""
    require_admin(request)
    q = request.query
    status = q.get("status", "all")
    sort = q.get("sort", "name")
    if status not in ("all", "active", "inactive") or sort not in ADMIN_TOPIC_SORTS or q.get("dir", "asc") not in ("asc", "desc"):
        raise ApiError("Noto'g'ri so'rov")
    idle = _int_query(request, "idle", 0, 0, 3650)
    page = _int_query(request, "page", 1, 1, 100_000)
    per = _int_query(request, "per", 25, 5, 100)
    hub, db = request.app[HUB], request.app[DB]
    hub.catalog.ensure()
    data = db.admin_topic_page(status, q.get("q", "").strip()[:100], idle, sort, q.get("dir") == "desc",
                               (page - 1) * per, per, hub.catalog.month_all)
    return ok({
        "items": [admin_topic_json(t, hub) for t in data["items"]],
        "total": data["total"],
        "page": page,
        "per": per,
        "pages": max(1, -(-data["total"] // per)),
        "counts": data["counts"],
        "settings": topic_activity_settings(db),
    })


@routes.get("/api/admin/topic-activity/suggested")
async def admin_topic_suggested(request: web.Request):
    """O'chirishga tavsiya: faol, lekin N kundan beri o'ynalmagan mavzular (standart — sozlamadagi 90 kun)."""
    require_admin(request)
    db, hub = request.app[DB], request.app[HUB]
    days = _int_query(request, "days", topic_activity_settings(db)["suggestDays"], 1, 3650)
    page = _int_query(request, "page", 1, 1, 100_000)
    per = _int_query(request, "per", 25, 5, 100)
    hub.catalog.ensure()
    data = db.suggested_topics(days, (page - 1) * per, per)
    return ok({"days": days, "items": [admin_topic_json(t, hub) for t in data["items"]], "total": data["total"],
               "page": page, "per": per, "pages": max(1, -(-data["total"] // per))})


@routes.get("/api/admin/topic-activity/suggested/ids")
async def admin_topic_suggested_ids(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    days = _int_query(request, "days", topic_activity_settings(db)["suggestDays"], 1, 3650)
    ids = db.suggested_ids(days, MAX_BULK)
    return ok({"days": days, "ids": ids})


@routes.post("/api/admin/topic-activity/status")
async def admin_topic_status(request: web.Request):
    """Bir nechta mavzuni yopish yoki qayta ochish (yumshoq: savollar va duellar tarixi saqlanadi), jurnalga yoziladi."""
    user = require_admin(request)
    data = await read_json(request)
    ids, active = data.get("ids"), data.get("active")
    if not isinstance(ids, list) or not ids or len(ids) > MAX_BULK or not all(valid_id(x) for x in ids):
        raise ApiError(f"Mavzularni tanlang (bir martada ko'pi bilan {MAX_BULK} ta)")
    if not isinstance(active, bool):
        raise ApiError("Holatni ko'rsating")
    reason = "bulk" if len(ids) > 1 else "manual"
    if data.get("source") == "suggested":
        reason = "suggested"
    db, hub = request.app[DB], request.app[HUB]
    changed = db.set_topics_active(ids, active, user, reason)
    if not active:
        for t in changed:
            hub.topic_removed(t["id"], "Siz kutayotgan mavzu yopildi")
    if changed:
        hub.topics_changed()
    log.info("%s: %d ta mavzu %s", user["login"], len(changed), "ochildi" if active else "yopildi")
    return ok({"changed": len(changed), "topics": changed})


@routes.get("/api/admin/topic-activity/log")
async def admin_topic_log(request: web.Request):
    require_admin(request)
    page = _int_query(request, "page", 1, 1, 100_000)
    per = _int_query(request, "per", 25, 5, 100)
    data = request.app[DB].status_log((page - 1) * per, per)
    items = [{
        "id": r["id"], "topicId": r["topic_id"], "topicName": r["topic_name"], "active": bool(r["active"]),
        "by": r["changed_by_login"], "reason": r["reason"], "at": r["changed_at"],
    } for r in data["items"]]
    return ok({"items": items, "total": data["total"], "page": page, "per": per, "pages": max(1, -(-data["total"] // per))})


@routes.patch("/api/admin/topic-activity/settings")
async def admin_topic_settings(request: web.Request):
    """Tavsiya chegarasi (kun) va avtomatik yopish (0 — o'chiq, standart)."""
    user = require_admin(request)
    data = await read_json(request)
    db = request.app[DB]
    for key, setting, low in (("autoDeactivateDays", "auto_deactivate_days", 0), ("suggestDays", "suggest_idle_days", 1)):
        if key in data:
            value = data[key]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= 3650 or (key == "autoDeactivateDays" and 0 < value < 7):
                raise ApiError("Kunlar soni noto'g'ri (avtomatik yopish: 0 — o'chiq yoki 7–3650)")
            db.set_setting(setting, str(value))
            log.info("%s: %s = %d", user["login"], setting, value)
    return ok({"settings": topic_activity_settings(db)})


# --------------------------------------------- savollarni qo'lda boshqarish
def own_topic(request: web.Request) -> dict:
    topic = request.app[DB].get_topic(int_param(request, "tid"))
    if not topic:
        raise ApiError("Mavzu topilmadi", 404)
    return topic


def checked_question(data: dict) -> dict:
    try:
        return validate_question(data)
    except QuestionError as e:
        raise ApiError(str(e))


def question_json(q: dict) -> dict:
    return {"id": q["id"], "text": q["text"], "options": q["options"], "correct": q["correct"]}


@routes.post("/api/admin/topics/{tid}/questions")
async def admin_add_question(request: web.Request):
    """Mavzuga bitta savolni qo'lda qo'shish: savol bankka yoziladi va mavzuga biriktiriladi."""
    user = require_admin(request)
    data = await read_json(request)
    topic = own_topic(request)
    q = checked_question(data)
    db = request.app[DB]
    (qid,) = db.append_questions(topic["id"], [q], user_id=user["id"])
    request.app[HUB].topics_changed()
    return ok({"question": question_json(db.question_by_id(qid)), "topic": topic_json(db.get_topic(topic["id"]))}, status=201)


@routes.put("/api/admin/topics/{tid}/questions/{qid}")
async def admin_edit_question(request: web.Request):
    """Mavzudagi savolni tahrirlash (bankdagi savol o'zgaradi — u biriktirilgan barcha mavzularda)."""
    require_admin(request)
    data = await read_json(request)
    topic = own_topic(request)
    q = checked_question(data)
    db = request.app[DB]
    qid = int_param(request, "qid")
    if not db.question_by_id(qid, topic["id"]):
        raise ApiError("Savol topilmadi", 404)
    db.update_question(qid, q)
    return ok({"question": question_json(db.question_by_id(qid))})


@routes.delete("/api/admin/topics/{tid}/questions/{qid}")
async def admin_unlink_question(request: web.Request):
    """Savolni mavzudan olib tashlash — savol bankda qoladi."""
    require_admin(request)
    topic = own_topic(request)
    db = request.app[DB]
    if not db.unlink_question(topic["id"], int_param(request, "qid")):
        raise ApiError("Savol topilmadi", 404)
    request.app[HUB].topics_changed()
    return ok({"topic": topic_json(db.get_topic(topic["id"]))})


@routes.post("/api/admin/topics/{tid}/append")
async def admin_append_questions(request: web.Request):
    """Fayldagi savollarni bankka yozib, mavjud mavzu oxiriga biriktirish."""
    user = require_admin(request)
    data = await read_json(request)
    topic = own_topic(request)
    parsed = parse_questions(_check_content(data))
    if not parsed["questions"]:
        raise ApiError("Faylda yaroqli savol topilmadi. Fayl formatini tekshiring")
    db = request.app[DB]
    source = str(data.get("fileName") or "")[:255] or None
    before = topic["question_count"]
    res = db.add_questions(parsed["questions"], [topic["id"]], source, user["id"])
    topic = db.get_topic(topic["id"])
    log.info("Mavzuga savollar qo'shildi: %s (+%d) — %s", topic["name"], topic["question_count"] - before, user["login"])
    request.app[HUB].topics_changed()
    return ok({
        "topic": topic_json(topic),
        "added": topic["question_count"] - before,
        "created": res["created"],
        "skipped": len(parsed["errors"]),
    })


@routes.post("/api/admin/topics/{tid}/link")
async def admin_link_questions(request: web.Request):
    """Bankdagi tanlangan savollarni mavzuga biriktirish."""
    require_admin(request)
    data = await read_json(request)
    topic = own_topic(request)
    ids = question_ids_param(data.get("questionIds"))
    db = request.app[DB]
    linked = db.link_questions(topic["id"], ids)
    request.app[HUB].topics_changed()
    return ok({"linked": linked, "topic": topic_json(db.get_topic(topic["id"]))})


# ---------------------------------------------------------- savollar banki
MAX_SELECT = 5000


def question_ids_param(value) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ApiError("Savollarni tanlang")
    if len(value) > MAX_SELECT:
        raise ApiError(f"Bir martada {MAX_SELECT} tadan ko'p savol tanlab bo'lmaydi")
    if not all(valid_id(x) for x in value):
        raise ApiError("Savol identifikatorlari noto'g'ri")
    return value


def topic_ids_param(db, value) -> list[int]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 100 or not all(valid_id(x) for x in value):
        raise ApiError("Mavzular noto'g'ri tanlangan")
    for tid in value:
        if not db.get_topic(tid):
            raise ApiError("Mavzu topilmadi", 404)
    return list(dict.fromkeys(value))


def bank_filter(request: web.Request) -> dict:
    q = request.query
    search = " ".join(q.get("search", "").split())[:200]
    topic = q.get("topic", "")
    try:
        topic_id = int(topic) if topic not in ("", "none") else None
    except ValueError:
        raise ApiError("Mavzu noto'g'ri")
    if topic_id is not None and not valid_id(topic_id):
        raise ApiError("Mavzu noto'g'ri")
    return {"search": search, "topic_id": topic_id, "unassigned": topic == "none"}


@routes.get("/api/admin/bank")
async def admin_bank(request: web.Request):
    """Savollar banki: qidiruv, mavzu bo'yicha filtr ("none" — mavzusiz) va sahifalash."""
    require_admin(request)
    try:
        page = min(1_000_000, max(1, int(request.query.get("page", 1))))
        per = max(10, min(100, int(request.query.get("per", 30))))
    except ValueError:
        raise ApiError("Sahifa raqami noto'g'ri")
    total, items = request.app[DB].bank_page(**bank_filter(request), offset=(page - 1) * per, limit=per)
    return ok({"total": total, "page": page, "per": per, "questions": items})


@routes.get("/api/admin/bank/ids")
async def admin_bank_ids(request: web.Request):
    """Filtrga mos barcha savollar identifikatorlari ("hammasini tanlash" uchun)."""
    require_admin(request)
    return ok({"ids": request.app[DB].bank_ids(**bank_filter(request), limit=MAX_SELECT)})


@routes.post("/api/admin/bank")
async def admin_bank_create(request: web.Request):
    user = require_admin(request)
    data = await read_json(request)
    db = request.app[DB]
    topics = topic_ids_param(db, data.get("topicIds"))
    q = checked_question(data)
    res = db.add_questions([q], topics, None, user["id"])
    if topics:
        request.app[HUB].topics_changed()
    return ok({"question": question_json(db.question_by_id(res["ids"][0])), "created": res["created"]}, status=201)


@routes.post("/api/admin/bank/upload")
async def admin_bank_upload(request: web.Request):
    """Fayldagi savollarni bankka yuklash (ixtiyoriy: tanlangan mavzularga ham biriktirish)."""
    user = require_admin(request)
    data = await read_json(request)
    db = request.app[DB]
    topics = topic_ids_param(db, data.get("topicIds"))
    parsed = parse_questions(_check_content(data))
    if not parsed["questions"]:
        raise ApiError("Faylda yaroqli savol topilmadi. Fayl formatini tekshiring")
    source = str(data.get("fileName") or "")[:255] or None
    res = db.add_questions(parsed["questions"], topics, source, user["id"])
    log.info("Bankka %d ta yangi savol yuklandi (%d tasi bor edi) — %s", res["created"], res["reused"], user["login"])
    if topics:
        request.app[HUB].topics_changed()
    return ok({"created": res["created"], "reused": res["reused"], "skipped": len(parsed["errors"])})


@routes.put("/api/admin/bank/{qid}")
async def admin_bank_edit(request: web.Request):
    require_admin(request)
    data = await read_json(request)
    q = checked_question(data)
    db = request.app[DB]
    qid = int_param(request, "qid")
    if not db.update_question(qid, q):
        raise ApiError("Savol topilmadi", 404)
    return ok({"question": question_json(db.question_by_id(qid))})


@routes.delete("/api/admin/bank/{qid}")
async def admin_bank_delete(request: web.Request):
    """Savolni bankdan butunlay o'chirish (barcha mavzulardan ham)."""
    require_admin(request)
    topics = request.app[DB].delete_bank_question(int_param(request, "qid"))
    if topics is None:
        raise ApiError("Savol topilmadi", 404)
    if topics:
        request.app[HUB].topics_changed()
    return ok({"topics": len(topics)})


@routes.post("/api/admin/bank/delete")
async def admin_bank_delete_many(request: web.Request):
    """Tanlangan savollarni bankdan (va barcha mavzulardan) o'chirish."""
    user = require_admin(request)
    data = await read_json(request)
    deleted, topics = request.app[DB].delete_bank_questions(question_ids_param(data.get("questionIds")))
    log.info("Bankdan %d ta savol o'chirildi — %s", deleted, user["login"])
    if topics:
        request.app[HUB].topics_changed()
    return ok({"deleted": deleted, "topics": topics})


@routes.delete("/api/admin/topics/{tid}")
async def admin_delete_topic(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    tid = int_param(request, "tid")
    if not db.get_topic(tid):
        raise ApiError("Mavzu topilmadi", 404)
    request.app[HUB].topic_removed(tid)
    db.delete_topic(tid)
    request.app[HUB].topics_changed()
    return ok()


def admin_user_json(u: dict, hub) -> dict:
    owner = is_superadmin(u)
    return {
        "id": u["id"],
        "login": u["login"],
        "isAdmin": bool(u["is_admin"]) or owner,
        "isSuperadmin": owner,
        "isTeacher": bool(u.get("is_teacher")),  # o'qituvchi roli (administratorlarda bu huquq baribir bor)
        "blocked": bool(u["blocked"]),
        "createdAt": u["created_at"],
        "lastSeenAt": u.get("last_seen_at"),
        "duels": u.get("duels", 0),
        "practices": u.get("practices", 0),
        "balloonGames": u.get("balloon_games", 0),
        "online": hub.is_online(u["id"]),
    }


def settings_json(db) -> dict:
    return {"registrationOpen": registration_open(db)}


@routes.get("/api/admin/overview")
async def admin_overview(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    hub = request.app[HUB]
    stats = db.overview(now_ms() - 7 * 86_400_000)
    stats["users"]["online"] = len(hub.conns)
    duels = [
        {
            "id": d["id"],
            "topicName": d["topic_name"],
            "players": [d["p1_login"], d["p2_login"]],
            "score": [d["p1_correct"], d["p2_correct"]],
            "total": d["total"],
            "winner": d["winner"],
            "reason": d["reason"],
            "finishedAt": d["finished_at"],
        }
        for d in db.recent_duels()
    ]
    games = [{"id": g["id"], "owner": g["owner"], **balloon.summary(g["state"])} for g in db.recent_balloon_games()]
    users = [
        {
            "id": u["id"], "login": u["login"], "isAdmin": bool(u["is_admin"]) or is_superadmin(u), "isSuperadmin": is_superadmin(u),
            "isTeacher": bool(u["is_teacher"]), "blocked": bool(u["blocked"]), "createdAt": u["created_at"], "online": hub.is_online(u["id"]),
        }
        for u in db.recent_users()
    ]
    return ok({"stats": stats, "recentUsers": users, "recentDuels": duels, "recentGames": games, "settings": settings_json(db)})


@routes.get("/api/admin/settings")
async def admin_settings(request: web.Request):
    require_admin(request)
    return ok({"settings": settings_json(request.app[DB])})


@routes.patch("/api/admin/settings")
async def admin_update_settings(request: web.Request):
    user = require_superadmin(request)
    data = await read_json(request)
    db = request.app[DB]
    if "registrationOpen" in data:
        db.set_setting("registration_open", "1" if data["registrationOpen"] else "0")
        log.info("Ro'yxatdan o'tish %s — %s", "ochildi" if data["registrationOpen"] else "yopildi", user["login"])
    return ok({"settings": settings_json(db)})


@routes.get("/api/admin/users")
async def admin_users(request: web.Request):
    require_admin(request)
    hub = request.app[HUB]
    return ok({"users": [admin_user_json(u, hub) for u in request.app[DB].list_users()]})


@routes.post("/api/admin/users")
async def admin_create_user(request: web.Request):
    """Bosh administrator yangi akkaunt yaratadi (masalan, o'quvchilar uchun)."""
    me_user = require_superadmin(request)
    data = await read_json(request)
    login = str(data.get("login", "")).strip()
    password = str(data.get("password", ""))
    validate_login(login)
    validate_password(password)
    db = request.app[DB]
    if db.user_by_login(login) or reserved_login(db, login):
        raise ApiError("Bu login band. Boshqa login tanlang", 409)
    pass_hash = await in_thread(hash_password, password)
    try:
        user_id = db.create_user(login, pass_hash, bool(data.get("isAdmin")), bool(data.get("isTeacher")))
    except sqlite3.IntegrityError:
        raise ApiError("Bu login band. Boshqa login tanlang", 409)
    log.info("Administrator %s yangi foydalanuvchi yaratdi: %s", me_user["login"], login)
    return ok({"user": admin_user_json(db.user_by_id(user_id), request.app[HUB])}, status=201)


@routes.patch("/api/admin/users/{uid}")
async def admin_update_user(request: web.Request):
    me_user = require_superadmin(request)
    db = request.app[DB]
    uid = int_param(request, "uid")
    target = db.user_by_id(uid)
    if not target:
        raise ApiError("Foydalanuvchi topilmadi", 404)
    data = await read_json(request)
    hub = request.app[HUB]
    is_self = uid == me_user["id"]
    if ("isAdmin" in data or "isTeacher" in data or "blocked" in data) and is_self:
        raise ApiError("O'zingizning huquqlaringizni o'zgartira olmaysiz")
    password_hash = None
    if "password" in data:
        password = str(data["password"])
        validate_password(password)
        password_hash = await in_thread(hash_password, password)
    if not db.user_by_id(uid):  # kutish vaqtida o'chirilgan bo'lishi mumkin
        raise ApiError("Foydalanuvchi topilmadi", 404)
    could_teach = is_teacher(target)
    if "isAdmin" in data:
        db.set_admin(uid, bool(data["isAdmin"]))
    if "isTeacher" in data:
        db.set_teacher(uid, bool(data["isTeacher"]))
        log.info("%s: o'qituvchi roli %s — %s", target["login"], "berildi" if data["isTeacher"] else "olindi", me_user["login"])
    if "isAdmin" in data or "isTeacher" in data:
        fresh = db.user_by_id(uid)
        # foydalanuvchining ochiq oynalarida menyu darhol yangilanadi
        hub.send_user(uid, "account", {"isAdmin": bool(fresh["is_admin"]) or is_superadmin(fresh), "isTeacher": is_teacher(fresh)})
        if could_teach and not is_teacher(fresh):
            end_teacher_games(request.app, uid, "O'qituvchi huquqi olib qo'yildi — o'yin yakunlandi")
    if "blocked" in data:
        db.set_blocked(uid, bool(data["blocked"]))
        if data["blocked"]:
            hub.kick_user(uid, "blocked")
            end_teacher_games(request.app, uid, "O'yin yakunlandi")
            request.app[OCTAGON].drop_hosts(uid)
        log.info("%s %s — %s", target["login"], "bloklandi" if data["blocked"] else "blokdan chiqarildi", me_user["login"])
    if password_hash is not None:
        # o'z parolini o'zgartirgan administrator joriy qurilmada tizimda qoladi
        current = request.cookies.get(config.SESSION_COOKIE)
        keep = token_hash(current) if is_self and current else None
        db.set_password(uid, password_hash, keep_session=keep)
        request.app[OCTAGON].drop_hosts(uid, keep=keep)  # eski sessiyalardagi Octagon boshqaruv oynalari uziladi
        if not is_self:
            hub.kick_user(uid, "password")
    return ok({"user": admin_user_json(db.user_by_id(uid), hub)})


@routes.delete("/api/admin/users/{uid}")
async def admin_delete_user(request: web.Request):
    me_user = require_superadmin(request)
    db = request.app[DB]
    uid = int_param(request, "uid")
    if uid == me_user["id"]:
        raise ApiError("O'zingizni o'chira olmaysiz")
    if not db.user_by_id(uid):
        raise ApiError("Foydalanuvchi topilmadi", 404)
    request.app[HUB].purge_user(uid)
    end_teacher_games(request.app, uid, "O'yin yakunlandi")
    request.app[OCTAGON].drop_hosts(uid)
    db.delete_user(uid)
    return ok()
