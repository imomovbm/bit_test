#!/usr/bin/env python3
"""Octagon yuklama sinovi: bir vaqtda ko'p o'yin (eng kattasida 300 o'yinchi), qo'shilish, javoblar, qayta ulanish.

    python3 scripts/octagon_load.py                       # 20 o'yin: biri 300 o'yinchili, qolganlari 30 tadan
    python3 scripts/octagon_load.py --games 20 --big 300 --small 30 --questions 5 --json natija.json

Skript o'zi vaqtinchalik bazada server ishga tushiradi (TD_TRUST_PROXY=1 — har bir o'yinchi o'z X-Forwarded-For
manzili bilan, haqiqiy telefonlardagidek), o'qituvchilar, mavzu va o'yinlarni REST orqali yaratadi, so'ng har bir o'yinni
haqiqiy WebSocket ulanishlari bilan boshidan oxirigacha o'ynaydi. O'lchanadi (bitta jarayon soati bilan):
  * join — qo'shilish so'rovidan "w" (xush kelibsiz) javobigacha;
  * broadcast — o'qituvchi amali (start/next) yuborilgandan har bir o'yinchiga yangi bosqich yetib kelguncha;
  * answer — javob yuborilgandan tasdiq (s.a) kelguncha;
  * resume — qayta ulanish (resume) so'rovidan holat kelguncha; ball va ism saqlanganligi tekshiriladi;
  * api — o'yin davomida REST so'rovlari (mavzular, o'yinlar ro'yxati, o'yin holati).
Server protsessor vaqti va xotirasi (/proc) ham yoziladi.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO = None  # serverning protokol versiyasi (hello/"v" dan); v1 da yo'q

# v1 (eski) va v2 bosqich nomlari -> umumiy nomlar
PHASE = {"lobby": "lobby", "ready": "read", "question": "active", "reveal": "result", "leaderboard": "board", "podium": "podium",
         "intro": "intro", "read": "read", "active": "active", "result": "result", "board": "board"}


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))]


def summary(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": round(pct(values, 50), 1), "p95": round(pct(values, 95), 1),
            "p99": round(pct(values, 99), 1), "max": round(max(values), 1), "mean": round(statistics.fmean(values), 1)}


class Stats:
    def __init__(self):
        self.lat = defaultdict(list)
        self.c = Counter()
        self.errors = Counter()
        self.bytes_in = Counter()   # xabar turi -> o'quvchilarga kelgan baytlar
        self.msgs_in = Counter()


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


def http(method, url, body=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read() or b"null"), (r.headers.get("Set-Cookie") or "").split(";")[0]


class Player:
    def __init__(self, game, idx, ip):
        self.game, self.idx, self.ip = game, idx, ip
        self.nick = f"O'quvchi {idx}"
        self.ws = None
        self.id = self.tok = None
        self.state = {}
        self.waiters: list[tuple] = []  # (predikat, future)
        self.reader = None
        self.avatar = idx % 40

    async def connect(self, session, url):
        self.ws = await session.ws_connect(url, headers={"X-Forwarded-For": self.ip}, max_msg_size=0)
        self.reader = asyncio.create_task(self.read())

    async def read(self):
        st = self.game.stats
        try:
            async for msg in self.ws:
                if msg.type != 1:
                    break
                now = time.perf_counter()
                m = json.loads(msg.data)
                t, d = m.get("t"), m.get("d") or {}
                st.bytes_in[t] += len(msg.data)
                st.msgs_in[t] += 1
                if t == "s":
                    self.state = d
                elif t == "e" and d.get("c") != "late":  # kech javob — yuqorida alohida sanaladi
                    st.errors[f"e:{d.get('c')}"] += 1
                elif t == "w":
                    self.id = d.get("id") or self.id
                    self.tok = d.get("tok") or self.tok
                for item in list(self.waiters):
                    pred, fut = item
                    if not fut.done() and pred(t, d):
                        fut.set_result((now, t, d))
                        self.waiters.remove(item)
        except Exception as e:  # noqa: BLE001
            st.errors[f"reader:{type(e).__name__}"] += 1

    def wait(self, pred, timeout=30.0, current=False):
        """Kelgusi xabarni kutish; current=True — oxirgi holat allaqachon mos kelsa, darhol qaytadi."""
        fut = asyncio.get_running_loop().create_future()
        if current and self.state and pred("s", self.state):
            fut.set_result((time.perf_counter(), "s", self.state))
        else:
            self.waiters.append((pred, fut))
        return asyncio.wait_for(fut, timeout)

    async def send(self, t, d):
        await self.ws.send_str(json.dumps({"t": t, "d": d}, separators=(",", ":")))


class Game:
    def __init__(self, pin, cookie, n_players, stats, gi):
        self.pin, self.cookie, self.n, self.stats, self.gi = pin, cookie, n_players, stats, gi
        self.players: list[Player] = []
        self.host = None
        self.host_state = {}
        self.host_waiters = []


async def run_game(game: Game, session, base, ws_url, opts, rnd):
    st = game.stats
    host = await session.ws_connect(ws_url, headers={"Cookie": game.cookie, "X-Forwarded-For": f"10.250.{game.gi}.1"}, max_msg_size=0)

    async def host_reader():
        async for msg in host:
            if msg.type != 1:
                break
            m = json.loads(msg.data)
            if m.get("t") == "h":
                game.host_state = m["d"]
                for item in list(game.host_waiters):
                    pred, fut = item
                    if not fut.done() and pred(m["d"]):
                        fut.set_result(m["d"])
                        game.host_waiters.remove(item)
            elif m.get("t") == "e":
                st.errors[f"host:{m['d'].get('c')}"] += 1
    hr = asyncio.create_task(host_reader())

    def host_wait(pred, timeout=60.0, current=True):
        fut = asyncio.get_running_loop().create_future()
        if current and game.host_state and pred(game.host_state):  # holat allaqachon kelgan bo'lishi mumkin
            fut.set_result(game.host_state)
        else:
            game.host_waiters.append((pred, fut))
        return asyncio.wait_for(fut, timeout)

    async def host_send(t, d=None):
        await host.send_str(json.dumps({"t": t, "d": {"phase": game.host_state.get("phase"), "q": game.host_state.get("index"), **(d or {})}}))

    await host.send_str(json.dumps({"t": "host", "d": {"pin": game.pin}}))
    await host_wait(lambda h: True, current=False)

    # ------------------------------------------------------------- qo'shilish
    async def join(p: Player):
        await asyncio.sleep(rnd.uniform(0, opts.join_spread))
        await p.connect(session, ws_url)
        t0 = time.perf_counter()
        fut = p.wait(lambda t, d: t == "w")
        data = {"pin": game.pin, "nick": p.nick}
        if opts.avatars:
            data["av"] = p.avatar
        await p.send("join", data)
        try:
            t1, _, _ = await fut
            st.lat["join"].append((t1 - t0) * 1000)
            st.c["joined"] += 1
        except asyncio.TimeoutError:
            st.errors["join_timeout"] += 1
    game.players = [Player(game, i, f"10.{game.gi}.{i // 250}.{i % 250 + 1}") for i in range(game.n)]
    await asyncio.gather(*(join(p) for p in game.players))
    await host_wait(lambda h: h.get("playerCount") == game.n, timeout=30)

    async def broadcast(action, want_phase, extra=None):
        """O'qituvchi amali -> har bir o'yinchiga yangi bosqich yetib kelguncha bo'lgan vaqt."""
        futs = [p.wait(lambda t, d, w=want_phase: t == "s" and PHASE.get(d.get("p")) == w) for p in game.players if p.ws and not p.ws.closed]
        t0 = time.perf_counter()
        await host_send(action, extra)
        res = await asyncio.gather(*futs, return_exceptions=True)
        for r in res:
            if isinstance(r, tuple):
                st.lat[f"broadcast_{game.n}" if game.n >= 100 else "broadcast_small"].append((r[0] - t0) * 1000)
            else:
                st.errors[f"broadcast_timeout:{want_phase}"] += 1

    async def resume(p: Player):
        """Uzilib qayta ulanish: o'sha o'yinchi (id, ism, ball) davom etishi kerak."""
        before = p.state.get("sc")
        try:
            await p.ws.close()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(rnd.uniform(0.05, 0.4))
        await p.connect(session, ws_url)
        fut = p.wait(lambda t, d: t == "s")
        t0 = time.perf_counter()
        await p.send("resume", {"pin": game.pin, "id": p.id, "tok": p.tok})
        try:
            t1, _, d = await fut
            st.lat["resume"].append((t1 - t0) * 1000)
            st.c["resumed"] += 1
            if before is not None and d.get("sc") != before:
                st.errors["resume_score_changed"] += 1
        except asyncio.TimeoutError:
            st.errors["resume_timeout"] += 1

    await broadcast("start", "intro" if opts.v2 else "read")
    for qi in range(opts.questions):
        # o'qish bosqichi tugashini kutamiz (server taymeri), so'ng javoblar
        actives = [p.wait(lambda t, d, q=qi: t == "s" and PHASE.get(d.get("p")) == "active" and d.get("q") == q, timeout=40, current=True) for p in game.players]
        res = await asyncio.gather(*actives, return_exceptions=True)
        if any(not isinstance(r, tuple) for r in res):
            st.errors["active_timeout"] += sum(1 for r in res if not isinstance(r, tuple))
        # bir qismi shu savol paytida qayta ulanadi
        reconnecting = rnd.sample(game.players, max(1, int(len(game.players) * opts.reconnect_share))) if opts.reconnect_share else []

        async def answer(p: Player, q=qi):
            await asyncio.sleep(rnd.uniform(0.2, opts.answer_spread))
            if p in reconnecting:
                await resume(p)
            if PHASE.get(p.state.get("p")) != "active" or p.state.get("q") != q:
                st.c["closed_before_answer"] += 1  # savol yopilgan (hamma ulangan o'yinchi javob berdi) — kutilgan holat
                return
            fut = p.wait(lambda t, d: (t == "s" and d.get("a") is not None and d.get("q") == q) or (t == "e" and d.get("c") == "late"))
            t0 = time.perf_counter()
            await p.send("a", {"q": q, "o": rnd.randrange(4)})
            try:
                t1, t, _ = await fut
                if t == "e":
                    st.c["late_after_close"] += 1  # savol shu orada yopildi — kutilgan holat, xato emas
                else:
                    st.lat["answer"].append((t1 - t0) * 1000)
                    st.c["answers"] += 1
            except asyncio.TimeoutError:
                st.errors["answer_timeout"] += 1
        await asyncio.gather(*(answer(p) for p in game.players))
        await host_wait(lambda h: PHASE.get(h.get("phase")) == "result", timeout=30)
        await broadcast("next", "board")
        last = qi + 1 >= opts.questions
        await broadcast("next", "podium" if last else ("read"))
    # o'yin oxiri: hamma podiumni ko'rdi; o'yinchilar soni o'zgarmagan (dublikat yo'q)
    if game.host_state.get("playerCount") != game.n:
        st.errors["player_count_changed"] += 1
    for p in game.players:
        if p.reader:
            p.reader.cancel()
        await p.ws.close()
    hr.cancel()
    await host.close()


async def api_load(base, pairs, stats, deadline):
    loop = asyncio.get_running_loop()

    def one(url, cookie):
        t0 = time.perf_counter()
        try:
            http("GET", base + url, cookie=cookie)
        except Exception as e:  # noqa: BLE001
            stats.errors[f"api:{type(e).__name__}"] += 1
        return (time.perf_counter() - t0) * 1000
    i = 0
    while time.monotonic() < deadline:
        pin, cookie = pairs[i % len(pairs)]  # har bir o'qituvchi faqat o'z o'yinini so'raydi
        url = ["/api/octagon/topics", "/api/octagon/games", f"/api/octagon/games/{pin}", "/api/auth/me"][i % 4]
        ms = await loop.run_in_executor(None, one, url, cookie)
        stats.lat["api"].append(ms)
        i += 1
        await asyncio.sleep(0.05)


async def main_async(opts, port, pid):
    import aiohttp
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/ws/octagon"
    stats = Stats()
    _, _, owner = http("POST", base + "/api/auth/login", {"login": "admin", "password": "owner123"})
    content = "\n++++\n".join("\n====\n".join([f"Yuklama savoli {i + 1}?", "#Toʻgʻri", "Notoʻgʻri 1", "Notoʻgʻri 2", "Notoʻgʻri 3"]) for i in range(max(opts.questions, 5)))
    _, topic, _ = http("POST", base + "/api/admin/topics", {"name": "Yuklama", "content": content, "shuffle": False}, owner)
    teachers = []
    for k in range((opts.games + 4) // 5):
        login = f"ustoz{k}"
        http("POST", base + "/api/admin/users", {"login": login, "password": "1234", "isTeacher": True}, owner)
        _, _, cookie = http("POST", base + "/api/auth/login", {"login": login, "password": "1234"})
        teachers.append(cookie)
    games = []
    for gi in range(opts.games):
        cookie = teachers[gi // 5]
        _, res, _ = http("POST", base + "/api/octagon/games", {"topicId": topic["topic"]["id"], "timeLimit": opts.time, "questionCount": opts.questions,
                                                             "shuffleQuestions": False, "shuffleAnswers": False}, cookie)
        games.append(Game(res["game"]["pin"], cookie, opts.big if gi == 0 else opts.small, stats, gi))
    cpu0, _ = proc_sample(pid)
    rss_peak = 0.0
    t0 = time.monotonic()
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn, cookie_jar=aiohttp.DummyCookieJar()) as session:
        done = asyncio.Event()

        async def sampler():
            nonlocal rss_peak
            while not done.is_set():
                _, rss = proc_sample(pid)
                rss_peak = max(rss_peak, rss or 0)
                await asyncio.sleep(0.5)
        smp = asyncio.create_task(sampler())
        api = asyncio.create_task(api_load(base, [(g.pin, g.cookie) for g in games], stats, time.monotonic() + 3600))
        results = await asyncio.gather(*(run_game(g, session, base, ws_url, opts, random.Random(opts.seed + g.gi)) for g in games), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                stats.errors[f"game:{type(r).__name__}:{r}"[:120]] += 1
        api.cancel()
        done.set()
        await smp
    elapsed = time.monotonic() - t0
    cpu1, rss_end = proc_sample(pid)
    players = sum(g.n for g in games)
    total_msgs = sum(stats.c.values())
    big = f"broadcast_{opts.big}"
    return {
        "config": {"games": opts.games, "biggest": opts.big, "others": opts.small, "players": players, "questions": opts.questions,
                   "reconnectShare": opts.reconnect_share, "protocol": PROTO},
        "elapsedS": round(elapsed, 1),
        "latencyMs": {k: summary(v) for k, v in sorted(stats.lat.items())},
        "biggestGameBroadcastP95": summary(stats.lat.get(big, []))["p95"] if stats.lat.get(big) else None,
        "counters": dict(stats.c),
        "errors": dict(stats.errors),
        "errorRate": round(sum(stats.errors.values()) / max(1, total_msgs), 5),
        "studentBytesByType": dict(stats.bytes_in),
        "studentMsgsByType": dict(stats.msgs_in),
        "avgStudentMsgBytes": {t: round(stats.bytes_in[t] / max(1, stats.msgs_in[t]), 1) for t in stats.msgs_in},
        "server": {"cpuSeconds": round((cpu1 or 0) - (cpu0 or 0), 1), "cpuPercentOfOneCore": round(100 * ((cpu1 or 0) - (cpu0 or 0)) / elapsed, 1),
                   "rssPeakMB": round(rss_peak, 1), "rssEndMB": round(rss_end or 0, 1)},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--big", type=int, default=300)
    ap.add_argument("--small", type=int, default=30)
    ap.add_argument("--questions", type=int, default=5)
    ap.add_argument("--time", type=int, default=20)
    ap.add_argument("--join-spread", type=float, default=3.0, help="o'yinchilar shuncha soniya ichida qo'shiladi")
    ap.add_argument("--answer-spread", type=float, default=3.0)
    ap.add_argument("--reconnect-share", type=float, default=0.1, help="har bir savolda qayta ulanadigan o'yinchilar ulushi")
    ap.add_argument("--avatars", action="store_true", help="qo'shilishda avatar (v2)")
    ap.add_argument("--v2", action="store_true", help="v2 protokol (topic intro bosqichi)")
    ap.add_argument("--port", type=int, default=8798)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--env", action="append", default=[], help="server uchun qo'shimcha muhit o'zgaruvchisi KEY=VALUE")
    opts = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="octagon-load-"))
    env = dict(os.environ, TD_SUPERADMIN_PASSWORD="owner123", TD_TRUST_PROXY="1")
    for kv in opts.env:
        k, _, v = kv.partition("=")
        env[k] = v
    log = open(tmp / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "run.py", "--host", "127.0.0.1", "--port", str(opts.port), "--db", str(tmp / "load.db")],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{opts.port}/api/auth/me", timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        res = asyncio.run(main_async(opts, opts.port, proc.pid))
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if opts.json:
        opts.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    errs = (tmp / "server.log").read_text(errors="replace").count("Traceback")
    print(f"server jurnalidagi xatolar (Traceback): {errs}; jurnal: {tmp / 'server.log'}")
    return 0 if not res["errors"] and not errs else 1


if __name__ == "__main__":
    sys.exit(main())
