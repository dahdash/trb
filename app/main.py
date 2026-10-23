import time
from pathlib import Path

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import httpx

from pydantic import BaseModel, Field

from . import assistant, catalog, followup, nearby
from .config import settings
from .text import fa

HERE = Path(__file__).resolve().parent
app = FastAPI(title="تربچه")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days


def age_fa(iso: str | None) -> str:
    d = age_days(iso)
    if d is None:
        return "تاریخ قیمت نامشخص"
    if d < 1:
        return "امروز"
    if d < 31:
        return f"{fa(d)} روز پیش"
    if d < 365:
        return f"{fa(d // 30)} ماه پیش"
    return f"{fa(d // 365)} سال پیش"


templates.env.filters.update(fa=fa, age=age_fa, age_days=age_days)
# Changes on every start (each deploy), so browsers never keep an old app.js/app.css
templates.env.globals.update(neshan_web_key=settings.neshan_web_key, asset_v=format(int(time.time()), "x"))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": settings.db_path.exists(),
            "llm": bool(settings.llm_token), "map": bool(settings.neshan_key)}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "chat.html", {"tab": "chat"})


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(request, "index.html", {"tab": "discover"})


@app.get("/api/search")
def api_search(q: str = "", category: str | None = None, brand: str | None = None,
               min: int | None = Query(None, ge=0), max: int | None = Query(None, ge=0),
               limit: int = Query(24, ge=1, le=60), offset: int = Query(0, ge=0, le=600)):
    return catalog.search(q[:120], category, brand, min, max, limit, offset)


@app.get("/api/products/{pid}")
def api_product(pid: int):
    p = catalog.product(pid)
    if not p:
        raise HTTPException(404, "محصول پیدا نشد")
    return p


def _ids(ids: str) -> list[int]:
    return [int(x) for x in ids.split(",") if x.strip().isdigit()][:4]


@app.get("/api/compare")
def api_compare(ids: str):
    return catalog.compare(_ids(ids))


@app.get("/p/{pid}", response_class=HTMLResponse)
def product_page(request: Request, pid: int):
    p = catalog.product(pid)
    if not p:
        raise HTTPException(404, "محصول پیدا نشد")
    return templates.TemplateResponse(request, "product.html", {"tab": "discover", "p": p})


@app.get("/shop/{sid}", response_class=HTMLResponse)
def shop_page(request: Request, sid: int):
    s = nearby.shop(sid)
    if not s:
        raise HTTPException(404, "فروشگاه پیدا نشد")
    return templates.TemplateResponse(request, "shop.html", {"tab": "nearby", "s": s})


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {"tab": "", "c": catalog.coverage()})


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, ids: str = ""):
    return templates.TemplateResponse(request, "compare.html", {"tab": "discover", "c": catalog.compare(_ids(ids))})


@app.get("/api/nearby")
def api_nearby(product: int, lat: float | None = Query(None, ge=35, le=36.5),
               lon: float | None = Query(None, ge=50.5, le=52.5)):
    p = catalog.product(product)
    if not p:
        raise HTTPException(404, "محصول پیدا نشد")
    return {"product": {k: p.get(k) for k in ("id", "title", "image", "min_price", "max_price", "price_at")},
            "sellers": nearby.sellers(product, lat, lon)}


@app.get("/api/areas")
def api_areas():
    return nearby.areas()


@app.get("/api/reverse")
def api_reverse(lat: float = Query(..., ge=35, le=36.5), lon: float = Query(..., ge=50.5, le=52.5)):
    """Neighbourhood name for a point (Neshan). The key stays on the server."""
    if not settings.neshan_key:
        return {"label": None}
    try:
        r = httpx.get("https://api.neshan.org/v5/reverse", params={"lat": lat, "lng": lon},
                      headers={"Api-Key": settings.neshan_key}, timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return {"label": None}
    return {"label": r.get("neighbourhood") or r.get("route_name") or None, "address": r.get("formatted_address")}


@app.get("/nearby", response_class=HTMLResponse)
def nearby_page(request: Request, product: int | None = None):
    p = catalog.product(product) if product else None
    return templates.TemplateResponse(request, "nearby.html", {"tab": "nearby", "p": p})


Client = Query(..., min_length=8, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
Lat, Lon = Query(None, ge=35, le=36.5), Query(None, ge=50.5, le=52.5)
AT = r"^([01]?\d|2[0-3]):[0-5]\d$"
At = Query(None, pattern=AT)  # demo clock (?at=23:30), today in Tehran


def _clock(at: str | None) -> datetime | None:
    if not at:
        return None
    h, m = map(int, at.split(":"))
    return datetime.now(nearby.TEHRAN).replace(hour=h, minute=m, second=0, microsecond=0)


class Ask(BaseModel):
    client: str = Field(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    product_id: int
    shop_id: int
    asks: list[Annotated[str, Field(max_length=60)]] = Field(default=[], max_length=8)
    message: str = Field(max_length=1000)


class Outcome(BaseModel):
    client: str = Field(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    outcome: str
    price: int | None = Field(None, ge=0)
    note: str | None = Field(None, max_length=300)


class Reply(BaseModel):
    in_stock: bool
    price: int | None = Field(None, ge=0)
    open_until: str | None = Field(None, max_length=20)
    note: str | None = Field(None, max_length=300)


@app.post("/api/inquiries")
def api_ask(a: Ask):
    q = followup.create(a.client, a.product_id, a.shop_id, a.asks, a.message)
    if not q:
        raise HTTPException(404, "این فروشگاه این محصول را ثبت نکرده")
    return q


@app.get("/api/inquiries")
def api_inquiries(client: str = Client):
    return followup.mine(client)


@app.post("/api/inquiries/{iid}/outcome")
def api_outcome(iid: int, o: Outcome):
    q = followup.record(iid, o.client, o.outcome, o.price, o.note)
    if not q:
        raise HTTPException(404, "پیگیری پیدا نشد")
    return q


@app.get("/api/inquiries/{iid}/alternatives")
def api_alternatives(iid: int, client: str = Client, lat: float | None = Lat, lon: float | None = Lon,
                     at: str | None = At):
    return followup.alternatives(iid, client, lat, lon, now=_clock(at))


@app.get("/api/plan")
def api_plan(client: str = Client, lat: float | None = Lat, lon: float | None = Lon, at: str | None = At):
    return followup.plan(client, lat, lon, now=_clock(at))


@app.get("/api/seller/inbox")
def api_inbox(shop: int | None = None):
    return followup.inbox(shop)


@app.post("/api/seller/inquiries/{iid}/reply")
def api_reply(iid: int, r: Reply):
    q = followup.seller_reply(iid, r.in_stock, r.price, r.open_until, r.note)
    if not q:
        raise HTTPException(404, "پیام پیدا نشد")
    return q


@app.get("/followups", response_class=HTMLResponse)
def followups_page(request: Request):
    return templates.TemplateResponse(request, "followups.html", {"tab": "followups"})


@app.get("/seller", response_class=HTMLResponse)
def seller_page(request: Request, shop: int | None = None):
    return templates.TemplateResponse(request, "seller.html", {"tab": None, "shop": shop})


class Msg(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=2000)


class Chat(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=30)
    client: str | None = Field(None, min_length=8, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    lat: float | None = Field(None, ge=35, le=36.5)
    lon: float | None = Field(None, ge=50.5, le=52.5)
    place: str | None = Field(None, max_length=60)
    at: str | None = Field(None, pattern=AT)


@app.post("/api/chat")
def api_chat(c: Chat, request: Request):
    if not assistant.allowed(request.client.host if request.client else "-"):
        raise HTTPException(429, "پیام‌ها زیاد شد؛ یک دقیقه صبر کن.")
    if c.messages[-1].role != "user" or len(c.messages[-1].content) > 500:
        raise HTTPException(422, "پیام نامعتبر است")
    # Last 10 turns only: older context costs tokens and rarely matters for a shopping errand.
    history = [m.model_dump() for m in c.messages[-10:]]
    lat, lon = (c.lat, c.lon) if c.lat is not None and c.lon is not None else (None, None)
    try:
        return assistant.chat(history, c.client, lat, lon, c.place, _clock(c.at))
    except assistant.OpenAIError:
        raise HTTPException(502, "دستیار الان جواب نمی‌دهد؛ چند لحظه بعد دوباره امتحان کن.")


class Refilter(BaseModel):
    pid: int
    sort: Literal["best", "price", "near"] = "best"
    open_now: bool = False
    installment: bool = False
    provider: str | None = Field(None, max_length=20)
    max_km: float | None = Field(None, gt=0, le=100)
    max_price: int | None = Field(None, gt=0)
    lat: float | None = Field(None, ge=35, le=36.5)
    lon: float | None = Field(None, ge=50.5, le=52.5)


@app.post("/api/chat/sellers")
def api_chat_sellers(r: Refilter):
    """The chat's live filter bar: same tool as the assistant, no LLM call."""
    lat, lon = (r.lat, r.lon) if r.lat is not None and r.lon is not None else (None, None)
    f = r.model_dump(exclude={"pid", "lat", "lon"})
    return assistant.refilter(r.pid, f, lat, lon)


@app.get("/chat")
def chat_page(request: Request):  # the assistant moved to "/" (T-029); keep old links and ?at= working
    q = request.url.query
    return RedirectResponse(f"/?{q}" if q else "/", status_code=301)


def run() -> None:
    import os

    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    run()
