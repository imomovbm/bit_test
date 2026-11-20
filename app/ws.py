"""WebSocket ulanishlari: brauzer <-> DuelHub."""
from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import WSMsgType, web

from .keys import HUB, SOCKETS, USER

log = logging.getLogger("testduel.ws")


class Conn:
    """Bitta brauzer ulanishi. Xabarlar navbat orqali tartib bilan yuboriladi."""

    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def send(self, msg_type: str, data) -> None:
        if not self.closed:
            self.queue.put_nowait(json.dumps({"t": msg_type, "d": data}, ensure_ascii=False))

    def close(self, reason: str = "closed") -> None:
        """Ulanishni server tomonidan yopish. 4401 kodi mijozga "tizimdan chiqing" degani (sabab: reason)."""
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(None)
            asyncio.ensure_future(self.ws.close(code=4401, message=reason.encode()[:120]))

    async def writer(self) -> None:
        while True:
            msg = await self.queue.get()
            if msg is None:
                return
            try:
                await self.ws.send_str(msg)
            except Exception:  # ulanish uzilgan
                return


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
        request.app[SOCKETS].discard(ws)
        conn.closed = True
        conn.queue.put_nowait(None)
        hub.disconnect(user["id"], conn)
        try:
            await asyncio.wait_for(writer, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            writer.cancel()
    return ws
