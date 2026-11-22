"""Testlar uchun umumiy sozlash."""
import pytest

from app import api


@pytest.fixture(autouse=True)
def fresh_http_rate_limits():
    """Modul darajasidagi chegaralar (ro'yxatdan o'tish va login xatolari, IP bo'yicha) butun test jarayoni uchun bitta:
    hamma testlar 127.0.0.1 dan keladi. Har bir test toza holatdan boshlansin — aks holda testlar soni oshgani sari
    keyingi fayllardagi ro'yxatdan o'tish chegaraga urilib, testlar tartibga bog'liq holda yiqiladi."""
    for limiter in (api.registrations, api.login_failures):
        limiter._hits.clear()
    yield
