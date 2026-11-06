"""Spotibai server: manipis na API sa ibabaw ng ytmusicapi.

GET /           -> health check
GET /home       -> mga rows para sa Home (Top, OPM, Bago, ...). Naka-cache sa memory ng 30 min.
GET /search?q=  -> listahan ng mga kanta. Naka-cache ng 15 min.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from ytmusicapi import YTMusic

app = FastAPI(title="Spotibai Server")
app.add_middleware(GZipMiddleware, minimum_size=1000)

try:
    yt = YTMusic(language="en", location="PH")
except Exception:  # kapag hindi tinanggap ang location
    yt = YTMusic()

COUNTRY = "PH"
HOME_TTL = 30 * 60
SEARCH_TTL = 15 * 60

# ---------------------------------------------------------------- helpers

_SIZE_RE = re.compile(r"=w\d+-h\d+")


def hq(url, size=400):
    """Palakihin ang thumbnail (yt3.googleusercontent.com ay tumatanggap ng =wXXX-hXXX)."""
    if not url:
        return None
    return _SIZE_RE.sub(f"=w{size}-h{size}", url, count=1)


def to_track(r):
    vid = r.get("videoId")
    if not vid:
        return None
    thumbs = r.get("thumbnails") or []
    artists = r.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists if a.get("name"))
    return {
        "videoId": vid,
        "title": r.get("title", ""),
        "artist": artist or r.get("artist", "") or "",
        "thumbnail": hq(thumbs[-1].get("url")) if thumbs else None,
        "duration": r.get("duration"),
    }


def clean(items, limit=20):
    """Gawing track, tanggalin ang walang videoId at ang duplicate."""
    seen, out = set(), []
    for r in items or []:
        t = to_track(r)
        if t and t["videoId"] not in seen:
            seen.add(t["videoId"])
            out.append(t)
        if len(out) >= limit:
            break
    return out


_cache = {}
_lock = threading.Lock()


def cached(key, ttl, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    if value:  # huwag i-cache ang walang laman
        with _lock:
            _cache[key] = (now, value)
            if len(_cache) > 300:
                for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:50]:
                    _cache.pop(k, None)
    return value


# ---------------------------------------------------------------- data sources


def search_songs(q, limit=20):
    return clean(yt.search(q, filter="songs", limit=limit), limit)


def top_charts():
    """Chart playlist ng bansa -> mga kanta. Fallback: search."""
    try:
        charts = yt.get_charts(COUNTRY)
        playlists = charts.get("videos") or []
        if playlists:
            pl = yt.get_playlist(playlists[0]["playlistId"], limit=25)
            tracks = clean(pl.get("tracks"), 20)
            if tracks:
                return tracks
    except Exception:
        pass
    return search_songs("top hits Philippines")


def q(query):
    return lambda: search_songs(query)


# Dito mo dagdagan/baguhin ang mga rows sa Home.
ROWS = [
    {"id": "top", "title": "Top ngayon sa Pilipinas", "fn": top_charts},
    {"id": "opm", "title": "OPM Hits", "fn": q("OPM hits")},
    {"id": "new", "title": "Bagong labas", "fn": q("new songs this week")},
    {"id": "rated", "title": "Top rated all-time", "fn": q("greatest songs of all time")},
    {"id": "pinoyrock", "title": "Pinoy Rock", "fn": q("pinoy rock classics")},
    {"id": "hugot", "title": "Hugot at Ballads", "fn": q("OPM love songs ballad")},
    {"id": "chill", "title": "Chill vibes", "fn": q("chill songs")},
]


def build_home():
    def run(row):
        try:
            tracks = row["fn"]()
        except Exception:
            tracks = []
        return {"id": row["id"], "title": row["title"], "tracks": tracks}

    with ThreadPoolExecutor(max_workers=len(ROWS)) as ex:
        rows = list(ex.map(run, ROWS))
    return [r for r in rows if r["tracks"]]


# ---------------------------------------------------------------- routes


@app.get("/")
def root():
    return {"ok": True, "name": "spotibai-server"}


@app.get("/home")
def home():
    return {"rows": cached("home", HOME_TTL, build_home) or []}


@app.get("/search")
def search(q: str = Query(..., min_length=1)):
    query = q.strip()
    return cached("search:" + query.lower(), SEARCH_TTL, lambda: search_songs(query)) or []
