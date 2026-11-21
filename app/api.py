"""REST API: ro'yxatdan o'tish, mavzular, o'rganish rejimi, Balloon Pop, statistika va boshqaruv."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re
import sqlite3
from urllib.parse import quote

from aiohttp import web

from . import balloon, config
from .db import now_ms
from .hub import prepare_question
from .keys import DB, HUB, USER
from .parser import format_questions, parse_questions
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
    except Exception:
        log.exception("Kutilmagan xato: %s %s", request.method, request.path)
        return web.json_response({"error": "Serverda kutilmagan xatolik yuz berdi"}, status=500, dumps=_dumps)


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


def is_superadmin(user: dict | None) -> bool:
    """Bosh administrator (tizim egasi) — login config.SUPERADMIN_LOGIN bo'lgan foydalanuvchi."""
    return bool(user) and user["login"].casefold() == config.SUPERADMIN_LOGIN.casefold()


def require_admin(request: web.Request) -> dict:
    user = require_user(request)
    if not (user["is_admin"] or is_superadmin(user)):
        raise ApiError("Bu amal faqat administrator uchun", 403)
    return user


def require_superadmin(request: web.Request) -> dict:
    user = require_admin(request)
    if not is_superadmin(user):
        raise ApiError("Foydalanuvchilarni faqat bosh administrator boshqaradi", 403)
    return user


def int_param(request: web.Request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except (KeyError, ValueError):
        raise ApiError("Noto'g'ri identifikator", 404)


def public_user(user: dict) -> dict:
    owner = is_superadmin(user)
    return {"id": user["id"], "login": user["login"], "isAdmin": bool(user["is_admin"]) or owner, "isSuperadmin": owner}


def reserved_login(db, login: str) -> bool:
    """Bosh administrator logini band: bazada boshqa foydalanuvchilar bo'lsa, uni hech kim egallay olmaydi."""
    return login.casefold() == config.SUPERADMIN_LOGIN.casefold() and db.count_users() > 0


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
        "sourceFile": t.get("source_file"),
        "createdAt": t["created_at"],
        "createdBy": t.get("created_by"),
    }


def client_ip(request: web.Request) -> str:
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
        secure=request.secure,
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
    topics = [topic_json(t) for t in request.app[DB].list_topics() if t["question_count"] > 0]
    return ok({"topics": topics})


@routes.get("/api/topics/{tid}/practice")
async def practice_questions(request: web.Request):
    require_user(request)
    db = request.app[DB]
    topic = db.get_topic(int_param(request, "tid"))
    if not topic:
        raise ApiError("Mavzu topilmadi", 404)
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
    user = require_user(request)
    game = request.app[DB].balloon_game(int_param(request, "gid"))
    if not game or game["owner_id"] != user["id"]:
        raise ApiError("O'yin topilmadi", 404)
    return game


@routes.get("/api/balloon/games")
async def balloon_list(request: web.Request):
    user = require_user(request)
    games = [{"id": g["id"], **balloon.summary(g["state"])} for g in request.app[DB].balloon_games(user["id"])]
    return ok({"games": games})


@routes.post("/api/balloon/games")
async def balloon_create(request: web.Request):
    user = require_user(request)
    data = await read_json(request)
    try:
        settings = balloon.clean_settings(data)
    except balloon.GameError as e:
        raise ApiError(str(e), e.status)
    db = request.app[DB]
    topic_id = data.get("topicId")
    topic = db.get_topic(topic_id) if isinstance(topic_id, int) and not isinstance(topic_id, bool) else None
    if not topic:
        if topic_id is None:
            raise ApiError("Mavzuni tanlang")
        raise ApiError("Mavzu topilmadi — u o'chirilgan bo'lishi mumkin", 404)
    if topic["question_count"] < 1:
        raise ApiError("Bu mavzuda savollar yo'q")
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
    parsed = parse_questions(_check_content(data))
    if not parsed["questions"]:
        raise ApiError("Faylda yaroqli savol topilmadi. Fayl formatini tekshiring")
    source = str(data.get("fileName") or "")[:255] or None
    try:
        topic_id = db.create_topic(name, parsed["questions"], bool(data.get("shuffle", True)), source, user["id"])
    except sqlite3.IntegrityError:
        raise ApiError("Bunday nomli mavzu allaqachon bor. Boshqa nom kiriting", 409)
    log.info("Yangi mavzu: %s (%d savol) — %s", name, len(parsed["questions"]), user["login"])
    request.app[HUB].broadcast("topics", {})
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
    db.replace_topic_questions(tid, parsed["questions"], source)
    log.info("Mavzu yangilandi: %s (%d savol) — %s", topic["name"], len(parsed["questions"]), user["login"])
    request.app[HUB].broadcast("topics", {})
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
    db.update_topic(tid, name=name, shuffle=shuffle)
    request.app[HUB].broadcast("topics", {})
    return ok({"topic": topic_json(db.get_topic(tid))})


@routes.delete("/api/admin/topics/{tid}")
async def admin_delete_topic(request: web.Request):
    require_admin(request)
    db = request.app[DB]
    tid = int_param(request, "tid")
    if not db.get_topic(tid):
        raise ApiError("Mavzu topilmadi", 404)
    request.app[HUB].topic_removed(tid)
    db.delete_topic(tid)
    request.app[HUB].broadcast("topics", {})
    return ok()


def admin_user_json(u: dict, hub) -> dict:
    owner = is_superadmin(u)
    return {
        "id": u["id"],
        "login": u["login"],
        "isAdmin": bool(u["is_admin"]) or owner,
        "isSuperadmin": owner,
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
            "blocked": bool(u["blocked"]), "createdAt": u["created_at"], "online": hub.is_online(u["id"]),
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
        user_id = db.create_user(login, pass_hash, bool(data.get("isAdmin")))
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
    if ("isAdmin" in data or "blocked" in data) and is_self:
        raise ApiError("O'zingizning huquqlaringizni o'zgartira olmaysiz")
    password_hash = None
    if "password" in data:
        password = str(data["password"])
        validate_password(password)
        password_hash = await in_thread(hash_password, password)
    if not db.user_by_id(uid):  # kutish vaqtida o'chirilgan bo'lishi mumkin
        raise ApiError("Foydalanuvchi topilmadi", 404)
    if "isAdmin" in data:
        db.set_admin(uid, bool(data["isAdmin"]))
        hub.send_user(uid, "account", {"isAdmin": bool(data["isAdmin"])})
    if "blocked" in data:
        db.set_blocked(uid, bool(data["blocked"]))
        if data["blocked"]:
            hub.kick_user(uid, "blocked")
        log.info("%s %s — %s", target["login"], "bloklandi" if data["blocked"] else "blokdan chiqarildi", me_user["login"])
    if password_hash is not None:
        # o'z parolini o'zgartirgan administrator joriy qurilmada tizimda qoladi
        current = request.cookies.get(config.SESSION_COOKIE)
        db.set_password(uid, password_hash, keep_session=token_hash(current) if is_self and current else None)
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
    db.delete_user(uid)
    return ok()
