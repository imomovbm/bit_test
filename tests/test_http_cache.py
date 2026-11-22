"""HTTP kesh, siqish va statik fayllar (app/assets.py, app/server.py: http_cache_middleware).

Qoidalar (README «Kesh va qurilmada saqlash»):
  * /assets/<RELEASE>/... — public, max-age=31536000, immutable (mazmun xeshi manzilda);
  * HTML qobiq — no-cache + ETag/304;
  * hamma uchun bir xil ro'yxatlar — private, no-cache + ETag/304; qolgan barcha API javoblari — private, no-store;
  * matnli fayllar va 1 KB dan katta API javoblari — gzip (Accept-Encoding bo'lsa).
"""
import asyncio
import gzip
import re

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.assets import IMMUTABLE, AssetStore, STATIC_IMPORT_RE
from app.keys import ASSETS
from app.server import create_app
from test_octagon_api import QUESTIONS, call

REF_RE = re.compile(r'(?:href|src)="(/assets/[^"]+)"')


def run(tmp_path, body):
    async def main():
        server = TestServer(create_app(db_path=tmp_path / "c.db"))
        client = TestClient(server)
        await client.start_server()
        try:
            await body(client, server.app)
        finally:
            await client.close()
    asyncio.run(main())


async def login(client, name="admin"):
    status, _ = await call(client, "POST", "/api/auth/register", {"login": name, "password": "1234"})
    assert status == 200


def test_html_shell_is_revalidated_and_points_at_release_assets(tmp_path):
    async def body(client, app):
        release = app[ASSETS].release
        for path, entry in (("/play", "play.js"), ("/play/123456", "play.js"), ("/", "app.js")):
            r = await client.get(path)
            html = await r.text()
            assert r.status == 200 and r.headers["Cache-Control"] == "no-cache" and r.headers["ETag"].startswith('W/"')
            assert f'src="/assets/{release}/js/{entry}"' in html
            assert not re.search(r'(?:href|src)="/(?:js|css|img)/', html)  # hammasi versiyali manzilda
            assert "Content-Security-Policy" in r.headers
            r2 = await client.get(path, headers={"If-None-Match": r.headers["ETag"]})
            assert r2.status == 304 and await r2.read() == b""
        play = await (await client.get("/play")).text()
        assert f'<link rel="modulepreload" href="/assets/{release}/js/octagon/common.js">' in play
        index = await (await client.get("/")).text()
        assert f'href="/assets/{release}/js/lib.js"' in index and "views/octagon.js" not in index  # kechiktirilgan ko'rinishlar oldindan yuklanmaydi
    run(tmp_path, body)


def test_release_assets_are_immutable_and_gzipped(tmp_path):
    async def body(client, app):
        refs = set()
        for path in ("/play", "/"):
            refs |= set(REF_RE.findall(await (await client.get(path)).text()))
        assert len(refs) >= 10
        for ref in sorted(refs):
            plain = await client.get(ref, headers={"Accept-Encoding": "identity"})
            raw = await plain.read()
            assert plain.status == 200 and plain.headers["Cache-Control"] == IMMUTABLE, ref
            assert "Content-Encoding" not in plain.headers and plain.headers["Vary"] == "Accept-Encoding"
            packed = await client.get(ref, headers={"Accept-Encoding": "gzip, deflate, br"}, auto_decompress=False)
            data = await packed.read()
            if ref.endswith((".js", ".css")):
                assert packed.headers["Content-Encoding"] == "gzip", ref
                assert gzip.decompress(data) == raw and len(data) < len(raw)
            kind = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}[ref.rsplit(".", 1)[1]]
            assert plain.headers["Content-Type"].startswith(kind), ref
        head = await client.head(sorted(refs)[0])
        assert head.status == 200
    run(tmp_path, body)


def test_every_module_import_resolves_to_a_served_file(tmp_path):
    store = AssetStore(__import__("app.config", fromlist=["STATIC_DIR"]).STATIC_DIR)
    dynamic = re.compile(r"""import\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")
    for rel, asset in store.files.items():
        if not rel.endswith(".js"):
            continue
        src = asset.body.decode("utf-8")
        for spec in STATIC_IMPORT_RE.findall(src) + dynamic.findall(src):
            parts = rel.split("/")[:-1]
            for piece in spec.split("/"):
                if piece == "..":
                    parts.pop()
                elif piece != ".":
                    parts.append(piece)
            assert "/".join(parts) in store.files, (rel, spec)


def test_stale_release_and_legacy_urls_still_work_but_are_never_immutable(tmp_path):
    async def body(client, app):
        for path in ("/assets/000000000000/js/play.js", "/js/play.js", "/css/play.css", "/img/logo.svg"):
            r = await client.get(path)
            assert r.status == 200 and r.headers["Cache-Control"] == "no-cache", path
            again = await client.get(path, headers={"If-None-Match": r.headers["ETag"]})
            assert again.status == 304, path
    run(tmp_path, body)


@pytest.mark.parametrize("path", [
    "/assets/{r}/../app/config.py", "/assets/{r}/js/../../app/config.py", "/assets/{r}/js/%2e%2e/%2e%2e/app/config.py",
    "/js/..%2f..%2fapp%2fconfig.py", "/js/../app/config.py", "/assets/{r}/index.html", "/assets/{r}/play.html",
    "/assets/{r}/js/nope.js", "/assets/{r}/app/config.py", "/assets/notarelease/js/play.js", "/assets/{r}/js/",
    "/css/../index.html", "/img/%2e%2e/play.html",
])
def test_static_paths_cannot_escape_the_asset_dirs(tmp_path, path):
    async def body(client, app):
        r = await client.get(path.format(r=app[ASSETS].release), allow_redirects=False)
        assert r.status == 404, (path, r.status)
    run(tmp_path, body)


def _tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_release_id_follows_file_contents(tmp_path):
    _tree(tmp_path, {"js/a.js": "import { x } from './b.js';\nexport const y = x;\n", "js/b.js": "export const x = 1;\n",
                     "css/s.css": "body{}", "page.html": '<script type="module" src="/js/a.js"></script>'})
    one, same = AssetStore(tmp_path), AssetStore(tmp_path)
    assert one.release == same.release and re.fullmatch(r"[0-9a-f]{12}", one.release)
    assert one.static_imports("js/a.js") == ["js/b.js"]
    assert f'<link rel="modulepreload" href="/assets/{one.release}/js/b.js">' in one.page("page.html").body.decode()
    (tmp_path / "js/b.js").write_text("export const x = 2;\n", encoding="utf-8")  # faqat bog'liq modul o'zgardi
    assert AssetStore(tmp_path).release != one.release


def test_dev_mode_reads_from_disk_and_never_rewrites(tmp_path):
    _tree(tmp_path, {"js/a.js": "export const a = 1;\n", "page.html": '<script type="module" src="/js/a.js"></script>'})
    store = AssetStore(tmp_path, dev=True)
    assert store.release == "dev" and store.page("page.html").body.decode() == '<script type="module" src="/js/a.js"></script>'
    (tmp_path / "js/a.js").write_text("export const a = 2;\n", encoding="utf-8")
    assert store.get("js/a.js").body == b"export const a = 2;\n"
    for bad in ("js/../page.html", "../etc/passwd", "js/../../x", "css/../js/a.js/..", "page.html"):
        assert store.get(bad) is None, bad


def test_api_cache_headers(tmp_path):
    async def body(client, app):
        r = await client.get("/api/auth/me")
        assert r.headers["Cache-Control"] == "private, no-store" and "ETag" not in r.headers
        r = await client.post("/api/auth/register", json={"login": "admin", "password": "1234"})
        assert r.status == 200 and r.headers["Cache-Control"] == "private, no-store"  # Set-Cookie bor javob
        for path in ("/api/stats/me", "/api/octagon/games", "/api/admin/users", "/api/octagon/games/123456", "/api/nope"):
            r = await client.get(path)
            assert r.headers["Cache-Control"] == "private, no-store" and "ETag" not in r.headers, path
        assert (await call(client, "POST", "/api/admin/topics", {"name": "Informatika", "content": QUESTIONS}))[0] == 201
        for path in ("/api/topics", "/api/topics/browse?period=hot", "/api/octagon/topics", "/api/stats/leaderboard"):
            r = await client.get(path)
            assert r.status == 200 and r.headers["Cache-Control"] == "private, no-cache", path
            etag = r.headers["ETag"]
            again = await client.get(path, headers={"If-None-Match": etag})
            assert again.status == 304 and again.headers["ETag"] == etag and await again.read() == b"", path
        before = (await client.get("/api/topics")).headers["ETag"]
        assert (await call(client, "POST", "/api/admin/topics", {"name": "Tarix", "content": QUESTIONS}))[0] == 201
        after = await client.get("/api/topics", headers={"If-None-Match": before})
        assert after.status == 200 and after.headers["ETag"] != before  # ma'lumot o'zgardi — yangi tana
        guest = TestClient(client.server)
        await guest.start_server()
        r = await guest.get("/api/topics", headers={"If-None-Match": before})
        assert r.status == 401 and r.headers["Cache-Control"] == "private, no-store"  # 304 ruxsatsiz berilmaydi
        await guest.close()
    run(tmp_path, body)


def test_large_api_responses_are_gzipped(tmp_path):
    async def body(client, app):
        await login(client)
        content = "\n++++\n".join(f"Savol {i}?\n====\n#Ha\n====\nYoʻq" for i in range(60))
        status, data = await call(client, "POST", "/api/admin/topics", {"name": "Katta", "content": content})
        assert status == 201
        path = f"/api/admin/topics/{data['topic']['id']}/questions"
        r = await client.get(path, headers={"Accept-Encoding": "gzip"}, auto_decompress=False)
        raw = await r.read()
        assert r.headers.get("Content-Encoding") == "gzip" and r.headers["Cache-Control"] == "private, no-store"
        assert len(gzip.decompress(raw)) > len(raw) * 3
        plain = await client.get(path, headers={"Accept-Encoding": "identity"})
        assert "Content-Encoding" not in plain.headers
        small = await client.get("/api/auth/me", headers={"Accept-Encoding": "gzip"})
        assert "Content-Encoding" not in small.headers  # 1 KB dan kichik — siqilmaydi
    run(tmp_path, body)
