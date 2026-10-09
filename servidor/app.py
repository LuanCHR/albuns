"""Servidor do "álbuns": login com Spotify, edição pelo site e uma vitrine pública por pessoa.

    python -m uvicorn servidor.app:app --port 8000     (ou dois cliques em servidor.bat)

Cada pessoa entra com o Spotify, o servidor busca as playlists e os álbuns salvos dela
e guarda num SQLite. Quem visita /u/<nome> só lê esse banco; nunca fala com o Spotify.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fetch_playlists as fp  # noqa: E402  (reaproveita a busca no Spotify)

fp.load_env()
DOCS = ROOT / "docs"
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", DOCS))
DB_FILE = Path(os.environ.get("ALBUNS_DB", ROOT / "albuns.db"))
SECRET_FILE = ROOT / ".secret_key"
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REDIRECT_URI = f"{BASE_URL}/callback"
SCOPES = f"{fp.SCOPES_PLAYLISTS} {fp.SCOPE_ALBUMS}"
MAX_TRACKS = 100
SYNC_COOLDOWN = 60  # segundos entre duas atualizações manuais


def _secret() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
    return SECRET_FILE.read_text(encoding="utf-8").strip()


def client_id() -> str:
    m = fp.CLIENT_ID_RE.search(os.environ.get("SPOTIFY_CLIENT_ID", ""))
    if not m:
        raise RuntimeError("Falta SPOTIFY_CLIENT_ID no arquivo .env (32 letras e números).")
    return m.group(0).lower()


# ------------------------------------------------------------------ banco --
_db_lock = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_lock, db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              spotify_id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
              avatar TEXT, profile_url TEXT, refresh_token TEXT,
              synced_at REAL, syncing INTEGER DEFAULT 0, sync_error TEXT, created_at REAL);
            CREATE TABLE IF NOT EXISTS items (
              user_id TEXT NOT NULL, item_id TEXT NOT NULL, position INTEGER NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY (user_id, item_id));
            CREATE TABLE IF NOT EXISTS edits (
              user_id TEXT NOT NULL, item_id TEXT NOT NULL, genre TEXT DEFAULT '', created TEXT DEFAULT '',
              collaborators TEXT DEFAULT '[]', note TEXT DEFAULT '', hidden INTEGER DEFAULT 0,
              PRIMARY KEY (user_id, item_id));
            """
        )
        c.execute("UPDATE users SET syncing = 0")  # um reinício interrompe qualquer busca em andamento


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "usuario"


def unique_slug(c: sqlite3.Connection, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while c.execute("SELECT 1 FROM users WHERE slug = ?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


# -------------------------------------------------------------- Spotify --
def spotify_token_request(data: dict) -> dict:
    r = requests.post(fp.TOKEN_URL, data={**data, "client_id": client_id()}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Spotify recusou o pedido de token ({r.status_code}): {r.text[:200]}")
    return r.json()


def sync_user(uid: str, access_token: str | None = None) -> None:
    """Busca playlists públicas e álbuns salvos e troca o que está no banco."""
    with _db_lock, db() as c:
        row = c.execute("SELECT refresh_token, syncing FROM users WHERE spotify_id = ?", (uid,)).fetchone()
        if not row or row["syncing"]:
            return
        c.execute("UPDATE users SET syncing = 1, sync_error = NULL WHERE spotify_id = ?", (uid,))
    error = None
    try:
        if not access_token:
            tok = spotify_token_request({"grant_type": "refresh_token", "refresh_token": row["refresh_token"]})
            access_token = tok["access_token"]
            if tok.get("refresh_token"):
                with _db_lock, db() as c:
                    c.execute("UPDATE users SET refresh_token = ? WHERE spotify_id = ?", (tok["refresh_token"], uid))
        api = fp.Spotify(access_token)
        _, raws = fp.collect(api, sources=("playlists", "albums"), include_private=False,
                             include_followed=False, max_albums=100, log=lambda *_: None)
        with _db_lock, db() as c:
            c.execute("DELETE FROM items WHERE user_id = ?", (uid,))
            c.executemany(
                "INSERT INTO items (user_id, item_id, position, data) VALUES (?,?,?,?)",
                [(uid, r["id"], i, json.dumps(r, ensure_ascii=False)) for i, r in enumerate(raws)],
            )
        import_old_config(uid)
    except fp.ApiError as e:
        error = "403" if e.status == 403 else f"spotify-{e.status}"
    except BaseException as e:  # SystemExit do cliente (cota) também
        error = str(e)[:200] or "erro"
    finally:
        with _db_lock, db() as c:
            c.execute(
                "UPDATE users SET syncing = 0, sync_error = ?, synced_at = ? WHERE spotify_id = ?",
                (error, time.time(), uid),
            )


def import_old_config(uid: str) -> None:
    """Quem já preencheu o config.json da versão antiga não perde nada: o que não tem edição ainda é importado."""
    try:
        albums = fp.load_config().get("albums") or {}
    except BaseException:
        return
    with _db_lock, db() as c:
        have = {r["item_id"] for r in c.execute("SELECT item_id FROM items WHERE user_id = ?", (uid,))}
        done = {r["item_id"] for r in c.execute("SELECT item_id FROM edits WHERE user_id = ?", (uid,))}
        for item_id, e in albums.items():
            if item_id not in have or item_id in done or not isinstance(e, dict):
                continue
            genre = e.get("genre") or ""
            if isinstance(genre, list):
                genre = ", ".join(g for g in genre if g)
            collabs = [str(x) for x in (e.get("collaborators") or []) if x]
            if not (genre or collabs or e.get("note") or e.get("created")):
                continue
            c.execute(
                "INSERT INTO edits (user_id, item_id, genre, created, collaborators, note) VALUES (?,?,?,?,?,?)",
                (uid, item_id, _clean(genre, 80), str(e.get("created") or "")[:10],
                 json.dumps(collabs[:12], ensure_ascii=False), _clean(e.get("note"), 280)),
            )


def start_sync(uid: str, access_token: str | None = None) -> None:
    threading.Thread(target=sync_user, args=(uid, access_token), daemon=True).start()


# ----------------------------------------------------------- vitrine/API --
def user_lookup(c: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    keys: dict[str, sqlite3.Row] = {}
    for u in c.execute("SELECT slug, name FROM users"):
        keys.setdefault(u["slug"].casefold(), u)
        keys.setdefault(u["name"].casefold(), u)
        keys.setdefault(slugify(u["name"]), u)
    return keys


def resolve_collaborators(names: list[str], lookup: dict) -> list[dict]:
    out = []
    for raw in names:
        text = raw.strip()
        key = text
        if "/u/" in text:
            key = urlparse(text).path.split("/u/")[-1].strip("/")
        key = key.lstrip("@").strip().casefold()
        u = lookup.get(key) or lookup.get(slugify(key))
        out.append({"name": u["name"] if u else text.lstrip("@"), "slug": u["slug"] if u else None})
    return out


def shape(raw: dict, edit: sqlite3.Row | None, lookup: dict) -> dict:
    tracks = raw["tracks"]
    is_album = raw["kind"] == "album"
    created, source = None, None
    if not is_album:
        manual = (edit["created"] if edit else "") or ""
        if manual:
            created, source = manual, "manual"
        else:
            created, source = fp.first_added_date(tracks), "primeira faixa"
    collabs = json.loads(edit["collaborators"]) if edit else []
    note = (edit["note"] if edit else "") or raw.get("description") or ""
    return {
        "id": raw["id"], "kind": raw["kind"], "title": raw["name"], "byline": raw["byline"],
        "released": raw["released"], "saved_at": raw["saved_at"], "cover": raw["cover_url"],
        "url": raw["url"], "genre": (edit["genre"] if edit else "") or "",
        "created": created, "created_source": source,
        "duration_min": round(sum(t["duration_ms"] for t in tracks) / 60000),
        "track_count": len(tracks), "collaborative": raw["collaborative"],
        "collaborators": resolve_collaborators(collabs, lookup), "note": note,
        "hidden": bool(edit["hidden"]) if edit else False,
        "tracks": [{k: t[k] for k in ("name", "artists", "duration_ms", "cover")} for t in tracks[:MAX_TRACKS]],
    }


def get_user(slug: str) -> sqlite3.Row | None:
    with db() as c:
        return c.execute("SELECT * FROM users WHERE slug = ?", (slug.casefold(),)).fetchone()


def session_user(request: Request) -> sqlite3.Row | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    with db() as c:
        return c.execute("SELECT * FROM users WHERE spotify_id = ?", (uid,)).fetchone()


def require_user(request: Request) -> sqlite3.Row:
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Entre com o Spotify.")
    if request.headers.get("x-requested-with") != "albuns":
        raise HTTPException(400, "Pedido inválido.")
    return user


# -------------------------------------------------------------------- app --
app = FastAPI(title="álbuns", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=_secret(), max_age=60 * 60 * 24 * 30,
    same_site="lax", https_only=BASE_URL.startswith("https://"),
)
init_db()


def wordmark_svg() -> str:
    m = re.search(r"<svg class=\"wordmark\".*?</svg>", (DOCS / "index.html").read_text(encoding="utf-8"), re.S)
    return m.group(0) if m else "<span>álbuns</span>"


STATIC_FILES = {"style.css": "text/css", "app.js": "text/javascript", "favicon.svg": "image/svg+xml",
                "favicon-32.png": "image/png", "apple-touch-icon.png": "image/png", "icon-192.png": "image/png",
                "icon-512.png": "image/png", "logo-a.svg": "image/svg+xml"}


def mark_svg() -> str:
    m = re.search(r'<svg class="mark".*?</svg>', (DOCS / "index.html").read_text(encoding="utf-8"), re.S)
    return m.group(0) if m else ""


@app.get("/static/{name}")
def static_file(name: str):
    if name not in STATIC_FILES:
        raise HTTPException(404)
    return FileResponse(DOCS / name, media_type=STATIC_FILES[name], headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
def favicon_ico():
    return FileResponse(DOCS / "favicon-32.png", media_type="image/png")


def point_to_static(page: str) -> str:
    """index.html usa caminhos relativos (style.css, app.js, ícones); no servidor eles vivem em /static/."""
    return re.sub(r'(href|src)="(?!https?:|/|#|data:)([^"]+)"', r'\1="/static/\2"', page)


ERRORS = {
    "negado": "Você cancelou o acesso no Spotify. Sem ele não dá para montar a vitrine.",
    "estado": "O login expirou ou veio de outra aba. Tente entrar de novo.",
    "limite": "Este beta ainda é fechado: o Spotify só deixa entrar quem foi liberado pelo dono do app. "
              "Peça para ser adicionado e tente de novo.",
    "spotify": "O Spotify não respondeu direito. Tente de novo em instantes.",
}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, erro: str = ""):
    user = session_user(request)
    if user and not erro:
        return RedirectResponse(f"/u/{user['slug']}")
    page = (Path(__file__).parent / "landing.html").read_text(encoding="utf-8")
    msg = html.escape(ERRORS.get(erro, ""))
    return HTMLResponse(page.replace("{{WORDMARK}}", wordmark_svg()).replace("{{ERRO}}", msg).replace("{{MARK}}", mark_svg()))


@app.get("/login")
def login(request: Request):
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    request.session["pkce"] = {"verifier": verifier, "state": state}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({
        "client_id": client_id(), "response_type": "code", "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "code_challenge_method": "S256", "code_challenge": challenge, "state": state,
    })
    return RedirectResponse(f"{fp.AUTH_URL}?{query}")


@app.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    saved = request.session.pop("pkce", None)
    if error:
        return RedirectResponse("/?erro=negado")
    if not saved or not code or not secrets.compare_digest(saved["state"], state):
        return RedirectResponse("/?erro=estado")
    try:
        tok = spotify_token_request({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "code_verifier": saved["verifier"],
        })
        me = fp.Spotify(tok["access_token"]).get("/me")
    except fp.ApiError as e:
        return RedirectResponse("/?erro=limite" if e.status == 403 else "/?erro=spotify")
    except Exception:
        return RedirectResponse("/?erro=spotify")

    name = (me.get("display_name") or me["id"]).strip()
    images = me.get("images") or []
    avatar = images[0]["url"] if images else ""
    profile = (me.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/user/{me['id']}"
    with _db_lock, db() as c:
        row = c.execute("SELECT slug FROM users WHERE spotify_id = ?", (me["id"],)).fetchone()
        slug = row["slug"] if row else unique_slug(c, name)
        c.execute(
            """INSERT INTO users (spotify_id, slug, name, avatar, profile_url, refresh_token, created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(spotify_id) DO UPDATE SET name=excluded.name, avatar=excluded.avatar,
                 profile_url=excluded.profile_url, refresh_token=COALESCE(excluded.refresh_token, refresh_token)""",
            (me["id"], slug, name, avatar, profile, tok.get("refresh_token"), time.time()),
        )
    request.session["uid"] = me["id"]
    start_sync(me["id"], tok["access_token"])
    return RedirectResponse(f"/u/{slug}")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/u/{slug}", response_class=HTMLResponse)
def vitrine(slug: str):
    page = (DOCS / "index.html").read_text(encoding="utf-8")
    user = get_user(slug)
    page = point_to_static(page)
    page = page.replace("<body>", f'<body data-api="/api/u/{html.escape(slug.casefold())}">')
    if user:
        who = html.escape(user["name"])
        desc = f"Playlists e álbuns de {who} no Spotify."
        page = re.sub(r'(<meta name="description" content=")[^"]*', rf"\g<1>{desc}", page)
        page = re.sub(r'(<meta property="og:title" content=")[^"]*', rf"\g<1>álbuns de {who}", page)
        page = re.sub(r'(<meta property="og:description" content=")[^"]*', rf"\g<1>{desc}", page)
        page = page.replace("<title>álbuns</title>", f"<title>álbuns de {who}</title>")
        if user["avatar"]:
            page = page.replace("</head>", f'  <meta property="og:image" content="{html.escape(user["avatar"])}">\n</head>')
    return HTMLResponse(page, status_code=200 if user else 404)


@app.get("/api/u/{slug}")
def api_vitrine(slug: str, request: Request):
    user = get_user(slug)
    if not user:
        raise HTTPException(404, "Vitrine não encontrada.")
    me = session_user(request)
    editable = bool(me and me["spotify_id"] == user["spotify_id"])
    with db() as c:
        lookup = user_lookup(c)
        edits = {e["item_id"]: e for e in c.execute("SELECT * FROM edits WHERE user_id = ?", (user["spotify_id"],))}
        items = [
            shape(json.loads(r["data"]), edits.get(r["item_id"]), lookup)
            for r in c.execute("SELECT data, item_id FROM items WHERE user_id = ? ORDER BY position", (user["spotify_id"],))
        ]
    if not editable:
        items = [i for i in items if not i["hidden"]]
    return JSONResponse(
        {
            "site": {"title": "álbuns", "owner": user["name"], "profile_url": user["profile_url"],
                     "avatar": user["avatar"], "slug": user["slug"]},
            "albums": items,
            "editable": editable,
            "me": {"slug": me["slug"], "name": me["name"]} if me else None,
            "syncing": bool(user["syncing"]),
            "can_export": editable and is_local(),
            "sync_error": user["sync_error"] if editable else None,
            "generated_at": datetime.fromtimestamp(user["synced_at"], timezone.utc).isoformat() if user["synced_at"] else None,
        },
        headers={"Cache-Control": "no-store"},
    )


DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _clean(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


@app.put("/api/item/{item_id}")
async def api_edit(item_id: str, request: Request):
    user = require_user(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON inválido.")
    raw_collabs = body.get("collaborators") or []
    if not isinstance(raw_collabs, list):
        raise HTTPException(422, "Colaboradores devem ser uma lista.")
    collabs = [c for c in (_clean(x, 60) for x in raw_collabs[:12]) if c]
    with _db_lock, db() as c:
        row = c.execute("SELECT data FROM items WHERE user_id = ? AND item_id = ?", (user["spotify_id"], item_id)).fetchone()
        if not row:
            raise HTTPException(404, "Item não encontrado.")
        c.execute(
            """INSERT INTO edits (user_id, item_id, genre, collaborators, note) VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, item_id) DO UPDATE SET genre=excluded.genre,
                 collaborators=excluded.collaborators, note=excluded.note""",
            (user["spotify_id"], item_id, _clean(body.get("genre"), 80),
             json.dumps(collabs, ensure_ascii=False), _clean(body.get("note"), 280)),
        )
        edit = c.execute("SELECT * FROM edits WHERE user_id = ? AND item_id = ?", (user["spotify_id"], item_id)).fetchone()
        lookup = user_lookup(c)
    return shape(json.loads(row["data"]), edit, lookup)


def is_local() -> bool:
    return urlparse(BASE_URL).hostname in ("127.0.0.1", "localhost")


@app.post("/api/export")
def api_export(request: Request):
    """Só no seu computador: grava a vitrine como site estático em docs/ (para o GitHub Pages)."""
    user = require_user(request)
    if not is_local():
        raise HTTPException(403, "A publicação no GitHub só funciona rodando no seu computador.")
    out = EXPORT_DIR
    covers = out / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    for old in covers.glob("sample-*"):
        old.unlink()
    with db() as c:
        lookup = user_lookup(c)
        edits = {e["item_id"]: e for e in c.execute("SELECT * FROM edits WHERE user_id = ?", (user["spotify_id"],))}
        rows = list(c.execute("SELECT data, item_id FROM items WHERE user_id = ? ORDER BY position", (user["spotify_id"],)))
    albums = []
    for r in rows:
        item = shape(json.loads(r["data"]), edits.get(r["item_id"]), lookup)
        if item["hidden"]:
            continue
        if item["cover"]:
            item["cover"] = fp.download_cover(item["cover"], covers, item["id"]) or item["cover"]
        item["collaborators"] = [c["name"] for c in item["collaborators"]]  # no site estático são só nomes
        albums.append(item)
    # Capas de playlists que saíram da vitrine (viraram privadas, por exemplo) não podem ficar na pasta publicada.
    keep = {a["id"] for a in albums} | {"avatar"}
    for f in covers.iterdir():
        if f.is_file() and f.stem not in keep:
            f.unlink()
    avatar = ""
    if user["avatar"]:
        try:
            resp = requests.get(user["avatar"], timeout=30)
            resp.raise_for_status()
            for old in covers.glob("avatar.*"):
                old.unlink()
            ext = ".png" if "png" in resp.headers.get("Content-Type", "") else ".jpg"
            (covers / f"avatar{ext}").write_bytes(resp.content)
            avatar = f"covers/avatar{ext}"
        except requests.RequestException:
            avatar = user["avatar"]
    (out / "data").mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site": {"title": "álbuns", "subtitle": "", "owner": user["name"], "profile_url": user["profile_url"], "avatar": avatar},
        "albums": albums,
    }
    (out / "data" / "playlists.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "count": len(albums), "folder": str(out)}


@app.post("/api/sync")
def api_sync(request: Request):
    user = require_user(request)
    if user["syncing"]:
        return {"ok": True}
    if user["synced_at"] and time.time() - user["synced_at"] < SYNC_COOLDOWN:
        raise HTTPException(429, "Espere um minuto antes de atualizar de novo.")
    start_sync(user["spotify_id"])
    return {"ok": True}


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError):
    return HTMLResponse(f"<p style='font:16px system-ui;padding:2rem'>{html.escape(str(exc))}</p>", status_code=500)
