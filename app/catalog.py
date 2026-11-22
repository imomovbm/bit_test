"""Bosh sahifa mavzular katalogi: reytinglar, "qizg'in" ball, qidiruv va kesh.

Reytinglar faqat kichik jadvallardan quriladi (``topics`` hisoblagichlari va ``topic_activity_daily``) — duellar
jadvali hech qachon sanalmaydi. Natija xotirada keshlanadi va quyidagi hollarda qayta quriladi:
  * mavzular o'zgarsa (yaratish, o'chirish, yopish, nom yoki savollar soni) — darhol;
  * yangi duel boshlangan bo'lsa — oxirgi qurilganidan ``config.RANKING_REFRESH`` soniya o'tgach;
  * aks holda — har ``config.RANKING_TTL`` soniyada (kun almashishi va "qizg'in" ball so'nishi uchun).
Sahifa so'rovlari keshdan o'qiladi (SQL so'rovsiz); "hozir kutmoqda / o'ynamoqda" sonlari esa har safar jonli.

Davrlar (mahalliy vaqt, config.TZ_OFFSET_HOURS):
  today — bugungi kun; week — oxirgi 7 kun (bugun bilan); month — oxirgi 30 kun; all — hamma vaqt (topics.total_duels);
  hot — "qizg'in": hot_score() (config.HOT_*), yaqindagi faollik eski jami sondan ustun.
Tartib: davrdagi duellar soni (ko'p), so'ng qizg'in ball, oxirgi o'yin (yangi), nom. Davrda faolligi bo'lmagan
mavzular faollardan keyin: oxirgi o'ynalgani (yangi) bo'yicha, hech o'ynalmaganlari — nom bo'yicha.
"""
from __future__ import annotations

import math

from . import config
from .db import day_back, day_key, name_key, now_ms

PERIODS = ("hot", "today", "week", "month", "all")
MAX_SEARCH = 100  # qidiruv so'zi uzunligi


def hot_weight(age_days: int) -> float:
    """Kunlik vazn: bugun — 1, HOT_HALF_LIFE_DAYS kun oldin — 0.5 va h.k.; HOT_WINDOW_DAYS dan eskisi — 0."""
    if age_days < 0 or age_days >= config.HOT_WINDOW_DAYS:
        return 0.0
    return 0.5 ** (age_days / config.HOT_HALF_LIFE_DAYS)


def hot_score(by_age: dict[int, int], live: int = 0) -> float:
    """Qizg'in ball: Σ duellar(d kun oldin) · 0.5^(d / yarim yemirilish) + HOT_LIVE_WEIGHT · hozirgi faollik."""
    return sum(n * hot_weight(age) for age, n in by_age.items()) + config.HOT_LIVE_WEIGHT * live


class TopicCatalog:
    def __init__(self, db, clock, live_counts=None):
        self.db = db
        self.clock = clock
        self.live_counts = live_counts or (lambda topic_id: (0, 0))  # mavzu -> (kutayotganlar, o'ynayotgan duellar)
        self.topics: dict[int, dict] = {}       # o'ynash mumkin bo'lgan mavzular
        self.order: dict[str, list[int]] = {}   # davr -> tartiblangan mavzu identifikatorlari
        self.counts: dict[str, dict[int, float]] = {}
        self.month_all: dict[int, int] = {}     # oxirgi 30 kun — barcha mavzular (boshqaruv paneli uchun)
        self.built_at = -math.inf
        self.built_day = ""
        self.rebuilds = 0
        self._topics_dirty = True
        self._activity_dirty = False

    # ----------------------------------------------------------- belgilar
    def topics_changed(self) -> None:
        self._topics_dirty = True

    def activity_changed(self) -> None:
        self._activity_dirty = True

    def ensure(self) -> None:
        age = self.clock.now() - self.built_at
        if (self._topics_dirty or age >= config.RANKING_TTL
                or (self._activity_dirty and age >= config.RANKING_REFRESH)):
            self.rebuild()

    # ------------------------------------------------------------ qurish
    def rebuild(self) -> None:
        today = day_key(now_ms())
        week_from, month_from = day_back(today, 6), day_back(today, 29)
        oldest = day_back(today, max(29, config.HOT_WINDOW_DAYS - 1))
        weights = {day_back(today, d): hot_weight(d) for d in range(config.HOT_WINDOW_DAYS)}
        cases = " ".join("WHEN ? THEN ?" for _ in weights)
        args = [a for item in weights.items() for a in item]
        rows = self.db.conn.execute(
            f"""SELECT topic_id,
                       SUM(CASE WHEN day = ? THEN duels_started ELSE 0 END),
                       SUM(CASE WHEN day >= ? THEN duels_started ELSE 0 END),
                       SUM(CASE WHEN day >= ? THEN duels_started ELSE 0 END),
                       SUM(duels_started * (CASE day {cases} ELSE 0 END))
                FROM topic_activity_daily INDEXED BY idx_activity_day WHERE day >= ? GROUP BY topic_id""",
            [today, week_from, month_from, *args, oldest],
        ).fetchall()
        topics = {t["id"]: t for t in self.db.playable_topics()}
        today_c, week_c, month_c, hot_c = {}, {}, {}, {}
        for tid, n_today, n_week, n_month, hot in rows:
            if tid not in topics:
                continue
            today_c[tid], week_c[tid], month_c[tid], hot_c[tid] = n_today, n_week, n_month, hot
        self.month_all = {tid: n for tid, _, _, n, _ in rows if n}
        for tid in topics:
            waiting, playing = self.live_counts(tid)
            if waiting or playing:
                hot_c[tid] = hot_c.get(tid, 0.0) + config.HOT_LIVE_WEIGHT * (waiting + playing)
        all_c = {tid: t["total_duels"] for tid, t in topics.items() if t["total_duels"]}
        counts = {"today": today_c, "week": week_c, "month": month_c, "all": all_c, "hot": hot_c}

        def rest_key(tid):
            t = topics[tid]
            return (-(t["last_played_at"] or 0), t["name_key"])

        quiet = sorted(topics, key=rest_key)
        for period, c in counts.items():
            active = sorted((tid for tid, n in c.items() if n > 0),
                            key=lambda tid: (-c[tid], -hot_c.get(tid, 0.0), *rest_key(tid)))
            seen = set(active)
            self.order[period] = active + [tid for tid in quiet if tid not in seen]
        self.counts = counts
        self.topics = topics
        self.built_at = self.clock.now()
        self.built_day = today
        self.rebuilds += 1
        self._topics_dirty = self._activity_dirty = False

    # ----------------------------------------------------------- so'rovlar
    def browse(self, period: str = "hot", query: str = "", offset: int = 0, limit: int = config.TOPICS_PAGE) -> dict:
        """Bir sahifa mavzular: davr bo'yicha tartib, ixtiyoriy qidiruv (nom ichida), jonli kutish/o'ynash sonlari."""
        if period not in PERIODS:
            period = "hot"
        self.ensure()
        order = self.order.get(period, [])
        q = name_key(query[:MAX_SEARCH]) if query else ""
        if q:
            order = [tid for tid in order if q in self.topics[tid]["name_key"]]
        offset = max(0, offset)
        page = order[offset:offset + limit]
        return {
            "period": period,
            "total": len(order),
            "offset": offset,
            "nextOffset": offset + len(page) if offset + len(page) < len(order) else None,
            "items": [self.card(tid, period) for tid in page],
            "builtAt": self.built_day,
        }

    def card(self, tid: int, period: str) -> dict:
        t = self.topics[tid]
        waiting, playing = self.live_counts(tid)
        return {
            "id": tid,
            "name": t["name"],
            "questionCount": t["question_count"],
            "lastPlayedAt": t["last_played_at"],
            "totalDuels": t["total_duels"],
            "today": self.counts["today"].get(tid, 0),
            "week": self.counts["week"].get(tid, 0),
            "periodCount": None if period == "hot" else self.counts[period].get(tid, 0),
            "hot": round(self.counts["hot"].get(tid, 0.0), 2),
            "waiting": waiting,
            "playing": playing,
        }

    def name(self, tid: int | None) -> str | None:
        t = self.topics.get(tid) if tid is not None else None
        return t["name"] if t else None

    def is_playable(self, tid: int | None) -> bool:
        self.ensure()
        return tid in self.topics

    def hottest(self, exclude: set | None = None) -> int | None:
        """Eng qizg'in o'ynash mumkin bo'lgan mavzu ("istalgan mavzu" bo'yicha juftlashda)."""
        self.ensure()
        for tid in self.order.get("hot", []):
            if not exclude or tid not in exclude:
                return tid
        return None
