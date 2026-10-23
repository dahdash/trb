// Visit plan: the shops that confirmed (ok or a new price), one stop per shop, in the order that drives least
// and still finds each door open. Every stop has the exact passage/floor/unit and a "can't find it" helper.
const Plan = {
  async load() {
    const box = document.getElementById("plan");
    if (!items.some((q) => q.outcome === "ok" || q.outcome === "price_diff")) { box.hidden = true; return; }
    const loc = Loc.get(), u = new URLSearchParams({ client: Me.id() }), at = new URLSearchParams(location.search).get("at");
    if (at) u.set("at", at);  // demo clock, as on the chat page
    if (loc) { u.set("lat", loc.lat); u.set("lon", loc.lon); }
    let d;
    try { d = await (await fetch(`/api/plan?${u}`)).json(); } catch { return; }
    if (!d.stops.length) { box.hidden = true; return; }
    Plan.d = d; box.hidden = false; box.innerHTML = Plan.html(d, loc);
  },

  html(d, loc) {
    const n = d.stops.length, closed = d.stops.filter((s) => s.state_at_arrival === "closed").length;
    const pts = [loc && `${loc.lat},${loc.lon}`, ...d.stops.map((s) => `${s.lat},${s.lon}`)].filter(Boolean);
    return `<div class="card planhead">
      <h2>برنامه‌ی بازدید</h2>
      <p class="small">${faNum(n)} فروشگاه · حدود ${faNum(d.total_min)} دقیقه با رفت‌وآمد و خرید ·
        حرکت ${fa(d.leave)}، تمام ${fa(d.back)}</p>
      ${d.start ? `<p class="muted small">ترتیب برای کمترین رانندگی از «${esc(loc.label || "مکان تو")}» چیده شده، طوری که هر مغازه وقت رسیدن باز باشد.</p>`
        : `<p class="muted small">مکانت را مشخص کن تا مسیر از نزدیک‌ترین فروشگاه شروع شود. <button type="button" class="linkish" onclick="LocSheet.open()">انتخاب مکان</button></p>`}
      ${closed ? `<p class="warnline small">${faNum(closed)} فروشگاه وقت رسیدن احتمالاً بسته است؛ قبل از رفتن زنگ بزن یا جایگزین بگیر.</p>` : ""}
      ${n > 1 ? `<div class="actions"><a class="btn" href="https://www.google.com/maps/dir/${pts.join("/")}" target="_blank" rel="noopener">کل مسیر روی نقشه</a></div>` : ""}
    </div>
    <ol class="stops">${d.stops.map(Plan.stop).join("")}</ol>`;
  },

  stop(s, i) {
    s = { ...s, unit: fa(s.unit || ""), address: fa(s.address || ""), floor: fa(s.floor || "") };
    const floor = s.floor && `طبقه ${s.floor.replace(/^طبقه\s*/, "")}`;
    const st = { open: ["ok", "باز"], closed: ["bad", "احتمالاً بسته"], unknown: ["unknown", "ساعت نامعلوم"] }[s.state_at_arrival];
    const leg = i === 0 && !Plan.d.start ? "شروع" : s.leg_km < 0.15 ? "پیاده، چند قدم از قبلی" :
      `${faNum(s.leg_min)} دقیقه رانندگی (${faNum(s.leg_km)} کیلومتر)`;
    return `<li class="stop">
      <span class="num">${faNum(i + 1)}</span>
      <div class="card">
        <div class="fhead"><div><h3>${esc(s.shop_name)}</h3><small class="muted">${leg} · رسیدن حدود ${fa(s.arrive)}</small></div>
          <span class="pill ${st[0]}">${st[1]}</span></div>
        <div class="addr">
          ${s.passage ? `<b>${esc(s.passage)}</b>` : ""}
          ${floor || s.unit ? `<div class="fl">${floor ? `<span>${esc(floor)}</span>` : ""}${s.unit ? `<span>${esc(s.unit)}</span>` : ""}</div>` : ""}
          <small class="muted">${esc(s.address || "نشانی ثبت نشده")}</small>
        </div>
        <ul class="buy">${s.items.map((it) => `<li><a href="/nearby?product=${it.product_id}">${esc(it.title)}</a>
          <span>${it.price ? `${faNum(it.price)} تومان` : `<i class="unknown">قیمت نامعلوم</i>`}</span></li>`).join("")}</ul>
        ${s.open_until ? `<p class="muted small">فروشنده گفت امروز تا ساعت ${fa(s.open_until)} باز است.</p>` : ""}
        <div class="actions"><a class="btn" href="https://neshan.org/maps/@${s.lat},${s.lon},18z,0p" target="_blank" rel="noopener">مسیریابی با نشان</a>
          ${s.phone ? `<a class="btn ghost" href="tel:${latin(s.phone)}">تماس</a>` : ""}</div>
        ${Plan.lost(s, floor)}
      </div></li>`;
  },

  // Inside a big passage the hard part is the last 50 metres: floor, unit, which escalator.
  lost(s, floor) {
    const tips = [];
    const u = latin(s.unit || "").match(/\d+/)?.[0], f = latin(s.floor || "").match(/\d+/)?.[0];
    if (u && f && u.length >= 3 && u.startsWith(f)) tips.push(`شماره‌ی واحد (${fa(u)}) با شماره‌ی طبقه (${fa(f)}) شروع می‌شود؛ با آسانسور یا پله‌برقی مستقیم برو طبقه‌ی ${fa(f)}.`);
    else if (u && u.length >= 3) tips.push(`در بیشتر پاساژها رقم اول شماره‌ی واحد (${fa(u[0])}) طبقه را نشان می‌دهد.`);
    if (s.passage) tips.push(`تابلوی راهنمای ورودی ${esc(s.passage)} یا نگهبان پاساژ واحدها را می‌شناسد؛ شماره‌ی واحد را نشانش بده.`);
    tips.push("اگر باز پیدا نشد، با پیام زیر زنگ بزن تا فروشنده نشانه بدهد.");
    const msg = `سلام، برای خرید ${s.items[0].title} پیام داده بودم. الان ${s.passage ? `داخل ${s.passage}` : "نزدیک مغازه"} هستم${floor ? `، ${floor}` : ""}؛ ${s.unit ? `${s.unit} ` : "مغازه "}از کدام طرف است؟ کنار چه مغازه یا تابلویی هستید؟`;
    return `<details class="rec lost"><summary>مغازه را پیدا نمی‌کنی؟</summary>
      <ul class="tips">${tips.map((t) => `<li>${t}</li>`).join("")}</ul>
      <p class="script">${esc(msg)}</p>
      <div class="actions">${s.phone ? `<a class="btn small" href="tel:${latin(s.phone)}">زنگ بزن</a>` : ""}
        <button type="button" class="ghost small" data-copy="${esc(msg)}">کپی متن</button></div>
    </details>`;
  },
};
const fa = (t) => String(t ?? "").replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);

document.getElementById("plan").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]"); if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "کپی شد ✓"; } catch { /* insecure context */ }
});
document.addEventListener("fu-changed", Plan.load);
document.addEventListener("loc", Plan.load);
