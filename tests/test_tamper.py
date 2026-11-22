"""Qurilmadagi ma'lumotlarni o'zgartirish (tamper) testlari — haqiqiy server va WebSocket orqali.

Qoida (README «Qurilmada saqlash»): telefonda faqat qayta ulanish yozuvi (o'yin PIN i bo'yicha: id, token, ism, avatar),
oxirgi ism/avatar va interfeys sozlamalari saqlanadi. O'zgartirilgan localStorage/cookie faqat mijoz serverga
YUBORADIGAN narsani o'zgartira oladi — shuning uchun bu yerda aynan shunday xabarlar yuboriladi va server natijani
o'zgartirmasligi tekshiriladi: ball, ism, avatar, rol, boshqa o'yinchining tokeni, soxta vaqt.
(Brauzerdagi haqiqiy localStorage/Date.now o'zgartirish — e2e/octagon.e2e.js.)
"""
import asyncio

import pytest

from app import config
from test_octagon_api import call, recv, recv_state
from test_octagon_security import world


@pytest.fixture(autouse=True)
def short_phases(monkeypatch):
    monkeypatch.setattr(config, "OCTAGON_INTRO", 0.05)
    monkeypatch.setattr(config, "OCTAGON_READ", 0.05)


async def joined(client, pin, nick, av=0):
    ws = await client.ws_connect("/ws/octagon")
    await ws.send_json({"t": "join", "d": {"v": 2, "pin": pin, "nick": nick, "av": av}})
    return ws, await recv(ws, "w")


async def host_socket(client, pin):
    ws = await client.ws_connect("/ws/octagon")
    await ws.send_json({"t": "host", "d": {"v": 2, "pin": pin}})
    await recv(ws, "h")
    return ws


def test_tampered_reconnect_record_cannot_change_score_name_avatar_or_role(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a, questionCount=2, timeLimit=20)
            ws, me = await joined(w.guest, pin, "Ali", av=3)
            host = await host_socket(w.a, pin)
            await host.send_json({"t": "start", "d": {}})
            s = await recv_state(ws, "question_active")
            await ws.send_json({"t": "a", "d": {"q": s["q"], "o": 3}})   # noto'g'ri javob — 0 ball
            await ws.close()
            # o'zgartirilgan yozuv: o'zining id/token i + ball, ism, avatar, rol "o'zgartirilgan"
            forged = {"v": 2, "pin": pin, "id": me["id"], "tok": me["tok"], "sc": 99999, "score": 99999, "nick": "Admin",
                      "av": 29, "role": "teacher", "isTeacher": True, "host": True, "at": 4102444800000}
            ws2 = await w.guest.ws_connect("/ws/octagon")
            await ws2.send_json({"t": "resume", "d": forged})
            again = await recv(ws2, "w")
            state = await recv(ws2, "s")
            assert again["nick"] == "Ali" and again["av"] == 3 and state["sc"] == 0
            for t in ("start", "next", "skip", "end", "kick", "lock"):   # rol mijoz yozuvidan olinmaydi
                await ws2.send_json({"t": t, "d": {"id": me["id"]}})
                assert (await recv(ws2, "e"))["status"] == 403, t
            game = (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
            assert game["playerCount"] == 1 and game["phase"] in ("question_active", "question_result")
            await ws2.close()
            await host.close()
    asyncio.run(body())


def test_another_players_token_from_storage_is_useless(tmp_path):
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a)
            a, wa = await joined(w.guest, pin, "Ali")
            b, wb = await joined(w.student, pin, "Vali")
            attempts = [
                {"id": wb["id"], "tok": wa["tok"]},      # o'z tokeni + boshqa o'yinchi ID si
                {"id": wa["id"], "tok": wb["tok"]},      # aksincha
                {"id": wb["id"], "tok": wb["tok"][:-1] + ("A" if wb["tok"][-1] != "A" else "B")},  # bitta belgi farq
                {"id": wb["id"], "tok": wb["tok"], "pin": "999999"},  # boshqa o'yin PIN i bilan
            ]
            for data in attempts:
                c = await w.client()
                ws = await c.ws_connect("/ws/octagon")
                await ws.send_json({"t": "resume", "d": {"v": 2, "pin": pin, **data}})
                err = await recv(ws, "e")
                assert err["c"] in ("gone", "pin"), data
                await ws.close()
            # haqiqiy egalari ulanganicha qoldi, o'yinchi qo'shilmadi
            await b.send_json({"t": "ping", "d": {}})
            game = (await call(w.a, "GET", f"/api/octagon/games/{pin}"))[1]["game"]
            assert game["playerCount"] == 2 and game["connectedCount"] == 2
            await a.close()
            await b.close()
    asyncio.run(body())


def test_fake_client_time_changes_nothing(tmp_path):
    """Telefon soati noto'g'ri yoki ataylab o'zgartirilgan: bosqich vaqtlari va javob vaqti faqat server soatidan."""
    async def body():
        async with world(tmp_path) as w:
            pin = await w.game(w.a, questionCount=1, timeLimit=20)
            ws, _ = await joined(w.guest, pin, "Ali")
            for c in (4102444800000, -1, "kecha", None, {"x": 1}, 10**30):
                await ws.send_json({"t": "sync", "d": {"c": c}})
                reply = await recv(ws, "sync")
                assert isinstance(reply["s"], int) and (reply["c"] is None or reply["c"] == c)
            host = await host_socket(w.a, pin)
            await host.send_json({"t": "start", "d": {}})
            s = await recv_state(ws, "question_active")
            h = await recv(host, "h")
            while h["phase"] != "question_active":
                h = await recv(host, "h")
            assert (s["ps"], s["pe"]) == (h["phaseStart"], h["phaseEnd"])   # o'quvchi va o'qituvchi — bir xil server vaqtlari
            await ws.send_json({"t": "a", "d": {"q": s["q"], "o": 0, "t": 0, "ms": 0, "time": 0, "ts": 1, "at": 0, "elapsed": 0}})
            res = await recv_state(ws, "question_result")
            assert res["res"]["ok"] is True and 500 <= res["res"]["pts"] <= 1000  # ball server o'lchagan vaqtdan
            await ws.close()
            await host.close()
    asyncio.run(body())
