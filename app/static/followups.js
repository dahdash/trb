// Step 4: the follow-up list. Each question waits for the shop (seller panel) or for the user to record the call;
// a bad answer (closed, no answer, no stock, other price) brings up the next best shops for the same product.
const $ = (id) => document.getElementById(id);
const STATE = {
  null: ["wait", "منتظر جواب"], ok: ["ok", "تأیید شد"], price_diff: ["bad", "قیمت فرق دارد"],
  no_stock: ["bad", "موجود نیست"], no_answer: ["bad", "جواب نداد"], closed: ["bad", "بسته بود"],
};
const OUTS = [["ok", "موجود است، قیمت درست"], ["price_diff", "قیمت فرق داشت"], ["no_stock", "موجود نبود"], ["no_answer", "جواب نداد"], ["closed", "بسته بود"]];
let items = [], last = "", alts = {}, timer;

const ago = (iso) => {
  const m = Math.round((Date.now() - Date.parse(iso)) / 6e4);
  return m < 1 ? "همین حالا" : m < 60 ? `${faNum(m)} دقیقه پیش` : m < 1440 ? `${faNum(Math.round(m / 60))} ساعت پیش` : `${faNum(Math.round(m / 1440))} روز پیش`;
};
const navi = (q) => `https://neshan.org/maps/@${q.lat},${q.lon},17z,0p`;

async function load() {
  let d;
  try { d = await (await fetch(`/api/inquiries?client=${Me.id()}`)).json(); }
  catch { $("status").textContent = "فهرست بارگیری نشد؛ اتصال را بررسی کن."; return; }
  const sig = JSON.stringify(d);
  if (sig !== last) { last = sig; items = d; render(); document.dispatchEvent(new Event("fu-changed")); }
  clearTimeout(timer);
  // The seller panel answers from another device; poll while something is still waiting.
  if (items.some((q) => !q.outcome)) timer = setTimeout(load, 5000);
}

function render() {
  if (!items.length) {
    $("status").textContent = "";
    $("list").innerHTML = `<div class="card empty"><b>هنوز از فروشنده‌ای چیزی نپرسیده‌ای.</b>
      <p class="muted small">روی کارت فروشنده «پرسیدن از فروشنده» را بزن.</p>
      <a class="btn" href="/">از دستیار بپرس</a></div>`;
    return;
  }
  const wait = items.filter((q) => !q.outcome).length;
  $("status").textContent = wait ? `${faNum(wait)} پیگیری منتظر جواب است؛ جواب فروشنده خودکار اینجا می‌آید.` : "";
  $("list").innerHTML = items.map(card).join("");
  items.filter((q) => q.bad).forEach((q) => loadAlts(q));
}

function answer(q) {
  if (!q.outcome) return "";
  const rows = [];
  if (q.price) {
    const diff = q.listed_price ? Math.round((q.price / q.listed_price - 1) * 100) : 0;
    rows.push(`<div><dt>قیمت امروز</dt><dd><b>${faNum(q.price)}</b> تومان${diff ? ` <span class="${diff > 0 ? "up" : "down"}">${diff > 0 ? "+" : "−"}${faNum(Math.abs(diff))}٪ نسبت به قیمت ثبت‌شده</span>` : ""}</dd></div>`);
  }
  if (q.open_until) rows.push(`<div><dt>باز تا ساعت</dt><dd>${esc(q.open_until.replace(/^0/, "").replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]))}</dd></div>`);
  if (q.note) rows.push(`<div><dt>توضیح</dt><dd>${esc(q.note)}</dd></div>`);
  if (!rows.length && q.source !== "seller") return "";  // the status badge already says what the user recorded
  return `<div class="answer"><small class="muted">${q.source === "seller" ? "جواب فروشنده" : "نتیجه‌ای که ثبت کردی"} · ${ago(q.answered)}</small>${rows.length ? `<dl>${rows.join("")}</dl>` : ""}</div>`;
}

function card(q) {
  const [cls, label] = STATE[q.outcome] || STATE.null;
  const where = [q.passage, q.floor && `طبقه ${q.floor.replace(/^طبقه\s*/, "")}`, q.unit].filter(Boolean).map(esc).join("، ");
  return `<article class="card fu ${cls}" data-id="${q.id}">
    <div class="fhead">
      <div><h3><a class="shopl" href="/shop/${q.shop_id}">${esc(q.shop_name)}</a></h3><a class="muted small" href="/nearby?product=${q.product_id}">${esc(q.product_title)}</a></div>
      <span class="pill ${cls}">${label}</span>
    </div>
    <p class="muted small">پرسیدی ${ago(q.created)}${q.listed_price ? ` · قیمت ثبت‌شده ${faNum(q.listed_price)} تومان` : ""}</p>
    ${answer(q)}
    ${!q.outcome ? `<details class="rec"><summary>زنگ زدی؟ نتیجه را ثبت کن</summary>
      <div class="outs">${OUTS.map(([k, t]) => `<button type="button" class="chip" data-out="${k}">${t}</button>`).join("")}</div>
      <div class="pricein" hidden><input inputmode="numeric" placeholder="قیمتی که گفت (تومان)" aria-label="قیمت جدید"><button type="button" class="btn small" data-saveprice>ثبت</button></div>
    </details>` : ""}
    ${q.outcome === "ok" || q.outcome === "price_diff" ? `<div class="go">${where ? `<p class="small"><b>${where}</b></p>` : ""}
      <div class="actions"><a class="btn" href="${navi(q)}" target="_blank" rel="noopener">مسیریابی با نشان</a>${q.phone ? `<a class="btn ghost" href="tel:${latin(q.phone)}">تماس</a>` : ""}</div></div>` : ""}
    ${q.bad ? `<div class="alts" id="alts${q.id}"><h3>${q.outcome === "price_diff" ? "ارزان‌تر از قیمت امروزش:" : "به جایش از این‌ها بپرس:"}</h3><p class="muted small">در حال پیدا کردن…</p></div>` : ""}
  </article>`;
}

async function loadAlts(q) {
  const loc = Loc.get(), box = $(`alts${q.id}`);
  if (!alts[q.id]) {
    const u = new URLSearchParams({ client: Me.id() }), at = new URLSearchParams(location.search).get("at");
    if (at) u.set("at", at);  // demo clock, as on the chat page
    if (loc) { u.set("lat", loc.lat); u.set("lon", loc.lon); }
    try { alts[q.id] = await (await fetch(`/api/inquiries/${q.id}/alternatives?${u}`)).json(); } catch { alts[q.id] = []; }
  }
  const list = alts[q.id];
  if (!box) return;
  box.querySelector("p").outerHTML = list.length ? `<div class="altlist">${list.map((s) => `<div class="alt">
      <div><b>${esc(s.name)}</b><small class="muted">${faNum(s.price)} تومان${s.quoted ? " (قیمتی که خودش گفت)" : ""}${s.eta_min != null ? ` · ${s.eta_src === "estimate" ? "حدود " : ""}${faNum(s.eta_min)} دقیقه` : ""} · ${s.hours.state === "open" ? "الان باز" : "ساعت نامعلوم"}</small></div>
      <button type="button" class="btn small" data-alt="${q.id}:${s.shop_id}">پرسیدن</button></div>`).join("")}</div>`
    : q.outcome === "price_diff" ? `<p class="muted small">با قیمت جدید هم، بین فروشنده‌های باز اطراف ارزان‌ترین همین است. <a href="/nearby?product=${q.product_id}">همه‌ی فروشنده‌ها</a></p>`
    : `<p class="muted small">فروشنده‌ی دیگری با قیمت قابل‌اعتماد پیدا نشد. <a href="/nearby?product=${q.product_id}">همه‌ی فروشنده‌ها</a></p>`;
}

async function record(q, outcome, price) {
  await fetch(`/api/inquiries/${q.id}/outcome`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client: Me.id(), outcome, price: price || null }),
  });
  load();
}

$("list").addEventListener("click", (e) => {
  const t = e.target.closest("button"); if (!t) return;
  const el = t.closest(".fu"), q = items.find((x) => x.id === +el?.dataset.id);
  if (t.dataset.out === "price_diff") { el.querySelector(".pricein").hidden = false; el.querySelector(".pricein input").focus(); }
  else if (t.dataset.out) record(q, t.dataset.out);
  else if (t.dataset.saveprice !== undefined) {
    const v = parseInt(latin(el.querySelector(".pricein input").value).replace(/\D/g, ""), 10);
    if (v) record(q, "price_diff", v);
  } else if (t.dataset.alt) {
    const [iid, sid] = t.dataset.alt.split(":").map(Number);
    const s = alts[iid].find((x) => x.shop_id === sid), src = items.find((x) => x.id === iid);
    Contact.open(s, { id: src.product_id, title: src.product_title });
  }
});
document.addEventListener("loc", () => { alts = {}; render(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
load();
