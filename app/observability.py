"""Kuzatuv: tuzilgan (JSON) jurnal, hisoblagichlar, kechikishlar (p50/p95/p99) va xatolar uchun ilgak.

Qoida: jurnal va ko'rsatkichlarda maxfiy yoki shaxsiy ma'lumot yo'q — faqat identifikatorlar (o'yin PIN i, foydalanuvchi
raqami), sonlar, xabar turlari va marshrut namunalari (`/api/octagon/games/{pin}`, URL emas). O'quvchi ismlari,
loginlar, tokenlar, IP manzillar, savol matnlari yozilmaydi (tests/test_observability.py tekshiradi).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import Counter, deque
from typing import Any, Callable

log = logging.getLogger("testduel.errors")
LATENCY_WINDOW = 300.0     # foizliklar oxirgi 5 daqiqa bo'yicha
MAX_SAMPLES = 5000         # har bir ko'rsatkich uchun xotiradagi eng ko'p o'lchov
WEBHOOK_EVERY = 30.0       # bitta turdagi xato webhook ga ko'pi bilan shuncha soniyada bir marta


# ------------------------------------------------------------------- jurnal
class JsonFormatter(logging.Formatter):
    """Har bir qator — bitta JSON obyekt (log yig'uvchi tizimlar uchun): ts, level, logger, msg va qo'shimcha maydonlar."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            out.update({k: v for k, v in fields.items() if k not in out})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(fmt: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


# --------------------------------------------------------------- ko'rsatkichlar
class Metrics:
    """Jarayon ichidagi oddiy ko'rsatkichlar: hisoblagichlar, o'lchovlar (funksiya) va kechikishlar oynasi."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.started = clock()
        self.counters: Counter = Counter()          # (nom, yorliqlar) -> son
        self.samples: dict[str, deque] = {}         # nom -> (vaqt, ms)
        self.gauges: dict[str, Callable[[], float]] = {}

    def inc(self, name: str, n: int = 1, **labels: str) -> None:
        self.counters[(name, tuple(sorted(labels.items())))] += n

    def count(self, name: str, **labels: str) -> int:
        return self.counters.get((name, tuple(sorted(labels.items()))), 0)

    def observe(self, name: str, ms: float) -> None:
        q = self.samples.get(name)
        if q is None:
            q = self.samples[name] = deque(maxlen=MAX_SAMPLES)
        q.append((self.clock(), ms))

    def gauge(self, name: str, fn: Callable[[], float]) -> None:
        self.gauges[name] = fn

    def percentiles(self, name: str) -> dict | None:
        now = self.clock()
        values = sorted(ms for t, ms in self.samples.get(name, ()) if now - t <= LATENCY_WINDOW)
        if not values:
            return None

        def pick(p: float) -> float:
            return values[min(len(values) - 1, max(0, math.ceil(p / 100 * len(values)) - 1))]
        return {"n": len(values), "p50": round(pick(50), 2), "p95": round(pick(95), 2), "p99": round(pick(99), 2),
                "max": round(values[-1], 2)}

    def _gauge_values(self) -> dict[str, float]:
        out = {}
        for name, fn in self.gauges.items():
            try:
                out[name] = float(fn())
            except Exception:  # noqa: BLE001 — ko'rsatkich hech qachon xizmatni buzmasin
                out[name] = float("nan")
        return out

    def snapshot(self) -> dict:
        counters: dict[str, Any] = {}
        for (name, labels), value in sorted(self.counters.items()):
            if labels:
                counters.setdefault(name, {})[",".join(f"{k}={v}" for k, v in labels)] = value
            else:
                counters[name] = value
        return {
            "uptimeS": round(self.clock() - self.started, 1),
            "gauges": self._gauge_values(),
            "counters": counters,
            "latencyMs": {name: self.percentiles(name) for name in sorted(self.samples)},
        }

    def prometheus(self, prefix: str = "testduel") -> str:
        lines = [f"# TYPE {prefix}_uptime_seconds gauge", f"{prefix}_uptime_seconds {self.clock() - self.started:.1f}"]
        for name, value in sorted(self._gauge_values().items()):
            lines += [f"# TYPE {prefix}_{name} gauge", f"{prefix}_{name} {_num(value)}"]
        seen = set()
        for (name, labels), value in sorted(self.counters.items()):
            if name not in seen:
                lines.append(f"# TYPE {prefix}_{name} counter")
                seen.add(name)
            lines.append(f"{prefix}_{name}{_labels(labels)} {value}")
        lines.append(f"# TYPE {prefix}_latency_ms gauge")
        for name in sorted(self.samples):
            pct = self.percentiles(name)
            if pct:
                for q in ("p50", "p95", "p99"):
                    lines.append(f'{prefix}_latency_ms{{metric="{name}",quantile="0.{q[1:]}"}} {pct[q]}')
        return "\n".join(lines) + "\n"


def _labels(labels: tuple) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for k, v in labels)
    return "{" + body + "}"


def _num(value: float) -> str:
    return "NaN" if math.isnan(value) else (f"{int(value)}" if value == int(value) else f"{value:g}")


class Timer:
    """with METRICS_TIMER("nom"): ... — blok davomiyligi (ms) o'lchanadi."""

    def __init__(self, metrics: Metrics, name: str):
        self.metrics, self.name = metrics, name

    def __enter__(self) -> "Timer":
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.metrics.observe(self.name, (time.perf_counter() - self.t0) * 1000)


METRICS = Metrics()


def timed(name: str) -> Timer:
    return Timer(METRICS, name)


# ------------------------------------------------------------ xatolar ilgagi
class ErrorHook:
    """Kutilmagan xatolar: jurnalga (tuzilgan maydonlar bilan), hisoblagichga va — sozlangan bo'lsa — webhook ga
    (Slack/Discord/Sentry-ga mos har qanday JSON qabul qiluvchi). Bitta turdagi xato webhook ga 30 soniyada bir marta."""

    def __init__(self) -> None:
        self.url = ""
        self.release = ""
        self.sent: dict[str, float] = {}
        self.post: Callable[[str, dict], Any] | None = None   # testlar uchun almashtiriladi

    def configure(self, url: str = "", release: str = "") -> None:
        self.url, self.release = url, release

    def report(self, kind: str, message: str, *, level: int = logging.ERROR, exc: BaseException | bool | None = None,
               **fields: Any) -> None:
        """exc: True — joriy istisno, istisno obyekti — uning izi; maydonlarda shaxsiy ma'lumot bo'lmasin."""
        METRICS.inc("errors_total", kind=kind)
        log.log(level, "%s: %s", kind, message, exc_info=exc or None, extra={"fields": {"kind": kind, **fields}})
        if not self.url:
            return
        now = time.monotonic()
        if now - self.sent.get(kind, float("-inf")) < WEBHOOK_EVERY:
            return
        self.sent[kind] = now
        payload = {"kind": kind, "message": str(message)[:500], "fields": fields, "release": self.release,
                   "text": f"[testduel {self.release}] {kind}: {str(message)[:300]}"}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._send(payload))

    async def _send(self, payload: dict) -> None:
        try:
            if self.post is not None:
                await self.post(self.url, payload)
                return
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.post(self.url, json=payload) as resp:
                    await resp.read()
        except Exception:  # noqa: BLE001 — webhook ishlamasa ham xizmat davom etadi
            log.warning("Xato webhook iga yuborib bo'lmadi", extra={"fields": {"kind": "webhook"}})


ERRORS = ErrorHook()


def install_loop_handler(loop: asyncio.AbstractEventLoop) -> None:
    """Hech kim kutmagan vazifalardagi xatolar ham yo'qolmasin (jarayon to'xtamaydi, xato ilgakka tushadi)."""
    def handler(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        message = context.get("message") or (type(exc).__name__ if exc else "?")
        ERRORS.report("loop", f"{message}: {type(exc).__name__ if exc else ''}".rstrip(": "), exc=exc)
    loop.set_exception_handler(handler)
