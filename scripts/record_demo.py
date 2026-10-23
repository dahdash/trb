"""Record the demo video (T-010) by driving the deployed Torobche UI per docs/demo-script.fa.md.

Port of ~/Work/liara/scripts/record_demo.py. Headless Chromium (light theme, 1920×1080) is screencast
over CDP; in-page overlays show the section label and a "⏩ ۸×" badge while waits are sped up. ffmpeg
then builds the MP4: waits play 8× faster, and each narration block (N0..N16) is held long enough to
be read. If --out/voice/N<n>.wav exist (scripts/tts.py, Gemini TTS), each block is timed to its clip,
idle holds beyond it are trimmed, and the voice is mixed in. Outputs in --out (default out/demo):
demo.mp4, timing.md (N-block start times), narration.srt.

Usage, from the repo root, with Liara's venv (has playwright + chromium):
  ~/Work/liara/.venv/bin/python scripts/record_demo.py                  # prod, everything, then assemble
  ~/Work/liara/.venv/bin/python scripts/record_demo.py --only hook,rescue   # a subset (testing)
  ~/Work/liara/.venv/bin/python scripts/record_demo.py --assemble       # rebuild the MP4 from the last capture
  ~/Work/liara/.venv/bin/python scripts/record_demo.py --base http://127.0.0.1:8011 --rules   # local smoke test
--rules swaps the typed questions for ones the offline keyword assistant understands (no LLM locally).
Each run uses a fresh browser profile: new uid, no chat, no follow-ups. Do not redeploy between takes.
"""
from __future__ import annotations

import argparse, array, asyncio, base64, json, re, shutil, subprocess, sys, time, wave
from pathlib import Path

import httpx
from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://torobche-app.liara.run"
FAST = 8          # speed-up of waits
FPS = 30
FAST_AFTER = 3.0  # seconds of waiting on the assistant before switching to fast-forward
WPS = 2.3         # narration words per second (Persian, calm pace)
LEAD, TAIL = 0.4, 0.6  # silence before / after a TTS clip within its block
SLACK = 1.5       # idle seconds a voiced block may keep beyond its clip before holds are trimmed
MIN_HOLD = {"N0": 6.0}  # blocks shown at least this long even if the clip is shorter (title card)
SPREAD: dict[str, float] = {}  # blocks whose extra time goes to their earlier holds; last frame kept this long
# Layout: the mobile-first app renders as a centered column in a 1920×1080 desktop frame.
# For a narrower, phone-like page use e.g. VIEW = {"width": 960, "height": 540}, SCALE = 2.
VIEW = {"width": 1280, "height": 720}
SCALE = 1.5       # VIEW × SCALE = 1920×1080 frames, larger text
LOC = {"lat": 35.7035, "lon": 51.4065, "label": "خیابان جمهوری"}
NIGHT, DAY = "22:15", "12:00"  # demo clock (?at=) for the rescue scene and the rest
STEPS = ["hook", "rescue", "model", "sellers", "ask", "end"]

# Questions typed in the chat. Prod answers them with the LLM; --rules uses keyword-friendly ones.
MSG = {"charger": "شارژر گوشی فوری لازم دارم",
       "model": "هدفون بلوتوثی انکر R50i یا R50i NC؟ کدوم بهتره",
       "sellers": "فروشنده‌های نزدیک انکر R50i NC که قسطی می‌فروشند"}
RULES_MSG = {"model": "هدفون انکر R50i", "sellers": "انکر R50i NC قسطی"}

# Installed with context.add_init_script, so it survives every navigation (labels are re-applied).
OVERLAY_JS = r"""
(() => {
  if (window.top !== window || window.__rec) return;
  const css = `
  #rec-ov{position:fixed;inset:0;pointer-events:none;z-index:2147483647;font-family:Vazirmatn,Tahoma,sans-serif}
  #rec-top{position:absolute;top:14px;left:18px;display:flex;gap:8px;align-items:center;direction:rtl}
  #rec-label{background:#1c2333;color:#fff;border-radius:10px;padding:5px 14px;font-size:16px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.25);display:none}
  #rec-fast{background:#d93a3a;color:#fff;border-radius:10px;padding:5px 10px;font-size:15px;font-weight:700;display:none}
  #rec-cursor{position:absolute;left:640px;top:360px;width:22px;height:22px;transition:left .6s ease,top .6s ease;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))}
  #rec-screen{position:absolute;inset:0;background:#f4f6fb;display:none;pointer-events:none}
  .rec-spot{outline:3px solid #ff8a00 !important;outline-offset:3px;border-radius:10px;transition:outline .3s}
  .rec-title{position:absolute;inset:0;display:grid;place-items:center;overflow:hidden;color:#fff;direction:rtl;text-align:center;
    background:radial-gradient(circle at 85% 15%,rgba(255,255,255,.14) 0 180px,transparent 181px),radial-gradient(circle at 8% 92%,rgba(224,49,83,.35) 0 260px,transparent 261px),linear-gradient(135deg,#4f46e5 0%,#3730a3 45%,#1c2333 100%)}
  .rec-title .in{animation:rec-up .9s ease both}
  @keyframes rec-up{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
  .rec-title .tag{color:#fff;display:inline-flex;gap:10px;align-items:center;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:6px 18px;font-size:17px;font-weight:500;letter-spacing:.2px}
  .rec-title .tag b{font-family:system-ui,sans-serif;direction:ltr;unicode-bidi:isolate}
  .rec-title .mark{width:96px;height:96px;margin:30px auto 10px;border-radius:26px;background:#fff;display:grid;place-items:center;box-shadow:0 12px 40px rgba(0,0,0,.3)}
  .rec-title .mark img{width:64px;height:64px}
  .rec-title h1{font-size:76px;margin:6px 0 4px;font-weight:700}
  .rec-title .sub{font-size:23px;margin:0;opacity:.92}
  .rec-title ul{list-style:none;padding:0;margin:26px auto 0;display:grid;grid-template-columns:auto auto;gap:6px 40px;font-size:20px;justify-content:center;text-align:right}
  .rec-title .rule{width:80px;height:3px;border-radius:2px;background:rgba(255,255,255,.5);margin:30px auto 18px}
  .rec-title .by{font-size:26px;font-weight:700}.rec-title .by small{display:block;font-size:15px;font-weight:400;opacity:.75;margin-bottom:2px}
  .rec-title .url{direction:ltr;font-family:ui-monospace,monospace;font-size:18px;opacity:.85;margin-top:14px}`;
  const init = () => {
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const ov = document.createElement('div'); ov.id = 'rec-ov';
    ov.innerHTML = `<div id="rec-screen"></div><div id="rec-top"><span id="rec-label"></span><span id="rec-fast">⏩ ۸×</span></div>
      <svg id="rec-cursor" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    document.body.appendChild(ov);
  };
  const $ = (id) => document.getElementById(id);
  window.__rec = {
    // a modal <dialog> sits in the top layer, above any z-index: keep the overlay inside the open one
    host() { const ov = $('rec-ov'), d = document.querySelector('dialog[open]') || document.body; if (ov && ov.parentNode !== d) d.appendChild(ov); },
    label(t) { this.host(); const l = $('rec-label'); l.textContent = t; l.style.display = t ? 'inline-block' : 'none'; },
    fast(on) { this.host(); $('rec-fast').style.display = on ? 'inline-block' : 'none'; },
    move(x, y) { this.host(); const c = $('rec-cursor'); c.style.left = x + 'px'; c.style.top = y + 'px'; },
    top(on) { $('rec-top').style.visibility = on ? '' : 'hidden'; },
    screen(h) { const s = $('rec-screen'); s.innerHTML = h || ''; s.style.display = h ? 'block' : 'none'; $('rec-cursor').style.display = h ? 'none' : ''; },
  };
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init);
})();
"""


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def narration() -> dict[str, str]:
    text = (ROOT / "docs/demo-script.fa.md").read_text()
    return {f"N{n}": t.strip() for n, t in re.findall(r"^> \*\*N(\d+)\*\* — (.+)$", text, re.M)}


def need(text: str) -> float:
    return len(text.split()) / WPS + 0.8


def voice_len(out: Path, n: str) -> float | None:
    """Length of the TTS clip for block n (scripts/tts.py), or None if there is none."""
    f = out / "voice" / f"{n}.wav"
    if not f.exists():
        return None
    with wave.open(str(f)) as w:
        rate, n_frames, pcm = w.getframerate(), w.getnframes(), w.readframes(w.getnframes())
    # Gemini TTS ends each clip with a short noise burst after a gap: cut at that gap
    a, win = array.array("h", pcm), int(rate * 0.02)
    rms = [(sum(x * x for x in a[i:i + win]) / win) ** 0.5 for i in range(0, len(a) - win + 1, win)]
    quiet = [r < 100 for r in rms]  # ≈ −50 dBFS
    i, tail = len(rms) - 1, int(0.6 / 0.02)
    while i >= 0 and not quiet[i] and len(rms) - i <= tail:
        i -= 1
    if i < 0 or not quiet[i] or i == len(rms) - 1:
        return n_frames / rate
    while i > 0 and quiet[i - 1]:
        i -= 1
    return min(n_frames / rate, (i + 8) * 0.02)  # keep 0.16 s of the gap as natural decay


def trim(dur: list[float], fast: list[bool], a: int, b: int, excess: float):
    """Shorten dur[a:b] by up to `excess` seconds: first static frames (≥0.5 s: holds, idle waits,
    kept ≥0.25 s), then fast-forwarded waits (up to 3× more, i.e. 24×), then the rest (up to 1.5×)."""
    tiers = [([i for i in range(a, b) if dur[i] >= 0.5], lambda d: 0.25),
             ([i for i in range(a, b) if fast[i] and dur[i] < 0.5], lambda d: d / 3),
             ([i for i in range(a, b) if not fast[i] and dur[i] < 0.5], lambda d: d / 1.5)]
    for idx, floor in tiers:
        if excess <= 0:
            return
        lo = {i: floor(dur[i]) for i in idx}
        room = sum(dur[i] - lo[i] for i in idx)
        if room <= 0:
            continue
        k = min(1.0, excess / room)
        for i in idx:
            dur[i] -= (dur[i] - lo[i]) * k
        excess -= room * k


# ---------------------------------------------------------------- capture

class Capture:
    """CDP screencast → JPEG files with wall-clock timestamps; marks for narration and cuts."""

    def __init__(self, out: Path):
        self.dir = out / "frames"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.frames: list[dict] = []
        self.marks: list[dict] = []
        self.on = False
        self.fast = False
        self.cdp = None

    async def attach(self, page: Page):
        self.cdp = await page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88,
                                                     "maxWidth": 1920, "maxHeight": 1080})

    def _frame(self, p):
        asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))
        if not self.on:
            return
        ts = p["metadata"].get("timestamp") or time.time()
        if self.frames and ts - self.frames[-1]["ts"] < (FAST if self.fast else 1) / FPS:
            return
        f = self.dir / f"{len(self.frames):06d}.jpg"
        f.write_bytes(base64.b64decode(p["data"]))
        self.frames.append({"f": f.name, "ts": ts, "fast": self.fast})

    def mark(self, n: str):
        self.marks.append({"kind": "n", "id": n, "ts": time.time()})
        say("mark", n)

    def resume(self):
        self.on = True

    def pause(self):
        if self.on:
            self.marks.append({"kind": "cut", "ts": time.time()})
        self.on = False

    def save(self, out: Path):
        (out / "timeline.json").write_text(json.dumps({"frames": self.frames, "marks": self.marks}))


# ---------------------------------------------------------------- driver

class Demo:
    def __init__(self, page: Page, cap: Capture, base: str, msg: dict[str, str]):
        self.p, self.cap, self.base, self.msg = page, cap, base, msg
        self.http = httpx.AsyncClient(base_url=base, timeout=60)
        self.cur = ""  # section label, re-applied after each navigation
        self.iids: list[int] = []

    # -- page helpers
    async def go(self, path: str, wait: str | None = None):
        await self.p.goto(self.base + path)
        if wait:
            await self.p.wait_for_selector(wait, timeout=60000)
        await self.p.wait_for_function("() => window.__rec && document.getElementById('rec-ov')")
        await self.label(self.cur)
        await self.hold(0.8)

    async def js(self, expr: str, arg=None):
        return await self.p.evaluate(expr, arg)

    async def label(self, text: str):
        self.cur = text
        await self.js("t => window.__rec.label(t)", text)

    async def set_fast(self, on: bool):
        if self.cap.fast != on:
            self.cap.fast = on
            await self.js("on => window.__rec.fast(on)", on)

    async def hold(self, s: float):
        await self.p.wait_for_timeout(int(s * 1000))

    async def point(self, sel, pause=0.5):
        loc = self.p.locator(sel).last if isinstance(sel, str) else sel
        await loc.scroll_into_view_if_needed()
        b = await loc.bounding_box()
        if b:
            await self.js("([x, y]) => window.__rec.move(x, y)", [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2])
            await self.hold(0.7 + pause)
        return loc

    async def click(self, sel, pause=0.4):
        loc = await self.point(sel, pause)
        await loc.click()
        return loc

    async def spot(self, loc, s=2.5):
        loc = self.p.locator(loc).first if isinstance(loc, str) else loc
        await loc.scroll_into_view_if_needed()
        await loc.evaluate("e => e.classList.add('rec-spot')")
        await self.hold(s)
        await loc.evaluate("e => e.classList.remove('rec-spot')")

    async def screen(self, h: str | None):
        await self.js("h => window.__rec.screen(h)", h)

    # -- assistant turns (busy while #send is disabled)
    async def turn(self, trigger, timeout=180):
        n0 = await self.js("() => document.querySelectorAll('#log .turn.assistant:not(#typing)').length")
        await trigger()
        t0 = time.time()
        while not await self.js("() => document.getElementById('send').disabled"):
            if time.time() - t0 > 8:
                break
            await self.hold(0.1)
        while await self.js("() => document.getElementById('send').disabled"):
            if time.time() - t0 > FAST_AFTER:
                await self.set_fast(True)
            if time.time() - t0 > timeout:
                raise TimeoutError("assistant reply timed out")
            await self.hold(0.25)
        await self.set_fast(False)
        await self.hold(1.2)  # smooth scroll to the answer
        n1 = await self.js("() => document.querySelectorAll('#log .turn.assistant:not(#typing)').length")
        last = self.p.locator("#log .turn.assistant").last
        say("  reply:", (await last.locator(".bub").inner_text())[:140].replace("\n", " / ") if n1 > n0 else "(none)")
        return last

    async def send(self, text: str):
        async def go():
            await self.click("#msg", 0.2)
            await self.p.keyboard.type(text, delay=45)
            await self.hold(0.5)
            await self.p.keyboard.press("Enter")
        say("send:", text)
        return await self.turn(go)

    async def chip(self, text: str):
        say("chip:", text)
        return await self.turn(lambda: self.click(self.p.locator("#chips .chip", has_text=text).first, 0.6))

    async def uid(self) -> str:
        return await self.js("() => Me.id()")

    async def inquiries(self) -> list[dict]:
        return (await self.http.get("/api/inquiries", params={"client": await self.uid()})).json()

    async def seller_reply(self, iid: int, shop: int, in_stock: bool, n: str | None = None):
        """Answer one inquiry in the demo seller panel (/seller?shop=…), on camera."""
        await self.go(f"/seller?shop={shop}", f'.inq[data-id="{iid}"] .reply')
        card = self.p.locator(f'.inq[data-id="{iid}"]')
        await self.spot(card.locator(".bubble"), 1.5)
        if n:
            self.cap.mark(n)
        if not in_stock:
            await self.click(card.locator('[data-stock="0"]'), 0.6)
        else:
            await self.point(card.locator('[data-stock="1"]'), 0.6)
        await self.click(card.locator('.reply [type=submit]'), 0.4)
        await self.p.wait_for_selector(f'.inq.done[data-id="{iid}"]', timeout=20000)
        await self.hold(1.5)

    # ---------------------------------------------------------- scenes

    async def s_hook(self):
        await self.go(f"/?at={NIGHT}", "#chips .chip")
        await self.label("")
        await self.js("() => window.__rec.top(false)")
        await self.screen(title_card())
        self.cap.resume()
        self.cap.mark("N0")
        await self.hold(5)
        await self.js("() => window.__rec.top(true)")
        await self.screen(None)
        self.cap.mark("N1")
        await self.point("#locChip", 2.5)
        await self.point("#chips .chip", 1.5)

    async def s_rescue(self):
        await self.label("بسته بود؟ جایگزین فوری")
        await self.chip(self.msg["charger"])
        self.cap.mark("N2")
        await self.spot(".rescue .rhead", 1.5)
        if await self.p.locator(".rescue .scard").count():
            await self.spot(".rescue .scard", 3)
        self.cap.mark("N3")
        for sel in (".rescue .hub", ".rescue .calls", ".rescue p.muted:last-child"):
            if await self.p.locator(sel).count():
                await self.spot(sel, 2.5)
        await self.hold(1)

    async def s_model(self):
        # a normal day: new clock, fresh conversation
        await self.js("() => localStorage.removeItem('chat')")
        await self.go(f"/?at={DAY}", "#chips .chip")
        await self.label("کدام مدل؟ مقایسه با دلیل")
        self.cap.mark("N4")
        turn = await self.send(self.msg["model"])
        if not await turn.locator('.card.link[href^="/compare"]').count() and \
                await self.p.locator("#chips .chip", has_text="مقایسه").count():
            turn = await self.chip("مقایسه")
        self.cap.mark("N5")
        for c in (await turn.locator(".pcard").all())[:2]:
            await self.spot(c, 2.5)
        cmp = turn.locator('.card.link[href^="/compare"]')
        if not await cmp.count():
            say("  ⚠ no compare card")
            return
        self.cap.mark("N6")
        await self.click(cmp.first, 0.8)
        await self.p.wait_for_load_state()
        await self.go(self.p.url.removeprefix(self.base), "table, .card")
        await self.hold(2.5)
        await self.p.mouse.wheel(0, 500)
        await self.hold(3)
        await self.p.go_back()
        await self.p.wait_for_selector("#log .turn", timeout=30000)
        await self.label(self.cur)
        await self.hold(0.8)

    async def s_sellers(self):
        await self.label("فروشنده‌ی نزدیک · اقساط · فیلتر زنده")
        self.cap.mark("N7")
        turn = await self.send(self.msg["sellers"])
        if await turn.locator(".fbar").count():
            self.cap.mark("N8")
            await self.spot(turn.locator(".fbar"), 2)
            for t in ("تا ۵ کیلومتر", "همه‌جا"):
                fx = self.p.locator("#log .turn.assistant").last.locator(".fbar .fx", has_text=t)
                if await fx.count():
                    await self.click(fx.first, 0.5)
                    await self.p.wait_for_function("() => !document.querySelector('.fbar.busy')", timeout=30000)
                    await self.hold(2.5)
        else:
            say("  ⚠ no filter bar")
        turn = self.p.locator("#log .turn.assistant").last
        if not await turn.locator(".verdict").count():
            say("  ⚠ no verdict")
            return
        self.cap.mark("N9")
        await self.spot(turn.locator(".verdict"), 3.5)
        more = turn.locator("details.more")
        if await more.count():
            await self.click(more.locator("summary"), 0.4)
            await self.hold(0.6)
            await self.spot(more.locator(".where").first, 3)

    async def s_ask(self):
        await self.label("پرسیدن و پیگیری")
        turn = self.p.locator("#log .turn.assistant").last
        await (await self.point(turn.locator(".verdict .pick").first, 0.3)).scroll_into_view_if_needed()
        self.cap.mark("N10")
        await self.click(turn.locator(".verdict .pick .ask").first, 0.6)
        await self.p.wait_for_selector("#askSheet[open] #askMsg")
        await self.js("() => window.__rec.host()")
        await self.spot("#askMsg", 3)
        await self.click("#askSend", 0.6)
        await self.p.wait_for_selector(".sent a[href='/followups']", timeout=20000)
        await self.hold(1.2)
        await self.click(".sent a[href='/followups']", 0.4)
        await self.p.wait_for_url("**/followups", timeout=20000)
        await self.go(f"/followups?at={DAY}", ".fu")
        self.cap.mark("N11")
        await self.spot(".fu", 3)
        q1 = (await self.inquiries())[0]
        self.iids.append(q1["id"])
        say("  inquiry", q1["id"], "shop", q1["shop_id"], q1["shop_name"])

        await self.seller_reply(q1["id"], q1["shop_id"], in_stock=False, n="N12")
        await self.go(f"/followups?at={DAY}", f'.fu[data-id="{q1["id"]}"] .alts')
        alts = f'#alts{q1["id"]}'
        try:
            await self.p.wait_for_selector(f"{alts} .alt, {alts} p.muted:not(:first-child)", timeout=30000)
        except Exception:
            pass
        self.cap.mark("N13")
        await self.spot(alts, 3)
        alt = self.p.locator(f"{alts} .alt [data-alt]")
        if not await alt.count():
            say("  ⚠ no alternatives for this product — the plan scene needs another product")
            return
        await self.click(alt.first, 0.6)
        await self.p.wait_for_selector("#askSheet[open] #askSend")
        await self.js("() => window.__rec.host()")
        await self.hold(1.5)
        await self.click("#askSend", 0.5)
        await self.p.wait_for_selector(".sent", timeout=20000)
        await self.hold(1.2)
        q2 = next(q for q in await self.inquiries() if q["id"] not in self.iids)
        self.iids.append(q2["id"])
        say("  inquiry", q2["id"], "shop", q2["shop_id"], q2["shop_name"])

        await self.seller_reply(q2["id"], q2["shop_id"], in_stock=True)
        await self.go(f"/followups?at={DAY}", ".fu")
        try:
            await self.p.wait_for_selector("#plan:not([hidden]) .stop", timeout=30000)
        except Exception:
            say("  ⚠ no visit plan")
            return
        self.cap.mark("N14")
        await self.spot("#plan", 3)
        lost = self.p.locator("#plan details.lost").first
        if await lost.count():
            await self.click(lost.locator("summary"), 0.4)
            await self.hold(0.6)
            await self.spot(lost, 3.5)

    async def s_end(self):
        await self.label("چطور کار می‌کند")
        self.cap.mark("N15")
        await self.js("() => window.__rec.top(false)")
        await self.screen(tech_card())
        await self.hold(3)
        await self.label("")
        self.cap.mark("N16")
        await self.js("() => window.__rec.top(false)")
        await self.screen(title_card(final=True))
        await self.hold(5)


def tech_card() -> str:
    """How-it-works card for N15: what the agent does and why its answers can be trusted."""
    rows = ["ایجنت LLM با فراخوانی ابزار", "کارت‌ها فقط از ردیف واقعی دیتاست",
            "Generative UI: سؤال، جمع‌بندی، فیلتر", "فیلتر زنده بدون LLM، فوری",
            "جستجوی فارسی SQLite FTS5", "زمان رسیدن از Neshan",
            "پاساژ/طبقه/واحد از متن نشانی", "دیپلوی‌شده با Docker، تست و سقف هزینه"]
    return ('<div class="rec-title"><div class="in"><h1 style="font-size:54px">چطور کار می‌کند</h1>'
            '<ul style="font-size:24px;gap:12px 48px">' + "".join(f"<li>✓ {r}</li>" for r in rows) + "</ul></div></div>")


def title_card(final: bool = False) -> str:
    """Opening / closing card: product, event, challenge, author."""
    ticks = ("<ul><li>✓ پیدا کردن و مقایسه‌ی مدل</li><li>✓ فروشنده‌ی نزدیک و باز</li>"
             "<li>✓ اقساط و نشانی دقیق پاساژ</li><li>✓ پرسیدن، پیگیری و جایگزین</li></ul>") if final else ""
    return ('<div class="rec-title"><div class="in">'
            '<div class="tag">هکاتون <b>Agentic AI</b> · چالش ترب</div>'
            '<div class="mark"><img src="/static/radish.svg" alt=""></div><h1>تربچه</h1>'
            '<p class="sub">دستیار خرید حضوری از مغازه‌ها و پاساژهای تهران</p>'
            f'{ticks}<div class="rule"></div>'
            f'<div class="by"><small>{"ساخته‌ی" if final else "ارائه از"}</small>کیوان رشادی‌پور</div>'
            f'<div class="url">{SITE.removeprefix("https://")}</div></div></div>')


# ---------------------------------------------------------------- assembly

def fmt(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:04.1f}"


def srt_t(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def assemble(out: Path):
    tl = json.loads((out / "timeline.json").read_text())
    frames, marks = tl["frames"], tl["marks"]
    if not frames:
        sys.exit("no frames captured")
    cuts = sorted(m["ts"] for m in marks if m["kind"] == "cut")
    dur = []
    for i, f in enumerate(frames):
        nxt = frames[i + 1]["ts"] if i + 1 < len(frames) else next((c for c in cuts if c > f["ts"]), f["ts"] + 2)
        cut = next((c for c in cuts if f["ts"] <= c < nxt), None)  # don't stretch across a pause
        d = (cut if cut is not None else nxt) - f["ts"]
        dur.append(max(d / (FAST if f["fast"] else 1), 1 / FPS))
    fast = [f["fast"] for f in frames]
    texts = narration()
    ns = [m for m in marks if m["kind"] == "n"]
    idx = [next((i for i, f in enumerate(frames) if f["ts"] >= m["ts"]), len(frames) - 1) for m in ns]
    voice = {m["id"]: voice_len(out, m["id"]) for m in ns}
    want = {m["id"]: (v + LEAD + TAIL) if (v := voice[m["id"]]) else need(texts.get(m["id"], "")) for m in ns}
    want = {k: max(v, MIN_HOLD.get(k, 0)) for k, v in want.items()}
    for k, m in enumerate(ns):  # fit each block to its narration: hold the last frame, or trim idle holds
        end = idx[k + 1] if k + 1 < len(ns) else len(frames)
        span = sum(dur[idx[k]:end])
        if span < want[m["id"]] and end > idx[k]:
            extra = want[m["id"]] - span
            body = sum(dur[idx[k]:end - 1])
            if m["id"] in SPREAD and body > 0:
                last = max(0.0, min(extra, SPREAD[m["id"]] - dur[end - 1]))
                dur[end - 1] += last
                for i in range(idx[k], end - 1):
                    dur[i] *= 1 + (extra - last) / body
            else:
                dur[end - 1] += extra
        elif voice[m["id"]]:
            trim(dur, fast, idx[k], end, span - want[m["id"]] - SLACK)
    starts = [sum(dur[:i]) for i in idx]
    total = sum(dur)

    lst = out / "frames.txt"
    with lst.open("w") as fh:
        fh.write("ffconcat version 1.0\n")
        # the concat demuxer's timebase is 1/25 s and it bumps shorter frames to a full tick, which
        # stretched the video; snap cumulative times to that grid and drop frames that get 0 ticks
        t, at = 0.0, 0
        for f, d in zip(frames, dur):
            t += d
            ticks = round(t * 25) - at
            if ticks > 0:
                fh.write(f"file 'frames/{f['f']}'\nduration {ticks / 25:.2f}\n")
                at += ticks
        fh.write(f"file 'frames/{frames[-1]['f']}'\n")
    say(f"assembling {len(frames)} frames, {fmt(total)}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", f"fps={FPS},scale=1920:1080:flags=lanczos,format=yuv420p",
                    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart",
                    "-t", f"{total:.3f}",  # fps= pads the last frame past the demuxer's EOF otherwise
                    str(out / "video.mp4")], check=True)
    clips = [(starts[k] + LEAD, out / "voice" / f"{m['id']}.wav") for k, m in enumerate(ns) if voice[m["id"]]]
    if clips:  # mix the TTS clips in at their block starts
        ins = sum((["-i", str(f)] for _, f in clips), [])
        fl = "".join(f"[{i + 1}:a]atrim=end={voice_len(out, f.stem):.3f},afade=t=out:st={voice_len(out, f.stem) - 0.05:.3f}:d=0.05,"
                     f"adelay={int(t * 1000)}:all=1[a{i}];" for i, (t, f) in enumerate(clips))
        fl += "".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad[aout]"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "video.mp4"), *ins,
                        "-filter_complex", fl, "-map", "0:v", "-map", "[aout]", "-shortest",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
                        str(out / "demo.mp4")], check=True)
    else:
        (out / "video.mp4").replace(out / "demo.mp4")

    rows, srt = [], []
    for k, m in enumerate(ns):
        end = starts[k + 1] if k + 1 < len(ns) else total
        t = texts.get(m["id"], "")
        rows.append(f"| {m['id']} | {fmt(starts[k])} | {end - starts[k]:.1f} s | {want[m['id']]:.1f} s | {t} |")
        srt.append(f"{k + 1}\n{srt_t(starts[k])} --> {srt_t(min(end, starts[k] + want[m['id']]))}\n{m['id']} — {t}\n")
    (out / "timing.md").write_text(
        '<div dir="rtl">\n\n# برگه‌ی زمان‌بندی گفتار\n\n'
        f"طول کل ویدیو: **{fmt(total)}**\n\n| بند | شروع | فرصت | زمان تخمینی خواندن | متن |\n|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n\n</div>\n")
    (out / "narration.srt").write_text("\n".join(srt))
    missing = sorted(set(texts) - {m["id"] for m in ns}, key=lambda n: int(n[1:]))
    say(f"done: {out / 'demo.mp4'}  total {fmt(total)}" + ("  ⚠ over 5:00" if total > 300 else "")
        + (f"  ⚠ blocks not reached: {','.join(missing)}" if missing else ""))
    print("\n".join(rows))


# ---------------------------------------------------------------- main

async def record(out: Path, base: str, steps: list[str], msg: dict[str, str], headed: bool):
    try:
        h = httpx.get(base + "/health", timeout=30).json()
    except httpx.HTTPError as e:
        sys.exit(f"{base} is not reachable: {e}")
    if not h.get("db"):
        sys.exit(f"{base}/health: no catalog db")
    cap = Capture(out)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        ctx = await browser.new_context(viewport=VIEW, device_scale_factor=SCALE, color_scheme="light",
                                        locale="fa-IR", timezone_id="Asia/Tehran")
        await ctx.add_init_script(OVERLAY_JS)
        await ctx.add_init_script(f"try {{ localStorage.setItem('loc', {json.dumps(json.dumps(LOC, ensure_ascii=False))}); }} catch {{}}")
        page = await ctx.new_page()
        d = Demo(page, cap, base, msg)
        await d.go("/", "#chips .chip")
        await cap.attach(page)
        try:
            for s in steps:
                say("== step", s)
                if s != "hook":
                    cap.resume()
                await getattr(d, f"s_{s}")()
        except BaseException:
            cap.save(out)
            raise
        finally:
            cap.pause()
            await d.http.aclose()
            await browser.close()
    cap.save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=SITE, help="app URL (default: production)")
    ap.add_argument("--only", help="comma-separated steps: " + ",".join(STEPS))
    ap.add_argument("--out", default=str(ROOT / "out/demo"))
    ap.add_argument("--assemble", action="store_true", help="only rebuild the MP4 from the last capture")
    ap.add_argument("--rules", action="store_true", help="questions the offline keyword assistant understands")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not a.assemble:
        steps = a.only.split(",") if a.only else STEPS
        bad = [s for s in steps if s not in STEPS]
        if bad:
            sys.exit(f"unknown steps: {bad}")
        msg = {**MSG, **RULES_MSG} if a.rules else MSG
        asyncio.run(record(out, a.base.rstrip("/"), steps, msg, a.headed))
    assemble(out)


if __name__ == "__main__":
    main()
