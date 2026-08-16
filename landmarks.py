#!/usr/bin/env python3
"""Landmarks along a drive: route polyline, then what you pass and what you see."""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OSRM = "https://router.project-osrm.org"
UA = "NewportNavigator/1.0 (https://newport-navigator.fly.dev; family trip map)"
PASS_M = 120
PEAK_KM = 28
WATER_KM = 10
BEND_DEG = 38
CONE_DEG = 105
M_PER_LAT = 110540.0

# Named skyline / water — not "on the road", in the view.
SKYLINE = (
    {"id": "croagh-patrick", "name": "Croagh Patrick", "kind": "peak", "lat": 53.76, "lng": -9.658},
    {"id": "clew-bay", "name": "Clew Bay", "kind": "water", "lat": 53.855, "lng": -9.65},
    {"id": "nephin", "name": "Nephin", "kind": "peak", "lat": 54.011, "lng": -9.368},
)

PROFILES = {"drive": "driving", "bike": "cycling", "walk": "foot"}


class LandmarkError(Exception):
    pass


def m_per_lng(lat: float) -> float:
    return 111320.0 * math.cos(math.radians(lat))


def haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    s = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(s)))


def heading_deg(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    y = math.sin(math.radians(b_lng - a_lng)) * math.cos(math.radians(b_lat))
    x = (
        math.cos(math.radians(a_lat)) * math.sin(math.radians(b_lat))
        - math.sin(math.radians(a_lat)) * math.cos(math.radians(b_lat))
        * math.cos(math.radians(b_lng - a_lng))
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def bearing_deg(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    return heading_deg(a_lat, a_lng, b_lat, b_lng)


def rel_bearing(heading: float, bearing: float) -> float:
    return (bearing - heading + 540) % 360 - 180


def compass8(deg: float) -> str:
    names = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
    return names[int((deg + 22.5) % 360) // 45]


def side_from_rel(rel: float) -> str:
    if abs(rel) <= 22:
        return "ahead"
    return "right" if rel > 0 else "left"


def wrap_delta(a: float, b: float) -> float:
    return abs((b - a + 540) % 360 - 180)


class Route:
    def __init__(self, coords: list[tuple[float, float]], metres: float, seconds: float, steps: list):
        self.coords = coords
        self.metres = metres
        self.seconds = seconds
        self.steps = steps
        self.lat0 = coords[0][0] if coords else 53.85
        self.cum = [0.0]
        for i in range(1, len(coords)):
            self.cum.append(
                self.cum[-1]
                + haversine_m(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
            )

    @property
    def km(self) -> float:
        return round(self.metres / 1000.0, 2)

    @property
    def mins(self) -> int:
        return max(1, int(round(self.seconds / 60.0)))

    def xy(self, lat: float, lng: float) -> tuple[float, float]:
        return (lng * m_per_lng(self.lat0), lat * M_PER_LAT)

    def project(self, lat: float, lng: float) -> dict:
        if len(self.coords) < 2:
            raise LandmarkError("Route is too short.")
        px, py = self.xy(lat, lng)
        best = None
        for i in range(len(self.coords) - 1):
            a_lat, a_lng = self.coords[i]
            b_lat, b_lng = self.coords[i + 1]
            ax, ay = self.xy(a_lat, a_lng)
            bx, by = self.xy(b_lat, b_lng)
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            t = 0.0 if len2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
            qx, qy = ax + t * dx, ay + t * dy
            dist = math.hypot(px - qx, py - qy)
            if best is None or dist < best[0]:
                along = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
                head = heading_deg(a_lat, a_lng, b_lat, b_lng)
                cross = dx * (py - ay) - dy * (px - ax)
                side = "ahead" if abs(cross) < 8 else ("right" if cross < 0 else "left")
                best = (dist, along, side, head)
        dist, along, side, head = best
        return {"dist_m": dist, "km_along": along / 1000.0, "side": side, "heading": head}

    def point_at(self, metres: float) -> tuple[float, float, float]:
        target = max(0.0, min(metres, self.cum[-1]))
        for i in range(len(self.coords) - 1):
            if self.cum[i + 1] >= target or i == len(self.coords) - 2:
                span = self.cum[i + 1] - self.cum[i] or 1.0
                t = (target - self.cum[i]) / span
                a_lat, a_lng = self.coords[i]
                b_lat, b_lng = self.coords[i + 1]
                lat = a_lat + t * (b_lat - a_lat)
                lng = a_lng + t * (b_lng - a_lng)
                return lat, lng, heading_deg(a_lat, a_lng, b_lat, b_lng)
        lat, lng = self.coords[-1]
        return lat, lng, 0.0

    def bends(self) -> list[dict]:
        out = []
        if len(self.coords) < 3:
            return out
        last_emit = -400.0
        for i in range(1, len(self.coords) - 1):
            h0 = heading_deg(self.coords[i - 1][0], self.coords[i - 1][1], self.coords[i][0], self.coords[i][1])
            h1 = heading_deg(self.coords[i][0], self.coords[i][1], self.coords[i + 1][0], self.coords[i + 1][1])
            delta = wrap_delta(h0, h1)
            if delta >= BEND_DEG and self.cum[i] - last_emit > 250 and self.cum[i] > 300:
                out.append({
                    "km_along": self.cum[i] / 1000.0,
                    "metres": self.cum[i],
                    "delta": round(delta, 1),
                    "heading_before": h0,
                    "heading_after": h1,
                })
                last_emit = self.cum[i]
        return out


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=18) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        # macOS system Python 3.9 often fails TLS to OSRM; curl's stack is newer.
        import subprocess
        r = subprocess.run(
            ["curl", "-sS", "-A", UA, "--max-time", "18", url],
            capture_output=True, text=True, timeout=22,
        )
        if r.returncode != 0:
            raise LandmarkError("Could not fetch a route (need a signal to OSRM).")
        return json.loads(r.stdout)


def fetch_osrm(frm: dict, to: dict, how: str) -> Route:
    profile = PROFILES.get(how, "driving")
    path = f"{frm['lng']:.6f},{frm['lat']:.6f};{to['lng']:.6f},{to['lat']:.6f}"
    q = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "true"})
    url = f"{OSRM}/route/v1/{profile}/{path}?{q}"
    try:
        data = _http_json(url)
    except LandmarkError:
        raise
    except Exception as e:
        raise LandmarkError("Could not fetch a route (need a signal to OSRM).") from e
    if data.get("code") != "Ok" or not data.get("routes"):
        raise LandmarkError("No road route between those two points.")
    r0 = data["routes"][0]
    geo = (r0.get("geometry") or {}).get("coordinates") or []
    coords = [(latlng[1], latlng[0]) for latlng in geo]
    if len(coords) < 2:
        raise LandmarkError("No road route between those two points.")
    steps = []
    km = 0.0
    for leg in r0.get("legs") or []:
        for st in leg.get("steps") or []:
            man = st.get("maneuver") or {}
            typ = man.get("type") or ""
            dist_km = (st.get("distance") or 0) / 1000.0
            if typ in ("depart", "arrive", "new name"):
                km += dist_km
                continue
            mod = man.get("modifier") or ""
            name = st.get("name") or ""
            inst = " ".join(x for x in (typ.replace("_", " "), mod, ("onto " + name) if name else "") if x).strip()
            steps.append({
                "kmAlong": round(km, 2),
                "instruction": inst,
                "name": name,
                "type": typ,
                "modifier": mod,
            })
            km += dist_km
    return Route(coords, float(r0.get("distance") or 0), float(r0.get("duration") or 0), steps)


def load_catalogue() -> list[dict]:
    data = json.loads((ROOT / "data" / "places.json").read_text(encoding="utf-8"))
    out = []
    for p in data.get("places") or []:
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            "id": p.get("id") or "",
            "name": p.get("name") or "",
            "lat": lat,
            "lng": lng,
            "cat": p.get("cat") or "",
            "host": bool(p.get("host")),
        })
    return out


def in_cone(heading: float, lat: float, lng: float, feat: dict, max_km: float) -> dict | None:
    dist_km = haversine_m(lat, lng, feat["lat"], feat["lng"]) / 1000.0
    if dist_km > max_km or dist_km < 0.4:
        return None
    br = bearing_deg(lat, lng, feat["lat"], feat["lng"])
    rel = rel_bearing(heading, br)
    if abs(rel) > CONE_DEG:
        return None
    return {
        "dist_km": round(dist_km, 1),
        "rel": rel,
        "bearing": br,
        "side": side_from_rel(rel),
        "compass": compass8(br),
    }


def pass_landmarks(route: Route, candidates: list[dict], skip_ids: set[str]) -> list[dict]:
    hits = []
    for p in candidates:
        if p.get("id") in skip_ids:
            continue
        pr = route.project(p["lat"], p["lng"])
        if pr["dist_m"] > PASS_M:
            continue
        if pr["km_along"] < 0.08 or pr["km_along"] > route.km - 0.08:
            continue
        hits.append({
            "kind": "pass",
            "id": p.get("id") or "",
            "name": p.get("name") or "",
            "lat": p["lat"],
            "lng": p["lng"],
            "kmAlong": round(pr["km_along"], 2),
            "distM": int(round(pr["dist_m"])),
            "side": pr["side"],
            "host": bool(p.get("host")),
            "cat": p.get("cat") or "",
        })
    hits.sort(key=lambda x: x["kmAlong"])
    rank = {"shop": 3, "food": 3, "home": 2, "landmarks": 2, "beach": 1, "do": 1, "golf": 1}
    kept = []
    for h in hits:
        if kept and h["kmAlong"] - kept[-1]["kmAlong"] < 0.12:
            prev = kept[-1]
            score = rank.get(h["cat"], 0) + (2 if h["host"] else 0)
            pscore = rank.get(prev["cat"], 0) + (2 if prev["host"] else 0)
            if score > pscore:
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def see_landmarks(route: Route) -> list[dict]:
    out = []
    seen = set()
    for bend in route.bends():
        before_m = max(0.0, bend["metres"] - 180)
        after_m = min(route.cum[-1], bend["metres"] + 180)
        b_lat, b_lng, b_head = route.point_at(before_m)
        a_lat, a_lng, a_head = route.point_at(after_m)
        for feat in SKYLINE:
            if feat["id"] in seen:
                continue
            cap = PEAK_KM if feat["kind"] == "peak" else WATER_KM
            vis_before = in_cone(b_head, b_lat, b_lng, feat, cap)
            vis_after = in_cone(a_head, a_lat, a_lng, feat, cap)
            if vis_after and not vis_before:
                seen.add(feat["id"])
                out.append({
                    "kind": "reveal",
                    "id": feat["id"],
                    "name": feat["name"],
                    "lat": feat["lat"],
                    "lng": feat["lng"],
                    "kmAlong": round(bend["km_along"], 2),
                    "side": vis_after["side"],
                    "compass": vis_after["compass"],
                    "see": feat["kind"],
                    "bendDeg": bend["delta"],
                })
    step = 400
    m = 250
    while m < route.cum[-1] - 200:
        lat, lng, head = route.point_at(m)
        for feat in SKYLINE:
            if feat["id"] in seen:
                continue
            cap = PEAK_KM if feat["kind"] == "peak" else WATER_KM
            vis = in_cone(head, lat, lng, feat, cap)
            if vis:
                seen.add(feat["id"])
                out.append({
                    "kind": "see",
                    "id": feat["id"],
                    "name": feat["name"],
                    "lat": feat["lat"],
                    "lng": feat["lng"],
                    "kmAlong": round(m / 1000.0, 2),
                    "side": vis["side"],
                    "compass": vis["compass"],
                    "see": feat["kind"],
                })
        m += step
    return out


def strip(frm: dict, to: dict, how: str, extra: list[dict] | None = None) -> dict:
    how = how if how in PROFILES else "drive"
    route = fetch_osrm(frm, to, how)
    skip = {frm.get("id") or "", to.get("id") or ""}
    cands = load_catalogue() + (extra or [])
    passed = pass_landmarks(route, cands, skip)
    seen = see_landmarks(route)
    marks = [{
        "kind": "start",
        "id": frm.get("id") or "",
        "name": frm.get("name") or "Start",
        "lat": frm["lat"],
        "lng": frm["lng"],
        "kmAlong": 0.0,
    }]
    marks.extend(sorted(passed + seen, key=lambda x: (x["kmAlong"], 0 if x["kind"] == "pass" else 1)))
    marks.append({
        "kind": "end",
        "id": to.get("id") or "",
        "name": to.get("name") or "End",
        "lat": to["lat"],
        "lng": to["lng"],
        "kmAlong": route.km,
    })
    return {
        "how": how,
        "km": route.km,
        "mins": route.mins,
        "from": {"id": frm.get("id") or "", "name": frm.get("name") or "", "lat": frm["lat"], "lng": frm["lng"]},
        "to": {"id": to.get("id") or "", "name": to.get("name") or "", "lat": to["lat"], "lng": to["lng"]},
        "landmarks": marks,
        "turns": route.steps,
    }


def point_from_body(raw, catalogue: list[dict]) -> dict:
    if not isinstance(raw, dict):
        raise LandmarkError("from and to must be objects with lat/lng or id.")
    pid = str(raw.get("id") or "")
    if pid:
        hit = next((p for p in catalogue if p["id"] == pid), None)
        if hit:
            return {
                "id": hit["id"],
                "name": str(raw.get("name") or hit["name"]),
                "lat": hit["lat"],
                "lng": hit["lng"],
            }
    try:
        lat, lng = float(raw["lat"]), float(raw["lng"])
    except (KeyError, TypeError, ValueError) as e:
        raise LandmarkError("Each end needs lat/lng, or an id from the map.") from e
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise LandmarkError("That point is not on the globe.")
    return {"id": pid, "name": str(raw.get("name") or ""), "lat": lat, "lng": lng}


def landmarks_for_request(data: dict, extra: list[dict] | None = None) -> dict:
    cat = load_catalogue()
    frm = point_from_body(data.get("from"), cat)
    to = point_from_body(data.get("to"), cat)
    if haversine_m(frm["lat"], frm["lng"], to["lat"], to["lng"]) < 3:
        raise LandmarkError("Those two pins sit on the same spot.")
    return strip(frm, to, str(data.get("how") or "drive"), extra)


def self_test() -> None:
    r = Route([(53.8, -9.6), (53.8, -9.5)], haversine_m(53.8, -9.6, 53.8, -9.5), 60, [])
    pr = r.project(53.801, -9.55)
    assert pr["dist_m"] < 130
    assert pr["side"] == "left"
    assert wrap_delta(0, 40) == 40
    assert wrap_delta(350, 20) == 30
    assert compass8(0) == "north"
    assert compass8(90) == "east"
    print("landmarks self-test ok")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) < 2:
        sys.stderr.write("usage: python3 landmarks.py <from-id> <to-id>\n")
        raise SystemExit(2)
    out = landmarks_for_request({"from": {"id": args[0]}, "to": {"id": args[1]}, "how": "drive"})
    print(json.dumps(out, indent=2, ensure_ascii=False))
