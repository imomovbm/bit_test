"""WebSocket ulanishlari: brauzer <-> DuelHub (/ws) va brauzer <-> OctagonHub (/ws/octagon)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque

from aiohttp import WSMsgType, web

from .api import client_ip
from .keys import HUB, OCTAGON, SOCKETS, USER

log = logging.getLogger("testduel.ws")


class Conn:
    """Bitta brauzer ulanishi. Xabarlar navbat orqali tartib bilan yuboriladi."""

    def __init__(self, ws: web.WebSocketResponse, compact: bool = False):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.ip = "?"
        self._separators = (",", ":") if compact else None

    def send(self, msg_type: str, data) -> None:
        if not self.closed:
            self.queue.put_nowait(json.dumps({"t": msg_type, "d": data}, ensure_ascii=False, separators=self._separators))

    def close(self, reason: str = "closed", code: int = 4401) -> None:
        """Ulanishni server tomonidan yopish (navbatdagi xabarlar yuborilgandan keyin).

        /ws: 4401 — mijozga "tizimdan chiqing" degani (sabab: reason).
        /ws/octagon: 4001 — boshqa oynada ochildi, 4002 — o'qituvchi chiqardi, 4003 — o'yin yopildi.
        """
        if not self.closed:
            self.closed = True
            self.queue.put_nowait((code, reason))

    async def writer(self) -> None:
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            if isinstance(msg, tuple):
                code, reason = msg
                try:
                    await self.ws.close(code=code, message=reason.encode()[:120])
                except Exception:
                    pass
                return
            try:
                await self.ws.send_str(msg)
            except Exception:  # ulanish uzilgan
                return


async def _finish(request: web.Request, ws, conn: Conn, writer: asyncio.Task) -> None:
    request.app[SOCKETS].discard(ws)
    conn.closed = True
    conn.queue.put_nowait(None)
    try:
        await asyncio.wait_for(writer, timeout=2)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        writer.cancel()


async def ws_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse(heartbeat=25.0, max_msg_size=64 * 1024)
    await ws.prepare(request)
    user = request.get(USER)
    if not user:
        await ws.close(code=4401, message=b"unauthorized")
        return ws

    hub = request.app[HUB]
    conn = Conn(ws)
    request.app[SOCKETS].add(ws)
    writer = asyncio.create_task(conn.writer())
    hub.connect(user, conn)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                payload = data.get("d")
                try:
                    hub.handle(user["id"], conn, data.get("t"), payload if isinstance(payload, dict) else {})
                except Exception:
                    log.exception("Xabarni qayta ishlashda xato: %r", data.get("t"))
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        conn.closed = True
        hub.disconnect(user["id"], conn)
        await _finish(request, ws, conn, writer)
    return ws


FLOOD_WINDOW = 10.0   # soniya
FLOOD_LIMIT = 60      # shu oraliqda ko'pi bilan shuncha xabar (javoblar, ping, qo'shilish urinishlari)


async def octagon_ws_handler(request: web.Request) -> web.StreamResponse:
    """Octagon: o'quvchilar (ro'yxatdan o'tmasdan, PIN + ism) va o'yinni boshqaradigan o'qituvchi uchun bitta kanal."""
    hub = request.app[OCTAGON]
    ip = client_ip(request)
    if not hub.socket_opened(ip):
        return web.json_response({"error": "Bu tarmoqdan juda ko'p ulanish"}, status=429)
    ws = web.WebSocketResponse(heartbeat=20.0, max_msg_size=4096)
    try:
        await ws.prepare(request)
    except Exception:
        hub.socket_closed(ip)
        raise
    conn = Conn(ws, compact=True)
    conn.ip = ip
    user = request.get(USER)  # o'qituvchi sessiyasi (o'quvchilar uchun None)
    request.app[SOCKETS].add(ws)
    writer = asyncio.create_task(conn.writer())
    loop = asyncio.get_running_loop()
    recent: deque = deque()
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                now = loop.time()
                recent.append(now)
                while recent and now - recent[0] > FLOOD_WINDOW:
                    recent.popleft()
                if len(recent) > FLOOD_LIMIT:
                    conn.close("flood", 4008)
                    break
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                payload = data.get("d")
                try:
                    hub.handle(conn, data.get("t"), payload if isinstance(payload, dict) else {}, user)
                except Exception:
                    log.exception("Octagon xabarida xato: %r", data.get("t"))
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        conn.closed = True
        hub.disconnect(conn)
        hub.socket_closed(ip)
        await _finish(request, ws, conn, writer)
    return ws
