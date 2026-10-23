"""Step 2 (find nearby): shops that list a product, by distance from the user, with hours and payment."""
import json
import math
import statistics
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings
from .db import conn
from .text import fa

TEHRAN = timezone(timedelta(hours=3, minutes=30))  # no DST since 2022
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday() order


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (haversine) distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


# Fallback when Neshan has no answer: streets are longer than the crow flies, plus parking/start-up minutes.
ROAD_FACTOR, CITY_KMH, OVERHEAD_MIN = 1.4, 20, 4
_eta_cache: dict[tuple, tuple[int, float] | None] = {}
_neshan_calls: deque = deque()  # request times, for a global per-minute cap on the paid API
NESHAN_PER_MIN = 60


def etas(lat: float, lon: float, shops: list[dict], limit: int = 100) -> None:
    """Fill eta_min / road_km / eta_src on the nearest shops: Neshan driving matrix, haversine estimate otherwise."""
    todo = [s for s in shops[:limit] if s["km"] is not None]
    key = lambda s: (round(lat, 3), round(lon, 3), s["shop_id"])
    miss = [s for s in todo if key(s) not in _eta_cache]
    for i in range(0, len(miss) if settings.neshan_key else 0, 50):
        now = time.monotonic()
        while _neshan_calls and now - _neshan_calls[0] > 60:
            _neshan_calls.popleft()
        if len(_neshan_calls) >= NESHAN_PER_MIN:
            break  # over budget: the rest get the haversine estimate below
        _neshan_calls.append(now)
        chunk = miss[i:i + 50]
        try:
            r = httpx.get("https://api.neshan.org/v1/distance-matrix", timeout=4, headers={"Api-Key": settings.neshan_key},
                          params={"type": "car", "origins": f"{lat},{lon}",
                                  "destinations": "|".join(f"{s['lat']},{s['lon']}" for s in chunk)})
            for s, e in zip(chunk, r.json()["rows"][0]["elements"]):
                # No route (e.g. inside the traffic-restricted zone) is cached as None and falls back to the estimate.
                _eta_cache[key(s)] = (round(e["duration"]["value"] / 60), round(e["distance"]["value"] / 1000, 1)) \
                    if e.get("status") == "Ok" else None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            break
        if len(_eta_cache) > 50_000:
            _eta_cache.clear()
    for s in shops:
        if s["km"] is None:
            continue
        hit = _eta_cache.get(key(s))
        if hit:
            s.update(eta_min=max(hit[0], 1), road_km=hit[1], eta_src="neshan")
        else:
            road = s["km"] * ROAD_FACTOR
            s.update(eta_min=round(OVERHEAD_MIN + road / CITY_KMH * 60), road_km=round(road, 1), eta_src="estimate")


def _hm(t: str) -> int:
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def open_status(hours_json: str | None, now: datetime | None = None) -> dict:
    """{state: open|closed|unknown, today: "۱۰:۰۰ تا ۱۸:۰۰" | None}. Unknown when the shop did not declare hours."""
    if not hours_json:
        return {"state": "unknown", "today": None}
    now = now or datetime.now(TEHRAN)
    day = json.loads(hours_json).get(DAYS[now.weekday()]) or {}
    if day.get("status") == "closed":
        return {"state": "closed", "today": "امروز تعطیل"}
    if day.get("status") != "declared":
        return {"state": "unknown", "today": None}
    # 00:00–00:00 (or 00:00:01) is an empty slot in this export; an end of 00:00 after a start means midnight.
    shifts = [(a, b or 24 * 60) for a, b in ((_hm(s["start_time"]), _hm(s["end_time"])) for s in day.get("shifts") or [])
              if a != b]
    if not shifts:
        return {"state": "unknown", "today": None}
    t = now.hour * 60 + now.minute
    is_open = any(a <= t < b for a, b in shifts)
    text = "، ".join(f"{_clock(a)} تا {_clock(b)}" for a, b in shifts)
    return {"state": "open" if is_open else "closed", "today": text}


def _clock(m: int) -> str:
    return fa(m // 60) if m % 60 == 0 else f"{fa(m // 60)}:{fa(m % 60).rjust(2, '۰')}"


def payments(payments_json: str | None) -> list[dict]:
    """Installment providers; channel in_person means confirmed for in-store purchase, unknown means not stated."""
    seen, out = set(), []
    for p in json.loads(payments_json or "[]"):
        name = (p.get("provider_name") or "").replace("دیجی پی", "دیجی‌پی")
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "in_person": p.get("channel") == "in_person"})
    return out


SHOP_COLS = (" s.id, s.name, s.real_name, s.address, s.passage, s.floor, s.unit, s.area, s.lat, s.lon, s.hours,"
             " s.payments, s.fast_delivery, s.instagram, s.website, s.phone")


def _row(r, lat: float | None, lon: float | None, now: datetime | None) -> dict:
    d = km(lat, lon, r["lat"], r["lon"]) if lat is not None and r["lat"] is not None else None
    return {
        "shop_id": r["id"], "name": r["name"], "real_name": bool(r["real_name"]), "phone": r["phone"],
        "address": r["address"], "passage": r["passage"], "floor": r["floor"], "unit": r["unit"], "area": r["area"],
        "lat": r["lat"], "lon": r["lon"], "km": round(d, 2) if d is not None else None,
        "price": r["price"], "price_at": r["price_at"], "warranty_months": r["warranty_months"],
        "hours": open_status(r["hours"], now), "payments": payments(r["payments"]),
        "fast_delivery": None if r["fast_delivery"] is None else bool(r["fast_delivery"]),
        "link": link(r["website"], r["instagram"]),
    }


def sellers(pid: int, lat: float | None, lon: float | None, now: datetime | None = None) -> list[dict]:
    """Every shop listing the product. Sorted by distance when a location is known, else by price."""
    rows = conn().execute("SELECT o.price, o.price_at, o.warranty_months," + SHOP_COLS +
                          " FROM offers o JOIN shops s ON s.id = o.shop_id WHERE o.product_id = ?", (pid,)).fetchall()
    out = [_row(r, lat, lon, now) for r in rows]
    big = float("inf")
    # A shop can list several variants (colour, size); keep its cheapest priced one and count the rest.
    by_shop: dict[int, dict] = {}
    for s in out:
        b = by_shop.get(s["shop_id"])
        if b is None:
            by_shop[s["shop_id"]] = s | {"variants": 1}
        else:
            b["variants"] += 1
            if (s["price"] or big) < (b["price"] or big):
                b.update(price=s["price"], price_at=s["price_at"], warranty_months=s["warranty_months"])
    out = list(by_shop.values())
    # Listings under one product are noisy (accessories, other versions); flag prices far from the median.
    prices = [s["price"] for s in out if s["price"]]
    mid = statistics.median(prices) if len(prices) >= 4 else None
    for s in out:
        s["price_flag"] = None if not (mid and s["price"]) else \
            "low" if s["price"] < mid * 0.4 else "high" if s["price"] > mid * 2.5 else None
    out.sort(key=lambda s: (s["km"] if s["km"] is not None else big, s["price"] or big))
    if lat is not None:
        etas(lat, lon, out)
    return out


def cost(s: dict, cheapest: int) -> float:
    """Same scale as "پیشنهاد ما" in nearby.js: 1 point per % above the cheapest, 0.7 per minute of driving."""
    c = (s["price"] / cheapest - 1) * 100 if s["price"] else 40
    c += (s.get("eta_min") or (s["km"] * 4 if s["km"] is not None else 30)) * 0.7
    c += {"closed": 15, "unknown": 5}.get(s["hours"]["state"], 0)
    if s["price_at"]:
        d = (datetime.now(timezone.utc) - datetime.fromisoformat(s["price_at"])).days
        c += 10 if d > 180 else 3 if d > 30 else 0
    return c - (2 if any(p["in_person"] for p in s["payments"]) else 0)


def areas(limit: int = 16) -> list[dict]:
    """Neighbourhoods that have shops in the dataset, as quick location presets."""
    rows = conn().execute(
        "SELECT area, avg(lat) lat, avg(lon) lon, count(*) n FROM shops WHERE area != '' AND lat IS NOT NULL"
        " GROUP BY area ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
    return [{"label": r["area"], "lat": round(r["lat"], 5), "lon": round(r["lon"], 5), "n": r["n"]} for r in rows]


def link(website: str | None, instagram: str | None) -> str | None:
    """The shop's real site or Instagram page (instagram is JSON {handle, profile_url}); http(s) only."""
    url = website
    if not url and instagram:
        try:
            url = json.loads(instagram).get("profile_url")
        except (ValueError, AttributeError):
            url = None
    return url if url and url.startswith(("https://", "http://")) else None


WEEK = [("sat", "شنبه"), ("sun", "یکشنبه"), ("mon", "دوشنبه"), ("tue", "سه‌شنبه"), ("wed", "چهارشنبه"),
        ("thu", "پنجشنبه"), ("fri", "جمعه")]


def week(hours_json: str | None) -> list[dict]:
    """Saturday-first weekly hours; text None means the shop did not declare that day."""
    days = json.loads(hours_json) if hours_json else {}
    today = DAYS[datetime.now(TEHRAN).weekday()]
    out = []
    for key, label in WEEK:
        d = days.get(key) or {}
        if d.get("status") == "closed":
            text = "تعطیل"
        else:
            shifts = [(a, b or 24 * 60) for a, b in ((_hm(s["start_time"]), _hm(s["end_time"]))
                                                     for s in d.get("shifts") or []) if a != b]
            text = "، ".join(f"{_clock(a)} تا {_clock(b)}" for a, b in shifts) if d.get("status") == "declared" and shifts else None
        out.append({"day": label, "text": text, "today": key == today})
    return out


def shop(sid: int, limit: int = 60) -> dict | None:
    """One shop for its page: location, weekly hours, payment and what it lists (newest price first)."""
    r = conn().execute("SELECT * FROM shops WHERE id = ?", (sid,)).fetchone()
    if not r:
        return None
    rows = conn().execute(
        "SELECT p.id, p.title, p.image, p.category, min(o.price) price, max(o.price_at) price_at FROM offers o"
        " JOIN products p ON p.id = o.product_id WHERE o.shop_id = ? GROUP BY p.id"
        " ORDER BY price IS NULL, price_at DESC", (sid,)).fetchall()
    cats: dict[str, int] = {}
    for x in rows:
        if x["category"]:
            cats[x["category"]] = cats.get(x["category"], 0) + 1
    return {
        "id": r["id"], "name": r["name"], "real_name": bool(r["real_name"]), "phone": r["phone"],
        "address": r["address"], "passage": r["passage"], "floor": r["floor"], "unit": r["unit"], "area": r["area"],
        "lat": r["lat"], "lon": r["lon"], "hours": open_status(r["hours"]), "week": week(r["hours"]),
        "payments": payments(r["payments"]),
        "fast_delivery": None if r["fast_delivery"] is None else bool(r["fast_delivery"]),
        "link": link(r["website"], r["instagram"]),
        "n_products": len(rows), "categories": sorted(cats.items(), key=lambda c: -c[1])[:6],
        "products": [dict(x) for x in rows[:limit]],
    }


# ---- Rescue: nothing open nearby (late night, Friday) → the nearest open Torob seller even if far, a nearby bazaar
# that may have open shops Torob does not list, and the earliest opening.

def _shifts(days: dict, key: str) -> list[tuple[int, int]]:
    d = days.get(key) or {}
    if d.get("status") != "declared":
        return []
    return [(a, b or 24 * 60) for a, b in ((_hm(s["start_time"]), _hm(s["end_time"])) for s in d.get("shifts") or [])
            if a != b]


def closes_at(hours_json: str | None, now: datetime) -> str | None:
    """When the current shift ends, as "۲۲:۳۰"."""
    t = now.hour * 60 + now.minute
    days = json.loads(hours_json) if hours_json else {}
    return next((_clock(b % (24 * 60)) for a, b in _shifts(days, DAYS[now.weekday()]) if a <= t < b), None)


def next_open(hours_json: str | None, now: datetime) -> tuple[int, str] | None:
    """(minutes from now, "فردا ۹") for the next declared opening within a week."""
    days = json.loads(hours_json) if hours_json else {}
    t = now.hour * 60 + now.minute
    for i in range(8):
        for a, _ in sorted(_shifts(days, DAYS[(now.weekday() + i) % 7])):
            if i or a > t:
                when = "امروز" if i == 0 else "فردا" if i == 1 else WEEK_FA[(now.weekday() + i) % 7]
                return i * 1440 + a - t, f"{when} ساعت {_clock(a)}"
    return None


WEEK_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]  # datetime.weekday() order
_hubs: list[dict] | None = None


def hubs() -> list[dict]:
    """Passages / malls with many listed shops: shopping hubs, where more shops exist than Torob lists."""
    global _hubs
    if _hubs is None:
        groups: dict[str, list] = {}
        for r in conn().execute("SELECT passage, lat, lon, hours, categories FROM shops"
                                " WHERE passage IS NOT NULL AND passage != '' AND lat IS NOT NULL"):
            name = r["passage"].replace("علاالدین", "علاءالدین")
            groups.setdefault(name, []).append(r)
        _hubs = []
        for name, rs in groups.items():
            if len(rs) < 12:
                continue
            _hubs.append({"name": name, "lat": statistics.median(r["lat"] for r in rs),
                          "lon": statistics.median(r["lon"] for r in rs),
                          "shops": [(r["hours"], set(json.loads(r["categories"] or "[]"))) for r in rs]})
    return _hubs


def hub_near(lat: float, lon: float, cats: set[str], now: datetime, max_km: float = 6) -> dict | None:
    """The nearest hub with at least a few shops in these categories, and how many of its listed shops are open now."""
    best = None
    for h in hubs():
        rel = [hrs for hrs, c in h["shops"] if c & cats]
        if len(rel) < 5:
            continue
        d = km(lat, lon, h["lat"], h["lon"])
        score = (d + 0.3) / math.sqrt(len(rel))  # a big bazaar a little farther beats a building with five such shops
        if d <= max_km and (best is None or score < best[0]):
            best = (score, d, h, rel)
    if not best:
        return None
    _, d, h, rel = best
    states = [open_status(hrs, now)["state"] for hrs, _ in h["shops"]]
    out = {"shop_id": "hub:" + h["name"], "name": h["name"], "lat": round(h["lat"], 6), "lon": round(h["lon"], 6), "km": round(d, 2),
           "n": len(h["shops"]), "rel": len(rel), "open": states.count("open"), "unknown": states.count("unknown")}
    etas(lat, lon, [out])
    return out


def rescue(pids: list[int], lat: float | None, lon: float | None, now: datetime | None = None,
           near_km: float = 2.0) -> dict | None:
    """Across products that would do (any phone charger, not one model): is anything open within near_km?
    If not: the nearest open seller at any distance, nearby sellers with unknown hours (call first), the nearest hub,
    and the earliest opening."""
    if lat is None or lon is None or not pids:
        return None
    now = now or datetime.now(TEHRAN)
    ids = list(dict.fromkeys(pids))[:400]
    rows = conn().execute(
        "SELECT o.product_id, p.title, s.categories, o.price, o.price_at, o.warranty_months," + SHOP_COLS +
        f" FROM offers o JOIN shops s ON s.id = o.shop_id JOIN products p ON p.id = o.product_id"
        f" WHERE o.product_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    big = float("inf")
    shops: dict[int, dict] = {}
    cats: dict[str, int] = {}
    for r in rows:
        b = shops.get(r["id"])
        if b is None or (r["price"] or big) < (b["price"] or big):
            if b is None:
                for c in json.loads(r["categories"] or "[]"):
                    cats[c] = cats.get(c, 0) + 1
            shops[r["id"]] = _row(r, lat, lon, now) | {"p": {"id": r["product_id"], "title": r["title"]},
                                                       "_hours": r["hours"]}
    found = sorted((s for s in shops.values() if s["km"] is not None), key=lambda s: s["km"])
    if not found:
        return None
    near = [s for s in found if s["km"] <= near_km]
    opened = [s for s in found if s["hours"]["state"] == "open"]
    calls = [s for s in found if s["hours"]["state"] == "unknown" and s["km"] <= near_km * 2][:2]
    first = opened[0] if opened else None
    etas(lat, lon, ([first] if first else []) + calls)
    if first:
        first["closes"] = closes_at(first["_hours"], now)
    soon = min(((n, s) for s in found[:20] if s["hours"]["state"] == "closed"
                for n in [next_open(s["_hours"], now)] if n), key=lambda x: x[0][0], default=None)
    top = {c for c, _ in sorted(cats.items(), key=lambda x: -x[1])[:3]}
    hub = hub_near(lat, lon, top, now)
    if hub and first and hub["km"] >= first["km"]:
        hub = None  # the open shop is nearer than the hub: just go there
    for s in shops.values():
        s.pop("_hours", None)
    return {"need": not any(s["hours"]["state"] == "open" for s in near), "at": _clock(now.hour * 60 + now.minute)
            if now.minute else f"{fa(now.hour)}:۰۰", "near_km": near_km, "n_near": len(near), "n": len(found),
            "open": first, "call": calls, "hub": hub,
            "soon": {"s": soon[1], "when": soon[0][1]} if soon else None}
