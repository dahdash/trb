"""Smoke tests against the built database: every page renders and the main APIs answer."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import needs_db

pytestmark = needs_db
VANAK = {"lat": 35.7575, "lon": 51.41}


@pytest.fixture(scope="module")
def c():
    return TestClient(app)


@pytest.fixture(scope="module")
def tv(c):
    items = c.get("/api/search", params={"q": "تلویزیون سامسونگ"}).json()["items"]
    assert items
    return max(items, key=lambda p: p["n_shops"] or 0)


@pytest.mark.parametrize("path", ["/", "/about", "/health", "/search", "/nearby", "/followups", "/seller", "/compare"])
def test_pages(c, path):
    assert c.get(path).status_code == 200


def test_product_shop_and_404s(c, tv):
    assert c.get(f"/p/{tv['id']}").status_code == 200
    sid = c.get("/api/nearby", params={"product": tv["id"]}).json()["sellers"][0]["shop_id"]
    r = c.get(f"/shop/{sid}")
    assert r.status_code == 200 and "ساعت کاری هفته" in r.text
    assert c.get("/p/999999999").status_code == 404
    assert c.get("/shop/999999999").status_code == 404


def test_nearby_sorted_by_distance(c, tv):
    s = c.get("/api/nearby", params={"product": tv["id"], **VANAK}).json()["sellers"]
    kms = [x["km"] for x in s]
    assert kms == sorted(kms)
    assert c.get("/api/nearby", params={"product": tv["id"], "lat": 10, "lon": 10}).status_code == 422


def test_compare(c, tv):
    items = c.get("/api/search", params={"q": "تلویزیون سامسونگ"}).json()["items"][:2]
    r = c.get("/api/compare", params={"ids": ",".join(str(p["id"]) for p in items)}).json()
    assert len(r["products"]) == 2


def test_chat_rules_search_asks_budget(c):
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "تلویزیون"}]}).json()
    assert any(x["type"] == "product" for x in r["cards"])
    assert any(x["type"] == "ask" for x in r["cards"])


def test_chat_sellers_widgets_and_refilter(c):
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "تلویزیون اقساطی نزدیک من"}], **VANAK}).json()
    bar = next(x for x in r["cards"] if x["type"] == "filters")
    assert bar["f"]["installment"] is True
    f = c.post("/api/chat/sellers", json={"pid": bar["pid"], "sort": "price", **VANAK}).json()
    assert any(x["type"] == "filters" for x in f["cards"]) and f["text"]
    assert c.post("/api/chat/sellers", json={"pid": bar["pid"], "max_km": 1000}).status_code == 422


def test_chat_rejects_bad_input(c):
    assert c.post("/api/chat", json={"messages": []}).status_code == 422
    assert c.post("/api/chat", json={"messages": [{"role": "user", "content": "x" * 501}]}).status_code == 422


def test_chat_rescue_late_night(c):
    """23:30 near the Jomhouri bazaar: no charger seller open within 2 km → rescue card with the bazaar."""
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "شارژر گوشی فوری لازم دارم"}],
                                  "lat": 35.7035, "lon": 51.4065, "at": "23:30"}).json()
    card = next(x for x in r["cards"] if x["type"] == "rescue")
    assert card["need"] and card["at"] == "۲۳:۳۰" and card["n_near"] > 0
    assert card["hub"] and "علاءالدین" in card["hub"]["name"]
    assert card["open"] is None or card["open"]["hours"]["state"] == "open"
    assert c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "at": "25:00"}).status_code == 422


def test_chat_redirects_home_keeping_query(c):
    r = c.get("/chat?at=22:15", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/?at=22:15"
