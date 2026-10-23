# تربچه — دستیار خرید حضوری

Entry for the Torob challenge: an assistant for buying **in person** from Tehran stores, malls and passages.

**Demo:** https://torobche-app.liara.run · **About the data:** [/about](https://torobche-app.liara.run/about)

## What it does

| Step | Page | What the user gets |
|---|---|---|
| 1. Discover | `/`, `/p/{id}`, `/compare` | Search with reasons ("why this one"), category/brand/budget filters, a side-by-side spec table with "differences only" |
| 2. Find nearby | `/nearby?product=…` | Shops that list the product, with distance and drive time (Neshan Distance Matrix), on a map |
| 3. Compare shops | seller cards, `/shop/{id}` | Price **and its age**, open now, installment providers (in person or not), warranty, passage / floor / unit card, Neshan navigation |
| 4. Contact & follow up | ask sheet, `/followups`, `/seller` | A ready message to confirm stock, price and hours; follow-up list; alternatives when a shop is closed, does not answer or quotes another price; a visit plan; a simulated seller panel for the demo |
| Assistant | `/chat` | Chat over the same tools, with **generative UI**: clarifying questions as buttons, a verdict card (best balance / cheapest / nearest, each with a reason) and a live filter bar that re-ranks without another LLM call; voice input (fa-IR) |

Unknown data is shown as unknown, never as a default. See `/about` for coverage numbers and how each gap is handled.

## How the assistant works

- `app/assistant.py` runs an OpenAI-compatible tool loop (boxapi, `gpt-5.4-mini`) over `search_products`, `compare_products`, `find_sellers` and `visit_plan`. These are the same functions the pages use.
- Cards and widgets are built server-side **only from rows a tool returned in that turn**, so the model cannot invent a price or a shop. Dataset text is treated as data, not instructions.
- The model chooses *which* widgets to show (`ask`, `verdict`, `filters`), and the server fills them. `/api/chat/sellers` re-runs `find_sellers` when a filter chip changes, with no LLM call.
- When `LLM_ENABLED` is not set, `app/rules.py` is a keyword assistant with the same output shape and no API calls. It is used for local development and the tests.
- Rate limits: 12 chat requests per minute per IP and 120 per minute globally. Neshan ETA calls are capped at 60 per minute and fall back to a haversine estimate.

## Stack

Python 3.12, FastAPI, and SQLite with FTS5 in one service. The UI is Jinja plus plain JS, mobile-first and RTL. Distance is haversine in Python, refined by Neshan's driving ETA. The map uses Neshan's Leaflet SDK, with OSM as a fallback.

```
app/main.py       routes, Jinja filters
app/catalog.py    step 1: search rerank, facets, compare, data coverage
app/nearby.py     steps 2–3: sellers near a point, ETA, cost() ranking, shop page
app/followup.py   step 4: inquiries (data/app.db), seller replies, alternatives, visit plan
app/assistant.py  chat: LLM tool loop + generative UI widgets
app/rules.py      chat without an LLM
app/text.py       Farsi normalization and FTS query, shared by ETL and queries
etl/build_db.py   CSVs → data/torob.db (parsed passage/floor/unit, price stats, FTS index)
tests/            pytest smoke tests (no network, no LLM)
```

Ranking ("best balance"): % above the cheapest price + 0.7 × minutes of driving, + a penalty when the shop is closed or its hours are unknown, + a penalty for a stale price, − a bonus for in-person installments. A price far below the others is flagged and not used as the cheapest.

## Run locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                       # NESHAN keys optional; leave LLM_ENABLED empty
unzip -o starcoach-dataset-v16-cap300-csv.zip -d data/raw
.venv/bin/python etl/build_db.py           # ~30 s, ~325 MB
.venv/bin/uvicorn app.main:app --reload    # http://127.0.0.1:8000
.venv/bin/python -m pytest -q
```

## Deploy

Liara app `torobche-app` (Docker). The image builds `data/torob.db` from the dataset zip at build time. `scripts/deploy.py --app torobche-app` stages the build context, sets env from `.env` plus `LLM_ENABLED=1`, and waits until the app is ready.

## Data caveats (from the challenge brief)

Shop names (except the 112 with a site or Instagram) and all phone numbers are synthetic, while locations are real. A listing is not confirmed stock. About half of the prices are older than a month. Only ~4% of shops declare installment providers. The app says so wherever it matters.
