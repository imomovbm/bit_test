"""Foydalanuvchi rollari: bosh administrator, administrator, o'qituvchi, oddiy foydalanuvchi.

  * bosh administrator (tizim egasi) — login ``config.SUPERADMIN_LOGIN``; hamma narsani boshqaradi;
  * administrator (``users.is_admin``) — mavzular va savollar banki; o'qituvchi huquqlari ham bor;
  * o'qituvchi (``users.is_teacher``) — «O'yinlar» paneli: Balloon Pop va Octagon o'yinlarini yaratadi va boshqaradi;
  * oddiy foydalanuvchi — duel, o'rganish, reyting.
"""
from __future__ import annotations

from . import config


def is_superadmin(user: dict | None) -> bool:
    """Bosh administrator (tizim egasi) — login config.SUPERADMIN_LOGIN bo'lgan foydalanuvchi."""
    return bool(user) and user["login"].casefold() == config.SUPERADMIN_LOGIN.casefold()


def is_admin(user: dict | None) -> bool:
    return bool(user) and (bool(user.get("is_admin")) or is_superadmin(user))


def is_teacher(user: dict | None) -> bool:
    """O'yinlarni yaratish va boshqarish huquqi: o'qituvchi roli yoki administrator."""
    return bool(user) and (bool(user.get("is_teacher")) or is_admin(user))
