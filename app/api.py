"""REST API: ro'yxatdan o'tish, mavzular, o'rganish rejimi, statistika va boshqaruv."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3

from aiohttp import web

from . import config
from .hub import prepare_question
from .keys import DB, HUB, USER
from .parser import parse_questions
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


def require_admin(request: web.Request) -> dict:
    user = require_user(request)
    if not user["is_admin"]:
        raise ApiError("Bu amal faqat administrator uchun", 403)
    return user


def int_param(request: web.Request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except (KeyError, ValueError):
        raise ApiError("Noto'g'ri identifikator", 404)


def public_user(user: dict) -> dict:
    return {"id": user["id"], "login": user["login"], "isAdmin": bool(user["is_admin"])}


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
    if not LOGIN_RE.fullmatch(login):
        raise ApiError("Login 3–32 ta harf, raqam yoki . _ - belgilaridan iborat bo'lishi kerak")
    validate_password(password)
    ip = client_ip(request)
    if registrations.blocked(ip):
        raise ApiError("Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring", 429)
    db = request.app[DB]
    if db.user_by_login(login):
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
    return ok({"user": public_user(user) if user else None})


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


@routes.get("/api/admin/users")
async def admin_users(request: web.Request):
    require_admin(request)
    hub = request.app[HUB]
    users = [
        {
            "id": u["id"],
            "login": u["login"],
            "isAdmin": bool(u["is_admin"]),
            "createdAt": u["created_at"],
            "duels": u["duels"],
            "practices": u["practices"],
            "online": hub.is_online(u["id"]),
        }
        for u in request.app[DB].list_users()
    ]
    return ok({"users": users})


@routes.patch("/api/admin/users/{uid}")
async def admin_update_user(request: web.Request):
    me_user = require_admin(request)
    db = request.app[DB]
    uid = int_param(request, "uid")
    target = db.user_by_id(uid)
    if not target:
        raise ApiError("Foydalanuvchi topilmadi", 404)
    data = await read_json(request)
    if "isAdmin" in data:
        if uid == me_user["id"]:
            raise ApiError("O'zingizning huquqlaringizni o'zgartira olmaysiz")
        db.set_admin(uid, bool(data["isAdmin"]))
    if "password" in data:
        password = str(data["password"])
        validate_password(password)
        db.set_password(uid, await in_thread(hash_password, password))
    return ok()


@routes.delete("/api/admin/users/{uid}")
async def admin_delete_user(request: web.Request):
    me_user = require_admin(request)
    db = request.app[DB]
    uid = int_param(request, "uid")
    if uid == me_user["id"]:
        raise ApiError("O'zingizni o'chira olmaysiz")
    if not db.user_by_id(uid):
        raise ApiError("Foydalanuvchi topilmadi", 404)
    request.app[HUB].purge_user(uid)
    db.delete_user(uid)
    return ok()
