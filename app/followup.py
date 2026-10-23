"""Step 4 (contact & follow up): questions sent to a shop, the answer (simulated seller panel or recorded by the user),
and alternatives when the answer is bad. Kept in a small writable SQLite next to the read-only catalog."""
import itertools
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import catalog, nearby
from .config import settings
from .db import conn

OUTCOMES = {"ok", "price_diff", "no_stock", "no_answer", "closed"}
BAD = {"price_diff", "no_stock", "no_answer", "closed"}
_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = sqlite3.connect(settings.db_path.with_name("app.db"), check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.executescript("""
        CREATE TABLE IF NOT EXISTS inquiries (
          id INTEGER PRIMARY KEY, client TEXT NOT NULL, product_id INTEGER, product_title TEXT,
          shop_id INTEGER, shop_name TEXT, asks TEXT, message TEXT, listed_price INTEGER, listed_at TEXT,
          created TEXT, lat REAL, lon REAL, address TEXT, passage TEXT, floor TEXT, unit TEXT, phone TEXT,
          outcome TEXT, price INTEGER, open_until TEXT, note TEXT, source TEXT, answered TEXT);
        CREATE INDEX IF NOT EXISTS inq_client ON inquiries(client, id);
        CREATE INDEX IF NOT EXISTS inq_shop ON inquiries(shop_id, id);
        """)
    return _db


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["asks"] = json.loads(d["asks"] or "[]")
    d["bad"] = d["outcome"] in BAD
    return d


def create(client: str, product_id: int, shop_id: int, asks: list[str], message: str) -> dict | None:
    p = catalog.product(product_id)
    offer = next((s for s in nearby.sellers(product_id, None, None) if s["shop_id"] == shop_id), None)
    if not p or not offer:
        return None
    with _lock:
        cur = db().execute(
            "INSERT INTO inquiries (client, product_id, product_title, shop_id, shop_name, asks, message,"
            " listed_price, listed_at, created, lat, lon, address, passage, floor, unit, phone)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client, product_id, p["title"], shop_id, offer["name"], json.dumps(asks, ensure_ascii=False),
             message[:1000], offer["price"], offer["price_at"], now(), offer["lat"], offer["lon"],
             offer["address"], offer["passage"], offer["floor"], offer["unit"], offer["phone"]))
        db().commit()
    return get(cur.lastrowid)


def get(iid: int) -> dict | None:
    r = db().execute("SELECT * FROM inquiries WHERE id = ?", (iid,)).fetchone()
    return _row(r) if r else None


def mine(client: str) -> list[dict]:
    return [_row(r) for r in db().execute("SELECT * FROM inquiries WHERE client = ? ORDER BY id DESC LIMIT 50", (client,))]


def record(iid: int, client: str, outcome: str, price: int | None, note: str | None,
           open_until: str | None = None, source: str = "user") -> dict | None:
    """The answer, from the user (after a call) or from the shop (seller panel)."""
    if outcome not in OUTCOMES:
        return None
    q = "UPDATE inquiries SET outcome=?, price=?, note=?, open_until=?, source=?, answered=? WHERE id=?"
    args = [outcome, price, (note or "")[:300] or None, open_until, source, now(), iid]
    if source == "user":
        q += " AND client=?"
        args.append(client)
    with _lock:
        n = db().execute(q, args).rowcount
        db().commit()
    return get(iid) if n else None


def seller_reply(iid: int, in_stock: bool, price: int | None, open_until: str | None, note: str | None) -> dict | None:
    """The shop answers: no stock, or a price that differs from the listed one by more than 3%, is a bad outcome."""
    q = get(iid)
    if not q:
        return None
    listed = q["listed_price"]
    outcome = "no_stock" if not in_stock else \
        "price_diff" if price and listed and abs(price - listed) > listed * 0.03 else "ok"
    return record(iid, "", outcome, price if in_stock else None, note, open_until, source="seller")


def inbox(shop_id: int | None = None) -> list[dict]:
    """Seller panel: one shop's questions, or every recent one (demo convenience)."""
    if shop_id:
        rows = db().execute("SELECT * FROM inquiries WHERE shop_id = ? ORDER BY id DESC LIMIT 50", (shop_id,))
    else:
        rows = db().execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT 50")
    return [_row(r) for r in rows]


def alternatives(iid: int, client: str, lat: float | None, lon: float | None, n: int = 3,
                 now: datetime | None = None) -> list[dict]:
    """Other shops for the same product: not closed now, a believable price, not already answered badly."""
    q = get(iid)
    if not q or q["client"] != client:
        return []
    tried = {r["shop_id"] for r in db().execute(
        "SELECT shop_id FROM inquiries WHERE client = ? AND product_id = ? AND outcome IN ('no_stock','no_answer','closed')",
        (client, q["product_id"]))} | {q["shop_id"]}
    # a price a shop already quoted in another inquiry beats its (often stale) listed price
    quoted = {r["shop_id"]: (r["price"], r["answered"]) for r in db().execute(
        "SELECT shop_id, price, answered FROM inquiries WHERE client = ? AND product_id = ? AND outcome IN ('ok','price_diff')"
        " AND price IS NOT NULL ORDER BY answered", (client, q["product_id"]))}
    out = []
    for s in nearby.sellers(q["product_id"], lat, lon, now):
        if s["shop_id"] in quoted:
            (s["price"], s["price_at"]), s["price_flag"], s["quoted"] = quoted[s["shop_id"]], None, True
        if s["shop_id"] not in tried and s["hours"]["state"] != "closed" and s["price"] and not s["price_flag"]:
            out.append(s)
    if q["outcome"] == "price_diff" and q["price"]:
        # The shop has the item at a known price now; another trip is only worth it if it is cheaper.
        out = [s for s in out if s["price"] < q["price"]]
    if not out:
        return []
    cheapest = min(s["price"] for s in out)
    for s in out:
        s["cost"] = nearby.cost(s, cheapest)
    out.sort(key=lambda s: s["cost"])
    return out[:n]


DWELL_MIN = 20  # parking, finding the unit inside the passage, buying
WALK_KM = 0.15  # closer than this (same passage or block) is a short walk, not a drive


def _leg(a: tuple[float, float] | None, b: dict) -> tuple[int, float]:
    """Minutes and road km between two points, using the same estimate as the nearby list."""
    if a is None:
        return 0, 0.0
    d = nearby.km(a[0], a[1], b["lat"], b["lon"])
    if d < WALK_KM:
        return 3, round(d, 2)
    road = d * nearby.ROAD_FACTOR
    return round(nearby.OVERHEAD_MIN + road / nearby.CITY_KMH * 60), round(road, 1)


def _route(start: tuple[float, float] | None, stops: list[dict], t0: datetime) -> tuple[float, list[dict]]:
    """Walk the stops in this order: arrival time, open state at arrival, and a cost that punishes closed doors."""
    out, pos, t, cost = [], start, t0, 0.0
    for s in stops:
        m, road = _leg(pos, s)
        t += timedelta(minutes=m)
        state = nearby.open_status(s["hours"], t)["state"]
        if s["open_until"]:  # the seller said today when they close; trust that over the declared hours
            state = "open" if t.strftime("%H:%M") < s["open_until"] else "closed"
        out.append(s | {"leg_min": m, "leg_km": road, "arrive": t.strftime("%H:%M"), "state_at_arrival": state})
        cost += m + (90 if state == "closed" else 0)
        t += timedelta(minutes=DWELL_MIN)
        pos = (s["lat"], s["lon"])
    return cost, out


def plan(client: str, lat: float | None, lon: float | None, now: datetime | None = None) -> dict:
    """Visit plan from confirmed answers (ok or a new price): one stop per shop, ordered for the least driving
    with every shop still open when we get there."""
    latest: dict[tuple, dict] = {}
    for q in reversed(mine(client)):  # oldest first, so a later answer for the same shop and product wins
        latest[(q["shop_id"], q["product_id"])] = q
    stops: dict[int, dict] = {}
    for q in latest.values():
        if q["outcome"] not in ("ok", "price_diff") or q["lat"] is None:
            continue
        s = stops.setdefault(q["shop_id"], {k: q[k] for k in (
            "shop_id", "shop_name", "lat", "lon", "address", "passage", "floor", "unit", "phone")} | {
            "open_until": None, "items": []})
        s["items"].append({"product_id": q["product_id"], "title": q["product_title"], "inquiry": q["id"],
                           "price": q["price"] or q["listed_price"], "listed_price": q["listed_price"]})
        if q["open_until"]:
            s["open_until"] = q["open_until"]
    if not stops:
        return {"stops": [], "total_min": 0}
    marks = ",".join("?" * len(stops))
    for r in conn().execute(f"SELECT id, hours FROM shops WHERE id IN ({marks})", list(stops)):
        stops[r["id"]]["hours"] = r["hours"]
    start = (lat, lon) if lat is not None and lon is not None else None
    t0 = now or datetime.now(nearby.TEHRAN)
    todo = list(stops.values())
    if len(todo) <= 7:
        best = min((_route(start, list(p), t0) for p in itertools.permutations(todo)), key=lambda x: x[0])
    else:  # nearest neighbour; more than seven shops in one trip is not a realistic plan anyway
        order, pos = [], start or (todo[0]["lat"], todo[0]["lon"])
        while todo:
            nxt = min(todo, key=lambda s: nearby.km(pos[0], pos[1], s["lat"], s["lon"]))
            todo.remove(nxt)
            order.append(nxt)
            pos = (nxt["lat"], nxt["lon"])
        best = _route(start, order, t0)
    route = best[1]
    for s in route:
        s.pop("hours", None)
    total = sum(s["leg_min"] for s in route) + DWELL_MIN * len(route)
    return {"start": bool(start), "stops": route, "total_min": total,
            "leave": t0.strftime("%H:%M"), "back": (t0 + timedelta(minutes=total)).strftime("%H:%M")}
