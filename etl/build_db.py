"""Build data/torob.db (SQLite + FTS5) from the dataset CSVs.

Usage: python etl/build_db.py [RAW_DIR_OR_ZIP] [OUT_DB]
RAW_DIR_OR_ZIP defaults to data/raw, falling back to the dataset zip in the repo root.
"""
import csv
import io
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.text import norm  # noqa: E402

csv.field_size_limit(10**9)
MAX_SPECS = 60  # specs are most of the dataset's size; the first entries are the useful ones

SCHEMA = """
CREATE TABLE shops (
  id INTEGER PRIMARY KEY, ext_id TEXT UNIQUE, name TEXT, real_name INTEGER, address TEXT,
  passage TEXT, floor TEXT, unit TEXT, area TEXT, lat REAL, lon REAL,
  categories TEXT, phone TEXT, hours TEXT, payments TEXT, installment INTEGER,
  fast_delivery INTEGER, instagram TEXT, website TEXT
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY, ext_id TEXT UNIQUE, title TEXT, model TEXT, brand TEXT, category TEXT,
  image TEXT, images TEXT, specs TEXT,
  min_price INTEGER, max_price INTEGER, n_offers INTEGER, n_shops INTEGER
);
CREATE TABLE offers (
  id INTEGER PRIMARY KEY, ext_id TEXT, shop_id INTEGER, product_id INTEGER, seller_title TEXT,
  description TEXT, price INTEGER, price_at TEXT, warranty TEXT, warranty_months INTEGER
);
CREATE VIRTUAL TABLE products_fts USING fts5(
  title, brand, category, extra, content='', tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE categories (name TEXT PRIMARY KEY, n_products INTEGER);
CREATE TABLE brands (name TEXT, category TEXT, n_products INTEGER);
"""
INDEXES = """
CREATE INDEX offers_product ON offers(product_id, price);
CREATE INDEX offers_shop ON offers(shop_id);
CREATE INDEX products_category ON products(category, min_price);
CREATE INDEX products_brand ON products(brand);
CREATE INDEX brands_category ON brands(category);
"""


def nul(v: str | None):
    return None if v in (None, "", "null") else v


def js(v: str | None):
    v = nul(v)
    return json.loads(v) if v else None


PASSAGE_RE = re.compile(
    r"((?:پاساژ|مجتمع(?: تجاری)?|مرکز (?:خرید|تجاری|تجارت)|ساختمان|بازار|سرای|تیمچه|برج|مال)\s+[^،,\-]+)")
FLOOR_RE = re.compile(r"طبقه\s*(منفی[\s\u200c]*(?:\d+|یک|دو|سه)|[^\s،,]+)|(همکف|زیرزمین|زیر همکف)")  # «طبقه منفی ۱» keeps its number
UNIT_RE = re.compile(r"((?:واحد|غرفه|مغازه|پلاک)\s*[\w\-/.]+)")


def parse_address(addr: str | None) -> tuple[str | None, str | None, str | None]:
    if not addr:
        return None, None, None
    addr = addr.replace("ك", "ک").replace("ي", "ی")
    p = PASSAGE_RE.search(addr)
    f = FLOOR_RE.search(addr)
    u = None
    # the unit is the last واحد/غرفه/پلاک number (پلاک alone is usually the street number)
    for m in UNIT_RE.finditer(addr):
        u = m.group(1).removesuffix(".0")
    floor = (f.group(1) or f.group(2)).strip() if f else None
    return (p.group(1).strip() if p else None), floor, u


def open_csv(src: Path, name: str):
    if src.is_dir():
        return open(src / name, encoding="utf-8", newline="")
    z = zipfile.ZipFile(src)
    member = next(n for n in z.namelist() if n.endswith(name))
    return io.TextIOWrapper(z.open(member), encoding="utf-8", newline="")


def build(src: Path, out: Path) -> None:
    t0 = time.time()
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)

    shop_ids: dict[str, int] = {}
    with open_csv(src, "shops.csv") as f:
        for r in csv.DictReader(f):
            pays = js(r["payment_options"]) or []
            contacts = js(r["contacts"]) or []
            phone = next((c.get("display_number") or c.get("value") for c in contacts if c.get("display_number") or c.get("value")), None)
            fd = nul(r["supports_fast_delivery"])
            passage, floor, unit = parse_address(nul(r["address"]))
            sid = len(shop_ids) + 1
            shop_ids[r["shop_id"]] = sid
            db.execute("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                sid, r["shop_id"], nul(r["name"]),
                int(bool(nul(r["instagram"]) or nul(r["website_url"]))),
                nul(r["address"]), passage, floor, unit, nul(r["location_label"]),
                float(r["lat"]) if nul(r["lat"]) else None, float(r["lon"]) if nul(r["lon"]) else None,
                nul(r["category_names"]), phone, nul(r["weekly_hours"]),
                json.dumps(pays, ensure_ascii=False) if pays else None, int(bool(pays)),
                None if fd is None else int(fd == "true"), nul(r["instagram"]), nul(r["website_url"])))
    print(f"shops: {len(shop_ids)}  {time.time() - t0:.0f}s")

    prod_ids: dict[str, int] = {}
    with open_csv(src, "products.csv") as f:
        for r in csv.DictReader(f):
            pid = len(prod_ids) + 1
            prod_ids[r["product_id"]] = pid
            imgs = js(r["image_urls"]) or []
            specs = js(r["specs"]) or []
            specs = [[s.get("section"), s.get("key"), s.get("value")] for s in specs[:MAX_SPECS]]
            db.execute("INSERT INTO products (id, ext_id, title, model, brand, category, image, images, specs)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", (
                           pid, r["product_id"], nul(r["persian_title"]), nul(r["model"]), nul(r["brand_name"]),
                           nul(r["category_name"]), imgs[0] if imgs else None,
                           json.dumps(imgs[:4]) if imgs else None,
                           json.dumps(specs, ensure_ascii=False) if specs else None))
    print(f"products: {len(prod_ids)}  {time.time() - t0:.0f}s")

    seller_titles: dict[int, list[str]] = {}
    n = 0
    with open_csv(src, "offers.csv") as f:
        rows = []
        for r in csv.DictReader(f):
            pid, sid = prod_ids.get(r["product_id"]), shop_ids.get(r["shop_id"])
            if not pid or not sid:
                continue
            w = js(r["warranty"])
            price = nul(r["price_toman"])
            rows.append((r["offer_id"], sid, pid, nul(r["seller_title"]), nul(r["description"]),
                         int(float(price)) if price else None, nul(r["last_price_changed_at"]),
                         json.dumps(w, ensure_ascii=False) if w else None,
                         (w or {}).get("period_months")))
            st = nul(r["seller_title"])
            if st:
                seller_titles.setdefault(pid, []).append(st)
            n += 1
            if len(rows) >= 20000:
                db.executemany("INSERT INTO offers (ext_id, shop_id, product_id, seller_title, description,"
                               " price, price_at, warranty, warranty_months) VALUES (?,?,?,?,?,?,?,?,?)", rows)
                rows = []
        db.executemany("INSERT INTO offers (ext_id, shop_id, product_id, seller_title, description,"
                       " price, price_at, warranty, warranty_months) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    print(f"offers: {n}  {time.time() - t0:.0f}s")

    db.executescript(INDEXES)
    db.execute("""UPDATE products SET (min_price, max_price, n_offers, n_shops) = (
        SELECT min(price), max(price), count(*), count(DISTINCT shop_id) FROM offers o WHERE o.product_id = products.id)""")

    # FTS over normalized text; seller titles add the colloquial names shops use
    fts = []
    for pid, title, brand, cat, model in db.execute("SELECT id, title, brand, category, model FROM products"):
        extra = " ".join(dict.fromkeys(seller_titles.get(pid, [])[:3]))
        fts.append((pid, norm(title or ""), norm(brand or ""), norm(cat or ""), norm(f"{model or ''} {extra}")))
    db.executemany("INSERT INTO products_fts (rowid, title, brand, category, extra) VALUES (?,?,?,?,?)", fts)
    db.execute("INSERT INTO categories SELECT category, count(*) FROM products WHERE category IS NOT NULL GROUP BY 1")
    db.execute("INSERT INTO brands SELECT brand, category, count(*) FROM products WHERE brand IS NOT NULL GROUP BY 1, 2")
    db.execute("INSERT INTO products_fts(products_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    print(f"done: {out} {out.stat().st_size / 1e6:.0f} MB  {time.time() - t0:.0f}s")


if __name__ == "__main__":
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw"
    if not raw.exists():
        raw = ROOT / "starcoach-dataset-v16-cap300-csv.zip"
    build(raw, Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/torob.db")
