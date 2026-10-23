"""Step 1 (discover): product search, facets and side-by-side comparison."""
import json
import math
import re
from collections import Counter

from .db import conn
from .text import fa, fts_query, norm

CANDIDATES = 600
# Title words that mark an accessory/part. A query for "گوشی سامسونگ" should rank phones before cases.
ACCESSORY = {"کاور", "قاب", "گلس", "محافظ", "باتری", "شارژر", "کابل", "قطعه", "فلت", "برد", "اسپیکر", "دوربین",
             "تاچ", "ال", "lcd", "پیچ", "درب", "هولدر", "پایه", "کیف", "بند", "استند", "مگنت", "آداپتور", "لنز", "سوکت"}

_TAIL = re.compile(r"[\s,،]+$")

COLS = "p.id, p.title, p.brand, p.category, p.image, p.min_price, p.max_price, p.n_offers, p.n_shops"


def _row(r) -> dict:
    return {k: r[k] for k in ("id", "title", "brand", "category", "image", "min_price", "max_price", "n_shops")}


def _filters(category, brand, lo, hi) -> tuple[str, list]:
    sql, args = [], []
    if category:
        sql.append("p.category = ?"); args.append(category)
    if brand:
        sql.append("p.brand = ?"); args.append(brand)
    if lo:  # budget: the cheapest listing must fit
        sql.append("p.min_price >= ?"); args.append(lo)
    if hi:
        sql.append("p.min_price <= ?"); args.append(hi)
    return "".join(f" AND {s}" for s in sql), args


def _score(r, toks: list[str], bm25: float) -> tuple[float, list[str]]:
    """Relevance plus market signals. Returns (score, reasons in Farsi)."""
    title, cat = norm(r["title"] or ""), norm(r["category"] or "")
    words = set(title.split())
    s, why = -bm25, []
    if toks and title.startswith(toks[0]):
        s += 4
    hits = [t for t in toks if t in cat]
    if hits:
        s += 6
        why.append(f"دسته «{r['category']}» با جست‌وجو می‌خواند")
    if (words & ACCESSORY) and not (set(toks) & ACCESSORY):
        s -= 8  # an accessory nobody asked for
    if r["n_shops"] and r["n_shops"] > 1:
        s += 2.5 * math.log2(r["n_shops"])
        why.append(f"{fa(r['n_shops'])} فروشگاه آن را دارند؛ امکان مقایسه هست")
    elif r["n_shops"] == 1:
        why.append("فقط یک فروشگاه آن را دارد")
    if r["min_price"] is None:
        s -= 5
        why.append("قیمت ثبت نشده")
    return s, why


def search(q: str = "", category: str | None = None, brand: str | None = None,
           lo: int | None = None, hi: int | None = None, limit: int = 24, offset: int = 0) -> dict:
    where, args = _filters(category, brand, lo, hi)
    match = fts_query(q) if q else None
    toks = norm(q).split() if q else []
    if match:
        rows = conn().execute(
            f"SELECT {COLS}, bm25(products_fts, 10, 3, 2, 1) AS b FROM products_fts"
            f" JOIN products p ON p.id = products_fts.rowid WHERE products_fts MATCH ?{where}"
            f" ORDER BY b LIMIT {CANDIDATES}", [match, *args]).fetchall()
        scored = [(r, *_score(r, toks, r["b"])) for r in rows]
    elif category or brand:
        rows = conn().execute(
            f"SELECT {COLS} FROM products p WHERE 1{where}"
            f" ORDER BY p.n_shops DESC, p.min_price IS NULL LIMIT {CANDIDATES}", args).fetchall()
        scored = [(r, *_score(r, [], 0)) for r in rows]
    else:
        return {"items": [], "total": 0, "facets": {"categories": [], "brands": []}}

    scored.sort(key=lambda x: -x[1])
    priced = [r["min_price"] for r, *_ in scored if r["min_price"]]
    cheapest = min(priced) if priced else None
    items = []
    for r, _, why in scored[offset:offset + limit]:
        d = _row(r)
        if cheapest and r["min_price"] == cheapest and len(priced) > 1:
            why = ["ارزان‌ترین در این نتایج", *why]
        if hi and r["min_price"]:
            why.append("در محدودهٔ بودجه")
        d["why"] = why[:3]
        items.append(d)
    _attach_freshness(items)
    cats = Counter(r["category"] for r, *_ in scored if r["category"])
    brands = Counter(r["brand"] for r, *_ in scored if r["brand"])
    return {"items": items, "total": len(scored), "capped": len(scored) >= CANDIDATES,
            "facets": {"categories": cats.most_common(8), "brands": brands.most_common(10)}}


def _attach_freshness(items: list[dict]) -> None:
    """Newest price update per product, so cards can show how old the price is."""
    if not items:
        return
    ids = [i["id"] for i in items]
    q = f"SELECT product_id, max(price_at) FROM offers WHERE product_id IN ({','.join('?' * len(ids))})" \
        " AND price IS NOT NULL GROUP BY 1"
    fresh = dict(conn().execute(q, ids).fetchall())
    for i in items:
        i["price_at"] = fresh.get(i["id"])


def product(pid: int) -> dict | None:
    r = conn().execute(f"SELECT {COLS}, p.model, p.images, p.specs FROM products p WHERE p.id = ?", (pid,)).fetchone()
    if not r:
        return None
    d = _row(r)
    d["model"] = r["model"]
    d["images"] = json.loads(r["images"] or "[]")[:6]
    # Some source values end in empty list items ("256 گیگابایت, ,"); drop that tail.
    d["specs"] = [[sec, key, _TAIL.sub("", val or "")] for sec, key, val in json.loads(r["specs"] or "[]")]
    o = conn().execute(
        "SELECT count(*) n, min(price_at) old, max(warranty_months) wm,"
        " sum(price IS NULL) unpriced FROM offers WHERE product_id = ?", (pid,)).fetchone()
    d.update(n_offers=o["n"], oldest_price_at=o["old"], max_warranty=o["wm"],
             unpriced=o["unpriced"])
    _attach_freshness([d])
    return d


def compare(ids: list[int]) -> dict:
    prods = [p for p in (product(i) for i in ids[:4]) if p]
    keys: dict[tuple[str, str], dict[int, str]] = {}
    for p in prods:
        for sec, key, val in p.pop("specs"):
            keys.setdefault((sec, key), {})[p["id"]] = val
    rows = []
    for (sec, key), vals in keys.items():
        present = [vals.get(p["id"]) for p in prods]
        known = {norm(v) for v in present if v}
        # A spec only one product lists can't be compared: "sparse", hidden with "only differences".
        kind = "sparse" if sum(1 for v in present if v) < 2 else "diff" if len(known) > 1 else "same"
        rows.append({"section": sec, "key": key, "values": present, "kind": kind})
    # Rows shared by every product come first: those are the ones worth comparing.
    rows.sort(key=lambda r: (sum(v is None for v in r["values"]), r["kind"] != "diff"))
    mixed = len({p["category"] for p in prods}) > 1
    return {"products": prods, "rows": rows, "verdict": _verdict(prods), "mixed": mixed}


def _verdict(prods: list[dict]) -> list[dict]:
    """Short "which one and why" notes, based only on data we actually have."""
    out = []
    priced = [p for p in prods if p["min_price"]]
    if len(priced) > 1:
        c = min(priced, key=lambda p: p["min_price"])
        out.append({"id": c["id"], "label": "ارزان‌ترین", "text": "کمترین قیمت ثبت‌شده"})
    if len(prods) > 1:
        m = max(prods, key=lambda p: p["n_shops"] or 0)
        if (m["n_shops"] or 0) > 1:
            out.append({"id": m["id"], "label": "بیشترین فروشنده",
                        "text": f"{fa(m['n_shops'])} فروشگاه؛ احتمال پیدا کردن حضوری بیشتر"})
        f = max(prods, key=lambda p: p["price_at"] or "")
        # Only worth saying when the update dates differ by at least a day.
        if f["price_at"] and len({(p["price_at"] or "")[:10] for p in prods}) > 1:
            out.append({"id": f["id"], "label": "قیمت تازه‌تر", "text": "آخرین به‌روزرسانی قیمت جدیدتر است"})
        w = max(prods, key=lambda p: p["max_warranty"] or 0)
        if w["max_warranty"]:
            out.append({"id": w["id"], "label": "گارانتی بلندتر", "text": f"تا {fa(w['max_warranty'])} ماه گارانتی"})
    return out


_coverage: dict | None = None


def coverage() -> dict:
    """What the dataset does and does not tell us, for the «درباره داده» page (computed once, ~0.2 s)."""
    global _coverage
    if _coverage is None:
        c = conn()
        s = c.execute(
            "SELECT count(*) n, sum(real_name) real, sum(passage != '') passage, sum(hours LIKE '%\"declared\"%') hours,"
            " sum(payments IS NOT NULL AND payments != '[]') pay, sum(payments LIKE '%in_person%') inp,"
            " sum(fast_delivery IS NOT NULL) fast, count(DISTINCT nullif(area, '')) areas FROM shops").fetchone()
        p = c.execute("SELECT count(*) n, sum(min_price IS NOT NULL) priced, sum(n_shops > 1) multi FROM products").fetchone()
        o = c.execute(
            "SELECT count(*) n, sum(price IS NULL) noprice, sum(price_at >= date('now', '-30 day')) month,"
            " sum(price_at >= date('now', '-365 day')) year, sum(warranty_months > 0) warranty,"
            " min(price_at) first, max(price_at) last FROM offers").fetchone()
        _coverage = {"shops": dict(s), "products": dict(p), "offers": dict(o)}
    return _coverage
