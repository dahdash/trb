// Step 2: shops that list the product, around the user's location. Filters run client-side so results are live.
const $ = (id) => document.getElementById(id);
const F = { r: 3, sort: "best", open: false, pay: false };
let data = null, map = null, layer = null, markers = {};

const short = (p) => p >= 1e6 ? `${(p / 1e6).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} میلیون` : faNum(p);
const days = (s) => s.price_at ? (Date.now() - Date.parse(s.price_at)) / 864e5 : Infinity;

async function load() {
  const loc = Loc.get();
  const q = loc ? `&lat=${loc.lat}&lon=${loc.lon}` : "";
  $("status").textContent = "در حال پیدا کردن فروشنده‌ها…";
  data = await (await fetch(`/api/nearby?product=${PRODUCT}${q}`)).json();
  render();
}

function visible() {
  const loc = Loc.get();
  let s = data.sellers.slice();
  if (loc && F.r) s = s.filter((x) => x.km != null && x.km <= F.r);
  if (F.open) s = s.filter((x) => x.hours.state === "open");
  if (F.pay) s = s.filter((x) => x.payments.length);
  const big = Infinity;
  if (F.sort === "best" && loc) {
    const min = Math.min(...s.filter((x) => x.price != null && !x.price_flag).map((x) => x.price));
    s.forEach((x) => x.cost = cost(x, min));
    s.sort((a, b) => a.cost - b.cost);
  } else if (F.sort === "price" || !loc) {
    // Suspiciously low prices are probably another item; list them after the believable ones.
    const p = (x) => x.price_flag === "low" ? 1e12 + x.price : x.price ?? big;
    s.sort((a, b) => p(a) - p(b) || (a.km ?? big) - (b.km ?? big));
  }
  return s;
}

// "Our pick": each 1% above the cheapest price ≈ 1 point, each minute of driving ≈ 0.7; closed, unknown hours and stale prices cost extra.
function cost(s, min) {
  let c = s.price == null || !isFinite(min) ? 40 : s.price_flag === "low" ? 50 : (s.price / min - 1) * 100;
  c += (s.eta_min ?? (s.km != null ? s.km * 4 : 30)) * 0.7;
  c += { closed: 15, unknown: 5 }[s.hours.state] || 0;
  const d = days(s);
  c += d > 180 ? 10 : d > 30 ? 3 : 0;
  if (s.payments.some((p) => p.in_person)) c -= 2;
  return c;
}

function best(list) {
  const priced = list.filter((x) => x.price != null && !x.price_flag);
  const by = (f) => list.reduce((a, b) => (f(b) < f(a) ? b : a), list[0]);
  return {
    top: F.sort === "best" && Loc.get() ? list[0] : null,
    cheap: priced.length > 1 ? priced.reduce((a, b) => (b.price < a.price ? b : a)) : null,
    near: list.some((x) => x.km != null) ? by((x) => x.eta_min ?? x.km ?? Infinity) : null,
  };
}

function reasons(s, b) {
  const why = [];
  if (s === b.top) why.push("بهترین تعادل قیمت و زمان رسیدن در این فیلترها");
  if (s === b.cheap) why.push("ارزان‌ترین قیمت ثبت‌شده در این فهرست");
  if (s === b.near) why.push(s.eta_min != null ? "زودتر از بقیه به آن می‌رسی" : "نزدیک‌ترین فروشنده");
  if (days(s) <= 30) why.push("قیمتش در یک ماه اخیر به‌روز شده");
  if (s.payments.some((p) => p.in_person)) why.push("خرید اقساطی حضوری را اعلام کرده");
  if (s.passage && why.length < 3) why.push("داخل پاساژ است؛ طبقه و واحد بالای کارت آمده");
  return why.slice(0, 3);
}

function summary(list, b) {
  const el = $("summary");
  // One tile per shop; a shop that wins twice gets both labels.
  const rows = [];
  for (const [label, s] of [["پیشنهاد ما", b.top], ["ارزان‌ترین", b.cheap], ["زودترین", b.near]]) {
    if (!s) continue;
    const r = rows.find(([, x]) => x === s);
    if (r) r[0] += ` و ${label}`; else rows.push([label, s]);
  }
  el.hidden = list.length < 2 || !rows.length;
  el.innerHTML = rows.map(([label, s]) => `<button type="button" class="pick3" data-go="${s.shop_id}">
    <small>${label}</small><b><span class="num">${faNum(list.indexOf(s) + 1)}</span>${esc(s.name)}</b>
    <span>${s.price != null ? `${short(s.price)} تومان` : "قیمت نامعلوم"}${s.eta_min != null ? ` · ${eta(s)}` : ""}</span></button>`).join("");
}

function card(s, i, b) {
  const age = priceAge(s.price_at);
  const price = s.price == null ? `<em class="unknown">قیمت ثبت نشده</em>` : `${faNum(s.price)} <small>تومان</small>`;
  const flag = { low: "خیلی ارزان‌تر از بقیه؛ شاید مدل یا نسخه‌ی دیگری باشد", high: "خیلی گران‌تر از بقیه؛ شاید بسته یا نسخه‌ی دیگری باشد" }[s.price_flag];
  const why = reasons(s, b);
  return `<article class="card scard" id="s${s.shop_id}" data-id="${s.shop_id}">
    <div class="shead">
      <span class="num">${faNum(i + 1)}</span>
      <div><h3><a class="shopl" href="/shop/${s.shop_id}">${esc(s.name)}</a></h3><div class="meta">${s.area ? `<span class="tag">${esc(s.area)}</span>` : ""}${s.variants > 1 ? `<span class="tag">${faNum(s.variants)} مدل/رنگ</span>` : ""}</div></div>
      <span class="km">${s.eta_min != null ? `<b>${eta(s)}</b><small>${dist(s.road_km ?? s.km)} با ماشین</small>` : s.km != null ? dist(s.km) : "فاصله نامعلوم"}</span>
    </div>
    ${where(s)}
    <div class="ptag"><div class="price">${price}</div><div class="age ${age.cls}">${age.text}</div>${flag ? `<div class="age aging">⚠ ${flag}</div>` : ""}</div>
    <div class="facts">${hours(s.hours)}${pays(s.payments)}${extras(s)}</div>
    ${why.length ? `<ul class="why">${why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <div class="actions">
      <button type="button" class="btn ask" data-id="${s.shop_id}">پرسیدن از فروشنده</button>
      <a class="btn ghost" href="${naviUrl(s)}" target="_blank" rel="noopener">مسیریابی</a>
      <button type="button" class="ghost onmap" data-id="${s.shop_id}">روی نقشه</button>
    </div>
  </article>`;
}

function render() {
  const loc = Loc.get(), list = visible();
  syncChips();
  if (!loc) {
    $("status").innerHTML = `موقعیتت را نمی‌دانیم؛ فهرست به ترتیب قیمت است. <button type="button" class="linkish" id="askLoc">تعیین موقعیت</button>`;
    $("askLoc").onclick = LocSheet.open;
  } else if (!list.length) {
    // Say what actually hides the results: a filter, or a too-small radius.
    const fits = data.sellers.filter((x) => x.km != null && (!F.open || x.hours.state === "open") && (!F.pay || x.payments.length));
    const near = fits[0];
    const what = [F.open && "«الان باز»", F.pay && "«اقساطی»"].filter(Boolean).join(" و ");
    if (near) {
      const r = [1, 3, 10].find((r) => r >= near.km) || 0;
      $("status").innerHTML = `در ${faNum(F.r)} کیلومتری فروشنده‌ای${what ? ` با ${what}` : ""} نیست؛ نزدیک‌ترین در ${dist(near.km)} است. <button type="button" class="linkish" id="widen">شعاع ${r ? `${faNum(r)} کیلومتر` : "همه‌ی شهر"}</button>`;
      $("widen").onclick = () => { F.r = r; syncChips(); render(); };
    } else if (what) {
      $("status").innerHTML = `هیچ فروشنده‌ای با ${what} پیدا نشد. <button type="button" class="linkish" id="relax">برداشتن فیلتر</button>`;
      $("relax").onclick = () => { F.open = F.pay = false; syncChips(); render(); };
    } else $("status").textContent = "هیچ فروشگاهی این محصول را ثبت نکرده.";
  } else {
    $("status").textContent = `${faNum(list.length)} فروشنده${F.r ? ` تا ${faNum(F.r)} کیلومتری ${loc.label}` : ` در کل شهر`}؛ زمان با ماشین از نشان`;
  }
  const b = best(list);
  summary(list, b);
  $("results").innerHTML = list.map((s, i) => card(s, i, b)).join("");
  drawMap(list, loc);
}

async function drawMap(list, loc) {
  const L = await loadLeaflet();
  if (!map) {
    map = newMap(L, "nmap", loc ? [loc.lat, loc.lon] : TEHRAN_CENTER, 13);
  }
  layer?.remove(); layer = L.layerGroup().addTo(map); markers = {};
  const pts = [];
  if (loc) {
    L.circleMarker([loc.lat, loc.lon], { radius: 8, color: "#fff", weight: 3, fillColor: "#e03153", fillOpacity: 1 })
      .bindTooltip("تو اینجایی").addTo(layer);
    if (F.r) L.circle([loc.lat, loc.lon], { radius: F.r * 1000, color: "#3b5bdb", weight: 1, fillOpacity: .05 }).addTo(layer);
    pts.push([loc.lat, loc.lon]);
  }
  // Shops in one building (often a whole passage) share a pin: it shows the best rank and a count, and opens a list.
  const spots = new Map();
  list.slice(0, 40).forEach((s, i) => {
    if (s.lat == null) return;
    const k = `${(s.lat * 3000).toFixed()},${(s.lon * 3000).toFixed()}`;  // ≈30 m cells
    if (!spots.has(k)) spots.set(k, []);
    spots.get(k).push([s, i]);
  });
  for (const group of spots.values()) {
    const [[s, i]] = group, n = group.length;
    const cls = i < 3 ? "mpin top" : "mpin";
    const m = L.marker([s.lat, s.lon], { zIndexOffset: 1000 - i, icon: L.divIcon({ className: cls, iconSize: [30, 30], iconAnchor: [15, 30],
      html: `<span><i>${faNum(i + 1)}</i></span>${n > 1 ? `<em>${faNum(n)}</em>` : ""}` }) }).addTo(layer);
    if (n > 1) {
      m.bindPopup(`<div class="mpop"><b>${esc(s.passage || "همین ساختمان")} · ${faNum(n)} فروشنده</b>${group.map(([x, j]) =>
        `<button type="button" data-go="${x.shop_id}"><span class="num">${faNum(j + 1)}</span>${esc(x.name)}<small>${x.price != null ? short(x.price) : "—"}</small></button>`).join("")}</div>`,
        { closeButton: false, minWidth: 200 });
    } else m.on("click", () => focusCard(s.shop_id));
    group.forEach(([x]) => markers[x.shop_id] = m);
    if (i < 12) pts.push([s.lat, s.lon]);
  }
  if (pts.length > 1) map.fitBounds(pts, { padding: [28, 28], maxZoom: 16 });
  else if (pts.length) map.setView(pts[0], 15);
}

function focusCard(id) {
  const el = $(`s${id}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}
function bounce(m) {
  const el = m.getElement();
  el?.classList.remove("hop"); void el?.offsetWidth; el?.classList.add("hop");
}

function syncChips() {
  // Without a location only the price order means anything.
  const loc = Loc.get(), sort = loc ? F.sort : "price";
  document.querySelectorAll("#radius .chip").forEach((c) => { c.classList.toggle("on", +c.dataset.r === F.r); c.disabled = !loc; });
  document.querySelectorAll("[data-sort]").forEach((c) => {
    c.classList.toggle("on", c.dataset.sort === sort); c.disabled = !loc && c.dataset.sort !== "price";
  });
  $("fOpen").classList.toggle("on", F.open); $("fOpen").setAttribute("aria-pressed", F.open);
  $("fPay").classList.toggle("on", F.pay); $("fPay").setAttribute("aria-pressed", F.pay);
}

document.querySelector(".nfilters").addEventListener("click", (e) => {
  const c = e.target.closest(".chip");
  if (!c || c.disabled) return;
  if (c.dataset.r != null) F.r = +c.dataset.r;
  else if (c.dataset.sort) F.sort = c.dataset.sort;
  else if (c.id === "fOpen") F.open = !F.open;
  else if (c.id === "fPay") F.pay = !F.pay;
  syncChips(); render();
});
$("results").addEventListener("click", (e) => {
  const a = e.target.closest(".ask");
  if (a) return Contact.open(data.sellers.find((x) => x.shop_id === +a.dataset.id), data.product);
  const b = e.target.closest(".onmap");
  if (!b || !map) return;
  const m = markers[b.dataset.id];
  if (!m) return;
  $("nmap").scrollIntoView({ behavior: "smooth", block: "center" });
  map.flyTo(m.getLatLng(), 17);
  map.once("moveend", () => m.getPopup() ? m.openPopup() : bounce(m));
});
// Summary tiles and the shared-pin popup both jump to a card.
for (const el of [$("summary"), $("nmap")]) el.addEventListener("click", (e) => {
  const t = e.target.closest("[data-go]");
  if (t) { map?.closePopup(); focusCard(t.dataset.go); }
});
document.addEventListener("loc", load);
load();
