"""Labradoor connector `seerr`: Seerr (Jellyseerr/Overseerr) for the module `seerr`, PER USER — full Seerr management.

Seerr has one admin API key, so the module can't call Seerr directly and still keep things per person. This connector
verifies X-Lab-Auth, maps the lab user (Authentik username) to a Seerr user (explicit list, never guessed), and decides
what each caller may see and do. The gateway's manifest checks are the first line; every route is checked AGAIN here
(min role, owner-only), because the API key behind this connector is Seerr's all-powerful admin key.

Guests (the module's guest groups) with a mapped Seerr account: their own requests + quota, search/discover/details, request media
AS THEMSELVES (X-Api-User = their Seerr id; Seerr applies their own permissions + quotas; advanced fields such as
userId/server/profile/root folder are dropped), cancel their own pending requests. Never anyone else's requests.
Admins: everything else, except owner-only (identity: importing/deleting Seerr users, admin-level permission bits,
login + default-permission settings) — those need role owner or a lab owner approval (claim "a").
Nothing that holds a credential (API keys, webhook URLs, tokens, e-mail addresses) is ever returned (see scrub()).

Config (module config, from the gateway — connectors/README.md):
  url          Seerr as the lab host reaches it
  api_key      Seerr's API key (Settings → General)
  public_url   links in the UI (default: url)
  users        ["labuser=seerruser", …]: lab username = Seerr user (numeric Seerr id, Jellyfin username, Seerr username or
               e-mail). Nobody is matched by guessing: a lab user who is not listed gets {linked: false} and no Seerr data.

Routes: see ROUTES at the bottom (method, path, min role, handler)."""
import http.client
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import labconn  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "seerr")
PORT = int(os.environ.get("PORT", "8114"))
LAB_FROM = "127.0.0.1"
PUBLIC = ""  # links in the UI (config public_url, else url)
log = logging.getLogger(ID)

REQ_STATUS = {1: "pending", 2: "approved", 3: "declined", 4: "failed", 5: "completed"}
MEDIA_STATUS = {1: "unknown", 2: "pending", 3: "processing", 4: "partial", 5: "available", 6: "blocklisted", 7: "deleted"}
ISSUE_TYPE = {1: "video", 2: "audio", 3: "subtitles", 4: "other"}
ISSUE_STATUS = {1: "open", 2: "resolved"}
USER_TYPE = {1: "plex", 2: "local", 3: "jellyfin", 4: "emby"}
REQ_FILTERS = ("all", "pending", "approved", "processing", "available", "failed", "completed", "unavailable", "deleted")
DISCOVER = {"trending": "/discover/trending", "movies": "/discover/movies", "tv": "/discover/tv",
            "upcoming": "/discover/movies/upcoming", "upcoming-tv": "/discover/tv/upcoming"}
# agent → the options that must be filled before it can send anything (their values never leave the connector)
NOTIFY_NEEDS = {"email": ("smtpHost", "emailFrom"), "discord": ("webhookUrl",), "slack": ("webhookUrl",),
                "telegram": ("botAPI", "chatId"), "pushover": ("accessToken", "userToken"), "pushbullet": ("accessToken",),
                "gotify": ("url", "token"), "ntfy": ("url", "topic"), "webhook": ("webhookUrl",), "webpush": ()}
NOTIFY_AGENTS = tuple(NOTIFY_NEEDS)

# Seerr permission bits (server/lib/permissions.ts). PRIVILEGED = identity-level: only the owner may grant/remove them.
PERMS = {"ADMIN": 2, "MANAGE_SETTINGS": 4, "MANAGE_USERS": 8, "MANAGE_REQUESTS": 16, "REQUEST": 32, "VOTE": 64,
         "AUTO_APPROVE": 128, "AUTO_APPROVE_MOVIE": 256, "AUTO_APPROVE_TV": 512, "REQUEST_4K": 1024,
         "REQUEST_4K_MOVIE": 2048, "REQUEST_4K_TV": 4096, "REQUEST_ADVANCED": 8192, "REQUEST_VIEW": 16384,
         "AUTO_APPROVE_4K": 32768, "AUTO_APPROVE_4K_MOVIE": 65536, "AUTO_APPROVE_4K_TV": 131072, "REQUEST_MOVIE": 262144,
         "REQUEST_TV": 524288, "MANAGE_ISSUES": 1048576, "VIEW_ISSUES": 2097152, "CREATE_ISSUES": 4194304,
         "AUTO_REQUEST": 8388608, "AUTO_REQUEST_MOVIE": 16777216, "AUTO_REQUEST_TV": 33554432, "RECENT_VIEW": 67108864,
         "WATCHLIST_VIEW": 134217728, "MANAGE_BLOCKLIST": 268435456, "VIEW_BLOCKLIST": 1073741824}
PRIVILEGED = PERMS["ADMIN"] | PERMS["MANAGE_SETTINGS"] | PERMS["MANAGE_USERS"]
ALL_PERMS = sum(PERMS.values())

# main settings: what an admin may change vs. what is access/identity (owner)
MAIN_ADMIN = {"applicationTitle": str, "applicationUrl": str, "hideAvailable": bool, "hideBlocklisted": bool,
              "partialRequestsEnabled": bool, "enableSpecialEpisodes": bool, "cacheImages": bool, "locale": str,
              "discoverRegion": str, "streamingRegion": str, "originalLanguage": str, "versionCheck": bool, "youtubeUrl": str}
MAIN_OWNER = {"localLogin": bool, "mediaServerLogin": bool, "newPlexLogin": bool, "defaultPermissions": int, "defaultQuotas": dict}
SERVER_EDIT = {"radarr": {"activeProfileId": int, "activeDirectory": str, "minimumAvailability": str, "isDefault": bool,
                          "syncEnabled": bool, "preventSearch": bool, "tagRequests": bool, "externalUrl": str},
               "sonarr": {"activeProfileId": int, "activeDirectory": str, "activeAnimeProfileId": int,
                          "activeAnimeDirectory": str, "enableSeasonFolders": bool, "isDefault": bool, "syncEnabled": bool,
                          "preventSearch": bool, "tagRequests": bool, "externalUrl": str}}
SECRET_KEYS = {"apikey", "api_key", "password", "token", "accesstoken", "usertoken", "botapi", "webhookurl", "email",
               "plextoken", "jellyfinauthtoken", "jellyfindeviceid", "resetpasswordguid", "recoverylinkexpirationdate",
               "customheaders", "vapidprivate", "authpass", "authuser", "pgppassword", "pgpprivatekey", "chatid"}


def parse_users(text):
    out = {}
    for part in re.split(r"[,\s]+", text or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip().lower()] = v.strip().lower()
    return out


USERS = {}


def scrub(x):
    """Last line of defence: drop every credential-like or personal field from what goes back to the browser."""
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items() if k.lower() not in SECRET_KEYS}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


class SeerrError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class Refused(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class Seerr:
    def __init__(self, url, key):
        u = urllib.parse.urlsplit(url or "http://unset.invalid")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80)
        self.base, self.key = u.path.rstrip("/"), key

    def _conn(self, timeout=20):
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=timeout)

    def call(self, method, path, body=None, as_user=None):
        h = {"X-Api-Key": self.key, "Accept": "application/json", "User-Agent": "lab-connector-seerr/2"}
        if as_user:
            h["X-Api-User"] = str(int(as_user))
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c = self._conn()
        try:
            c.request(method, self.base + path, body=data, headers=h)
            r = c.getresponse()
            raw = r.read(16 * 1024 * 1024)
        except (OSError, http.client.HTTPException) as e:
            raise SeerrError(502, f"Seerr unreachable: {e}") from None
        finally:
            c.close()
        if r.status >= 400:
            try:
                msg = json.loads(raw).get("message") or ""
            except (ValueError, AttributeError):
                msg = ""
            code = r.status if r.status in (400, 404, 409) else 403 if r.status in (401, 403) else 502
            raise SeerrError(code, f"Seerr {path.split('?')[0]}: HTTP {r.status} {msg}".strip())
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def image(self, path):
        """(content-type, bytes) from Seerr's own image proxy (it caches TMDB images on disk when cacheImages is on)."""
        c = self._conn(15)
        try:
            c.request("GET", self.base + "/imageproxy/tmdb/t/p/" + path, headers={"User-Agent": "lab-connector-seerr/2"})
            r = c.getresponse()
            raw = r.read(4 * 1024 * 1024 + 1)
        except (OSError, http.client.HTTPException) as e:
            raise SeerrError(502, f"image: {e}") from None
        finally:
            c.close()
        ctype = r.getheader("Content-Type") or ""
        if r.status != 200 or not ctype.startswith("image/") or len(raw) > 4 * 1024 * 1024:
            raise SeerrError(404, "no image")
        return ctype.split(";")[0], raw


API = Seerr("", "")


def configure(v, conf=None):
    global API, PUBLIC, USERS
    API = Seerr(labconn.url(v, "url"), labconn.text(v, "api_key"))
    PUBLIC = labconn.url(v, "public_url") or labconn.url(v, "url")
    USERS = parse_users(",".join(v.get("users") or []))


CONF = labconn.Config(ID, None, apply=configure)


def validate(values):
    """Config test: the CANDIDATE URL + API key must read Seerr's status and an admin-only list."""
    if not labconn.url(values, "url"):
        return {"ok": False, "error": "no URL"}
    s = Seerr(labconn.url(values, "url"), labconn.text(values, "api_key"))
    try:
        st = s.call("GET", "/api/v1/status") or {}
        s.call("GET", "/api/v1/user?take=1")
    except SeerrError as e:
        return {"ok": False, "error": str(e)}
    bad = [p for p in values.get("users") or [] if "=" not in str(p)]
    if bad:
        return {"ok": False, "error": "users: each entry is labuser=seerruser"}
    return {"ok": True, "detail": f"Seerr {st.get('version') or ''} answered with this API key".replace("  ", " ")}


class TTL:
    """Small thread-safe cache: get(key, ttl, fn)."""

    def __init__(self, max_items=4000):
        self.d, self.lock, self.max = {}, threading.Lock(), max_items

    def get(self, key, ttl, fn):
        now = time.time()
        with self.lock:
            hit = self.d.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        val = fn()
        with self.lock:
            if len(self.d) >= self.max:
                for k, _ in sorted(self.d.items(), key=lambda kv: kv[1][0])[: self.max // 4]:
                    self.d.pop(k, None)
            self.d[key] = (now, val)
        return val

    def drop(self, *prefixes):
        with self.lock:
            for k in [k for k in self.d if str(k).startswith(prefixes)]:
                self.d.pop(k, None)


CACHE = TTL()


def changed():
    """After any write: forget everything that shows request/media/user state."""
    CACHE.drop("admin", "mine:", "users", "rawusers", "quota:", "recent", "reqs:", "detail:", "settings", "issues")


# --- users -----------------------------------------------------------------------------------------------------------
def raw_users():
    return CACHE.get("rawusers", 60, lambda: API.call("GET", "/api/v1/user?take=500&skip=0&sort=created").get("results", []))


def uname(u):
    return u.get("displayName") or u.get("jellyfinUsername") or u.get("username") or f"#{u.get('id')}"


def users():
    def load():
        return [{"id": u["id"], "name": uname(u),
                 "keys": {str(u["id"]), *(str(u.get(k) or "").lower() for k in ("jellyfinUsername", "username", "email", "plexUsername"))} - {""},
                 "requests": u.get("requestCount", 0), "permissions": u.get("permissions") or 0} for u in raw_users()]
    return CACHE.get("users", 60, load)


def seerr_user(lab_user):
    want = USERS.get((lab_user or "").lower())
    if not want:
        return None
    for u in users():
        if want in u["keys"]:
            return u
    return None


def lab_users_for(seerr_id):
    out = []
    for lab_u, want in USERS.items():
        for u in users():
            if u["id"] == seerr_id and want in u["keys"]:
                out.append(lab_u)
    return out


def quota(seerr_id):
    def load():
        q = API.call("GET", f"/api/v1/user/{int(seerr_id)}/quota") or {}
        return {k: {"limit": (q.get(k) or {}).get("limit") or 0, "days": (q.get(k) or {}).get("days") or 0,
                    "used": (q.get(k) or {}).get("used") or 0, "remaining": (q.get(k) or {}).get("remaining"),
                    "restricted": bool((q.get(k) or {}).get("restricted"))} for k in ("movie", "tv")}
    return CACHE.get(f"quota:{seerr_id}", 30, load)


def perm_flags(p):
    if p & PERMS["ADMIN"]:
        return ["ADMIN"]
    return [k for k, v in PERMS.items() if p & v]


def user_view(u, with_quota=True):
    p = u.get("permissions") or 0
    out = {"id": u["id"], "name": uname(u), "jellyfin": u.get("jellyfinUsername"), "type": USER_TYPE.get(u.get("userType"), "?"),
           "permissions": p, "flags": perm_flags(p), "admin": bool(p & PERMS["ADMIN"]), "requests": u.get("requestCount", 0),
           "created": u.get("createdAt"), "lab": lab_users_for(u["id"]),
           "quotaSet": {"movieLimit": u.get("movieQuotaLimit"), "movieDays": u.get("movieQuotaDays"),
                        "tvLimit": u.get("tvQuotaLimit"), "tvDays": u.get("tvQuotaDays")}}
    if with_quota:
        try:
            out["quota"] = quota(u["id"])
        except SeerrError:
            out["quota"] = None
    return out


# --- media + requests --------------------------------------------------------------------------------------------------
def year_of(date):
    date = date or ""
    return int(date[:4]) if date[:4].isdigit() else None


def poster(path):
    """Browser path for a TMDB poster through this connector (lab's CSP only allows same-origin images)."""
    if not path or not re.match(r"^/[A-Za-z0-9_-]{5,80}\.(?:jpg|png)$", path):
        return None
    return f"/api/m/{ID}/api/img/w185{path}"


def title(media_type, tmdb_id):
    """{title, year, poster} for a TMDB id via Seerr (it caches TMDB too); cached here for a day."""
    if not tmdb_id or media_type not in ("movie", "tv"):
        return {"title": "?", "year": None, "poster": None}

    def load():
        try:
            d = API.call("GET", f"/api/v1/{media_type}/{int(tmdb_id)}")
        except SeerrError:
            return {"title": f"tmdb {tmdb_id}", "year": None, "poster": None}
        return {"title": d.get("title") or d.get("name") or f"tmdb {tmdb_id}",
                "year": year_of(d.get("releaseDate") or d.get("firstAirDate")), "poster": poster(d.get("posterPath"))}
    return CACHE.get(f"t:{media_type}:{tmdb_id}", 86400, load)


def downloads(media, k4=False):
    out = []
    for d in (media or {}).get("downloadStatus4k" if k4 else "downloadStatus") or []:
        size, left = d.get("size") or 0, d.get("sizeLeft") or 0
        out.append({"title": d.get("title") or "", "status": d.get("status") or "",
                    "progress": round(1 - left / size, 4) if size else None,
                    "eta": d.get("estimatedCompletionTime"), "left": d.get("timeLeft")})
    return out


def media_link(media, mtype, tmdb):
    return (media or {}).get("mediaUrl") or f"{PUBLIC}/{mtype}/{tmdb}"


def request_view(r, with_user=False, admin=False):
    m = r.get("media") or {}
    mtype, tmdb = m.get("mediaType") or r.get("type"), m.get("tmdbId")
    t = title(mtype, tmdb)
    k4 = bool(r.get("is4k"))
    out = {"id": r["id"], "type": mtype, "tmdb": tmdb, "title": t["title"], "year": t["year"], "poster": t["poster"],
           "status": REQ_STATUS.get(r.get("status"), "unknown"),
           "media": MEDIA_STATUS.get(m.get("status4k" if k4 else "status"), "unknown"), "mediaId": m.get("id"),
           "created": r.get("createdAt"), "updated": r.get("updatedAt"),
           "seasons": [{"n": s.get("seasonNumber"), "status": MEDIA_STATUS.get(s.get("status"), "unknown")} for s in r.get("seasons") or []],
           "downloads": downloads(m, k4), "url": media_link(m, mtype, tmdb), "seerr": f"{PUBLIC}/{mtype}/{tmdb}", "is4k": k4,
           "object": f"seerr:{mtype}:{tmdb}"}
    if with_user:
        u = r.get("requestedBy") or {}
        out["by"] = uname(u) if u else "?"
        out["byId"] = u.get("id")
        mb = r.get("modifiedBy") or {}
        out["modifiedBy"] = uname(mb) if mb else None
    if admin:
        out.update({"serverId": r.get("serverId"), "profileId": r.get("profileId"), "rootFolder": r.get("rootFolder"),
                    "service": (m.get("serviceUrl4k") if k4 else m.get("serviceUrl")) or None, "auto": bool(r.get("isAutoRequest"))})
    return out


def mine(seerr_id):
    def load():
        r = API.call("GET", f"/api/v1/user/{int(seerr_id)}/requests?take=40&skip=0")
        return [request_view(x) for x in r.get("results", [])]
    return CACHE.get(f"mine:{seerr_id}", 10, load)


def recent():
    def load():
        r = API.call("GET", "/api/v1/media?take=16&skip=0&filter=allavailable&sort=mediaAdded")
        out = []
        for m in r.get("results", []):
            t = title(m.get("mediaType"), m.get("tmdbId"))
            out.append({"type": m.get("mediaType"), "tmdb": m.get("tmdbId"), "title": t["title"], "year": t["year"],
                        "poster": t["poster"], "status": MEDIA_STATUS.get(m.get("status"), "unknown"),
                        "added": m.get("mediaAddedAt"), "url": media_link(m, m.get("mediaType"), m.get("tmdbId"))})
        return out
    return CACHE.get("recent", 60, load)


def admin_part():
    def load():
        allr = API.call("GET", "/api/v1/request?take=40&skip=0&filter=all&sort=added")
        pend = API.call("GET", "/api/v1/request?take=50&skip=0&filter=pending&sort=added")
        failed = API.call("GET", "/api/v1/request?take=20&skip=0&filter=failed&sort=modified")
        counts = API.call("GET", "/api/v1/request/count")
        try:
            issues = API.call("GET", "/api/v1/issue/count") or {}
        except SeerrError:
            issues = {}
        status = CACHE.get("status", 600, lambda: API.call("GET", "/api/v1/status"))
        return {"all": [request_view(x, True, True) for x in allr.get("results", [])],
                "pending": [request_view(x, True, True) for x in pend.get("results", [])],
                "failed": [request_view(x, True, True) for x in failed.get("results", [])],
                "counts": counts, "issues": {"open": issues.get("open", 0), "total": issues.get("total", 0)},
                "version": status.get("version"), "updateAvailable": bool(status.get("updateAvailable")),
                "commitsBehind": status.get("commitsBehind") or 0, "restartRequired": bool(status.get("restartRequired")),
                "users": [{"id": u["id"], "name": u["name"], "requests": u["requests"]} for u in users()]}
    return CACHE.get("admin", 10, load)


def media_summary(mi, claims, su, k4=False):
    """A media item's state as the caller may see it (guests: only their own requests, no *arr links)."""
    mi = mi or {}
    admin = labauth.at_least(claims, "admin")
    reqs = mi.get("requests") or []
    if not admin:
        reqs = [r for r in reqs if su and (r.get("requestedBy") or {}).get("id") == su["id"]]
    out = {"id": mi.get("id"), "status": MEDIA_STATUS.get(mi.get("status"), "unknown") if mi else "unknown",
           "status4k": MEDIA_STATUS.get(mi.get("status4k"), "unknown") if mi else "unknown",
           "jellyfin": mi.get("mediaUrl"), "jellyfin4k": mi.get("mediaUrl4k"),
           "seasons": {str(s.get("seasonNumber")): MEDIA_STATUS.get(s.get("status"), "unknown") for s in mi.get("seasons") or []},
           "requests": [{"id": r["id"], "status": REQ_STATUS.get(r.get("status"), "unknown"), "is4k": bool(r.get("is4k")),
                         "by": uname(r.get("requestedBy") or {}), "byId": (r.get("requestedBy") or {}).get("id"),
                         "created": r.get("createdAt"), "seasons": [s.get("seasonNumber") for s in r.get("seasons") or []],
                         **({"serverId": r.get("serverId"), "profileId": r.get("profileId"), "rootFolder": r.get("rootFolder")} if admin else {})}
                        for r in reqs],
           "downloads": downloads(mi) + downloads(mi, True)}
    if admin:
        out.update({"service": mi.get("serviceUrl"), "service4k": mi.get("serviceUrl4k"), "added": mi.get("mediaAddedAt"),
                    "issues": len(mi.get("issues") or []), "slug": mi.get("externalServiceSlug"),
                    "serviceId": mi.get("serviceId"), "externalId": mi.get("externalServiceId")})
    return out


def item_view(x):
    """A search / discover / credits result → compact card."""
    mt = x.get("mediaType") or ("tv" if x.get("name") and not x.get("title") else "movie")
    if mt == "person":
        return {"type": "person", "id": x.get("id"), "title": x.get("name"), "poster": poster(x.get("profilePath")),
                "dept": x.get("knownForDepartment")}
    mi = x.get("mediaInfo") or {}
    return {"type": mt, "tmdb": x.get("id"), "title": x.get("title") or x.get("name") or "?",
            "year": year_of(x.get("releaseDate") or x.get("firstAirDate")), "poster": poster(x.get("posterPath")),
            "rating": round(x.get("voteAverage") or 0, 1), "status": MEDIA_STATUS.get(mi.get("status"), "unknown") if mi else "unknown",
            "pop": x.get("popularity") or 0, "role": x.get("character") or x.get("job")}


def public_flags():
    p = CACHE.get("public", 300, lambda: API.call("GET", "/api/v1/settings/public") or {})
    return {"movie4k": bool(p.get("movie4kEnabled")), "series4k": bool(p.get("series4kEnabled")),
            "partial": bool(p.get("partialRequestsEnabled")), "specials": bool(p.get("enableSpecialEpisodes"))}


# --- handlers --------------------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, claims, match, query, body):
        self.claims, self.m, self.q, self.body = claims, match, query, body
        self._su = False

    @property
    def su(self):
        if self._su is False:
            self._su = seerr_user(self.claims["u"])
        return self._su

    @property
    def admin(self):
        return labauth.at_least(self.claims, "admin")

    @property
    def owner(self):
        return self.claims.get("r") == "owner" or bool(self.claims.get("a"))

    def acting(self):
        """X-Api-User for writes: the caller's own Seerr id (None → Seerr falls back to its owner, user 1)."""
        return self.su["id"] if self.su else None

    def linked(self):
        if not self.su and not self.admin:
            raise Refused(403, "no Seerr account linked to you yet — ask owner")

    def int(self, i):
        return int(self.m.group(i))

    def qint(self, k, default, lo, hi):
        try:
            return max(lo, min(hi, int(self.q.get(k, default))))
        except (TypeError, ValueError):
            return default


def h_overview(c):
    su = c.su
    out = {"me": {"linked": bool(su), "name": su["name"] if su else None, "id": su["id"] if su else None,
                  "public": PUBLIC, "role": c.claims.get("r")},
           "mine": mine(su["id"]) if su else [], "recent": recent() if su or c.admin else []}
    if su:
        try:
            out["me"]["quota"] = quota(su["id"])
            out["me"]["admin"] = bool(su["permissions"] & PERMS["ADMIN"])
        except SeerrError:
            out["me"]["quota"] = None
    if c.admin:
        out.update(admin_part())
    out["at"] = int(time.time())
    return out


def h_search(c):
    c.linked()
    q = (c.q.get("q") or "").strip()[:100]
    if len(q) < 2:
        return {"results": [], "page": 1, "pages": 0}
    page = c.qint("page", 1, 1, 50)
    d = API.call("GET", f"/api/v1/search?query={urllib.parse.quote(q)}&page={page}")
    return {"results": [item_view(x) for x in d.get("results", [])], "page": d.get("page", page), "pages": d.get("totalPages", 0),
            "total": d.get("totalResults", 0)}


def h_discover(c):
    c.linked()
    kind = c.m.group(1)
    if kind not in DISCOVER:
        raise Refused(404, "unknown list")
    page = c.qint("page", 1, 1, 50)

    def load():
        d = API.call("GET", f"/api/v1{DISCOVER[kind]}?page={page}")
        return {"results": [item_view(x) for x in d.get("results", []) if x.get("mediaType") != "person"],
                "page": d.get("page", page), "pages": d.get("totalPages", 0)}
    return CACHE.get(f"disc:{kind}:{page}", 600, load)


def h_detail(c):
    c.linked()
    mtype, tmdb = c.m.group(1), c.int(2)
    d = CACHE.get(f"detail:{mtype}:{tmdb}", 20, lambda: API.call("GET", f"/api/v1/{mtype}/{tmdb}"))
    flags = public_flags()
    out = {"type": mtype, "tmdb": tmdb, "title": d.get("title") or d.get("name"), "year": year_of(d.get("releaseDate") or d.get("firstAirDate")),
           "poster": poster(d.get("posterPath")), "overview": (d.get("overview") or "")[:1200], "rating": round(d.get("voteAverage") or 0, 1),
           "genres": [g.get("name") for g in d.get("genres") or []][:5], "runtime": d.get("runtime") or (d.get("episodeRunTime") or [None])[0],
           "state": d.get("status"), "media": media_summary(d.get("mediaInfo"), c.claims, c.su),
           "seerr": f"{PUBLIC}/{mtype}/{tmdb}", "object": f"seerr:{mtype}:{tmdb}",
           "can4k": flags["series4k" if mtype == "tv" else "movie4k"], "partial": flags["partial"],
           "cast": [{"id": p.get("id"), "name": p.get("name"), "role": p.get("character")} for p in ((d.get("credits") or {}).get("cast") or [])[:8]]}
    if mtype == "tv":
        out["tvdb"] = (d.get("externalIds") or {}).get("tvdbId")
        out["seasons"] = [{"n": s.get("seasonNumber"), "name": s.get("name"), "episodes": s.get("episodeCount"), "air": s.get("airDate"),
                           "status": out["media"]["seasons"].get(str(s.get("seasonNumber")), "unknown")}
                          for s in d.get("seasons") or [] if s.get("seasonNumber") or flags["specials"]]
        out["network"] = ", ".join(n.get("name") for n in d.get("networks") or [])[:80]
    return out


def h_person(c):
    c.linked()
    pid = c.int(1)

    def load():
        p = API.call("GET", f"/api/v1/person/{pid}")
        cr = API.call("GET", f"/api/v1/person/{pid}/combined_credits") or {}
        seen, items = set(), []
        for x in sorted((cr.get("cast") or []) + (cr.get("crew") or []), key=lambda x: -(x.get("popularity") or 0)):
            it = item_view(x)
            k = (it["type"], it.get("tmdb"))
            if k in seen:
                continue
            seen.add(k)
            items.append(it)
        return {"id": pid, "name": p.get("name"), "poster": poster(p.get("profilePath")), "dept": p.get("knownForDepartment"),
                "born": p.get("birthday"), "bio": (p.get("biography") or "")[:800], "credits": items[:60]}
    return CACHE.get(f"person:{pid}", 3600, load)


def h_img(c):
    size, f = c.m.group(1), c.m.group(2)
    ctype, raw = API.image(f"{size}{f}")  # not cached here: the browser keeps it a day
    return Raw(ctype, raw, "private, max-age=86400")


class Raw:
    def __init__(self, ctype, data, cache="no-store"):
        self.ctype, self.data, self.cache = ctype, data, cache


def h_requests(c):
    """Request list with filters. Guests: always only their own (requestedBy forced to their Seerr id)."""
    c.linked()
    flt = c.q.get("filter") or "all"
    if flt not in REQ_FILTERS:
        raise Refused(400, f"filter: one of {', '.join(REQ_FILTERS)}")
    take, skip = c.qint("take", 30, 1, 100), c.qint("skip", 0, 0, 100000)
    sort = "modified" if c.q.get("sort") == "modified" else "added"
    qs = f"take={take}&skip={skip}&filter={flt}&sort={sort}"
    if c.q.get("type") in ("movie", "tv"):
        qs += f"&mediaType={c.q['type']}"
    if not c.admin:
        qs += f"&requestedBy={int(c.su['id'])}"
    elif str(c.q.get("by") or "").isdigit():
        qs += f"&requestedBy={int(c.q['by'])}"
    d = API.call("GET", f"/api/v1/request?{qs}")
    return {"results": [request_view(r, True, c.admin) for r in d.get("results", [])],
            "total": (d.get("pageInfo") or {}).get("results", 0), "take": take, "skip": skip, "filter": flt}


def _ints(v, lo=0, hi=200, n=200):
    if not isinstance(v, list) or len(v) > n or not all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in v):
        raise Refused(400, "expected a list of numbers")
    return v


def request_body(c, b, mtype, tmdb, for_edit=False):
    """The Seerr request body from the lab body. Guests: only type/tmdb/seasons(/is4k); everything else is dropped."""
    out = {"mediaType": mtype, "mediaId": tmdb}
    if mtype == "tv":
        seasons = b.get("seasons", "all")
        out["seasons"] = seasons if seasons == "all" else _ints(seasons)
        if not out["seasons"]:
            raise Refused(400, "pick at least one season")
        if isinstance(b.get("tvdb"), int):
            out["tvdbId"] = b["tvdb"]
    if b.get("is4k") is True:
        out["is4k"] = True
    if c.admin:
        for k in ("serverId", "profileId", "languageProfileId"):
            if isinstance(b.get(k), int) and not isinstance(b.get(k), bool):
                out[k] = b[k]
        if isinstance(b.get("rootFolder"), str) and b["rootFolder"].startswith("/") and len(b["rootFolder"]) < 300:
            out["rootFolder"] = b["rootFolder"]
        if isinstance(b.get("tags"), list):
            out["tags"] = _ints(b["tags"], 0, 100000, 50)
        if isinstance(b.get("userId"), int) and not isinstance(b.get("userId"), bool):
            if not any(u["id"] == b["userId"] for u in users()):
                raise Refused(400, "no such Seerr user")
            out["userId"] = b["userId"]
    if for_edit:
        out.pop("mediaId", None)
    return out


def h_request_new(c):
    c.linked()
    b = c.body
    mtype, tmdb = b.get("type"), b.get("tmdb")
    if mtype not in ("movie", "tv") or not isinstance(tmdb, int) or isinstance(tmdb, bool) or tmdb <= 0:
        raise Refused(400, "type movie|tv and a TMDB id")
    body = request_body(c, b, mtype, tmdb)
    if not c.su and not body.get("userId"):
        raise Refused(400, "you have no Seerr account: pick who the request is for")
    r = API.call("POST", "/api/v1/request", body=body, as_user=c.acting())
    changed()
    log.info("%s requested %s %s%s", c.claims["u"], mtype, tmdb, f" for seerr user {body['userId']}" if body.get("userId") else "")
    return {"ok": True, "id": (r or {}).get("id"), "status": REQ_STATUS.get((r or {}).get("status"), "unknown")}


def _request(rid):
    return API.call("GET", f"/api/v1/request/{int(rid)}")


def h_request_edit(c):
    rid = c.int(1)
    cur = _request(rid)
    mtype = (cur.get("media") or {}).get("mediaType") or cur.get("type")
    b = dict(c.body)
    for k in ("serverId", "profileId", "rootFolder", "languageProfileId"):
        b.setdefault(k, cur.get(k))
    b.setdefault("userId", (cur.get("requestedBy") or {}).get("id"))
    if mtype == "tv":
        b.setdefault("seasons", [s.get("seasonNumber") for s in cur.get("seasons") or []])
    b["is4k"] = bool(cur.get("is4k"))
    body = request_body(c, b, mtype, None, for_edit=True)
    body["is4k"] = bool(cur.get("is4k"))
    API.call("PUT", f"/api/v1/request/{rid}", body=body, as_user=c.acting())
    changed()
    return {"ok": True, "id": rid}


def h_request_delete(c):
    """Cancel/delete a request. Guests: only their own, only while pending (the same rule Seerr has)."""
    c.linked()
    rid = c.int(1)
    if not c.admin:
        cur = _request(rid)
        if (cur.get("requestedBy") or {}).get("id") != c.su["id"] or cur.get("status") != 1:
            raise Refused(403, "you can only cancel your own pending requests")
    API.call("DELETE", f"/api/v1/request/{rid}", as_user=c.acting())
    changed()
    log.info("%s deleted request %d", c.claims["u"], rid)
    return {"ok": True, "id": rid}


def h_request_verb(c):
    rid, verb = c.int(1), c.m.group(2)
    API.call("POST", f"/api/v1/request/{rid}/{verb}", body={}, as_user=c.acting())
    changed()
    log.info("%s %s request %d%s", c.claims["u"], verb, rid, f" (approved by {c.claims['a']})" if c.claims.get("a") else "")
    return {"ok": True, "id": rid, "verb": verb}


def h_request_bulk(c):
    verb = c.body.get("verb")
    if verb not in ("approve", "decline"):
        raise Refused(400, "verb approve|decline")
    ids = _ints(c.body.get("ids"), 1, 10**9, 100)
    done, failed = [], []
    for rid in ids:
        try:
            API.call("POST", f"/api/v1/request/{rid}/{verb}", body={}, as_user=c.acting())
            done.append(rid)
        except SeerrError as e:
            failed.append({"id": rid, "error": str(e)})
    changed()
    log.info("%s bulk %s %s", c.claims["u"], verb, done)
    return {"ok": not failed, "done": done, "failed": failed}


# media
MEDIA_SET = ("available", "partial", "processing", "pending", "unknown")


def h_media_status(c):
    mid, st = c.int(1), c.body.get("status")
    if st not in MEDIA_SET:
        raise Refused(400, f"status: one of {', '.join(MEDIA_SET)}")
    API.call("POST", f"/api/v1/media/{mid}/{st}", body={"is4k": c.body.get("is4k") is True}, as_user=c.acting())
    changed()
    return {"ok": True}


def h_media_clear(c):
    mid = c.int(1)
    API.call("DELETE", f"/api/v1/media/{mid}", as_user=c.acting())
    changed()
    log.info("%s cleared media %d", c.claims["u"], mid)
    return {"ok": True}


def h_media_file(c):
    mid = c.int(1)
    k4 = "true" if c.body.get("is4k") is True else "false"
    API.call("DELETE", f"/api/v1/media/{mid}/file?is4k={k4}", as_user=c.acting())
    changed()
    log.info("%s deleted the files of media %d (4k %s)", c.claims["u"], mid, k4)
    return {"ok": True}


# issues
def issue_view(i, full=False):
    m = i.get("media") or {}
    t = title(m.get("mediaType"), m.get("tmdbId"))
    out = {"id": i["id"], "type": ISSUE_TYPE.get(i.get("issueType"), "other"), "status": ISSUE_STATUS.get(i.get("status"), "open"),
           "season": i.get("problemSeason") or None, "episode": i.get("problemEpisode") or None,
           "by": uname(i.get("createdBy") or {}), "created": i.get("createdAt"), "updated": i.get("updatedAt"),
           "mediaType": m.get("mediaType"), "tmdb": m.get("tmdbId"), "title": t["title"], "year": t["year"], "poster": t["poster"],
           "mediaId": m.get("id"), "object": f"seerr:{m.get('mediaType')}:{m.get('tmdbId')}", "comments": len(i.get("comments") or [])}
    if full:
        out["thread"] = [{"id": x.get("id"), "by": uname(x.get("user") or {}), "at": x.get("createdAt"), "message": (x.get("message") or "")[:4000]}
                         for x in i.get("comments") or []]
    return out


def h_issues(c):
    flt = c.q.get("filter") if c.q.get("filter") in ("all", "open", "resolved") else "open"
    take, skip = c.qint("take", 30, 1, 100), c.qint("skip", 0, 0, 100000)
    d = API.call("GET", f"/api/v1/issue?take={take}&skip={skip}&filter={flt}&sort=modified")
    counts = API.call("GET", "/api/v1/issue/count") or {}
    return {"results": [issue_view(i) for i in d.get("results", [])], "total": (d.get("pageInfo") or {}).get("results", 0),
            "counts": {k: counts.get(k, 0) for k in ("total", "open", "closed", "video", "audio", "subtitles", "others")}}


def h_issue(c):
    return issue_view(API.call("GET", f"/api/v1/issue/{c.int(1)}"), full=True)


def h_issue_comment(c):
    msg = c.body.get("message")
    if not isinstance(msg, str) or not msg.strip() or len(msg) > 4000:
        raise Refused(400, "message: 1..4000 characters")
    API.call("POST", f"/api/v1/issue/{c.int(1)}/comment", body={"message": msg.strip()}, as_user=c.acting())
    CACHE.drop("issues")
    return {"ok": True}


def h_issue_status(c):
    st = {"resolve": "resolved", "reopen": "open"}[c.m.group(2)]
    API.call("POST", f"/api/v1/issue/{c.int(1)}/{st}", body={}, as_user=c.acting())
    changed()
    return {"ok": True}


# users
def h_users(c):
    return {"users": [user_view(u) for u in raw_users()], "perms": PERMS, "privileged": PRIVILEGED}


def h_jf_users(c):
    jf = API.call("GET", "/api/v1/settings/jellyfin/users") or []
    have = {u.get("jellyfinUserId") for u in raw_users()}
    return {"users": [{"id": u.get("id"), "name": u.get("username"), "imported": u.get("id") in have} for u in jf]}


def h_users_import(c):
    ids = c.body.get("ids")
    if not (isinstance(ids, list) and 0 < len(ids) <= 50 and all(isinstance(x, str) and re.match(r"^[0-9a-f]{32}$", x) for x in ids)):
        raise Refused(400, "ids: Jellyfin user ids")
    r = API.call("POST", "/api/v1/user/import-from-jellyfin", body={"jellyfinUserIds": ids}, as_user=c.acting())
    changed()
    log.info("%s imported Jellyfin users %s", c.claims["u"], ids)
    return {"ok": True, "imported": [uname(u) for u in r or []]}


def _target_user(c, uid):
    if uid == 1:
        raise Refused(403, "Seerr's owner account (#1) is changed in Seerr only")
    u = next((x for x in raw_users() if x["id"] == uid), None)
    if not u:
        raise Refused(404, "no such Seerr user")
    return u


def h_user_perms(c, full=False):
    uid = c.int(1)
    u = _target_user(c, uid)
    p = c.body.get("permissions")
    if not isinstance(p, int) or isinstance(p, bool) or p < 0 or p & ~ALL_PERMS:
        raise Refused(400, "permissions: a Seerr permission bit mask")
    cur = u.get("permissions") or 0
    if not full and (p & PRIVILEGED) != (cur & PRIVILEGED):
        raise Refused(403, "admin / manage-settings / manage-users are identity: use the owner-only route")
    if full and not c.owner:
        raise Refused(403, "owner only")
    if c.su and c.su["id"] == uid:
        raise Refused(403, "you cannot change your own Seerr permissions")
    API.call("POST", f"/api/v1/user/{uid}/settings/permissions", body={"permissions": p}, as_user=c.acting())
    changed()
    log.info("%s set permissions of seerr user %d: %d → %d", c.claims["u"], uid, cur, p)
    return {"ok": True, "permissions": p}


def _qnum(v, hi):
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= hi:
        raise Refused(400, "quota values: whole numbers (or null = global default)")
    return v or None


def h_user_quota(c):
    uid = c.int(1)
    u = _target_user(c, uid)
    if (u.get("permissions") or 0) & (PERMS["ADMIN"] | PERMS["MANAGE_USERS"]):
        raise Refused(400, "quotas do not apply to Seerr admins / user managers (Seerr ignores them)")
    b = c.body
    cur = API.call("GET", f"/api/v1/user/{uid}/settings/main") or {}
    # Seerr's POST replaces all of these; a user who never saved settings has nulls, and locale may not be null
    body = {k: cur.get(k) for k in ("username", "email", "watchlistSyncMovies", "watchlistSyncTv")}
    body.update({k: cur.get(k) or "" for k in ("locale", "discoverRegion", "streamingRegion", "originalLanguage")})
    body.update({"movieQuotaLimit": _qnum(b.get("movieLimit"), 1000), "movieQuotaDays": _qnum(b.get("movieDays"), 365),
                 "tvQuotaLimit": _qnum(b.get("tvLimit"), 1000), "tvQuotaDays": _qnum(b.get("tvDays"), 365)})
    API.call("POST", f"/api/v1/user/{uid}/settings/main", body=body, as_user=c.acting())
    changed()
    log.info("%s set quotas of seerr user %d", c.claims["u"], uid)
    return {"ok": True}


def h_user_delete(c):
    uid = c.int(1)
    _target_user(c, uid)
    if c.su and c.su["id"] == uid:
        raise Refused(403, "not yourself")
    API.call("DELETE", f"/api/v1/user/{uid}", as_user=c.acting())
    changed()
    log.info("%s deleted seerr user %d", c.claims["u"], uid)
    return {"ok": True}


# settings
def _servers(app):
    return [{k: v for k, v in s.items() if k.lower() != "apikey"} for s in API.call("GET", f"/api/v1/settings/{app}") or []]


def h_settings(c):
    def load():
        main = API.call("GET", "/api/v1/settings/main") or {}
        jf = API.call("GET", "/api/v1/settings/jellyfin") or {}
        try:
            sync = API.call("GET", "/api/v1/settings/jellyfin/sync") or {}
        except SeerrError:
            sync = {}
        notif = []  # a list: scrub() drops dict keys such as "email"
        for a in NOTIFY_AGENTS:
            try:
                n = API.call("GET", f"/api/v1/settings/notifications/{a}") or {}
            except SeerrError:
                continue
            notif.append({"agent": a, "enabled": bool(n.get("enabled")), "types": n.get("types"), "configured": configured(a, n)})
        about = API.call("GET", "/api/v1/settings/about") or {}
        status = API.call("GET", "/api/v1/status") or {}
        return {
            "main": {k: main.get(k) for k in (*MAIN_ADMIN, *MAIN_OWNER)},
            "jellyfin": {"name": jf.get("name"), "host": f"{'https' if jf.get('useSsl') else 'http'}://{jf.get('ip')}:{jf.get('port')}{jf.get('urlBase') or ''}",
                         "external": jf.get("externalHostname"), "libraries": jf.get("libraries") or [],
                         "sync": {"running": bool(sync.get("running")), "progress": sync.get("progress"), "total": sync.get("total"),
                                  "library": (sync.get("currentLibrary") or {}).get("name")}},
            "radarr": _servers("radarr"), "sonarr": _servers("sonarr"), "notifications": notif,
            "jobs": [{k: j.get(k) for k in ("id", "name", "type", "interval", "cronSchedule", "nextExecutionTime", "running")}
                     for j in API.call("GET", "/api/v1/settings/jobs") or []],
            "caches": [{"id": x.get("id"), "name": x.get("name"), **(x.get("stats") or {})} for x in (API.call("GET", "/api/v1/settings/cache") or {}).get("apiCaches", [])],
            "about": {"version": about.get("version"), "media": about.get("totalMediaItems"), "requests": about.get("totalRequests"),
                      "tz": about.get("tz"), "updateAvailable": bool(status.get("updateAvailable")),
                      "commitsBehind": status.get("commitsBehind") or 0, "restartRequired": bool(status.get("restartRequired"))},
            "perms": PERMS, "privileged": PRIVILEGED,
        }
    return CACHE.get("settings", 5, load)


def _typed(body, allowed):
    out = {}
    for k, v in body.items():
        t = allowed.get(k)
        if t is None:
            raise Refused(400, f"field not editable here: {k}")
        if t is int and (isinstance(v, bool) or not isinstance(v, int)):
            raise Refused(400, f"{k}: a whole number")
        if t is not int and not isinstance(v, t):
            raise Refused(400, f"{k}: wrong type")
        if t is str and len(v) > 300:
            raise Refused(400, f"{k}: too long")
        out[k] = v
    if not out:
        raise Refused(400, "nothing to change")
    return out


def h_main(c, owner=False):
    allowed = MAIN_OWNER if owner else MAIN_ADMIN
    body = _typed(c.body, allowed)
    if "defaultPermissions" in body and (body["defaultPermissions"] < 0 or body["defaultPermissions"] & ~ALL_PERMS
                                         or body["defaultPermissions"] & PRIVILEGED):
        raise Refused(400, "defaultPermissions: request-level bits only (never admin for every new user)")
    if "defaultQuotas" in body:
        dq = body["defaultQuotas"]
        clean = {}
        for k in ("movie", "tv"):
            x = dq.get(k) or {}
            clean[k] = {"quotaLimit": _qnum(x.get("quotaLimit"), 1000), "quotaDays": _qnum(x.get("quotaDays"), 365)}
        body["defaultQuotas"] = clean
    if "applicationUrl" in body and body["applicationUrl"] and not re.match(r"^https?://[^\s]+$", body["applicationUrl"]):
        raise Refused(400, "applicationUrl: http(s)://…")
    API.call("POST", "/api/v1/settings/main", body=body, as_user=c.acting())
    changed()
    CACHE.drop("public")
    log.info("%s changed main settings %s", c.claims["u"], sorted(body))
    return {"ok": True, "changed": sorted(body)}


def h_jf_library(c):
    lib = c.m.group(1)
    if not isinstance(c.body.get("enabled"), bool):
        raise Refused(400, "enabled: true/false")
    API.call("PUT", f"/api/v1/settings/jellyfin/library/{lib}", body={"enabled": c.body["enabled"]}, as_user=c.acting())
    changed()
    return {"ok": True}


def h_jf_libraries_refresh(c):
    API.call("POST", "/api/v1/settings/jellyfin/library/sync", body={}, as_user=c.acting())
    changed()
    return {"ok": True}


def h_jf_sync(c):
    verb = c.m.group(1)
    API.call("POST", "/api/v1/settings/jellyfin/sync", body={"start": True} if verb == "start" else {"cancel": True}, as_user=c.acting())
    changed()
    return {"ok": True}


def h_server_options(c):
    app, sid = c.m.group(1), c.int(2)
    d = API.call("GET", f"/api/v1/service/{app}/{sid}") or {}
    out = {"profiles": [{"id": p.get("id"), "name": p.get("name")} for p in d.get("profiles") or []],
           "roots": [{"path": r.get("path"), "free": r.get("freeSpace")} for r in d.get("rootFolders") or []],
           "languages": [{"id": p.get("id"), "name": p.get("name")} for p in d.get("languageProfiles") or []],
           "tags": [{"id": t.get("id"), "label": t.get("label")} for t in d.get("tags") or []]}
    return out


def h_request_options(c):
    """Servers + profiles + root folders + users for admins' advanced request / edit form."""
    def load():
        out = {"radarr": [], "sonarr": []}
        for app in ("radarr", "sonarr"):
            for s in API.call("GET", f"/api/v1/service/{app}") or []:
                try:
                    opts = API.call("GET", f"/api/v1/service/{app}/{int(s['id'])}") or {}
                except SeerrError:
                    opts = {}
                out[app].append({"id": s["id"], "name": s.get("name"), "is4k": bool(s.get("is4k")), "isDefault": bool(s.get("isDefault")),
                                 "profile": s.get("activeProfileId"), "root": s.get("activeDirectory"),
                                 "profiles": [{"id": p.get("id"), "name": p.get("name")} for p in opts.get("profiles") or []],
                                 "roots": [{"path": r.get("path"), "free": r.get("freeSpace")} for r in opts.get("rootFolders") or []]})
        out["users"] = [{"id": u["id"], "name": u["name"]} for u in users()]
        return out
    return CACHE.get("reqopts", 120, load)


def h_server_edit(c):
    app, sid = c.m.group(1), c.int(2)
    body = _typed(c.body, SERVER_EDIT[app])
    if "minimumAvailability" in body and body["minimumAvailability"] not in ("announced", "inCinemas", "released"):
        raise Refused(400, "minimumAvailability: announced|inCinemas|released")
    if "externalUrl" in body and body["externalUrl"] and not re.match(r"^https?://[^\s]+$", body["externalUrl"]):
        raise Refused(400, "externalUrl: http(s)://…")
    cur = next((s for s in API.call("GET", f"/api/v1/settings/{app}") or [] if s.get("id") == sid), None)
    if not cur:
        raise Refused(404, f"no {app} server {sid}")
    opts = API.call("GET", f"/api/v1/service/{app}/{sid}") or {}
    names = {p.get("id"): p.get("name") for p in opts.get("profiles") or []}
    roots = {r.get("path") for r in opts.get("rootFolders") or []}
    for k in ("activeProfileId", "activeAnimeProfileId"):
        if k in body and body[k] not in names:
            raise Refused(400, f"{k}: not a {app} quality profile")
    for k in ("activeDirectory", "activeAnimeDirectory"):
        if k in body and body[k] not in roots:
            raise Refused(400, f"{k}: not a {app} root folder")
    new = {**cur, **body}  # the stored API key stays in here, server side; it is never sent to or taken from the browser
    if "activeProfileId" in body:
        new["activeProfileName"] = names[body["activeProfileId"]]
    if "activeAnimeProfileId" in body:
        new["activeAnimeProfileName"] = names[body["activeAnimeProfileId"]]
    new.pop("id", None)
    API.call("PUT", f"/api/v1/settings/{app}/{sid}", body=new, as_user=c.acting())
    changed()
    CACHE.drop("reqopts")
    log.info("%s changed %s server %d: %s", c.claims["u"], app, sid, sorted(body))
    return {"ok": True, "changed": sorted(body)}


def h_server_test(c):
    app, sid = c.m.group(1), c.int(2)
    cur = next((s for s in API.call("GET", f"/api/v1/settings/{app}") or [] if s.get("id") == sid), None)
    if not cur:
        raise Refused(404, f"no {app} server {sid}")
    r = API.call("POST", f"/api/v1/settings/{app}/test", body=cur, as_user=c.acting()) or {}
    return {"ok": True, "profiles": len(r.get("profiles") or []), "roots": len(r.get("rootFolders") or [])}


def configured(agent, n):
    opts = n.get("options") or {}
    return all(opts.get(k) not in (None, "") for k in NOTIFY_NEEDS[agent])


def h_notify_test(c):
    agent = c.m.group(1)
    cur = API.call("GET", f"/api/v1/settings/notifications/{agent}") or {}
    API.call("POST", f"/api/v1/settings/notifications/{agent}/test", body=cur, as_user=c.acting())
    return {"ok": True}


def h_notify_enabled(c):
    agent = c.m.group(1)
    on = c.body.get("enabled")
    if not isinstance(on, bool):
        raise Refused(400, "enabled: true/false")
    cur = API.call("GET", f"/api/v1/settings/notifications/{agent}") or {}
    if on and not configured(agent, cur):
        raise Refused(400, f"{agent} is not configured in Seerr yet ({', '.join(NOTIFY_NEEDS[agent])})")
    cur["enabled"] = on
    API.call("POST", f"/api/v1/settings/notifications/{agent}", body=cur, as_user=c.acting())
    CACHE.drop("settings")
    return {"ok": True}


def h_job(c):
    jid, verb = c.m.group(1), c.m.group(2)
    API.call("POST", f"/api/v1/settings/jobs/{jid}/{verb}", body={}, as_user=c.acting())
    CACHE.drop("settings")
    log.info("%s %s job %s", c.claims["u"], verb, jid)
    return {"ok": True}


def h_cache_flush(c):
    API.call("POST", f"/api/v1/settings/cache/{c.m.group(1)}/flush", body={}, as_user=c.acting())
    CACHE.drop("settings")
    return {"ok": True}


# (method, path regex, min role: guest|admin|owner, handler). "guest" = anyone with module access; handlers that need
# a linked Seerr account call c.linked(). "owner" = role owner or a lab owner approval ("a" claim).
N = r"(\d{1,9})"
ROUTES = [
    ("GET", r"/api/overview", "guest", h_overview),
    ("GET", r"/api/search", "guest", h_search),
    ("GET", r"/api/discover/([a-z-]{2,20})", "guest", h_discover),
    ("GET", r"/api/(movie|tv)/" + N, "guest", h_detail),
    ("GET", r"/api/person/" + N, "guest", h_person),
    ("GET", r"/api/img/(w92|w185|w342)(/[A-Za-z0-9_-]{5,80}\.(?:jpg|png))", "guest", h_img),
    ("GET", r"/api/requests", "guest", h_requests),
    ("POST", r"/api/requests", "guest", h_request_new),
    ("DELETE", r"/api/requests/" + N, "guest", h_request_delete),
    ("GET", r"/api/request-options", "admin", h_request_options),
    ("POST", r"/api/requests/bulk", "admin", h_request_bulk),
    ("PUT", r"/api/requests/" + N, "admin", h_request_edit),
    ("POST", r"/api/requests/" + N + r"/(approve|decline|retry)", "admin", h_request_verb),
    ("POST", r"/api/media/" + N + r"/status", "admin", h_media_status),
    ("POST", r"/api/media/" + N + r"/clear", "admin", h_media_clear),
    ("POST", r"/api/media/" + N + r"/delete-file", "admin", h_media_file),
    ("GET", r"/api/issues", "admin", h_issues),
    ("GET", r"/api/issues/" + N, "admin", h_issue),
    ("POST", r"/api/issues/" + N + r"/comment", "admin", h_issue_comment),
    ("POST", r"/api/issues/" + N + r"/(resolve|reopen)", "admin", h_issue_status),
    ("GET", r"/api/users", "admin", h_users),
    ("GET", r"/api/users/jellyfin", "admin", h_jf_users),
    ("POST", r"/api/users/import", "owner", h_users_import),
    ("POST", r"/api/users/" + N + r"/permissions", "admin", h_user_perms),
    ("POST", r"/api/users/" + N + r"/permissions/full", "owner", lambda c: h_user_perms(c, True)),
    ("POST", r"/api/users/" + N + r"/quota", "admin", h_user_quota),
    ("DELETE", r"/api/users/" + N, "owner", h_user_delete),
    ("GET", r"/api/settings", "admin", h_settings),
    ("POST", r"/api/settings/main", "admin", h_main),
    ("POST", r"/api/settings/main/access", "owner", lambda c: h_main(c, True)),
    ("POST", r"/api/settings/jellyfin/libraries/([0-9a-f]{32})", "admin", h_jf_library),
    ("POST", r"/api/settings/jellyfin/libraries/refresh", "admin", h_jf_libraries_refresh),
    ("POST", r"/api/settings/jellyfin/sync/(start|cancel)", "admin", h_jf_sync),
    ("GET", r"/api/settings/(radarr|sonarr)/" + N + r"/options", "admin", h_server_options),
    ("POST", r"/api/settings/(radarr|sonarr)/" + N, "admin", h_server_edit),
    ("POST", r"/api/settings/(radarr|sonarr)/" + N + r"/test", "admin", h_server_test),
    ("POST", r"/api/settings/notifications/(" + "|".join(NOTIFY_AGENTS) + r")/test", "admin", h_notify_test),
    ("POST", r"/api/settings/notifications/(" + "|".join(NOTIFY_AGENTS) + r")/enabled", "admin", h_notify_enabled),
    ("POST", r"/api/jobs/([a-z0-9-]{2,60})/(run|cancel)", "admin", h_job),
    ("POST", r"/api/cache/([a-z0-9-]{2,40})/flush", "admin", h_cache_flush),
]
ROUTES = [(m, re.compile("^" + p + "$"), role, fn) for m, p, role, fn in ROUTES]


def allowed(claims, role):
    if role == "owner":
        return claims.get("r") == "owner" or (claims.get("r") == "admin" and bool(claims.get("a")))
    return labauth.at_least(claims, role)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    key = None

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _send(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(scrub(obj), separators=(",", ":")).encode(), "application/json")

    def _claims(self):
        if self.client_address[0] != LAB_FROM:
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), Handler.key, ID)

    def _handle(self, method):
        u = urllib.parse.urlsplit(self.path)
        path = u.path.rstrip("/") or "/"
        body = {}
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return self._json(413, {"error": "body too large"})
        raw = self.rfile.read(n) if n else b""
        if method == "GET" and path == "/healthz":
            return self._json(200, {"ok": True, "key": bool(Handler.key), "config": CONF.ready, "users": len(USERS)})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if method == "POST" and path == "/api/_validate":
            try:
                return self._json(200, validate(labconn.candidate(claims, json.loads(raw or b"{}"))))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        for m, rx, role, fn in ROUTES:
            if m != method:
                continue
            hit = rx.match(path)
            if not hit:
                continue
            if not allowed(claims, role):
                return self._json(403, {"error": "owner only" if role == "owner" else "admin only"})
            if raw:
                try:
                    body = json.loads(raw)
                except ValueError:
                    return self._json(400, {"error": "JSON body expected"})
                if not isinstance(body, dict):
                    return self._json(400, {"error": "JSON object expected"})
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                out = fn(Ctx(claims, hit, q, body))
            except Refused as e:
                return self._json(e.status, {"error": str(e)})
            except SeerrError as e:
                return self._json(e.status, {"error": str(e)})
            if isinstance(out, Raw):
                return self._send(200, out.data, out.ctype, out.cache)
            return self._json(200, out if out is not None else {"ok": True})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    pool = ThreadPoolExecutor(max_workers=8)

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)


def serve(host="127.0.0.1", port=PORT):
    Handler.key = CONF.key = labconn.load_key(ID)
    return PooledHTTPServer((host, port), Handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    srv = serve()
    log.info("connector %s on 127.0.0.1:%s (key %s)", ID, PORT, "ok" if Handler.key else "MISSING")
    CONF.start()
    srv.serve_forever()
