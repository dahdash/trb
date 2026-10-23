// Simulated seller panel (Q-007): the shop sees buyers' questions and answers stock, today's price and closing time.
const $ = (id) => document.getElementById(id);
let items = [], last = "";
const ago = (iso) => {
  const m = Math.round((Date.now() - Date.parse(iso)) / 6e4);
  return m < 1 ? "همین حالا" : m < 60 ? `${faNum(m)} دقیقه پیش` : m < 1440 ? `${faNum(Math.round(m / 60))} ساعت پیش` : `${faNum(Math.round(m / 1440))} روز پیش`;
};
const LABEL = { ok: "موجود، با همان قیمت", price_diff: "موجود، قیمت دیگر", no_stock: "موجود نیست", no_answer: "جواب نداد", closed: "بسته بود" };

async function load(force) {
  try {
    const d = await (await fetch(`/api/seller/inbox${SHOP ? `?shop=${SHOP}` : ""}`)).json();
    const sig = JSON.stringify(d);
    // Do not redraw while the seller is typing an answer.
    if (sig !== last && (force || !document.activeElement?.closest?.(".reply"))) { last = sig; items = d; render(); }
  } catch {}
}
const poll = () => load().finally(() => setTimeout(poll, 4000));

function render() {
  const open = items.filter((q) => !q.outcome).length;
  $("status").textContent = items.length ? `${faNum(open)} پیام بی‌جواب${SHOP && items[0] ? ` برای ${items[0].shop_name}` : " از همه‌ی فروشگاه‌ها"}` : "";
  $("inbox").innerHTML = items.length ? items.map(card).join("")
    : `<div class="card empty"><b>پیامی نیامده.</b><p class="muted small">از طرف خریدار «پرسیدن از فروشنده» ← «ارسال» را بزن.</p></div>`;
}

function card(q) {
  return `<article class="card inq ${q.outcome ? "done" : ""}" data-id="${q.id}">
    <div class="fhead"><div><h3>${esc(q.product_title)}</h3><small class="muted">${esc(q.shop_name)} · ${ago(q.created)}</small></div>
      ${q.outcome ? `<span class="pill ${q.bad ? "bad" : "ok"}">${LABEL[q.outcome]}</span>` : `<span class="pill wait">تازه</span>`}</div>
    <p class="bubble">${esc(q.message)}</p>
    ${q.outcome ? "" : `<form class="reply">
      <div class="seg" role="radiogroup" aria-label="موجودی">
        <button type="button" class="chip on" data-stock="1">موجود است</button>
        <button type="button" class="chip" data-stock="0">موجود نیست</button>
      </div>
      <label>قیمت امروز (تومان)<input name="price" inputmode="numeric" value="${q.listed_price ? faNum(q.listed_price) : ""}"></label>
      <label>امروز باز تا ساعت<input name="open_until" inputmode="numeric" placeholder="۲۱:۰۰" value="۲۱:۰۰"></label>
      <label>توضیح (اختیاری)<input name="note" maxlength="300" placeholder="مثلاً فقط رنگ مشکی مانده"></label>
      <button class="btn wide" type="submit">ارسال جواب</button>
    </form>`}
  </article>`;
}

$("inbox").addEventListener("click", (e) => {
  const c = e.target.closest("[data-stock]");
  if (!c) return;
  const f = c.closest("form");
  f.querySelectorAll("[data-stock]").forEach((b) => b.classList.toggle("on", b === c));
  f.price.closest("label").hidden = f.open_until.closest("label").hidden = c.dataset.stock === "0";
});
// type="time" follows the browser locale (12h "09:00 PM"); a text field keeps Farsi digits and 24h
const hhmm = (v) => {
  const m = latin(v).trim().match(/^(\d{1,2})(?:[:.٫](\d{2}))?$/);
  return m && +m[1] < 24 ? `${m[1].padStart(2, "0")}:${m[2] || "00"}` : null;
};
$("inbox").addEventListener("input", (e) => {
  if (e.target.name !== "price") return;
  const v = parseInt(latin(e.target.value).replace(/\D/g, ""), 10);
  e.target.value = v ? faNum(v) : "";
});
$("inbox").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, id = f.closest(".inq").dataset.id, stock = f.querySelector("[data-stock].on").dataset.stock === "1";
  f.querySelector("[type=submit]").disabled = true;
  await fetch(`/api/seller/inquiries/${id}/reply`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      in_stock: stock, price: stock ? parseInt(latin(f.price.value).replace(/\D/g, ""), 10) || null : null,
      open_until: stock ? hhmm(f.open_until.value) : null, note: f.note.value.trim() || null,
    }),
  });
  load(true);
});
poll();
