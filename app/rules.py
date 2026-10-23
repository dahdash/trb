"""Rule-based assistant: the same tools and card answer as the LLM, decided by keywords. Used in local development
(no API calls) and whenever LLM_ENABLED is off."""
import re

from .text import fa, norm

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
_NUM = r"(\d+(?:\.\d+)?)\s*(میلیون|میلیارد|هزار|م\b|تومن|تومان)?"
MAX_RE = re.compile(rf"(?:زیر|تا|حداکثر|کمتر\s*از|ماکزیمم|نهایتا|نهایتاً)\s*{_NUM}")
MIN_RE = re.compile(rf"(?:بالای|بیشتر\s*از|حداقل|از)\s*{_NUM}")
UNIT = {"میلیارد": 1e9, "میلیون": 1e6, "م": 1e6, "هزار": 1e3}

SELLERS = ("نزدیک", "کجا", "فروشنده", "فروشگاه", "مغازه", "بخرم", "حضوری", "پاساژ")
INSTALL = ("قسط", "اقساط", "ترب پی", "اسنپ پی", "دیجی پی", "تارا")
PROVIDERS = {"ترب پی": "ترب‌پی", "اسنپ پی": "اسنپ‌پی", "دیجی پی": "دیجی‌پی", "تارا": "تارا"}
OPEN = ("باز", "الان")
URGENT = ("فوری", "همین الان", "امشب", "دیروقت", "دیر وقت", "نصف شب", "سریع", "خراب شد", "لازم دارم", "الان")
COMPARE = ("مقایسه", "فرق", "کدوم بهتر", "کدام بهتر", "تفاوت")
PLAN = ("برنامه", "مسیر بازدید", "برنامه بازدید", "کجا برم", "ترتیب")
CHEAPER = ("ارزان تر", "ارزونتر", "ارزون تر", "ارزانتر", "ارزان")
# Demo openers (rescue story first); chat.js START mirrors this.
START = ["شارژر گوشی فوری لازم دارم", "تلویزیون اقساطی نزدیک من", "تلویزیون سامسونگ ۵۵ اینچ"]
ORD = {"اولی": 0, "اول": 0, "دومی": 1, "دوم": 1, "سومی": 2, "سوم": 2, "چهارمی": 3}
# Words that carry intent or politeness, not the product name.
FILLER = set(norm("""می خوام میخوام میخواهم میخوام دنبال هستم یه یک برای لطفا لطفاً پیدا کن کنید بده بدید چی چه خوب خوبه
    قیمت تومن تومان میلیون هزار زیر تا حداکثر کمتر بیشتر بالای حداقل از با که رو را و یا هم در به نزدیک من کجا
    بخرم بخریم خرید فروشنده فروشنده ها فروشگاه فروشگاه ها مغازه حضوری قسطی اقساطی اقساط قسط باز الان هست هستن
    داره دارن دارد ببینم نشون نشان بگو بهم مدل مدلی چند چندتا اولی دومی سومی ارزان ارزون تر ترین فقط ی کن
    فوری همین امشب دیروقت دیر وقت نصف شب سریع خراب شد شده لازم دارم الآن
    سلام درود ممنون مرسی خسته نباشی برنامه بازدید مسیر مقایسه فرق تفاوت کدوم کدام بهتر ترتیب برم""").split())


def _money(m: re.Match | None) -> int | None:
    if not m:
        return None
    v = float(m.group(1)) * UNIT.get(m.group(2) or "", 1)
    return int(v * 1e6) if v < 1000 else int(v)  # a bare "زیر ۲۰" means millions


def _budgets(prices: list[int]) -> list[str]:
    """Budget options around the shown prices (a fixed "زیر ۱۰ میلیون" is empty for phones and TVs)."""
    if not prices:
        return []
    m = min(prices) / 1e6
    nice = lambda v: max(1, round(v, -1) if v >= 20 else round(v))
    return [f"زیر {fa(int(v))} میلیون" for v in dict.fromkeys((nice(m * 0.8), nice(m * 1.5), nice(m * 3)))]


def _has(t: str, words) -> bool:
    return any(norm(w) in t for w in words)


def _pick(t: str, ctx: dict) -> int | None:
    prods = ctx.get("products") or []
    if not prods:
        return None
    for w, i in ORD.items():
        if re.search(rf"\b{w}\b", t) and i < len(prods):
            return prods[i][0]
    return prods[0][0]


def _query(t: str) -> str:
    t = MAX_RE.sub(" ", MIN_RE.sub(" ", t))
    ws = [w for w in norm(t).split() if w not in FILLER]  # budgets are cut above; "۵۵ اینچ" or "۱۳" are part of the product
    # "شارژرم ... شارژر": a possessive ending duplicates a word and breaks the AND search
    ws = [w for w in ws if not any(o != w and w.startswith(o) and len(w) - len(o) <= 2 for o in ws)]
    return " ".join(dict.fromkeys(ws))


def answer(msg: str, ctx: dict, turn) -> dict:
    raw = msg.translate(_DIGITS)
    t = norm(raw)
    hi, lo = _money(MAX_RE.search(raw)), _money(MIN_RE.search(raw))
    q = _query(raw)
    inst, opn = _has(t, INSTALL), _has(t, OPEN) and "باز" in t
    prov = next((v for k, v in PROVIDERS.items() if norm(k) in t), None)

    if _has(t, PLAN) and not q:
        return plan(turn)
    if _has(t, COMPARE):
        ids = [p[0] for p in ctx.get("products") or []][:3]
        if len(ids) >= 2:
            return compare(turn, ids, ctx)
        if not q:
            return {"text": "اول دو سه مدل پیدا کنیم. چه محصولی؟",
                    "chips": ["گوشی سامسونگ", "لپ تاپ", "یخچال"]}
    if _has(t, URGENT) and q and not inst and not any(w in t.split() for w in ORD):
        return rescue(turn, q)
    if _has(t, SELLERS) or inst or opn:
        pid = None if q and not any(w in t.split() for w in ORD) else _pick(t, ctx)
        if pid is None and q:
            items = turn.search_products(q, max_price=hi, min_price=lo, limit=30 if inst or opn else 6)["items"]
            pid = items[0]["id"] if items else None
            if inst or opn:  # "یخچال اقساطی": the first model that some shop sells on installments
                pid = next((i["id"] for i in items if turn.find_sellers(
                    i["id"], open_now=opn, installment=inst, provider=prov)["sellers"]), pid)
        if pid is None:
            return {"text": "کدام محصول؟ اسم یا مدلش را بنویس.",
                    "chips": ["گوشی سامسونگ A55", "هدفون بی سیم", "اتو بخار"]}
        return sellers(turn, pid, inst, opn, prov)
    if _has(t, CHEAPER) and not q and ctx.get("q"):
        first = next((p[2] for p in ctx.get("products") or [] if p[2]), None)
        return search(turn, ctx["q"], lo=None, hi=int(first * 0.9) if first else ctx.get("max"), cheaper=True)
    if not q:
        if (hi or lo) and ctx.get("q"):
            return search(turn, ctx["q"], lo, hi)
        return {"text": "سلام! دنبال چه محصولی هستی؟",
                "chips": START}
    return search(turn, q, lo, hi)


def search(turn, q: str, lo: int | None, hi: int | None, cheaper: bool = False) -> dict:
    cat = None
    if hi:  # a budget alone drifts to cheap accessories ("میز تلویزیون"); keep the category of the best plain hit
        top = turn.search_products(q, limit=1)["items"]
        cat = top[0]["category"] if top else None
    r = turn.search_products(q, category=cat, min_price=lo, max_price=hi, limit=24 if hi else 6)
    items = r["items"]
    budget = f" زیر {fa(hi // 1_000_000)} میلیون" if hi and hi >= 1_000_000 else ""
    if not items:
        return {"text": f"برای «{q}»{budget} چیزی پیدا نشد. کلی‌تر بنویس.",
                "q": q, "max": hi, "chips": [q] if hi else ["گوشی", "لپ تاپ", "تلویزیون"]}
    if hi:  # with a budget, the best fit uses most of it; the cheapest hits are usually basic or accessories
        items = sorted(items, key=lambda p: -(p["min_price"] or 0) if (p["min_price"] or 0) >= hi * 0.35 else 0)
    top = items[:3]
    lines = [f"{'ارزان‌تر از قبلی‌ها: ' if cheaper else ''}{fa(r['total'])} نتیجه برای «{q}»{budget}؛ این‌ها بهترین‌اند."]
    stale = [p for p in top if (p["price_age_days"] or 0) > 90]
    many = max(top, key=lambda p: p["n_shops"] or 0)
    if (many["n_shops"] or 0) > 1:
        lines.append(f"«{many['title'][:40]}» را {fa(many['n_shops'])} فروشگاه دارند؛ حضوری راحت‌تر پیدا می‌شود.")
    if stale:
        lines.append("بعضی قیمت‌ها قدیمی‌اند؛ قبل از رفتن بپرس.")
    chips = ["فروشنده‌های نزدیک اولی"]
    if len(top) > 1:
        chips.append("مقایسه کن")
    ask = []
    if not hi:  # clarifying questions as buttons, with options taken from these results
        budgets = _budgets([p["min_price"] for p in top if p["min_price"]])
        if budgets:
            ask.append({"q": "بودجه‌ات چقدر است؟", "options": [f"{q} {b}" for b in budgets]})
    else:
        chips.append("ارزان‌تر")
    brands = [b for b in r["brands"] if norm(b) not in norm(q)]
    if len(brands) > 1 and not any(norm(b) in norm(q) for b in r["brands"]):
        ask.append({"q": "برند خاصی مد نظرت هست؟", "options": [f"{q} {b}" for b in brands[:4]]})
    return {"text": "\n".join(lines), "products": [p["id"] for p in top], "q": q, "max": hi, "min": lo, "chips": chips,
            "ask": ask}


def compare(turn, ids: list[int], ctx: dict) -> dict:
    c = turn.compare_products(ids)
    lines = [f"{fa(len(c['products']))} مدل را کنار هم گذاشتم:"]
    lines += [f"• {v['label']}: {v['product']} ({v['text']})" for v in c["verdict"]]
    if c["mixed_categories"]:
        lines.append("دسته‌هایشان فرق دارد، پس مقایسه‌ی مشخصات محدود است.")
    lines.append(f"{fa(len(c['differences']))} مشخصه با هم فرق دارند؛ جدول کامل در کارت مقایسه است.")
    return {"text": "\n".join(lines), "compare": ids, "products": ids, "q": ctx.get("q"), "max": ctx.get("max"),
            "chips": ["فروشنده‌های نزدیک اولی", "فروشنده‌های نزدیک دومی"]}


def sellers(turn, pid: int, inst: bool, opn: bool, prov: str | None = None) -> dict:
    r = turn.find_sellers(pid, open_now=opn, installment=inst, provider=prov)
    rows = r.get("sellers") or []
    name = (r.get("product") or "")[:50]
    filt = "، ".join(x for x in (prov or ("اقساطی" if inst else ""), "الان باز" if opn else "") if x)
    if not rows:
        return {"text": f"برای «{name}» فروشنده‌ای{f' با فیلتر {filt}' if filt else ''} پیدا نکردم"
                        f" (از {fa(r.get('total_sellers', 0))} فروشنده‌ی ثبت‌شده).",
                "products": [pid], "chips": ["فروشنده‌های نزدیک اولی"] if filt else ["گوشی", "لپ تاپ"]}
    s = rows[0]
    lines = [f"«{name}» را {fa(r['total_sellers'])} فروشگاه ثبت کرده‌اند"
             + (f"؛ با فیلتر {filt}: {fa(r['after_filters'])}." if filt else ".")]
    if r["user_location_known"]:
        how = f"، {fa(s['eta_min'])} دقیقه راه" if s.get("eta_min") else ""
        lines.append(f"پیشنهاد اول: «{s['name']}»{how}.")
    else:
        lines.append("موقعیتت را نمی‌دانم؛ به ترتیب قیمت چیدم. موقعیت را از بالای صفحه بزن.")
    lines.append(f"قیمتش {fa(s['price_age_days'])} روز پیش ثبت شده؛ قبل از رفتن بپرس." if (s["price_age_days"] or 0) > 30
                 else "موجودی قطعی نیست؛ قبل از رفتن بپرس.")
    chips = ["برنامه‌ی بازدید"]
    return {"text": "\n".join(lines), "sellers": [[pid, x["shop_id"]] for x in rows[:3]], "chips": chips}


def rescue(turn, q: str) -> dict:
    r = turn.rescue(q)
    if r.get("error"):
        if turn.lat is None:
            return {"text": "اول موقعیتت را از بالای صفحه بزن.", "chips": [q]}
        return search(turn, q, None, None)
    o, h = r["nearest_open"], r["hub"]
    if r["any_open_within_2km"]:
        text = f"«{o['name']}» همین نزدیکی باز است."
    else:  # the rescue card carries the shop, the bazaar and the earliest opening; the text only frames it
        n = r["sellers_within_2km"]
        text = (f"ساعت {r['time']} از {fa(n)} فروشنده‌ی نزدیکت هیچ‌کدام باز نیست؛ " if n else f"ساعت {r['time']} نزدیکت فروشنده‌ای نیست؛ ") \
            + ("دو راه داری:" if o and h else "این کار را بکن:")
    return {"text": text, "q": q, "chips": [f"فروشنده‌های {q}"]}


def plan(turn) -> dict:
    r = turn.visit_plan()
    if not r.get("stops"):
        return {"text": "هنوز کسی موجودی را تأیید نکرده. اول از یکی دو فروشنده بپرس؛ بعد "
                        "مسیر بازدید با ترتیب و ساعت رسیدن را می‌چینم.", "chips": ["فروشنده‌های نزدیک اولی"]}
    closed = [s for s in r["stops"] if s["open_at_arrival"] == "closed"]
    text = (f"برنامه‌ی بازدید: {fa(len(r['stops']))} فروشگاه، حدود {fa(r['total_min'])} دقیقه "
            f"(حرکت {r['leave']}، پایان حدود {r['back']}).")
    if closed:
        text += f"\n⚠ «{closed[0]['shop']}» وقت رسیدن احتمالاً بسته است؛ قبلش زنگ بزن."
    return {"text": text, "chips": []}
