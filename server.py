#!/usr/bin/env python3
"""Newport Navigator — static PWA plus family pin API (resolve + sync)."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import irish_write as irish_write_mod
import landmarks as landmarks_mod

irish_write_mod.load_env_local()

ROOT = Path(__file__).resolve().parent
DEFAULT_TRIP = "clewbay2026"
NOMINATIM_UA = "NewportNavigator/1.0 (https://newport-navigator.fly.dev; family trip map)"
MAPS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
IE_LAT = (51.2, 55.6)
IE_LNG = (-11.0, -5.3)
MAX_PINS = 400
MAX_HOPS = 300
MAX_BODY = 1_000_000
PIN_KEYS = (
    "id", "name", "desc", "lat", "lng", "cat", "catLabel", "emoji",
    "addedBy", "createdAt", "updatedAt", "deleted",
)
KNOWN_CATS = frozenset(("family", "food", "shop", "beach", "do", "golf", "landmarks"))

_store_lock = threading.Lock()
_nominatim_lock = threading.Lock()
_nominatim_last = 0.0

EIRCODE_RE = re.compile(r"\b([A-Za-z]\d{2})\s*([A-Za-z0-9]{4})\b")
AT_RE = re.compile(r"@(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)")
BANG_RE = re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)")
LL_RE = re.compile(
    r"(?:[?&#](?:ll|q|query|destination|center|daddr|saddr)=)"
    r"(-?\d{1,2}\.\d+)[,+/](-?\d{1,3}\.\d+)",
    re.I,
)
GEO_RE = re.compile(
    r"geo:(?:0,0\?q=)?(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)",
    re.I,
)
RAW_RE = re.compile(
    r"^\s*(-?\d{1,2}\.\d+)\s*[,/\s]\s*(-?\d{1,3}\.\d+)\s*$"
)
PLACE_RE = re.compile(r"/maps/place/([^/@?#]+)", re.I)
SHORT_HOSTS = ("maps.app.goo.gl", "goo.gl", "g.co")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


class ResolveError(Exception):
    pass


def trip_code() -> str:
    return os.environ.get("NN_TRIP_CODE", DEFAULT_TRIP).strip() or DEFAULT_TRIP


def clan_answer() -> str:
    return os.environ.get("NN_CLAN_ANSWER", "").strip()


def norm_clan(raw) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip().lower())


def clan_ok(raw) -> bool:
    got = norm_clan(raw)
    want = norm_clan(clan_answer())
    if not got or len(got) != len(want):
        return False
    return hmac.compare_digest(got, want)


def pins_path() -> Path:
    env = os.environ.get("NN_DATA")
    if env:
        return Path(env)
    if Path("/data").is_dir():
        return Path("/data/family-pins.json")
    d = ROOT / ".data"
    d.mkdir(exist_ok=True)
    return d / "family-pins.json"


def hops_path() -> Path:
    env = os.environ.get("NN_HOPS")
    if env:
        return Path(env)
    if Path("/data").is_dir():
        return Path("/data/family-hops.json")
    d = ROOT / ".data"
    d.mkdir(exist_ok=True)
    return d / "family-hops.json"


def plausible(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def in_ireland(lat: float, lng: float) -> bool:
    return IE_LAT[0] <= lat <= IE_LAT[1] and IE_LNG[0] <= lng <= IE_LNG[1]


def pick_coords(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not pairs:
        return None
    ie = [p for p in pairs if in_ireland(*p)]
    lat, lng = (ie or pairs)[0]
    return (round(lat, 6), round(lng, 6))


def coords_in_text(text: str) -> tuple[float, float] | None:
    pairs: list[tuple[float, float]] = []
    for rx in (AT_RE, BANG_RE, LL_RE, GEO_RE):
        for m in rx.finditer(text):
            lat, lng = float(m.group(1)), float(m.group(2))
            if plausible(lat, lng):
                pairs.append((lat, lng))
    m = RAW_RE.match(text.strip())
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if plausible(lat, lng):
            pairs.append((lat, lng))
    return pick_coords(pairs)


def extract_eircode(text: str) -> str | None:
    m = EIRCODE_RE.search(text.replace("-", " "))
    if not m:
        return None
    return (m.group(1) + m.group(2)).upper()


def place_name_from_url(text: str) -> str | None:
    m = PLACE_RE.search(text)
    if not m:
        return None
    raw = urllib.parse.unquote_plus(m.group(1)).replace("+", " ").strip()
    raw = re.sub(r"\s+", " ", raw)
    if not raw or raw.lower() in {"data", "place"}:
        return None
    return raw[:79] or None


def geo_name(text: str) -> str | None:
    m = re.search(r"geo:[^#]*\(([^)]+)\)", text, re.I)
    if not m:
        return None
    name = urllib.parse.unquote_plus(m.group(1)).strip()
    return name[:79] or None


def looks_like_url(text: str) -> bool:
    t = text.strip()
    if re.match(r"^https?://", t, re.I):
        return True
    host = t.split("/")[0].lower()
    return host in SHORT_HOSTS or host.endswith("google.com") or host.endswith("maps.apple.com")


def normalize_url(text: str) -> str:
    t = text.strip()
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t
    return t


def parse_local(text: str) -> dict | None:
    t = text.strip()
    if not t:
        return None
    coords = coords_in_text(t)
    if not coords:
        return None
    lat, lng = coords
    name = geo_name(t) or place_name_from_url(t)
    source = "geo" if t.lower().startswith("geo:") else "maps" if looks_like_url(t) else "coords"
    out = {"lat": lat, "lng": lng, "source": source}
    if name:
        out["name"] = name
    return out


def _open(req: urllib.request.Request, timeout: float = 8):
    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedir)
    return opener.open(req, timeout=timeout)


def follow_redirects(url: str, hops: int = 10) -> list[str]:
    seen = [url]
    current = url
    for _ in range(hops):
        req = urllib.request.Request(current, method="GET", headers={"User-Agent": MAPS_UA})
        loc = None
        try:
            with _open(req) as resp:
                loc = resp.headers.get("Location")
                body_url = resp.geturl()
                if body_url and body_url not in seen:
                    seen.append(body_url)
                if not loc:
                    # Short links sometimes 200 with the coords only in HTML.
                    chunk = resp.read(65536).decode("utf-8", "replace")
                    if chunk:
                        seen.append("html:" + chunk[:8000])
                    break
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            try:
                e.read()
            except Exception:
                pass
        except Exception:
            break
        if not loc:
            break
        current = urllib.parse.urljoin(current, loc)
        if current in seen:
            break
        seen.append(current)
        if coords_in_text(current):
            break
    return seen


def compact_eircode(code: str) -> str:
    return re.sub(r"\s+", "", code).upper()


def _http_json(url: str, ua: str, timeout: float = 12, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": ua,
        "Accept": "application/json",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def nominatim_search(query: str, extra: dict | None = None, limit: int = 1) -> list:
    global _nominatim_last
    params = {
        "q": query,
        "format": "json",
        "limit": str(limit),
        "countrycodes": "ie",
        "addressdetails": "1",
    }
    if extra:
        params.update(extra)
    with _nominatim_lock:
        wait = 1.1 - (time.time() - _nominatim_last)
        if wait > 0:
            time.sleep(wait)
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
        try:
            data = _http_json(url, NOMINATIM_UA, timeout=10)
        except Exception:
            data = []
        _nominatim_last = time.time()
    return data if isinstance(data, list) else []


def nominatim_postalcode(code: str) -> list:
    global _nominatim_last
    spaced = code[:3] + " " + code[3:] if len(code) == 7 else code
    params = urllib.parse.urlencode({
        "postalcode": spaced,
        "country": "Ireland",
        "format": "json",
        "limit": "5",
        "addressdetails": "1",
    })
    with _nominatim_lock:
        wait = 1.1 - (time.time() - _nominatim_last)
        if wait > 0:
            time.sleep(wait)
        url = "https://nominatim.openstreetmap.org/search?" + params
        try:
            data = _http_json(url, NOMINATIM_UA, timeout=10)
        except Exception:
            data = []
        _nominatim_last = time.time()
    return data if isinstance(data, list) else []


def nominatim_hit(query: str) -> dict | None:
    data = nominatim_search(query, limit=1)
    if not data:
        return None
    return parse_nominatim_hit(data[0])


def parse_nominatim_hit(hit: dict) -> dict | None:
    try:
        lat, lng = float(hit["lat"]), float(hit["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not plausible(lat, lng) or not in_ireland(lat, lng):
        return None
    name = (hit.get("display_name") or "").split(",")[0].strip()
    return {"lat": round(lat, 6), "lng": round(lng, 6), "name": name[:79] if name else None}


def hit_has_eircode(hit: dict, code: str) -> bool:
    needle = compact_eircode(code)
    blob = json.dumps(hit).upper().replace(" ", "")
    return needle in blob


def overpass_eircode(code: str) -> dict | None:
    spaced = code[:3] + " " + code[3:]
    variants = {code, spaced, code.lower(), spaced.lower()}
    clauses = []
    for v in variants:
        for key in ("addr:eircode", "addr:postcode"):
            clauses.append(f'nwr["{key}"="{v}"];')
    q = "[out:json][timeout:8];(" + "".join(clauses) + ");out center 1;"
    body = urllib.parse.urlencode({"data": q}).encode("utf-8")
    endpoints = (
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    )
    for url in endpoints:
        try:
            data = _http_json(url, NOMINATIM_UA, timeout=9, data=body)
        except Exception:
            continue
        for el in data.get("elements") or []:
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lng = el.get("lon") or (el.get("center") or {}).get("lon")
            try:
                lat, lng = float(lat), float(lng)
            except (TypeError, ValueError):
                continue
            if not plausible(lat, lng):
                continue
            tags = el.get("tags") or {}
            name = tags.get("name") or tags.get("addr:housename") or spaced
            return {
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "name": str(name)[:79],
                "source": "eircode",
            }
    return None


def geocode_eircode(code: str) -> dict:
    code = compact_eircode(code)
    spaced = code[:3] + " " + code[3:]
    hit = overpass_eircode(code)
    if hit:
        return hit
    rows = nominatim_postalcode(code)
    for q in (spaced, code):
        rows.extend(nominatim_search(q, limit=5))
    for row in rows:
        if not hit_has_eircode(row, code):
            continue
        parsed = parse_nominatim_hit(row)
        if parsed:
            parsed["source"] = "eircode"
            parsed["name"] = parsed.get("name") or spaced
            return parsed
    raise ResolveError(
        "That Eircode isn't on the open map yet. Paste a Google or Apple Maps share, or hold on our map."
    )


def resolve_text(text: str) -> dict:
    t = (text or "").strip()
    if not t or len(t) > 2000:
        raise ResolveError("Paste a maps link, coordinates, or an Eircode.")
    local = parse_local(t)
    if local:
        return local
    code = extract_eircode(t)
    if code and (len(t) < 24 or not looks_like_url(t)):
        return geocode_eircode(code)
    if looks_like_url(t):
        url = normalize_url(t)
        for item in follow_redirects(url):
            blob = item[5:] if item.startswith("html:") else item
            found = parse_local(blob)
            if not found:
                pair = coords_in_text(blob)
                if pair:
                    found = {"lat": pair[0], "lng": pair[1], "source": "maps"}
            if found:
                name = place_name_from_url(blob) or place_name_from_url(url)
                if name:
                    found["name"] = name
                found["source"] = "maps"
                return found
        name = place_name_from_url(url)
        if name:
            hit = nominatim_hit(name + ", County Mayo, Ireland") or nominatim_hit(name + ", Ireland")
            if hit:
                hit["source"] = "maps"
                hit["name"] = name
                return hit
    if code:
        return geocode_eircode(code)
    raise ResolveError(
        "Could not find that. Try a Google or Apple Maps link, coordinates like 53.9, -9.58, or an Eircode."
    )


def load_pins() -> list:
    path = pins_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("pins")
    if not isinstance(data, list):
        return []
    return [p for p in (clean_pin(x) for x in data) if p]


def save_pins(pins: list) -> None:
    path = pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pins": pins}, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


def clean_pin(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or "")[:80]
    if not re.match(r"^[A-Za-z0-9._:-]+$", pid):
        return None
    deleted = bool(raw.get("deleted"))
    try:
        lat = float(raw.get("lat"))
        lng = float(raw.get("lng"))
    except (TypeError, ValueError):
        if not deleted:
            return None
        lat = lng = None
    if lat is not None and not plausible(lat, lng):
        return None
    name = str(raw.get("name") or "")[:79]
    if not deleted and not name:
        return None
    cat = str(raw.get("cat") or "family")[:24].lower()
    if cat not in KNOWN_CATS and not re.match(r"^[a-z][a-z0-9-]{0,23}$", cat):
        cat = "family"
    cat_label = ""
    if cat not in KNOWN_CATS:
        cat_label = str(raw.get("catLabel") or "")[:24]
    emoji_default = {"food": "🍽️", "shop": "🛒", "beach": "🏖️", "do": "🎡", "golf": "⛳", "landmarks": "🗿"}.get(cat, "📍")
    out = {
        "id": pid,
        "name": name or "Pin",
        "desc": str(raw.get("desc") or "")[:499],
        "lat": round(lat, 6) if lat is not None else None,
        "lng": round(lng, 6) if lng is not None else None,
        "cat": cat,
        "catLabel": cat_label,
        "emoji": str(raw.get("emoji") or emoji_default)[:8],
        "addedBy": str(raw.get("addedBy") or "")[:39],
        "createdAt": str(raw.get("createdAt") or "")[:40],
        "updatedAt": str(raw.get("updatedAt") or "")[:40],
        "deleted": deleted,
    }
    return {k: out[k] for k in PIN_KEYS}


def newer(a: dict, b: dict) -> dict:
    ta = a.get("updatedAt") or ""
    tb = b.get("updatedAt") or ""
    if ta != tb:
        return b if tb > ta else a
    return b


def hop_id(frm: str, to: str) -> str:
    return f"{frm}>{to}"


def clean_hop(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    frm = str(raw.get("from") or "")[:80]
    to = str(raw.get("to") or "")[:80]
    hid = str(raw.get("id") or hop_id(frm, to))[:161]
    if ">" not in hid:
        return None
    if not re.match(r"^[A-Za-z0-9._:-]+>[A-Za-z0-9._:-]+$", hid):
        return None
    if not frm or not to:
        frm, to = hid.split(">", 1)
    irish = raw.get("irish")
    if not isinstance(irish, list):
        return None
    lines = [str(x).strip()[:400] for x in irish if str(x).strip()]
    if not lines and not raw.get("deleted"):
        return None
    how = str(raw.get("how") or "drive")[:12]
    if how not in ("drive", "bike", "walk"):
        how = "drive"
    try:
        mins = int(raw.get("mins") or 1)
        km = float(raw.get("km") or 0)
    except (TypeError, ValueError):
        mins, km = 1, 0
    marks = []
    raw_marks = raw.get("landmarks")
    if isinstance(raw_marks, list):
        for m in raw_marks[:20]:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            marks.append({
                "kind": str(m.get("kind") or "")[:12],
                "id": str(m.get("id") or "")[:80],
                "name": str(m.get("name") or "")[:79],
                "side": str(m.get("side") or "")[:12],
            })
    return {
        "id": hid,
        "from": frm,
        "to": to,
        "mins": max(1, min(mins, 600)),
        "km": round(max(0.0, min(km, 400.0)), 2),
        "how": how,
        "irish": lines[:12],
        "usedHousePack": bool(raw.get("usedHousePack")),
        "generated": True,
        "landmarks": marks,
        "notes": irish_write_mod.clean_notes(raw.get("notes")),
        "savedBy": str(raw.get("savedBy") or "")[:39],
        "updatedAt": str(raw.get("updatedAt") or "")[:40],
        "deleted": bool(raw.get("deleted")),
    }


def load_hops() -> list:
    path = hops_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("hops")
    if not isinstance(data, list):
        return []
    return [h for h in (clean_hop(x) for x in data) if h]


def save_hops(hops: list) -> None:
    path = hops_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hops": hops}, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


def merge_hops(local: list, incoming: list) -> list:
    by_id = {h["id"]: h for h in local if h and h.get("id")}
    for h in incoming:
        if not h or not h.get("id"):
            continue
        cur = by_id.get(h["id"])
        by_id[h["id"]] = newer(cur, h) if cur else h
    hops = list(by_id.values())
    if len(hops) > MAX_HOPS:
        hops.sort(key=lambda h: (not h.get("deleted"), h.get("updatedAt") or ""))
        hops = hops[-MAX_HOPS:]
    return hops


def family_extra() -> list[dict]:
    extra = []
    for p in load_pins():
        if not p or p.get("deleted") or p.get("lat") is None:
            continue
        extra.append({
            "id": p.get("id") or "",
            "name": p.get("name") or "",
            "lat": p["lat"],
            "lng": p["lng"],
            "cat": p.get("cat") or "family",
            "host": False,
        })
    return extra


def merge_pins(local: list, incoming: list) -> list:
    by_id = {p["id"]: p for p in local if p and p.get("id")}
    for p in incoming:
        if not p or not p.get("id"):
            continue
        cur = by_id.get(p["id"])
        by_id[p["id"]] = newer(cur, p) if cur else p
    pins = list(by_id.values())
    if len(pins) > MAX_PINS:
        pins.sort(key=lambda p: (not p.get("deleted"), p.get("updatedAt") or ""))
        pins = pins[-MAX_PINS:]
    return pins


def json_bytes(obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def safe_file(rel: str) -> Path | None:
    rel = urllib.parse.unquote(rel.split("?", 1)[0])
    if rel in ("", "/"):
        rel = "/index.html"
    if ".." in rel or rel.startswith("/."):
        return None
    path = (ROOT / rel.lstrip("/")).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    if not path.is_file():
        return None
    if path.name.startswith(".") or path.suffix == ".py":
        return None
    if path.parent.name == ".data":
        return None
    if path.suffix.lower() not in MIME and path.name != ".nojekyll":
        return None
    return path


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, ctype, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "public, max-age=60")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            raise ValueError("bad body")
        raw = self.rfile.read(n)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("object required")
        return data

    def _auth(self) -> bool:
        got = (self.headers.get("X-Trip-Code") or "").strip()
        return got == trip_code()

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if self.path.split("?", 1)[0] == "/api/health":
            status, ctype, body = json_bytes({"ok": True})
            self._send(status, ctype, body)
            return
        if self.path.split("?", 1)[0] == "/api/pins":
            if not self._auth():
                self._send(*json_bytes({"error": "Wrong trip code."}, 403))
                return
            with _store_lock:
                pins = load_pins()
            self._send(*json_bytes({"pins": pins}))
            return
        if self.path.split("?", 1)[0] == "/api/hops":
            if not self._auth():
                self._send(*json_bytes({"error": "Wrong trip code."}, 403))
                return
            with _store_lock:
                hops = load_hops()
            self._send(*json_bytes({"hops": hops}))
            return
        if self.path.startswith("/api/"):
            self._send(*json_bytes({"error": "Not found."}, 404))
            return
        path = safe_file(self.path)
        if not path:
            self._send(*json_bytes({"error": "Not found."}, 404))
            return
        body = path.read_bytes()
        ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, ctype, body)

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        if route not in ("/api/gate", "/api/resolve", "/api/pins", "/api/landmarks", "/api/irish", "/api/hops"):
            self._send(*json_bytes({"error": "Not found."}, 404))
            return
        try:
            data = self._read_json()
        except Exception:
            self._send(*json_bytes({"error": "Send JSON."}, 400))
            return
        if route == "/api/gate":
            if clan_ok(data.get("answer")):
                self._send(*json_bytes({"ok": True, "trip": trip_code()}))
            else:
                self._send(*json_bytes({"error": "That's not it."}, 403))
            return
        if not self._auth():
            self._send(*json_bytes({"error": "Wrong trip code."}, 403))
            return
        if route == "/api/resolve":
            try:
                result = resolve_text(str(data.get("text") or ""))
            except ResolveError as e:
                self._send(*json_bytes({"error": str(e)}, 400))
                return
            self._send(*json_bytes(result))
            return
        if route == "/api/landmarks":
            with _store_lock:
                extra = family_extra()
            try:
                result = landmarks_mod.landmarks_for_request(data, extra)
            except landmarks_mod.LandmarkError as e:
                self._send(*json_bytes({"error": str(e)}, 400))
                return
            self._send(*json_bytes(result))
            return
        if route == "/api/irish":
            with _store_lock:
                extra = family_extra()
            try:
                hop = irish_write_mod.irish_for_request(data, extra)
            except landmarks_mod.LandmarkError as e:
                self._send(*json_bytes({"error": str(e)}, 400))
                return
            except Exception as e:
                sys.stderr.write("irish write failed: %s\n" % e)
                self._send(*json_bytes({"error": "Could not write that hop. Try two places that are not on top of each other."}, 502))
                return
            marks = hop.get("landmarks") or []
            hop["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            hop["id"] = hop_id(hop.get("from") or "", hop.get("to") or "")
            hop["draft"] = True
            out = hop
            out["landmarks"] = marks
            self._send(*json_bytes(out))
            return
        if route == "/api/hops":
            incoming = [clean_hop(h) for h in (data.get("hops") or [])]
            incoming = [h for h in incoming if h]
            with _store_lock:
                merged = merge_hops(load_hops(), incoming)
                save_hops(merged)
            self._send(*json_bytes({"hops": merged}))
            return
        incoming = [clean_pin(p) for p in (data.get("pins") or [])]
        incoming = [p for p in incoming if p]
        with _store_lock:
            merged = merge_pins(load_pins(), incoming)
            save_pins(merged)
        self._send(*json_bytes({"pins": merged}))


def self_test() -> int:
    assert extract_eircode("F28 X380") == "F28X380"
    assert extract_eircode("lime kiln f28x380 please") == "F28X380"
    dublin = {"display_name": "National Library of Ireland, Dublin, D02 P638"}
    assert not hit_has_eircode(dublin, "F28X380")
    assert hit_has_eircode({"display_name": "Lime Kiln House, F28 X380, Mayo"}, "F28X380")
    p = parse_local("53.8983, -9.5837")
    assert p and abs(p["lat"] - 53.8983) < 1e-6 and p["source"] == "coords"
    p = parse_local("geo:53.8,-9.52?q=53.8,-9.52(Savoir Fare)")
    assert p and p["name"] == "Savoir Fare" and p["source"] == "geo"
    url = "https://www.google.com/maps/place/The+Tavern+Bar/@53.777,-9.636,17z"
    p = parse_local(url)
    assert p and p["name"] == "The Tavern Bar" and abs(p["lat"] - 53.777) < 1e-6
    apple = "https://maps.apple.com/?ll=53.8869,-9.5453&q=Newport"
    p = parse_local(apple)
    assert p and abs(p["lng"] + 9.5453) < 1e-6
    bang = "https://www.google.com/maps/place/Foo/@x/data=!3d53.8!4d-9.52"
    # @x won't match AT_RE; bang coords should
    c = coords_in_text(bang)
    assert c and abs(c[0] - 53.8) < 1e-6
    a = {"id": "1", "updatedAt": "2026-01-01T00:00:00Z", "name": "old"}
    b = {"id": "1", "updatedAt": "2026-08-01T00:00:00Z", "name": "new"}
    assert newer(a, b)["name"] == "new"
    merged = merge_pins([a], [b, {"id": "2", "updatedAt": "2026-08-02T00:00:00Z", "name": "two", "lat": 53.8, "lng": -9.5, "deleted": False}])
    # clean_pin not applied here; merge is by id
    assert {p["id"] for p in merged} == {"1", "2"}
    prev = os.environ.get("NN_CLAN_ANSWER")
    os.environ["NN_CLAN_ANSWER"] = "spot"
    try:
        assert norm_clan("Spot") == "spot"
        assert clan_ok("Spot") and clan_ok("  spot  ") and not clan_ok("bear")
        os.environ["NN_CLAN_ANSWER"] = ""
        assert not clan_ok("spot")
    finally:
        if prev is None:
            os.environ.pop("NN_CLAN_ANSWER", None)
        else:
            os.environ["NN_CLAN_ANSWER"] = prev
    landmarks_mod.self_test()
    irish_write_mod.self_test()
    print("self-test ok")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not clan_answer():
        print("NN_CLAN_ANSWER is not set — the welcome check will reject everyone.", flush=True)
    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"Newport Navigator on http://127.0.0.1:{args.port}  (pins: {pins_path()})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)


if __name__ == "__main__":
    main()
