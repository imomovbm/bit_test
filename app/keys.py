"""aiohttp ilovasida saqlanadigan obyektlar uchun kalitlar."""
from aiohttp import web

from .db import Database
from .hub import DuelHub
from .octagon import OctagonHub

DB = web.AppKey("db", Database)
HUB = web.AppKey("hub", DuelHub)
OCTAGON = web.AppKey("octagon", OctagonHub)
SOCKETS = web.AppKey("sockets", set)

# aiohttp 3.14+ so'rov ma'lumotlari uchun RequestKey'ni tavsiya qiladi; eski versiyalarda oddiy satr.
_RequestKey = getattr(web, "RequestKey", None)
USER = _RequestKey("user", dict) if _RequestKey else "user"
