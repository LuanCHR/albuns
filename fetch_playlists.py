#!/usr/bin/env python3
"""Busca as suas playlists no Spotify e gera docs/data/playlists.json.

O site (pasta docs/) só lê esse JSON. Ninguém que visita o site fala com a
API do Spotify: você roda este script quando quiser atualizar a galeria.

Uso (no Windows, basta dar dois cliques em rodar.bat):
    python fetch_playlists.py
    python fetch_playlists.py --include-private     # inclui playlists privadas
    python fetch_playlists.py --source all          # playlists e álbuns salvos
    python fetch_playlists.py --max-tracks 50       # guarda só as 50 primeiras faixas

O que é manual fica em config.json (gênero, data de criação, colaboradores,
ordem, playlists escondidas). O script cria as entradas e nunca apaga o que
você escreveu.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
API = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_HOST, REDIRECT_PORT = "127.0.0.1", 8888
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"
SCOPES_PLAYLISTS = "playlist-read-private playlist-read-collaborative"
SCOPE_ALBUMS = "user-library-read"  # só é pedido se "albums" estiver em sources
VALID_SOURCES = ("playlists", "albums")
TOKEN_FILE = ROOT / ".spotify_token.json"
CONFIG_FILE = ROOT / "config.json"
ENV_FILE = ROOT / ".env"
# Um Client ID do Spotify tem exatamente 32 letras/números (hexadecimal).
CLIENT_ID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", re.IGNORECASE)
DEFAULT_SITE = {"title": "álbuns", "subtitle": "", "owner": "", "profile_url": "", "avatar": ""}
# Faixas "adicionadas" antes de 2008 têm data fictícia (1970); ignoramos.
MIN_VALID_YEAR = 2008


# ---------------------------------------------------------------- ambiente --
def load_env(path: Path | None = None) -> None:
    path = path or ENV_FILE
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client_id() -> str:
    """Lê o Client ID do .env; se faltar ou estiver errado, pergunta e salva.

    Aceita o ID mesmo com lixo em volta (aspas, espaços, uma barra que veio
    junto na cópia): só importa achar os 32 caracteres certos.
    """
    match = CLIENT_ID_RE.search(os.environ.get("SPOTIFY_CLIENT_ID", ""))
    if match:
        return match.group(0).lower()

    print("Falta o Client ID do seu app do Spotify (ou o que está no .env não é um).")
    print("Ele fica em developer.spotify.com/dashboard > seu app > Settings,")
    print("com 32 letras e números. Use o ícone de copiar ao lado dele.\n")
    while True:
        try:
            typed = input("Cole o Client ID aqui e aperte Enter: ")
        except EOFError:
            raise SystemExit("Sem Client ID não dá para continuar.")
        match = CLIENT_ID_RE.search(typed)
        if match:
            client_id = match.group(0).lower()
            ENV_FILE.write_text(f"SPOTIFY_CLIENT_ID={client_id}\n", encoding="utf-8")
            print(f"Salvo em {ENV_FILE.name}. Nas próximas vezes não pergunto de novo.\n")
            return client_id
        print("Isso não parece um Client ID (são 32 letras e números). Tente de novo.\n")


# ------------------------------------------------------------------- login --
def _token_request(data: dict) -> dict:
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if not r.ok:
        raise SystemExit(f"O Spotify recusou o login ({r.status_code}): {r.text}")
    return r.json()


def _save_token(payload: dict, old_refresh: str | None = None, scope: str | None = None) -> dict:
    data = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or old_refresh,
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope") or scope or "",
    }
    TOKEN_FILE.write_text(json.dumps(data), encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return data


def _browser_login(client_id: str, scopes: str) -> dict:
    """Login com PKCE: abre o navegador e espera o Spotify chamar o callback."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": scopes,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )

    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            received.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
            body = (
                "<meta charset='utf-8'><body style='font-family:sans-serif;padding:3rem'>"
                "<h2>Pronto!</h2><p>Pode fechar esta aba e voltar para o terminal.</p>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silencia o log do servidor
            pass

    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), Handler)
    server.timeout = 300
    print("Abrindo o navegador para você entrar no Spotify...")
    print(f"Se não abrir sozinho, cole este link no navegador:\n{url}\n")
    webbrowser.open(url)
    deadline = time.time() + 300
    while "code" not in received and "error" not in received and time.time() < deadline:
        server.handle_request()
    server.server_close()

    if "error" in received:
        raise SystemExit(f"Login cancelado ou recusado: {received['error']}")
    if "code" not in received:
        raise SystemExit("Tempo esgotado esperando o login. Rode o script de novo.")
    if received.get("state") != state:
        raise SystemExit("Resposta de login inválida (state diferente). Rode de novo.")

    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": received["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }
    )
    return _save_token(payload, scope=scopes)


def get_access_token(client_id: str, scopes: str = SCOPES_PLAYLISTS) -> str:
    wanted = set(scopes.split())
    if TOKEN_FILE.exists():
        try:
            cached = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        # login antigo sem as permissões de agora (ex.: álbuns salvos): autoriza de novo
        if not wanted <= set((cached.get("scope") or SCOPES_PLAYLISTS).split()):
            cached = {}
        if cached.get("access_token") and cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]
        if cached.get("refresh_token"):
            r = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": cached["refresh_token"],
                    "client_id": client_id,
                },
                timeout=30,
            )
            if r.ok:
                return _save_token(r.json(), cached["refresh_token"], cached.get("scope"))["access_token"]
    return _browser_login(client_id, scopes)["access_token"]


# ------------------------------------------------------------------- API ----
class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class Spotify:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **params):
        url = path if path.startswith("http") else API + path
        for attempt in range(6):
            r = self.session.get(url, params=params or None, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "2"))
                if "QUOTA_EXCEEDED" in r.text or wait > 120:
                    raise SystemExit(
                        "O Spotify bloqueou novas chamadas por excesso de uso "
                        f"(tente de novo em ~{max(wait // 60, 1)} min)."
                    )
                time.sleep(wait + 1)
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                raise ApiError(r.status_code, r.text)
            return r.json()
        raise ApiError(r.status_code, "Muitas tentativas sem sucesso")

    def paginate(self, path: str, **params):
        data = self.get(path, **params)
        while True:
            yield from data.get("items") or []
            if not data.get("next"):
                return
            data = self.get(data["next"])


# ----------------------------------------------------------- transformação --
def clean_text(value: str | None) -> str:
    """A descrição vem com entidades HTML e às vezes tags; deixamos texto puro."""
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_item(entry: dict) -> dict | None:
    """Converte um item de playlist em um dicionário simples.

    A API mudou os nomes dos campos em 2026 ("track" -> "item"); aceitamos os dois.
    """
    t = entry.get("item") or entry.get("track")
    if not t or not t.get("name"):
        return None  # faixa removida do Spotify
    artists = [a["name"] for a in t.get("artists") or [] if a.get("name")]
    if t.get("type") == "episode" and (t.get("show") or {}).get("name"):
        artists = [t["show"]["name"]]
    images = (t.get("album") or {}).get("images") or t.get("images") or []
    return {
        "name": t["name"],
        "artists": artists,
        "duration_ms": int(t.get("duration_ms") or 0),
        "cover": images[-1]["url"] if images else None,  # a menor
        "added_at": entry.get("added_at"),
        "added_by": (entry.get("added_by") or {}).get("id"),
    }


def fetch_tracks(api: Spotify, playlist_id: str, log=print) -> list[dict]:
    try:
        entries = list(api.paginate(f"/playlists/{playlist_id}/items", limit=50))
    except ApiError as e:
        if e.status == 404:  # nome antigo do endpoint
            entries = list(api.paginate(f"/playlists/{playlist_id}/tracks", limit=50))
        elif e.status == 403:
            log(f"  aviso: sem permissão para ler as faixas de {playlist_id}")
            return []
        else:
            raise
    return [t for t in (parse_item(e) for e in entries) if t]


def first_added_date(tracks: list[dict]) -> str | None:
    dates = []
    for t in tracks:
        raw = t.get("added_at")
        if not raw:
            continue
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.year >= MIN_VALID_YEAR:
            dates.append(d)
    return min(dates).date().isoformat() if dates else None


def collect_playlists(api: Spotify, my_id: str, *, include_private=False, include_followed=False, log=print):
    """Suas playlists, com todas as faixas."""
    raws = []
    for p in api.paginate("/me/playlists", limit=50):
        if not p:
            continue
        owned = (p.get("owner") or {}).get("id") == my_id
        if not owned and not include_followed:
            continue
        if p.get("public") is False and not include_private:
            continue
        log(f"- {p['name']}")
        images = p.get("images") or []
        raws.append(
            {
                "id": p["id"],
                "kind": "playlist",
                "name": p["name"],
                "description": clean_text(p.get("description")),
                "url": (p.get("external_urls") or {}).get("spotify")
                or f"https://open.spotify.com/playlist/{p['id']}",
                "cover_url": images[0]["url"] if images else None,
                "collaborative": bool(p.get("collaborative")),
                "tracks": fetch_tracks(api, p["id"], log),
                "byline": "",
                "released": None,
                "saved_at": None,
            }
        )
    return raws


def iter_pages(api: Spotify, page: dict):
    """Percorre uma página já em mãos e as seguintes (campo "next")."""
    while page:
        yield from page.get("items") or []
        page = api.get(page["next"]) if page.get("next") else None


def collect_saved_albums(api: Spotify, limit: int = 100, log=print):
    """Álbuns salvos na sua biblioteca (os mais recentes primeiro)."""
    raws = []
    try:
        for entry in api.paginate("/me/albums", limit=50):
            if len(raws) >= limit:
                break
            a = (entry or {}).get("album") or {}
            if not a.get("id") or not a.get("name"):
                continue
            log(f"- {a['name']} (álbum salvo)")
            images = a.get("images") or []
            thumb = images[-1]["url"] if images else None
            try:
                items = list(iter_pages(api, a.get("tracks") or {}))
                if not items and a.get("total_tracks"):
                    items = list(api.paginate(f"/albums/{a['id']}/tracks", limit=50))
            except ApiError as e:
                log(f"  aviso: não consegui ler as faixas de {a['name']} ({e.status})")
                items = []
            tracks = [
                {
                    "name": t["name"],
                    "artists": [x["name"] for x in t.get("artists") or [] if x.get("name")],
                    "duration_ms": int(t.get("duration_ms") or 0),
                    "cover": thumb,
                    "added_at": None,
                    "added_by": None,
                }
                for t in items
                if t and t.get("name")
            ]
            raws.append(
                {
                    "id": a["id"],
                    "kind": "album",
                    "name": a["name"],
                    "description": "",
                    "url": (a.get("external_urls") or {}).get("spotify")
                    or f"https://open.spotify.com/album/{a['id']}",
                    "cover_url": images[0]["url"] if images else None,
                    "collaborative": False,
                    "tracks": tracks,
                    "byline": ", ".join(x["name"] for x in a.get("artists") or [] if x.get("name")),
                    "released": a.get("release_date") or None,
                    "saved_at": (entry.get("added_at") or "")[:10] or None,
                }
            )
    except ApiError as e:
        log(f"aviso: não consegui ler seus álbuns salvos (erro {e.status}). Sigo sem eles.")
    return raws


def collect(api: Spotify, *, sources=("playlists",), include_private=False, include_followed=False,
            max_albums=100, log=print):
    """Retorna (perfil, itens). Cada item é uma playlist ou um álbum salvo."""
    me = api.get("/me")
    raws = []
    if "playlists" in sources:
        raws += collect_playlists(api, me["id"], include_private=include_private,
                                  include_followed=include_followed, log=log)
    if "albums" in sources:
        raws += collect_saved_albums(api, max_albums, log)
    return me, raws


def resolve_names(api: Spotify, user_ids: set[str], cache: dict) -> list[str]:
    names = []
    for uid in sorted(user_ids):
        if uid not in cache:
            try:
                cache[uid] = api.get(f"/users/{urllib.parse.quote(uid)}").get("display_name")
            except ApiError:
                cache[uid] = None  # perfis de outras pessoas podem estar bloqueados
        if cache[uid]:
            names.append(cache[uid])
    return names


def download_cover(url: str, dest_dir: Path, album_id: str) -> str | None:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  aviso: não consegui baixar a capa ({e}); vou usar o link do Spotify")
        return None
    kind = r.headers.get("Content-Type", "")
    ext = ".png" if "png" in kind else ".webp" if "webp" in kind else ".jpg"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{album_id}.*"):
        old.unlink()
    (dest_dir / f"{album_id}{ext}").write_bytes(r.content)
    return f"covers/{album_id}{ext}"


# ------------------------------------------------------------------ config --
def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_FILE
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    else:
        config = {}
    config["site"] = {**DEFAULT_SITE, **(config.get("site") or {})}
    config.setdefault("sources", ["playlists"])
    config.setdefault("albums", {})
    return config


def save_config(config: dict, path: Path | None = None) -> None:
    """Grava com site e sources no topo (a lista de álbuns é longa)."""
    head = {"site": config["site"], "sources": config["sources"], "albums": config["albums"]}
    ordered = {**head, **{k: v for k, v in config.items() if k not in head}}
    (path or CONFIG_FILE).write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_sources(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    result: list[str] = []
    for item in value or []:
        item = str(item).strip().lower()
        if item == "all":
            result += list(VALID_SOURCES)
        elif item in VALID_SOURCES:
            result.append(item)
        else:
            raise SystemExit(f'Valor desconhecido em "sources": {item!r}. Use "playlists" e/ou "albums".')
    return list(dict.fromkeys(result)) or ["playlists"]


def sync_config(config: dict, raws: list[dict]) -> list[str]:
    """Cria entradas para playlists novas (no topo) sem mexer no que já existe."""
    existing = config["albums"]
    created = {}
    for r in raws:
        if r["id"] not in existing:
            created[r["id"]] = {
                "name": r["name"],
                "kind": r["kind"],
                "genre": "",
                "created": "",
                "collaborators": [],
                "hidden": False,
                "note": "",
            }
    merged = {**created, **existing}
    for r in raws:
        merged[r["id"]]["name"] = r["name"]  # só para você achar o item no arquivo
        merged[r["id"]]["kind"] = r["kind"]
    config["albums"] = merged
    return [r["name"] for r in raws if r["id"] in created]


def build_albums(api, raws, config, my_id, *, max_tracks, covers_dir, download=True):
    by_id = {r["id"]: r for r in raws}
    name_cache: dict = {}
    albums = []
    for album_id, cfg in config["albums"].items():
        raw = by_id.get(album_id)
        if not raw or cfg.get("hidden"):
            continue
        tracks = raw["tracks"]

        manual_date = (cfg.get("created") or "").strip()
        if raw["kind"] == "album":
            created, created_source = None, None  # álbum salvo mostra data de lançamento
        elif manual_date:
            created, created_source = manual_date, "manual"
        else:
            created, created_source = first_added_date(tracks), "primeira faixa"

        collaborators = [c for c in cfg.get("collaborators") or [] if c]
        if not collaborators and raw["collaborative"]:
            ids = {t["added_by"] for t in tracks if t["added_by"] and t["added_by"] != my_id}
            collaborators = resolve_names(api, ids, name_cache)

        genre = cfg.get("genre") or ""
        if isinstance(genre, list):
            genre = ", ".join(g for g in genre if g)

        cover = None
        if raw["cover_url"]:
            cover = (download_cover(raw["cover_url"], covers_dir, album_id) if download else None) or raw["cover_url"]

        total_ms = sum(t["duration_ms"] for t in tracks)
        albums.append(
            {
                "id": album_id,
                "kind": raw["kind"],
                "title": cfg.get("title") or raw["name"],
                "byline": raw["byline"],
                "released": raw["released"],
                "saved_at": raw["saved_at"],
                "cover": cover,
                "url": raw["url"],
                "genre": genre.strip(),
                "created": created,
                "created_source": created_source,
                "duration_min": round(total_ms / 60000),
                "track_count": len(tracks),
                "collaborative": raw["collaborative"],
                "collaborators": collaborators,
                "note": cfg.get("note") or raw["description"],
                "tracks": [
                    {k: t[k] for k in ("name", "artists", "duration_ms", "cover")}
                    for t in tracks[:max_tracks]
                ],
            }
        )
    return albums


def resolve_avatar(me: dict, site_cfg: dict, out: Path, download: bool) -> str:
    """Foto do perfil: a que você escolheu no config, ou a do seu Spotify."""
    manual = (site_cfg.get("avatar") or "").strip()
    if manual:
        return manual  # arquivo dentro de docs/ ou link
    images = [i for i in me.get("images") or [] if i.get("url")]
    if not images:
        return ""
    url = max(images, key=lambda i: i.get("width") or 0)["url"]
    if download:
        saved = download_cover(url, out / "covers", "avatar")
        if saved:
            return saved
    return url


# -------------------------------------------------------------------- main --
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "docs"), help="pasta do site (padrão: docs)")
    parser.add_argument("--max-tracks", type=int, default=100, help="faixas guardadas por playlist")
    parser.add_argument("--source", choices=["playlists", "albums", "all"], help='o que buscar (padrão: "sources" do config.json)')
    parser.add_argument("--max-albums", type=int, default=100, help="quantos álbuns salvos trazer (os mais recentes)")
    parser.add_argument("--include-private", action="store_true", help="inclui playlists privadas")
    parser.add_argument("--include-followed", action="store_true", help="inclui playlists de outras pessoas que você segue")
    parser.add_argument("--no-covers", action="store_true", help="não baixa as capas (usa o link do Spotify)")
    args = parser.parse_args(argv)

    load_env()
    client_id = get_client_id()
    config = load_config()
    sources = normalize_sources([args.source] if args.source else config.get("sources"))
    scopes = SCOPES_PLAYLISTS + (f" {SCOPE_ALBUMS}" if "albums" in sources else "")

    out = Path(args.out)
    api = Spotify(get_access_token(client_id, scopes))

    names = {"playlists": "playlists", "albums": "álbuns salvos"}
    print("Buscando " + " e ".join(names[s] for s in sources) + "...")
    me, raws = collect(
        api, sources=sources, include_private=args.include_private,
        include_followed=args.include_followed, max_albums=args.max_albums,
    )
    if not raws:
        print("Nada encontrado. As playlists precisam ser públicas (ou use --include-private).")
        return 1

    new_names = sync_config(config, raws)
    save_config(config)

    for sample in (out / "covers").glob("sample-*"):
        sample.unlink()  # capas do exemplo que veio no projeto

    albums = build_albums(
        api, raws, config, me["id"],
        max_tracks=args.max_tracks, covers_dir=out / "covers", download=not args.no_covers,
    )

    site = dict(config["site"])
    site["owner"] = site["owner"] or me.get("display_name") or me["id"]
    site["profile_url"] = site["profile_url"] or (me.get("external_urls") or {}).get("spotify", "")
    site["avatar"] = resolve_avatar(me, config["site"], out, download=not args.no_covers)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site": site,
        "albums": albums,
    }
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "playlists.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    discs = sum(1 for a in albums if a["kind"] == "album")
    extra = f" ({len(albums) - discs} playlists e {discs} álbuns salvos)" if discs else ""
    print(f"\nPronto: {len(albums)} álbuns{extra} em {out / 'data' / 'playlists.json'}")
    if new_names:
        print(f"Novas no config.json: {', '.join(new_names)}")
    missing = [a["title"] for a in albums if not a["genre"] and a["kind"] == "playlist"]
    if missing:
        print("\nSem gênero ainda (preencha em config.json e rode de novo):")
        for name in missing:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
