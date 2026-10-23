// Step 1–4 by conversation. The server answers with text plus cards built only from real rows; the history (with the
// server's [context] memo) stays on this device.
const $ = (id) => document.getElementById(id);
const KEY = "chat";
const START = ["شارژر گوشی فوری لازم دارم", "تلویزیون اقساطی نزدیک من", "تلویزیون سامسونگ ۵۵ اینچ"];
let log = (() => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } })();
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(log.slice(-30))); } catch {} };
const sellers = {};
const AT = /^\d{1,2}:\d{2}$/.test(new URLSearchParams(location.search).get("at") || "") ? new URLSearchParams(location.search).get("at") : undefined;  // demo clock  // "pid:shop" → full seller row, for the ask sheet

function productCard(p) {
  const age = priceAge(p.price_at);
  const price = p.min_price == null ? `<em class="unknown">قیمت نامشخص</em>` : `${faNum(p.min_price)} <small>تومان</small>`;
  return `<article class="card pcard mini">
    <a class="thumb" href="/p/${p.id}">${p.image ? `<img src="${esc(p.image)}" alt="" loading="lazy">` : ""}</a>
    <div class="head">
      <a class="title" href="/p/${p.id}">${esc(p.title)}</a>
      <div class="meta"><span class="tag">${faNum(p.n_shops || 0)} فروشگاه</span></div>
      <div class="ptag"><div class="price">${price}</div><div class="age ${age.cls}">${age.text}</div></div>
    </div>
    <div class="foot"><div class="actions"><a class="btn" href="/nearby?product=${p.id}">فروشنده‌های نزدیک</a>
      <a class="ghost" href="/p/${p.id}">مشخصات</a></div></div>
  </article>`;
}

function sellerCard(s, p) {
  const key = `${p.id}:${s.shop_id}`;
  sellers[key] = [s, p];
  const age = priceAge(s.price_at);
  const price = s.price == null ? `<em class="unknown">قیمت ثبت نشده</em>` : `${faNum(s.price)} <small>تومان</small>`;
  const far = s.eta_min != null ? `<b>${eta(s)}</b><small>${dist(s.road_km ?? s.km)}</small>` : s.km != null ? dist(s.km) : "فاصله نامعلوم";
  return `<article class="card scard">
    <div class="shead"><div><h3><a class="shopl" href="/shop/${s.shop_id}">${esc(s.name)}</a></h3><div class="meta"><span class="tag">${esc(p.title.slice(0, 40))}</span></div></div>
      <span class="km">${far}</span></div>
    ${where(s)}
    <div class="ptag"><div class="price">${price}</div><div class="age ${age.cls}">${age.text}</div></div>
    <div class="facts">${hours(s.hours)}${pays(s.payments)}</div>
    <div class="actions">
      <button type="button" class="btn ask" data-k="${esc(key)}">پرسیدن از فروشنده</button>
      <a class="btn ghost" href="${naviUrl(s)}" target="_blank" rel="noopener">مسیریابی</a>
      <a class="ghost" href="/nearby?product=${p.id}">همه‌ی فروشنده‌ها</a>
    </div>
  </article>`;
}

// Generative UI: the assistant picks widgets (questions, verdict, live filters); the server fills them from real rows.
function askCard(c) {
  return `<div class="card askc">${c.groups.map((g) => `<div class="askq"><b>${esc(g.q)}</b>
    <div class="opts">${g.options.map((o) => `<button type="button" class="opt" data-send="${esc(o)}">${esc(o)}</button>`).join("")}</div></div>`).join("")}</div>`;
}

function verdictCard(c) {
  const picks = c.picks.map(({ labels, why, s }) => {
    const key = `${c.p.id}:${s.shop_id}`;
    sellers[key] = [s, c.p];
    const age = priceAge(s.price_at);
    const price = s.price == null ? `<em class="unknown">قیمت ثبت نشده</em>` : `${faNum(s.price)} <small>تومان</small>`;
    return `<div class="pick">
      <div class="badges">${labels.map((l) => `<span class="badge">${esc(l)}</span>`).join("")}</div>
      <a class="pname shopl" href="/shop/${s.shop_id}"><b>${esc(s.name)}</b></a>
      <div class="pline"><span class="price">${price}</span><span class="age ${age.cls}">${age.text}</span></div>
      <p class="why">${esc(why)}</p>
      <div class="actions"><button type="button" class="btn ask" data-k="${esc(key)}">پرسیدن</button>
        <a class="btn ghost" href="${naviUrl(s)}" target="_blank" rel="noopener">مسیریابی</a></div>
    </div>`;
  }).join("");
  return `<section class="card verdict"><h3>جمع‌بندی برای «${esc(c.p.title.slice(0, 45))}»</h3>
    <div class="picks">${picks}</div>
    ${c.located ? "" : `<p class="muted small">موقعیت را بزن تا «نزدیک‌ترین» را هم بگویم.</p>`}
    <p class="muted small">قیمت ثبت‌شده است، نه موجودی تأییدشده؛ قبل از رفتن بپرس.</p></section>`;
}

function filtersCard(c) {
  const f = c.f, chip = (k, v, label, on, dis) =>
    `<button type="button" class="chip fx${on ? " on" : ""}" data-k="${k}" data-v="${esc(JSON.stringify(v))}"${dis ? " disabled" : ""}>${label}</button>`;
  const sorts = [["best", "پیشنهاد ما"], ["price", "ارزان‌ترین"], ["near", "نزدیک‌ترین"]]
    .map(([v, l]) => chip("sort", v, l, f.sort === v, !c.located && v !== "price")).join("");
  const conds = chip("open_now", !f.open_now, "الان باز", f.open_now) + chip("installment", !f.installment, "اقساطی", f.installment)
    + c.providers.map((p) => chip("provider", f.provider === p ? null : p, esc(p), f.provider === p)).join("");
  const kms = c.kms.length ? chip("max_km", null, "همه‌جا", !f.max_km)
    + c.kms.map((k) => chip("max_km", k, `تا ${faNum(k)} کیلومتر`, f.max_km === k)).join("") : "";
  const prices = c.prices.length ? chip("max_price", null, "هر قیمتی", !f.max_price)
    + c.prices.map((v) => chip("max_price", v, `تا ${faNum(Math.round(v / 1e5) / 10)} میلیون`, f.max_price === v)).join("") : "";
  return `<section class="card fbar" data-pid="${Number(c.pid)}">
    <div class="fhead"><b>فیلتر زنده</b><span class="muted small">${faNum(c.after)} از ${faNum(c.total)} فروشنده</span></div>
    <div class="seg">${sorts}</div><div class="seg">${conds}</div>
    ${kms ? `<div class="seg">${kms}</div>` : ""}${prices ? `<div class="seg">${prices}</div>` : ""}
    ${c.after ? "" : `<p class="muted small">با این فیلترها فروشنده‌ای نماند؛ یکی را بردار.</p>`}
  </section>`;
}

// Rescue: nothing open nearby (late night, Friday). The open Torob shop even if far, a bazaar nearby that may have
// open shops Torob does not list, shops with unknown hours to call, and the earliest opening.
function rescueCard(c) {
  const o = c.open, h = c.hub;
  const head = c.need ? `ساعت ${esc(c.at)} · در ${faNum(c.near_km)} کیلومتری‌ات فروشنده‌ی بازی نیست` : `ساعت ${esc(c.at)} · نزدیکت باز است`;
  const far = (x) => x.eta_min != null ? `<b>${eta(x)}</b><small>${dist(x.road_km ?? x.km)}</small>` : dist(x.km);
  const pts = [o && [o.lat, o.lon, "۱"], h && [h.lat, h.lon, "۲"]].filter(Boolean);
  let out = `<section class="card rescue"><div class="rhead ${c.need ? "warn" : "ok"}">${head}</div>
    ${pts.length ? `<div class="rmap" data-pts="${esc(JSON.stringify(pts))}"></div>` : ""}`;
  if (o) out += `<h4><span class="num">۱</span> باز در ترب${o.closes ? ` · تا ${esc(o.closes)}` : ""}</h4>${sellerCard(o, o.p)}`;
  else out += `<p class="muted small">هیچ فروشنده‌ی «${esc(c.q)}» در ترب الان باز نیست.</p>`;
  if (h) out += `<h4><span class="num">۲</span> شاید نزدیک‌تر</h4><div class="hub">
    <div class="shead"><b>${esc(h.name)}</b><span class="km">${far(h)}</span></div>
    <p class="muted small">${faNum(h.n)} مغازه‌اش در ترب است${h.open ? `، ${faNum(h.open)} تا الان باز` : ""}. بقیه در ترب نیستند؛ ساعتشان نامعلوم.</p>
    <a class="btn ghost" href="${naviUrl(h)}" target="_blank" rel="noopener">مسیریابی</a></div>`;
  if (c.call.length) out += `<h4>ساعت نامعلوم؛ اول زنگ بزن</h4><ul class="calls">${c.call.map((s) =>
    `<li><a class="shopl" href="/shop/${s.shop_id}">${esc(s.name)}</a><small class="muted">${dist(s.km)}</small>
      ${s.phone ? `<a class="ghost" href="tel:${esc(s.phone)}">تماس</a>` : ""}</li>`).join("")}</ul>`;
  if (c.soon) out += `<p class="muted small">زودترین باز شدن: <a class="shopl" href="/shop/${c.soon.s.shop_id}">${esc(c.soon.s.name)}</a> ${esc(c.soon.when)}</p>`;
  return out + `</section>`;
}

// Mini maps in rescue cards: you, the open shop (1) and the bazaar (2).
async function rescueMaps() {
  const els = [...document.querySelectorAll(".rmap:not(.on)")];
  const me = Loc.get();
  if (!els.length) return;
  const L = await loadLeaflet();
  for (const el of els) {
    el.classList.add("on");
    const pts = JSON.parse(el.dataset.pts), m = newMap(L, el, [pts[0][0], pts[0][1]], 13);
    const all = pts.map(([a, b]) => [a, b]);
    if (me) { L.circleMarker([me.lat, me.lon], { radius: 8, color: "#fff", weight: 3, fillColor: "#e03153", fillOpacity: 1 }).addTo(m); all.push([me.lat, me.lon]); }
    for (const [a, b, n] of pts) L.marker([a, b], { icon: L.divIcon({ className: "mpin top", iconSize: [30, 30], iconAnchor: [15, 30], html: `<span><i>${n}</i></span>` }) }).addTo(m);
    m.fitBounds(all, { padding: [30, 30], maxZoom: 15 });
  }
}

function card(c) {
  if (c.type === "rescue") return rescueCard(c);
  if (c.type === "ask") return askCard(c);
  if (c.type === "verdict") return verdictCard(c);
  if (c.type === "filters") return filtersCard(c);
  if (c.type === "product") return productCard(c.p);
  if (c.type === "seller") return sellerCard(c.s, c.p);
  if (c.type === "compare") return `<a class="card link" href="/compare?ids=${c.ids.map(Number).join(",")}">
    <b>جدول مقایسه‌ی ${faNum(c.ids.length)} مدل</b><small class="muted">${c.titles.map((t) => esc(t.slice(0, 30))).join(" · ")}</small></a>`;
  if (c.type === "plan") return `<a class="card link" href="/followups"><b>برنامه‌ی بازدید: ${faNum(c.n)} فروشگاه</b>
    <small class="muted">حدود ${faNum(c.total_min)} دقیقه · مسیر روی نقشه در پیگیری‌ها</small></a>`;
  return "";
}

function bubble(m) {
  const text = esc(m.text ?? m.content).replace(/\n/g, "<br>");
  const cards = m.cards || [];
  // With a verdict, the full seller cards fold away; the verdict already has the next steps.
  const judged = new Set(cards.filter((c) => c.type === "verdict").map((c) => c.p.id));
  const folded = cards.filter((c) => c.type === "seller" && judged.has(c.p.id));
  const shown = cards.filter((c) => !folded.includes(c));
  const more = folded.length ? `<details class="more"><summary>جزئیات ${faNum(folded.length)} فروشنده‌ی اول</summary>
    <div class="cards">${folded.map(card).join("")}</div></details>` : "";
  const note = m.refiltered ? `<div class="renote">فیلتر عوض شد: ${esc(m.refiltered)}. متن بالا مربوط به پرسش اول است.</div>` : "";
  return `<div class="turn ${m.role}"><div class="bub">${text}${note}</div>${cards.length
    ? `<div class="cards">${shown.map(card).join("")}</div>${more}` : ""}</div>`;
}

// A filter chip changed: ask the server again (no LLM) and swap this product's widgets in that turn.
async function refilter(el) {
  const turn = el.closest(".turn"), i = [...$("log").children].indexOf(turn), m = log[i];
  const box = el.closest(".fbar"), pid = Number(box.dataset.pid);
  const bar = m?.cards?.find((c) => c.type === "filters" && c.pid === pid);
  if (!bar) return;
  const f = { ...bar.f, [el.dataset.k]: JSON.parse(el.dataset.v) };
  if (el.dataset.k === "provider" && f.provider) f.installment = true;
  if (el.dataset.k === "installment" && !f.installment) f.provider = null;
  const loc = Loc.get();
  box.classList.add("busy");
  try {
    const r = await fetch("/api/chat/sellers", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pid, ...f, lat: loc?.lat, lon: loc?.lon }) });
    if (!r.ok) throw 0;
    const a = await r.json();
    const mine = (c) => (c.type === "filters" && c.pid === pid) || ((c.type === "verdict" || c.type === "seller") && c.p.id === pid);
    const at = m.cards.findIndex(mine);
    let cards = a.cards;
    if (!cards.some((c) => c.type === "filters")) cards = [{ ...bar, f, after: 0 }];
    m.refiltered = a.text;
    m.cards = [...m.cards.slice(0, at).filter((c) => !mine(c)), ...cards, ...m.cards.slice(at).filter((c) => !mine(c))];
    save();
    turn.outerHTML = bubble(m);
    rescueMaps();
  } catch {
    box.classList.remove("busy");
  }
}

function render() {
  $("log").innerHTML = log.map(bubble).join("");  // empty: the #hello block greets instead
  chips(log.length ? log[log.length - 1].chips || [] : START);
  $("hello").hidden = $("plain").hidden = !!log.length;
  $("chathead").hidden = !log.length;
  rescueMaps();
}

function chips(list) {
  $("chips").innerHTML = list.map((c) => `<button type="button" class="chip">${esc(c)}</button>`).join("");
}

async function send(text) {
  text = text.trim();
  if (!text || $("send").disabled) return;
  log = log.filter((m) => !m.err);  // the last failure's notice is not part of the conversation
  log.push({ role: "user", content: text });
  $("msg").value = "";
  render();
  chips([]);
  $("log").insertAdjacentHTML("beforeend", `<div class="turn assistant" id="typing"><div class="bub muted">در حال گشتن…</div></div>`);
  $("typing").scrollIntoView({ behavior: "smooth", block: "end" });
  $("send").disabled = true;
  const loc = Loc.get();
  // The memo rides on the assistant turn so "دومی" or "ارزان‌تر" resolves on the server.
  const messages = log.slice(-10).map((m) => ({ role: m.role, content: m.role === "assistant" ? `${m.text}\n${m.memo || ""}`.slice(0, 2000) : m.content }));
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, client: Me.id(), lat: loc?.lat, lon: loc?.lon, place: loc?.label?.slice(0, 60), at: AT }) });
    const a = r.ok ? await r.json() : { text: r.status === 429 ? "کمی آهسته‌تر؛ چند ثانیه بعد دوباره بپرس." : "الان جواب نمی‌رسد؛ دوباره امتحان کن.", chips: [text] };
    log.push({ role: "assistant", ...a, err: !r.ok });
    if (r.ok) save();
    else log.splice(-2, 1);  // keep the failed question out of the history; the chip lets the user resend it
  } catch {
    log.push({ role: "assistant", text: "اتصال برقرار نشد؛ دوباره امتحان کن.", chips: [text], err: true });
    log.splice(-2, 1);
  }
  $("send").disabled = false;
  render();
  $("log").lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("form").onsubmit = (e) => { e.preventDefault(); send($("msg").value); };

// Voice input (Chrome/Android/Safari): Persian speech fills the box and sends when the speaker stops.
const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Speech) {
  const mic = $("mic"), rec = new Speech();
  rec.lang = "fa-IR"; rec.interimResults = true;
  let on = false, heard = false;
  mic.hidden = false;
  mic.onclick = () => { if (on) rec.stop(); else { try { rec.start(); } catch {} } };
  rec.onstart = () => { on = true; heard = false; mic.classList.add("rec"); $("msg").placeholder = "دارم گوش می‌دهم…"; };
  rec.onresult = (e) => {
    const r = e.results[e.results.length - 1];
    heard = true;
    $("msg").value = [...e.results].map((x) => x[0].transcript).join(" ");
    if (r.isFinal) rec.stop();
  };
  rec.onend = () => {
    on = false; mic.classList.remove("rec"); $("msg").placeholder = "مثلاً: تلویزیون اقساطی نزدیک من";
    if (heard && $("msg").value.trim()) send($("msg").value);
  };
  rec.onerror = (e) => { if (e.error === "not-allowed") { mic.hidden = true; } };
}
$("chips").onclick = (e) => { const b = e.target.closest(".chip"); if (b) send(b.textContent); };
$("log").onclick = (e) => {
  const o = e.target.closest(".opt");
  if (o) return send(o.dataset.send);
  const fx = e.target.closest(".fx");
  if (fx) return refilter(fx);
  const b = e.target.closest(".ask");
  if (b && sellers[b.dataset.k]) { const [s, p] = sellers[b.dataset.k]; Contact.open(s, { id: p.id, title: p.title }); }
};
$("reset").onclick = () => { log = []; save(); render(); $("msg").focus(); };
render();
