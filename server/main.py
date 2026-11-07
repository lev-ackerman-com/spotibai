"""Spotibai server: manipis na API sa ibabaw ng ytmusicapi.

GET /           -> health check
GET /home       -> mga rows para sa Music tab. Naka-cache sa memory ng 30 min.
GET /videos     -> mga rows para sa Video tab. Naka-cache ng 30 min.
GET /search?q=&type=songs|videos -> listahan ng kanta o video. Naka-cache ng 15 min.
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


def search_videos(q, limit=20):
    return clean(yt.search(q, filter="videos", limit=limit), limit)


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


def vq(query):
    return lambda: search_videos(query)


# Dito mo dagdagan/baguhin ang mga rows. (English ang mga pamagat dahil ito ang lalabas sa app.)
ROWS = [
    {"id": "top", "title": "Top Hits in the Philippines", "fn": top_charts},
    {"id": "opm", "title": "OPM Hits", "fn": q("OPM hits")},
    {"id": "new", "title": "New Releases", "fn": q("new songs this week")},
    {"id": "rated", "title": "Highest Rated of All Time", "fn": q("greatest songs of all time")},
    {"id": "pinoyrock", "title": "Pinoy Rock Classics", "fn": q("pinoy rock classics")},
    {"id": "hugot", "title": "Hugot & Ballads", "fn": q("OPM love songs ballad")},
    {"id": "chill", "title": "Chill Vibes", "fn": q("chill songs")},
]

VIDEO_ROWS = [
    {"id": "v-top", "title": "Trending Videos", "fn": vq("top music videos Philippines")},
    {"id": "v-opm", "title": "OPM Music Videos", "fn": vq("OPM official music video")},
    {"id": "v-live", "title": "Live Performances", "fn": vq("OPM live performance")},
    {"id": "v-lyric", "title": "Lyric Videos", "fn": vq("OPM lyric video")},
    {"id": "v-new", "title": "New Music Videos", "fn": vq("new music video this week")},
    {"id": "v-rock", "title": "Pinoy Rock Live", "fn": vq("pinoy rock live")},
]


def build_rows(rows_def):
    def run(row):
        try:
            tracks = row["fn"]()
        except Exception:
            tracks = []
        return {"id": row["id"], "title": row["title"], "tracks": tracks}

    with ThreadPoolExecutor(max_workers=len(rows_def)) as ex:
        rows = list(ex.map(run, rows_def))
    return [r for r in rows if r["tracks"]]


# ---------------------------------------------------------------- routes


@app.get("/")
def root():
    return {"ok": True, "name": "spotibai-server"}


@app.get("/home")
def home():
    return {"rows": cached("home", HOME_TTL, lambda: build_rows(ROWS)) or []}


@app.get("/videos")
def videos():
    return {"rows": cached("videos", HOME_TTL, lambda: build_rows(VIDEO_ROWS)) or []}


@app.get("/search")
def search(q: str = Query(..., min_length=1), type: str = Query("songs")):
    query = q.strip()
    kind = "videos" if type == "videos" else "songs"
    fn = search_videos if kind == "videos" else search_songs
    return cached(f"search:{kind}:{query.lower()}", SEARCH_TTL, lambda: fn(query)) or []