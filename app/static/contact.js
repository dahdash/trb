// Step 4: ask a shop before going. Builds the message / call script from what the user wants to confirm,
// sends it to the (simulated) seller panel or hands it to SMS / phone, and adds it to the follow-up list.
const Me = {
  id() {
    let v; try { v = localStorage.getItem("uid"); } catch {}
    if (!v) { v = (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`.replace(".", "")).replace(/[^A-Za-z0-9-]/g, ""); try { localStorage.setItem("uid", v); } catch {} }
    return v;
  },
};
const latin = (s) => String(s ?? "").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));

const ASKS = [
  ["stock", "موجودی", "الان موجود است؟"],
  ["price", "قیمت امروز", "قیمت امروزش چند است؟"],
  ["hours", "ساعت کاری", "امروز تا چه ساعتی باز هستید؟"],
  ["pay", "اقساط حضوری", null],
  ["warranty", "گارانتی", "گارانتی‌اش چیست و چند ماه است؟"],
  ["where", "آدرس دقیق", "آدرس دقیق مغازه (طبقه و واحد) کجاست؟"],
];

const Contact = {
  s: null, p: null, edited: false, sent: null,
  el() {
    let d = document.getElementById("askSheet");
    if (d) return d;
    d = document.createElement("dialog");
    d.className = "sheet"; d.id = "askSheet"; d.setAttribute("aria-labelledby", "askTitle");
    d.innerHTML = `<form method="dialog" class="sheet-head"><h2 id="askTitle"></h2>
        <button class="ghost icon" value="close" aria-label="بستن"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></form>
      <div id="askBody"></div>`;
    document.body.append(d);
    d.addEventListener("click", Contact.click);
    d.addEventListener("input", (e) => { if (e.target.id === "askMsg") Contact.edited = true; });
    return d;
  },
  // s: a seller row from /api/nearby (or alternatives); p: {id, title}
  open(s, p) {
    Object.assign(Contact, { s, p, edited: false, sent: null });
    const d = Contact.el();
    document.getElementById("askTitle").textContent = `پرسیدن از ${s.name}`;
    const on = new Set(["stock", "price"]);
    if (s.hours.state !== "open") on.add("hours");
    if (s.payments.length) on.add("pay");
    if (!s.passage) on.add("where");
    const phone = latin(s.phone || "");
    document.getElementById("askBody").innerHTML = `
      <p class="muted small">${esc(p.title)}</p>
      <h3>چه چیزی را بپرسیم؟</h3>
      <div class="asks">${ASKS.map(([k, label]) => `<button type="button" class="chip ${on.has(k) ? "on" : ""}" data-ask="${k}" aria-pressed="${on.has(k)}">${label}</button>`).join("")}</div>
      <h3>متن پیام <small class="muted">— همین را پشت تلفن هم بپرس</small></h3>
      <textarea id="askMsg" class="msg" rows="7"></textarea>
      <button type="button" class="btn wide" id="askSend"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12 20 4l-6 16-3-7z"/></svg>ارسال به فروشنده</button>
      <div class="askalt">
        <a class="btn ghost" id="askSms" href="sms:${phone}">پیامک</a>
        <a class="btn ghost" id="askCall" href="tel:${phone}">تماس${s.phone ? ` <small dir="ltr">${esc(s.phone)}</small>` : ""}</a>
        <button type="button" class="ghost" id="askCopy">کپی متن</button>
      </div>
      <p class="muted small note">شماره‌ها نمونه‌اند؛ «ارسال» به <a href="/seller?shop=${s.shop_id}" target="_blank">پنل فروشنده‌ی آزمایشی</a> می‌رود و در «پیگیری‌ها» ثبت می‌شود.</p>`;
    Contact.write();
    d.showModal();
  },
  asks() { return [...document.querySelectorAll("#askSheet [data-ask].on")].map((c) => c.dataset.ask); },
  text() {
    const { s, p } = Contact, a = new Set(Contact.asks());
    const pays = s.payments.map((x) => x.name).join(" یا ") || "ترب‌پی، اسنپ‌پی، دیجی‌پی یا تارا";
    const qs = ASKS.filter(([k]) => a.has(k)).map(([k, , q]) => k === "pay" ? `خرید اقساطی حضوری با ${pays} دارید؟` : q);
    const listed = s.price ? ` با قیمت ${faNum(s.price)} تومان (${priceAge(s.price_at).text.replace("قیمت به‌روز شده: ", "")})` : "";
    return `سلام، وقت بخیر. در ترب دیدم «${p.title}» را${listed} ثبت کرده‌اید.\n` +
      qs.map((q, i) => `${faNum(i + 1)}. ${q}`).join("\n") + "\nممنون.";
  },
  write() { if (!Contact.edited) document.getElementById("askMsg").value = Contact.text(); Contact.links(); },
  links() {
    const body = encodeURIComponent(document.getElementById("askMsg").value);
    document.getElementById("askSms").href = `sms:${latin(Contact.s.phone || "")}?body=${body}`;
  },
  // One follow-up per opened sheet, whichever way the user reaches the shop.
  async save() {
    if (Contact.sent) return Contact.sent;
    const r = await fetch("/api/inquiries", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client: Me.id(), product_id: Contact.p.id, shop_id: Contact.s.shop_id, asks: Contact.asks(), message: document.getElementById("askMsg").value }),
    });
    if (!r.ok) throw new Error("save");
    Contact.sent = await r.json();
    fuBadge();
    return Contact.sent;
  },
  done(how) {
    document.getElementById("askBody").innerHTML = `<div class="sent">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>
      <p><b>${how}</b><br><span class="muted">جواب در «پیگیری‌ها» می‌آید؛ اگر نشد، جایگزین می‌دهیم.</span></p>
      <a class="btn wide" href="/followups">رفتن به پیگیری‌ها</a></div>`;
  },
  async click(e) {
    const t = e.target.closest("button, a");
    if (!t) return;
    if (t.dataset.ask) {
      t.classList.toggle("on"); t.setAttribute("aria-pressed", t.classList.contains("on"));
      Contact.edited = false; Contact.write();
    } else if (t.id === "askSend") {
      t.disabled = true;
      try { await Contact.save(); Contact.done("پیام برای فروشنده فرستاده شد."); }
      catch { t.disabled = false; t.textContent = "ارسال نشد؛ دوباره بزن"; }
    } else if (t.id === "askSms" || t.id === "askCall") {
      Contact.links();
      Contact.save().catch(() => {});
    } else if (t.id === "askCopy") {
      try { await navigator.clipboard.writeText(document.getElementById("askMsg").value); t.textContent = "کپی شد ✓"; } catch { document.getElementById("askMsg").select(); }
      Contact.save().catch(() => {});
    }
  },
};
