"""Parollar, sessiya tokenlari va so'rovlar chastotasini cheklash."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import deque

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, key_hex = stored.split("$")
        if algo != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(key_hex) // 2,
        )
        return hmac.compare_digest(key.hex(), key_hex)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Bazada tokenning o'zi emas, faqat uning xeshi saqlanadi."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """Oddiy sirpanuvchi oyna: `window` soniya ichida `limit` tadan ortiq urinishga ruxsat bermaydi."""

    PRUNE_ABOVE = 2048  # kalitlar shundan ko'p bo'lsa, oynada bir marta eskirganlari tozalanadi

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = {}
        self._pruned = float("-inf")

    def _bucket(self, key: str) -> deque:
        now = time.monotonic()
        if len(self._hits) > self.PRUNE_ABOVE and now - self._pruned > self.window:
            self._prune(now)
        bucket = self._hits.setdefault(key, deque())
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        return bucket

    def _prune(self, now: float) -> None:
        """Oxirgi urinishi oynadan tashqarida qolgan kalitlar o'chiriladi: ko'p turli IP dan so'rovlarda ham xotira
        cheklangan (eng ko'pi ~2 oyna davomidagi IP lar) va bu ish har chaqiruvda emas, oynada bir marta bajariladi."""
        cutoff = now - self.window
        self._hits = {k: v for k, v in self._hits.items() if v and v[-1] >= cutoff}
        self._pruned = now

    def blocked(self, key: str) -> bool:
        return len(self._bucket(key)) >= self.limit

    def count(self, key: str) -> int:
        """Oxirgi `window` soniyadagi urinishlar soni."""
        return len(self._bucket(key))

    def hit(self, key: str) -> None:
        self._bucket(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
