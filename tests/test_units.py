"""Pure functions: Farsi text handling, opening hours, shop ranking."""
import json
from datetime import datetime, timedelta, timezone

from app import nearby, rules
from app.text import fa, fts_query, norm

TEHRAN = timezone(timedelta(hours=3, minutes=30))


def test_norm_unifies_arabic_letters_and_digits():
    assert norm("كيف ۱۲٣") == norm("کیف 123")
    assert norm("  گوشی،   سامسونگ ") == "گوشی سامسونگ"


def test_fts_query_prefixes_last_token_and_drops_empty():
    q = fts_query("گوشی سامس")
    assert q and q.rstrip().endswith("*")
    assert fts_query("  ،، ") is None


def test_fa_digits_and_separator():
    assert fa(1250000) == "۱٬۲۵۰٬۰۰۰"
    assert fa(None) == ""


HOURS = json.dumps({"mon": {"status": "declared", "shifts": [{"start_time": "10:00", "end_time": "19:00"}]},
                    "fri": {"status": "closed", "shifts": []},
                    "tue": {"status": "unsupported", "shifts": []}})


def test_open_status_states():
    mon_noon = datetime(2026, 10, 19, 12, 0, tzinfo=TEHRAN)  # a Monday
    assert nearby.open_status(HOURS, mon_noon)["state"] == "open"
    assert nearby.open_status(HOURS, mon_noon.replace(hour=20))["state"] == "closed"
    assert nearby.open_status(HOURS, datetime(2026, 10, 23, 12, 0, tzinfo=TEHRAN))["today"] == "امروز تعطیل"
    assert nearby.open_status(HOURS, datetime(2026, 10, 20, 12, 0, tzinfo=TEHRAN))["state"] == "unknown"
    assert nearby.open_status(None)["state"] == "unknown"


def test_week_is_saturday_first_and_keeps_unknown_days():
    w = nearby.week(HOURS)
    assert [d["day"] for d in w][0] == "شنبه" and len(w) == 7
    by = {d["day"]: d["text"] for d in w}
    assert by["دوشنبه"] == "۱۰ تا ۱۹" and by["جمعه"] == "تعطیل" and by["سه‌شنبه"] is None


def test_payments_dedupe_and_channel():
    p = nearby.payments(json.dumps([{"provider_name": "دیجی پی", "channel": "in_person"},
                                    {"provider_name": "دیجی پی", "channel": "unknown"},
                                    {"provider_name": "تارا", "channel": "unknown"}]))
    assert p == [{"name": "دیجی‌پی", "in_person": True}, {"name": "تارا", "in_person": False}]


def _shop(price, eta, state="open", pays=()):
    return {"price": price, "eta_min": eta, "km": None, "hours": {"state": state}, "price_at": None,
            "payments": [{"in_person": True} for _ in pays]}


def test_cost_prefers_cheap_near_open():
    cheap_far, dear_near = _shop(100, 40), _shop(110, 5)
    assert nearby.cost(dear_near, 100) < nearby.cost(cheap_far, 100)  # 10% dearer beats 35 more minutes
    assert nearby.cost(_shop(100, 10), 100) < nearby.cost(_shop(100, 10, "closed"), 100)
    assert nearby.cost(_shop(100, 10, pays=[1]), 100) < nearby.cost(_shop(100, 10), 100)
    assert nearby.km(35.7, 51.4, 35.7, 51.4) == 0


def test_link_reads_instagram_json_and_rejects_other_schemes():
    ig = json.dumps({"handle": "a", "profile_url": "https://www.instagram.com/a/"})
    assert nearby.link(None, ig) == "https://www.instagram.com/a/"
    assert nearby.link("https://x.ir", ig) == "https://x.ir"
    assert nearby.link("javascript:alert(1)", None) is None
    assert nearby.link(None, "@a") is None


def test_rate_limit_per_ip_and_global(monkeypatch):
    from app import assistant
    monkeypatch.setattr(assistant, "_hits", type(assistant._hits)(assistant._hits.default_factory))
    assert all(assistant.allowed("1.1.1.1") for _ in range(assistant.LIMIT))
    assert not assistant.allowed("1.1.1.1")
    monkeypatch.setattr(assistant, "GLOBAL_LIMIT", assistant.LIMIT + 1)
    assert assistant.allowed("2.2.2.2") and not assistant.allowed("3.3.3.3")


def test_next_open_and_closes_at():
    h = json.dumps({d: {"status": "declared", "shifts": [{"start_time": "10:00", "end_time": "21:00"}]}
                    for d in ("sat", "sun", "mon", "tue", "wed", "thu")} | {"fri": {"status": "closed", "shifts": []}})
    thu_night = datetime(2026, 10, 22, 23, 30, tzinfo=TEHRAN)
    assert nearby.next_open(h, thu_night)[1] == "شنبه ساعت ۱۰"  # Friday closed
    assert nearby.closes_at(h, datetime(2026, 10, 21, 12, 0, tzinfo=TEHRAN)) == "۲۱"
    assert nearby.closes_at(h, thu_night) is None
    assert nearby.next_open(None, thu_night) is None


def test_rules_query_keeps_model_numbers_but_cuts_budget():
    q = lambda s: rules._query(s.translate(rules._DIGITS))
    assert q("تلویزیون سامسونگ ۵۵ اینچ زیر ۴۰ میلیون") == norm("تلویزیون سامسونگ 55 اینچ")
    assert q("یه آیفون ۱۳ می خوام") == norm("آیفون 13")


def test_parse_address_keeps_negative_floor_number():
    from etl.build_db import parse_address
    assert parse_address("پاساژ علاءالدین، طبقه منفی ۱، واحد 12") == ("پاساژ علاءالدین", "منفی ۱", "واحد 12")
    assert parse_address("طبقه منفی واحد 4")[1] == "منفی"
    assert parse_address("طبقه 6، واحد 622")[1] == "6"


def test_alternatives_use_a_price_the_shop_already_quoted(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import followup
    monkeypatch.setattr(followup, "settings", SimpleNamespace(db_path=tmp_path / "torob.db"))
    monkeypatch.setattr(followup, "_db", None)
    shop = lambda sid, price: {"shop_id": sid, "price": price, "price_flag": None, "hours": {"state": "open"},
                               "km": 1.0, "eta_min": 5, "price_at": None, "payments": []}
    monkeypatch.setattr(nearby, "sellers", lambda pid, lat, lon, now=None: [shop(1, 100), shop(2, 900), shop(3, 1000)])
    db = followup.db()
    ins = "INSERT INTO inquiries (client, product_id, shop_id, outcome, price, answered) VALUES ('me', 7, ?, ?, ?, ?)"
    db.execute(ins, (2, "price_diff", 500, "2026-10-23T10:00:00+00:00"))  # shop 2 already quoted 500, not its listed 900
    iid = db.execute(ins, (1, "no_stock", None, "2026-10-23T11:00:00+00:00")).lastrowid
    alts = {s["shop_id"]: s for s in followup.alternatives(iid, "me", None, None)}
    assert alts[2]["price"] == 500 and alts[2]["quoted"] and alts[3]["price"] == 1000 and 1 not in alts
