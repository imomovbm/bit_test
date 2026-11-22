#!/usr/bin/env python3
"""TestDuel yuklama sinovi (load test): bosh sahifa, lobbi (juftlash) va boshqaruv ro'yxati.

Ma'lumotlar: 5 000 mavzu, 20 000 foydalanuvchi, bir yillik duellar (standart — kuniga ~1 500 ta, ~550 ming duel).
Yuklama: 500 ta bir vaqtda raqib qidirayotgan WebSocket mijozi (seek yaratish, lobbidan bir bosishda qo'shilish,
duelni o'ynash, qayta qidirish) + bosh sahifa katalogi va boshqaruv ro'yxatiga parallel HTTP so'rovlar.

Ishga tushirish (loyiha ildizidan, faqat ilovaning o'z bog'liqliklari — aiohttp — kerak):

    python3 scripts/loadtest.py                    # birinchi marta baza yaratiladi (~1-2 daqiqa), keyin sinov
    python3 scripts/loadtest.py --reseed           # bazani qaytadan yaratish
    python3 scripts/loadtest.py --duration 120 --seekers 500 --json natija.json
    python3 scripts/loadtest.py --explain          # asosiy so'rovlarning EXPLAIN QUERY PLAN natijalari

Sinov alohida bazada ishlaydi (standart: <vaqtinchalik katalog>/testduel-loadtest/loadtest.db) — ishchi bazaga tegmaydi.
Barcha mijozlar bitta kompyuterdan ulanadi, shuning uchun server TD_TRUST_PROXY=1 bilan ishga tushiriladi va har bir
mijoz o'z X-Forwarded-For manziliga ega (IP bo'yicha cheklovlar haqiqiy holatdagidek alohida hisoblanadi).
Duel savollari soni sinovda kamaytirilgan (--questions, standart 5): bu juftlash davrlarini ko'paytiradi.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import secrets
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.catalog import TopicCatalog  # noqa: E402
from app.db import Database, now_ms  # noqa: E402
from app.security import hash_password, token_hash  # noqa: E402

DAY = 86_400_000
SUBJECTS = ["Matematika", "Fizika", "Kimyo", "Biologiya", "Tarix", "Geografiya", "Adabiyot", "Ingliz tili", "Rus tili",
            "Informatika", "Iqtisodiyot", "Huquq", "Falsafa", "Psixologiya", "Astronomiya", "Statistika", "Algoritmlar",
            "Python", "Maʼlumotlar bazasi", "Tarmoqlar", "Elektrotexnika", "Tibbiyot", "Pedagogika", "Sotsiologiya"]


# =============================================================== baza yaratish
def seed(path: Path, opts) -> dict:
    rnd = random.Random(opts.seed)
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{path}{suffix}")
        if p.exists():
            p.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    db = Database(path)
    conn = db.conn
    now = now_ms()
    pw = hash_password(secrets.token_hex(8))  # hamma uchun bitta xesh (kirish sessiyalar orqali)
    with db.tx():
        conn.execute("INSERT INTO users (login, login_key, pass_hash, is_admin, is_teacher, created_at) VALUES ('admin', 'admin', ?, 1, 1, ?)",
                     (pw, now - 400 * DAY))
        conn.executemany(
            "INSERT INTO users (login, login_key, pass_hash, is_admin, is_teacher, created_at) VALUES (?, ?, ?, 0, 0, ?)",
            [(f"user{i:05d}", f"user{i:05d}", pw, now - rnd.randint(0, opts.days) * DAY) for i in range(opts.users)])
    admin_id = conn.execute("SELECT id FROM users WHERE login_key = 'admin'").fetchone()[0]
    user_ids = [r[0] for r in conn.execute("SELECT id FROM users WHERE login_key != 'admin' ORDER BY id")]
    logins = {uid: f"user{i:05d}" for i, uid in enumerate(user_ids)}
    t_users = time.perf_counter()

    topic_ids, names = [], {}
    for i in range(opts.topics):
        name = f"{SUBJECTS[i % len(SUBJECTS)]} — {i // len(SUBJECTS) + 1}-mavzu"
        qs = [{"text": f"{name}: savol {k + 1}?", "options": [f"Javob A{k}", f"Javob B{k}", f"Javob C{k}", f"Javob D{k}"], "correct": k % 4}
              for k in range(opts.questions_per_topic)]
        tid = db.create_topic(name, qs, True, None, admin_id)
        topic_ids.append(tid)
        names[tid] = name
    with db.tx():
        conn.executemany("UPDATE topics SET created_at = ? WHERE id = ?",
                         [(now - rnd.randint(opts.days // 2, opts.days + 300) * DAY, tid) for tid in topic_ids])
        inactive = rnd.sample(topic_ids, int(len(topic_ids) * 0.04))
        conn.executemany("UPDATE topics SET active = 0 WHERE id = ?", [(tid,) for tid in inactive])
    t_topics = time.perf_counter()

    # Mashhurlik: Zipf taqsimoti; ~28% mavzu hech o'ynalmagan; ba'zilari faqat ma'lum davrda (mavsumiy) yoki yaqinda paydo bo'lgan.
    played = rnd.sample(topic_ids, int(len(topic_ids) * 0.72))
    weight = {tid: 1.0 / (rank + 1) ** 1.05 for rank, tid in enumerate(played)}
    window = {}
    for tid in played:
        kind = rnd.random()
        if kind < 0.55:
            window[tid] = (0, opts.days)
        elif kind < 0.80:
            a = rnd.randint(0, opts.days - 30)
            window[tid] = (a, min(opts.days, a + rnd.randint(14, 120)))
        else:
            window[tid] = (rnd.randint(opts.days - 60, opts.days - 1), opts.days)
    insert = """INSERT INTO duels (topic_id, topic_name, p1_id, p2_id, p1_login, p2_login, p1_correct, p2_correct,
                                   p1_time_ms, p2_time_ms, total, winner, reason, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 15, ?, 'score', ?, ?)"""
    total_duels, batch = 0, []
    for d in range(opts.days):
        day_start = now - (opts.days - d) * DAY
        eligible = [tid for tid in played if window[tid][0] <= d < window[tid][1]]
        if not eligible:
            continue
        picks = rnd.choices(eligible, [weight[t] for t in eligible], k=int(opts.duels_per_day * rnd.uniform(0.7, 1.3)))
        for tid in picks:
            a, b = rnd.sample(user_ids, 2)
            started = day_start + rnd.randint(0, DAY - 1)
            if started > now - 120_000:
                continue
            c1, c2 = rnd.randint(0, 15), rnd.randint(0, 15)
            batch.append((tid, names[tid], a, b, logins[a], logins[b], c1, c2, rnd.randint(30_000, 200_000),
                          rnd.randint(30_000, 200_000), 1 if c1 > c2 else 2 if c2 > c1 else 0, started, started + rnd.randint(40_000, 230_000)))
        if len(batch) >= 50_000 or d == opts.days - 1:
            with db.tx():
                conn.executemany(insert, batch)
            total_duels += len(batch)
            batch = []
    t_duels = time.perf_counter()
    summary = db.backfill_activity()
    t_backfill = time.perf_counter()

    # Sessiyalar: seekerlar (user00000…), HTTP mijozlari va administrator — parol bilan kirish shart emas.
    tokens = {}
    with db.tx():
        for uid in [admin_id] + user_ids[:opts.seekers + 100]:
            token = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (token_hash(token), uid, now, now + 60 * DAY))
            tokens["admin" if uid == admin_id else logins[uid]] = token
    db.close()
    meta = {
        "topics": opts.topics, "users": opts.users, "days": opts.days, "duels": total_duels,
        "seedSeconds": {"users": round(t_users - t0, 2), "topics": round(t_topics - t_users, 2),
                        "duels": round(t_duels - t_topics, 2), "backfill": round(t_backfill - t_duels, 2)},
        "backfill": summary, "tokens": tokens, "createdAt": now,
    }
    Path(f"{path}.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


# ===================================================================== EXPLAIN
def explain(path: Path) -> list[tuple[str, str, list[str]]]:
    """Asosiy so'rovlar (bosh sahifa reytingi, boshqaruv ro'yxati, tavsiya, juftlash, faollik yozish) rejalari."""
    db = Database(path)
    captured: list[str] = []
    db.conn.set_trace_callback(captured.append)
    out = []

    def run(label, fn):
        captured.clear()
        fn()
        for sql in list(captured):
            head = sql.lstrip().split()[0].upper()
            if head not in ("SELECT", "UPDATE", "INSERT", "WITH", "DELETE"):
                continue
            db.conn.set_trace_callback(None)
            try:
                plan = [row[3] for row in db.conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
            except Exception as e:  # noqa: BLE001
                plan = [f"(reja olinmadi: {e})"]
            db.conn.set_trace_callback(captured.append)
            out.append((label, " ".join(sql.split())[:400], plan))

    class Clock:
        @staticmethod
        def now():
            return time.monotonic()

    cat = TopicCatalog(db, Clock(), lambda tid: (0, 0))
    run("Bosh sahifa: reyting keshini qurish (hot/today/week/month/all)", cat.rebuild)
    for sort in ("name", "lastPlayed", "total", "status", "created", "recent"):
        run(f"Boshqaruv: ro'yxat, saralash={sort}", lambda s=sort: db.admin_topic_page("all", "", 0, s, True, 0, 25, cat.month_all))
    run("Boshqaruv: filtr idle=90 + faol", lambda: db.admin_topic_page("active", "", 90, "lastPlayed", False, 0, 25, cat.month_all))
    run("Boshqaruv: nom bo'yicha qidiruv", lambda: db.admin_topic_page("all", "matem", 0, "name", False, 0, 25, cat.month_all))
    run("Boshqaruv: o'chirishga tavsiya (90 kun)", lambda: db.suggested_topics(90, 0, 25))
    run("Boshqaruv: tavsiya — barcha id (ommaviy yopish)", lambda: db.suggested_ids(90))
    uid = db.conn.execute("SELECT id FROM users WHERE login_key = 'user00001'").fetchone()[0]
    run("Juftlash: foydalanuvchining oxirgi mavzulari (istalgan mavzu)", lambda: db.recent_topics(uid, 5))
    run("Reyting sahifasi (leaderboard)", lambda: db.leaderboard())
    run("Boshqaruv: umumiy ko'rinish (duellar soni, oxirgi duellar)", lambda: (db.overview(now_ms() - 7 * DAY), db.recent_duels()))
    tid = db.conn.execute("SELECT id FROM topics WHERE active = 1 ORDER BY id LIMIT 1").fetchone()[0]
    run("Duel boshlanishi: faollikni yozish", lambda: db.record_duel_start(tid, [uid, uid + 1]))
    db.close()
    return out


# =================================================================== o'lchovlar
def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def summary_ms(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": round(pct(values, 50), 1), "p95": round(pct(values, 95), 1),
            "p99": round(pct(values, 99), 1), "max": round(max(values), 1), "mean": round(statistics.fmean(values), 1)}


class Stats:
    def __init__(self):
        self.lat = defaultdict(list)      # nom -> [ms]
        self.status = defaultdict(Counter)
        self.c = Counter()
        self.errors = Counter()
        self.diff_gaps: list[float] = []  # bitta mijozga ketma-ket kelgan lobby:diff xabarlari orasidagi vaqt (s)
        self.propagation: list[float] = []
        self.time_to_pair: list[float] = []
        # atomiklikni tekshirish: seek egasi, seekka qo'shilib yutganlar, duel ishtirokchilari
        self.seek_owner: dict[str, int] = {}
        self.join_wins: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.duel_members: dict[str, list[int]] = defaultdict(list)
        self.double_duel = 0


async def http_worker(session, base, headers, make_url, name, stats, deadline, think=(0.0, 0.15)):
    while time.monotonic() < deadline:
        url = make_url()
        t0 = time.perf_counter()
        try:
            async with session.get(base + url, headers=headers) as r:
                await r.read()
                code = r.status
        except Exception as e:  # noqa: BLE001
            code = type(e).__name__
        stats.lat[name].append((time.perf_counter() - t0) * 1000)
        stats.status[name][code] += 1
        await asyncio.sleep(random.uniform(*think))


ACTION_TIMEOUT = 15.0  # server javobini kutish (seek:create / seek:join / seek:cancel)


async def seeker(idx, session, ws_url, token, hot_ids, stats, start_at, deadline, rnd):
    """Bitta o'yinchi: lobbiga obuna, seek yaratadi yoki birovnikiga qo'shiladi, duelni o'ynaydi, takrorlaydi.

    Holatlar: connecting -> idle -> seeking -> waiting -> (cancelling) | joining -> duel -> connecting ...
    Server javoblari kechiksa ham holat buzilmaydi: har bir javob qaysi so'rovga tegishli ekani holatdan aniqlanadi."""
    await asyncio.sleep(max(0.0, start_at - time.monotonic()))
    headers = {"Cookie": f"{config.SESSION_COOKIE}={token}", "X-Forwarded-For": f"10.{idx // 250}.{idx % 250}.{rnd.randint(1, 254)}"}
    t0 = time.perf_counter()
    try:
        ws = await session.ws_connect(ws_url, headers=headers, max_msg_size=0, autoping=True)
    except Exception as e:  # noqa: BLE001
        stats.errors[f"connect:{type(e).__name__}"] += 1
        return
    stats.lat["ws_connect"].append((time.perf_counter() - t0) * 1000)
    seeks: dict[str, dict] = {}
    state = "connecting"
    sub_sent = None
    action_at = 0.0
    sent_at = 0.0            # oxirgi amal yuborilgan payt (monotonic) — javob kutish muddati uchun
    pending_join = None      # (seekId, perf_counter)
    seek_sent = None
    seek_open_at = None
    patience = 0.0
    last_diff = None
    in_duel = None
    watch = rnd.sample(hot_ids[:60], min(24, len(hot_ids[:60])))

    async def send(t, d=None):
        await ws.send_str(json.dumps({"t": t, "d": d or {}}))

    seen: set[str] = set()
    sub_wall = 0

    async def subscribe():
        nonlocal sub_sent, sub_wall
        sub_sent = time.perf_counter()
        sub_wall = now_ms()
        await send("lobby:sub", {"watch": watch})

    def go_idle(now, lo=0.3, hi=1.5):
        nonlocal state, action_at, pending_join
        state, action_at, pending_join = "idle", now + rnd.uniform(lo, hi), None

    try:
        while True:
            now = time.monotonic()
            if now >= deadline and state not in ("duel", "joining", "seeking"):
                break
            if now >= deadline + 30:
                break
            if state == "idle":
                timeout = max(0.01, action_at - now)
            elif state == "waiting":
                timeout = max(0.01, patience - now)
            elif state in ("seeking", "joining", "cancelling"):
                timeout = max(0.01, sent_at + ACTION_TIMEOUT - now)
            else:
                timeout = 5.0
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout)
            except asyncio.TimeoutError:
                msg = None
            if msg is not None:
                if msg.type != 1:  # TEXT
                    stats.c["closed_by_server"] += 1
                    break
                m = json.loads(msg.data)
                t, d = m.get("t"), m.get("d")
                now = time.monotonic()
                if t == "hello":
                    await subscribe()
                elif t == "lobby":
                    stats.lat["lobby_snapshot"].append((time.perf_counter() - sub_sent) * 1000)
                    seeks = {s["id"]: s for s in d["seeks"]}
                    seen.update(seeks)
                    last_diff = None
                    if state == "connecting":
                        go_idle(now, 0.1, 1.5)
                elif t == "lobby:diff":
                    stats.c["diffs"] += 1
                    if last_diff is not None:
                        stats.diff_gaps.append(now - last_diff)
                    last_diff = now
                    for sid in d.get("del", []):
                        seeks.pop(sid, None)
                    wall = now_ms()
                    for s in d.get("add", []):
                        seeks[s["id"]] = s
                        # yangi seekning boshqa mijozlarga yetib borish vaqti: faqat obunadan keyin yaratilgan va birinchi
                        # marta ko'rilganlar (eski seek "eng yangi 50 ta" oynasiga qaytib kirsa — bu kechikish emas)
                        if not s["mine"] and s["id"] not in seen and s["since"] >= sub_wall:
                            stats.propagation.append(wall - s["since"])
                        seen.add(s["id"])
                elif t == "queue":
                    if d:
                        stats.seek_owner[d["seekId"]] = idx
                        if state == "seeking":
                            state = "waiting"
                            seek_open_at = now
                            patience = now + rnd.uniform(25, 90)
                    elif state in ("waiting", "cancelling"):
                        stats.c["seek_cancelled" if state == "cancelling" else "seek_ended_unpaired"] += 1
                        go_idle(now, 0.3, 2.0)
                elif t == "duel:start":
                    if in_duel is not None:
                        stats.double_duel += 1  # bir o'yinchi bir vaqtda ikkita duelda — bo'lmasligi kerak
                    in_duel = d["duelId"]
                    stats.duel_members[in_duel].append(idx)
                    if state == "joining" and pending_join:
                        stats.c["join_won"] += 1
                        stats.join_wins[pending_join[0]].append((idx, in_duel))
                        stats.lat["join_to_duel"].append((time.perf_counter() - pending_join[1]) * 1000)
                    elif state == "seeking":
                        stats.c["instant_pair"] += 1
                        stats.lat["seek_to_duel_instant"].append((time.perf_counter() - seek_sent) * 1000)
                    elif state in ("waiting", "cancelling"):
                        stats.c["paired_while_waiting"] += 1
                        stats.time_to_pair.append(now - seek_open_at)
                    else:
                        stats.c[f"duel_start_in_{state}"] += 1
                    pending_join = None
                    state = "duel"
                    await send("lobby:unsub")
                elif t == "duel:question":
                    await send("duel:answer", {"duelId": d["duelId"], "index": d["index"], "choice": rnd.randrange(len(d["options"]))})
                elif t in ("duel:end", "duel:cancel"):
                    stats.c["duel_end" if t == "duel:end" else "duel_cancel"] += 1
                    in_duel = None
                    state = "connecting"
                    await subscribe()
                elif t == "error":
                    code = d.get("code") or "other"
                    if code == "taken":
                        stats.c["join_taken"] += 1
                        if d.get("seekId"):
                            seeks.pop(d["seekId"], None)
                    else:
                        stats.errors[f"ws:{code}"] += 1
                    if state in ("joining", "seeking"):
                        go_idle(now)
                continue
            now = time.monotonic()
            if state == "idle" and now >= action_at and now < deadline:
                others = sorted((s for s in seeks.values() if not s["mine"]), key=lambda s: -s["since"])
                sent_at = now
                if others and rnd.random() < 0.6:
                    target = rnd.choice(others[:8])  # eng yangilari — bir nechta o'yinchi bir seekka urinadi (poyga)
                    pending_join = (target["id"], time.perf_counter())
                    state = "joining"
                    stats.c["join_attempt"] += 1
                    await send("seek:join", {"seekId": target["id"]})
                else:
                    topic = None if rnd.random() < 0.1 else rnd.choice(hot_ids[:200] if rnd.random() < 0.7 else hot_ids)
                    seek_sent = time.perf_counter()
                    state = "seeking"
                    stats.c["seek_create"] += 1
                    await send("seek:create", {"topicId": topic})
            elif state == "waiting" and now >= patience:
                sent_at = now
                state = "cancelling"  # bekor qilish tasdig'ini (queue: null) kutamiz — shu orada juftlanish ham mumkin
                await send("seek:cancel")
            elif state in ("joining", "seeking", "cancelling") and now >= sent_at + ACTION_TIMEOUT:
                stats.errors[f"timeout:{state}"] += 1
                go_idle(now, 1.0, 1.0)
    except Exception as e:  # noqa: BLE001
        stats.errors[f"seeker:{type(e).__name__}"] += 1
    finally:
        await ws.close()


def verify_atomicity(stats: Stats) -> dict:
    """Har bir seekni ko'pi bilan bitta o'yinchi yutadi; har bir duelda aynan 2 ishtirokchi; seek egasi aynan o'sha duelda."""
    multi_win = sum(1 for wins in stats.join_wins.values() if len(wins) > 1)
    bad_duels = sum(1 for members in stats.duel_members.values() if len(members) != 2 or len(set(members)) != 2)
    owner_mismatch = 0
    for sid, wins in stats.join_wins.items():
        if len(wins) != 1:
            continue
        joiner, duel = wins[0]
        owner = stats.seek_owner.get(sid)
        if owner is None or owner not in stats.duel_members.get(duel, ()) or owner == joiner:
            owner_mismatch += 1
    return {"seeksWonByMoreThanOne": multi_win, "duelsWithout2Players": bad_duels, "joinOwnerMismatch": owner_mismatch,
            "playerInTwoDuels": stats.double_duel, "duelsObserved": len(stats.duel_members)}


def proc_sample(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split(")")[-1].split()
        ticks = int(parts[11]) + int(parts[12])
        with open(f"/proc/{pid}/status") as f:
            rss = next(int(line.split()[1]) for line in f if line.startswith("VmRSS"))
        return ticks / os.sysconf("SC_CLK_TCK"), rss / 1024
    except Exception:  # noqa: BLE001
        return None, None


async def run_load(opts, meta, port, server_pid) -> dict:
    import aiohttp

    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/ws"
    tokens = meta["tokens"]
    stats = Stats()
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn, cookie_jar=aiohttp.DummyCookieJar()) as session:
        def h(login, ip):
            return {"Cookie": f"{config.SESSION_COOKIE}={tokens[login]}", "X-Forwarded-For": ip}

        # sovuq ishga tushish: birinchi so'rov reyting keshini quradi
        t0 = time.perf_counter()
        async with session.get(f"{base}/api/topics/browse?period=hot&limit=60", headers=h("user00999" if "user00999" in tokens else "admin", "10.9.9.9")) as r:
            hot = (await r.json())["items"]
        cold_ms = (time.perf_counter() - t0) * 1000
        pages = []
        for off in range(0, 600, 60):
            async with session.get(f"{base}/api/topics/browse?period=hot&offset={off}&limit=60", headers=h("admin", "10.9.9.8")) as r:
                pages += [t["id"] for t in (await r.json())["items"]]
        hot_ids = pages or [t["id"] for t in hot]

        cpu0, _ = proc_sample(server_pid)
        start = time.monotonic()
        deadline = start + opts.duration
        tasks = []
        seekers = [k for k in tokens if k != "admin"][:opts.seekers]
        for i, login in enumerate(seekers):
            tasks.append(asyncio.create_task(seeker(i, session, ws_url, tokens[login], hot_ids, stats,
                                                    start + opts.ramp * i / max(1, len(seekers)), deadline, random.Random(opts.seed + 100 + i))))
        browse_users = [k for k in tokens if k != "admin"][opts.seekers:opts.seekers + opts.browsers]
        terms = ["matem", "tarix", "fizika", "python", "kimyo", "2-mavzu", "tarmoq", "zz-yo'q"]

        def browse_url():
            period = random.choice(["hot", "hot", "today", "week", "month", "all"])
            offset = random.choice([0, 0, 0, 24, 48, 96, 480])
            q = f"&q={random.choice(terms)}" if random.random() < 0.15 else ""
            return f"/api/topics/browse?period={period}&offset={offset}&limit=24{q}"

        for j, login in enumerate(browse_users):
            tasks.append(asyncio.create_task(http_worker(session, base, h(login, f"10.200.{j}.1"), browse_url, "main_page_browse", stats, deadline)))

        def admin_url():
            r = random.random()
            if r < 0.7:
                sort = random.choice(["name", "lastPlayed", "total", "recent", "status", "created"])
                return (f"/api/admin/topic-activity?sort={sort}&dir={random.choice(['asc', 'desc'])}&status={random.choice(['all', 'all', 'active', 'inactive'])}"
                        f"&idle={random.choice([0, 0, 30, 90, 180])}&page={random.randint(1, 8)}&per=25")
            if r < 0.85:
                return f"/api/admin/topic-activity/suggested?days={random.choice([30, 90, 180])}&page={random.randint(1, 4)}"
            return "/api/admin/topic-activity/log"

        for j in range(opts.admins):
            tasks.append(asyncio.create_task(http_worker(session, base, h("admin", f"10.250.{j}.1"), admin_url, "admin_list", stats, deadline, (0.05, 0.3))))
        other = [("/api/stats/leaderboard", "leaderboard"), ("/api/admin/overview", "admin_overview"), ("/api/topics", "legacy_all_topics")]
        for url, name in other:
            tasks.append(asyncio.create_task(http_worker(session, base, h("admin", "10.251.0.1"), lambda u=url: u, name, stats, deadline, (0.5, 1.0))))

        rss_peak = 0.0
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            _, rss = proc_sample(server_pid)
            rss_peak = max(rss_peak, rss or 0)
        await asyncio.wait(tasks, timeout=40)
        for t in tasks:
            t.cancel()
        elapsed = time.monotonic() - start
        cpu1, rss_end = proc_sample(server_pid)

    c = stats.c
    joins = c["join_attempt"]
    atomic = verify_atomicity(stats)
    resolved_seeks = c["instant_pair"] + c["paired_while_waiting"] + c["seek_ended_unpaired"]
    actions = c["join_attempt"] + c["seek_create"]
    errors = sum(stats.errors.values())
    return {
        "config": {"seekers": len(seekers), "browsers": len(browse_users), "admins": opts.admins, "duration": opts.duration,
                   "duelQuestions": opts.questions, "topics": meta["topics"], "users": meta["users"], "duels": meta["duels"]},
        "coldRankingBuildMs": round(cold_ms, 1),
        "latencyMs": {k: summary_ms(v) for k, v in sorted(stats.lat.items())},
        "httpStatus": {k: dict(v) for k, v in stats.status.items()},
        "throughputRps": {k: round(len(v) / elapsed, 1) for k, v in stats.lat.items() if k in ("main_page_browse", "admin_list")},
        "lobby": {
            "snapshotMs": summary_ms(stats.lat["lobby_snapshot"]),
            "seekPropagationMs": summary_ms(stats.propagation),
            "gapBetweenDiffsPerClientS": {"min": round(min(stats.diff_gaps), 3) if stats.diff_gaps else None,
                                          "p1": round(pct(stats.diff_gaps, 1), 3) if stats.diff_gaps else None,
                                          "p50": round(pct(stats.diff_gaps, 50), 3) if stats.diff_gaps else None},
            "diffMessages": c["diffs"],
        },
        "pairing": {
            "joinAttempts": joins,
            "joinWon": c["join_won"],
            "joinLostRace": c["join_taken"],
            "atomicity": atomic,
            "seeksCreated": c["seek_create"],
            "instantPairs": c["instant_pair"],
            "pairedWhileWaiting": c["paired_while_waiting"],
            "seeksExpiredOrClosed": c["seek_ended_unpaired"],
            "seeksCancelledByUser": c["seek_cancelled"],
            "timeToPairS": summary_ms(stats.time_to_pair),
            # seek natijasi: darhol yoki kutish paytida juftlandi / muddati tugadi (foydalanuvchi bekor qilganlari hisobga olinmaydi)
            "seekPairSuccessRate": round((c["instant_pair"] + c["paired_while_waiting"]) / max(1, resolved_seeks), 4),
            "joinSuccessRate": round(c["join_won"] / max(1, joins), 4),
            "errorRate": round(errors / max(1, actions), 5),
            "duelsFinished": c["duel_end"], "duelsCancelled": c["duel_cancel"],
        },
        "errors": dict(stats.errors),
        "counters": dict(c),
        "server": {"cpuSeconds": round((cpu1 or 0) - (cpu0 or 0), 1), "cpuPercentOfOneCore": round(100 * ((cpu1 or 0) - (cpu0 or 0)) / elapsed, 1),
                   "rssPeakMB": round(rss_peak, 1), "rssEndMB": round(rss_end or 0, 1)},
    }


def start_server(db_path: Path, port: int, opts, log_path: Path):
    env = dict(os.environ, TD_TRUST_PROXY="1", TD_DUEL_QUESTIONS=str(opts.questions))
    env.pop("TD_SUPERADMIN_PASSWORD", None)
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, "run.py", "--host", "127.0.0.1", "--port", str(port), "--db", str(db_path)],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    import urllib.request
    for _ in range(300):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/me", timeout=1).read()
            return proc
        except Exception:  # noqa: BLE001
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    proc.kill()
    raise SystemExit(f"Server ishga tushmadi, jurnal: {log_path}")


def print_report(res: dict, meta: dict) -> None:
    print("\n=== Ma'lumotlar ===")
    print(f"mavzular: {meta['topics']}, foydalanuvchilar: {meta['users']}, duellar: {meta['duels']} ({meta['days']} kun)")
    print(f"baza yaratish (s): {meta['seedSeconds']}  backfill: {meta['backfill']}")
    print(f"\nreyting keshi sovuq qurilishi (birinchi so'rov): {res['coldRankingBuildMs']} ms")
    print("\n=== Kechikish (ms) ===")
    print(f"{'nom':28} {'n':>7} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}")
    for k, v in res["latencyMs"].items():
        if v.get("n"):
            print(f"{k:28} {v['n']:>7} {v['p50']:>8} {v['p95']:>8} {v['p99']:>8} {v['max']:>8}")
    print("\nHTTP holatlari:", res["httpStatus"])
    print("O'tkazuvchanlik (so'rov/s):", res["throughputRps"])
    print("\n=== Lobbi ===")
    print(json.dumps(res["lobby"], ensure_ascii=False))
    print("\n=== Juftlash ===")
    print(json.dumps(res["pairing"], ensure_ascii=False, indent=1))
    print("xatolar:", res["errors"])
    print("server:", res["server"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path(tempfile.gettempdir()) / "testduel-loadtest" / "loadtest.db")
    ap.add_argument("--reseed", action="store_true", help="bazani qaytadan yaratish")
    ap.add_argument("--topics", type=int, default=5000)
    ap.add_argument("--users", type=int, default=20000)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--duels-per-day", type=int, default=1500)
    ap.add_argument("--questions-per-topic", type=int, default=10)
    ap.add_argument("--seekers", type=int, default=500)
    ap.add_argument("--browsers", type=int, default=25, help="bosh sahifani parallel so'rayotgan HTTP mijozlar")
    ap.add_argument("--admins", type=int, default=2)
    ap.add_argument("--duration", type=float, default=90.0)
    ap.add_argument("--ramp", type=float, default=10.0, help="seekerlar shuncha soniya ichida bosqichma-bosqich ulanadi")
    ap.add_argument("--questions", type=int, default=5, help="sinovdagi duel savollari soni (TD_DUEL_QUESTIONS)")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--json", type=Path, help="natijani JSON faylga yozish")
    ap.add_argument("--explain", action="store_true", help="faqat EXPLAIN QUERY PLAN natijalarini chiqarish")
    opts = ap.parse_args(argv)

    meta_path = Path(f"{opts.db}.json")
    if opts.reseed or not opts.db.exists() or not meta_path.exists():
        print(f"Baza yaratilmoqda: {opts.db} …", flush=True)
        meta = seed(opts.db, opts)
        print(f"tayyor: {meta['duels']} duel, {meta['seedSeconds']}", flush=True)
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if opts.explain:
        for label, sql, plan in explain(opts.db):
            print(f"\n-- {label}\n{sql}")
            for line in plan:
                print(f"   {line}")
        return 0
    log_path = opts.db.parent / "server.log"
    proc = start_server(opts.db, opts.port, opts, log_path)
    try:
        res = asyncio.run(run_load(opts, meta, opts.port, proc.pid))
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    res["seed"] = {k: meta[k] for k in ("topics", "users", "days", "duels", "seedSeconds", "backfill")}
    print_report(res, meta)
    if opts.json:
        opts.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    a = res["pairing"]["atomicity"]
    ok = not (a["seeksWonByMoreThanOne"] or a["duelsWithout2Players"] or a["joinOwnerMismatch"] or a["playerInTwoDuels"])
    print("atomiklik:", "OK" if ok else "BUZILDI", a)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
