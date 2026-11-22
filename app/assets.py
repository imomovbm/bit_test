"""Statik fayllar: xotiradan, oldindan siqilgan (gzip), mazmun xeshli manzillar va to'g'ri kesh sarlavhalari bilan.

Ishlab chiqarish rejimi (standart):
  * static/{js,css,img} dagi har bir fayl ishga tushishda o'qiladi; matnli fayllar uchun gzip (9-daraja) bir marta
    tayyorlanadi; diskdan har so'rovda o'qilmaydi.
  * RELEASE — barcha fayllar mazmunining xeshi. HTML sahifalar /assets/<RELEASE>/... manzillariga ishora qiladi:
    ``Cache-Control: public, max-age=31536000, immutable`` — takroriy tashrifda brauzer ularni so'ramaydi ham.
    Biror fayl o'zgarsa, RELEASE ham o'zgaradi (eski kesh hech qachon yangi kod bilan aralashmaydi).
  * HTML (/, /play, /play/PIN): ``no-cache`` + ETag (304) — joylashtirish darhol ko'rinadi; har bir modul skript
    uchun uning statik importlari ``<link rel="modulepreload">`` sifatida qo'shiladi (importlar zanjiri kutilmaydi).
  * Eski manzillar (/js/..., /css/..., /img/...) ishlashda davom etadi: ``no-cache`` + ETag (joylashtirishdan oldin
    ochilgan sahifalar uchun). Boshqa RELEASE bilan so'ralgan fayl joriy mazmun bilan, lekin ``no-cache`` bilan beriladi.

Ishlab chiquvchi rejimi (TD_DEV=1): fayllar har so'rovda diskdan o'qiladi, hammasi ``no-cache``, HTML o'zgartirilmaydi.
"""
from __future__ import annotations

import gzip
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

ASSET_DIRS = ("js", "css", "img")
COMPRESSIBLE = {".js", ".css", ".svg", ".html", ".json", ".txt", ".webmanifest", ".map"}
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
RELEASE_RE = re.compile(r"^(?:[0-9a-f]{12}|dev)$")
TEXT_TYPES = ("text/", "application/javascript", "application/json", "image/svg+xml", "application/manifest+json")
# statik importlar (dinamik import() — kerak bo'lganda yuklanadigan ko'rinishlar — bunga kirmaydi)
STATIC_IMPORT_RE = re.compile(r"""(?:\bfrom\s*|^\s*import\s*)['"](\.{1,2}/[^'"]+\.js)['"]""", re.M)
MODULE_SCRIPT_RE = re.compile(r"""<script type="module" src="/js/([^"]+)"></script>""")
ASSET_URL_RE = re.compile(r"""(?<=["'(])/(js|css|img)/""")


@dataclass(frozen=True)
class Asset:
    body: bytes
    gz: bytes | None
    etag: str
    content_type: str


def make_asset(body: bytes, name: str) -> Asset:
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if ctype.startswith(TEXT_TYPES):
        ctype += "; charset=utf-8"
    gz = None
    if Path(name).suffix in COMPRESSIBLE and len(body) > 256:
        packed = gzip.compress(body, compresslevel=9, mtime=0)
        if len(packed) < len(body) * 0.9:
            gz = packed
    return Asset(body, gz, f'W/"{hashlib.sha256(body).hexdigest()[:20]}"', ctype)


def accepts_gzip(request: web.Request) -> bool:
    for part in request.headers.get("Accept-Encoding", "").lower().split(","):
        token, _, params = part.strip().partition(";")
        if token.strip() in ("gzip", "*"):
            q = params.strip().replace(" ", "")
            if q.startswith("q="):
                try:
                    return float(q[2:]) > 0
                except ValueError:
                    return False
            return True
    return False


def not_modified(request: web.Request, etag: str) -> bool:
    """If-None-Match (kuchsiz taqqoslash, RFC 9110 13.1.2)."""
    header = request.headers.get("If-None-Match")
    if not header:
        return False
    if header.strip() == "*":
        return True
    want = etag.removeprefix("W/")
    return any(t.strip().removeprefix("W/") == want for t in header.split(","))


def respond(request: web.Request, asset: Asset, cache_control: str, headers: dict | None = None) -> web.Response:
    out = {"Cache-Control": cache_control, "ETag": asset.etag, "Vary": "Accept-Encoding", **(headers or {})}
    if not_modified(request, asset.etag):
        return web.Response(status=304, headers=out)
    out["Content-Type"] = asset.content_type
    if asset.gz is not None and accepts_gzip(request):
        out["Content-Encoding"] = "gzip"
        return web.Response(body=asset.gz, headers=out)
    return web.Response(body=asset.body, headers=out)


class AssetStore:
    def __init__(self, root: Path, dev: bool = False):
        self.root = Path(root).resolve()
        self.dev = dev
        self.files: dict[str, Asset] = {}
        self._pages: dict[str, Asset] = {}
        if dev:
            self.release = "dev"
        else:
            for sub in ASSET_DIRS:
                base = self.root / sub
                if not base.is_dir():
                    continue
                for path in sorted(base.rglob("*")):
                    if path.is_file() and not path.name.startswith("."):
                        rel = path.relative_to(self.root).as_posix()
                        self.files[rel] = make_asset(path.read_bytes(), rel)
            digest = hashlib.sha256()
            for rel, asset in sorted(self.files.items()):
                digest.update(f"{rel}\0{asset.etag}\0".encode())
            self.release = digest.hexdigest()[:12]
        self.prefix = f"/assets/{self.release}/"

    # ------------------------------------------------------------- fayllar
    def get(self, rel: str) -> Asset | None:
        top = rel.split("/", 1)[0]
        if top not in ASSET_DIRS:
            return None
        if not self.dev:
            return self.files.get(rel)  # faqat ishga tushishda ro'yxatga olingan fayllar
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root / top) or not path.is_file():  # js/../index.html kabi chiqishlar yo'q
            return None
        return make_asset(path.read_bytes(), path.relative_to(self.root).as_posix())

    def text(self, rel: str) -> str:
        asset = self.get(rel)
        return asset.body.decode("utf-8") if asset else ""

    def static_imports(self, entry: str) -> list[str]:
        """Modulning statik importlari (tranzitiv), "js/..." ko'rinishida, birinchi uchragan tartibda."""
        seen: list[str] = []
        stack = [entry]
        while stack:
            current = stack.pop(0)
            base = current.rsplit("/", 1)[0]
            for spec in STATIC_IMPORT_RE.findall(self.text(current)):
                parts = base.split("/")
                for piece in spec.split("/"):
                    if piece == "..":
                        if parts:
                            parts.pop()
                    elif piece != ".":
                        parts.append(piece)
                dep = "/".join(parts)
                if dep not in seen and dep != entry and self.get(dep):
                    seen.append(dep)
                    stack.append(dep)
        return seen

    # ------------------------------------------------------------ sahifalar
    def page(self, name: str) -> Asset:
        cached = self._pages.get(name)
        if cached is not None:
            return cached
        html = (self.root / name).read_text(encoding="utf-8")
        if not self.dev:
            html = self.rewrite(html)
        asset = make_asset(html.encode("utf-8"), name)
        if not self.dev:
            self._pages[name] = asset
        return asset

    def rewrite(self, html: str) -> str:
        def preload(m: re.Match) -> str:
            links = "".join(f'<link rel="modulepreload" href="/{dep}">\n' for dep in self.static_imports(f"js/{m.group(1)}"))
            return links + m.group(0)

        html = MODULE_SCRIPT_RE.sub(preload, html)
        return ASSET_URL_RE.sub(lambda m: f"{self.prefix}{m.group(1)}/", html)

    # ------------------------------------------------------------- marshrut
    async def versioned(self, request: web.Request) -> web.StreamResponse:
        release = request.match_info["release"]
        asset = self.get(request.match_info["path"]) if RELEASE_RE.match(release) else None
        if asset is None:
            raise web.HTTPNotFound()
        current = release == self.release and not self.dev
        return respond(request, asset, IMMUTABLE if current else REVALIDATE)

    def legacy(self, sub: str):
        async def handler(request: web.Request) -> web.StreamResponse:
            asset = self.get(f"{sub}/{request.match_info['path']}")
            if asset is None:
                raise web.HTTPNotFound()
            return respond(request, asset, REVALIDATE)
        return handler

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/assets/{release}/{path:.+}", self.versioned)
        for sub in ASSET_DIRS:
            app.router.add_get(f"/{sub}/{{path:.+}}", self.legacy(sub))
