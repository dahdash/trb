// Tray chip label: the model part, e.g. "گوشی سامسونگ (ویتنام) S25 FE 5G | حافظه 256 …" → "S25 FE 5G · 256"
function shortTitle(t) {
  const [name, rest = ""] = t.split("|");
  const n = name.replace(/\([^)]*\)/g, " ").trim();
  const m = n.match(/[A-Za-z][\s\S]*$/);
  const v = rest.match(/\d+/);
  const s = (m ? m[0].trim() : n) + (m && v ? ` · ${v[0]}` : "");
  return s.length > 24 ? s.slice(0, 23) + "…" : s;
}

// Step 1: live product search with filters, plus a compare tray (max 4) kept in localStorage.
const $ = (id) => document.getElementById(id);
const S = { q: "", category: "", brand: "", min: "", max: "", offset: 0 };
const PAGE = 24;

function readUrl() {
  const u = new URLSearchParams(location.search);
  for (const k of ["q", "category", "brand", "min", "max"]) S[k] = u.get(k) || "";
  $("q").value = S.q; $("min").value = S.min; $("max").value = S.max;
}
function writeUrl() {
  const u = new URLSearchParams();
  for (const k of ["q", "category", "brand", "min", "max"]) if (S[k]) u.set(k, S[k]);
  history.replaceState(null, "", u.toString() ? `/search?${u}` : "/search");
}
const toman = (m) => m === "" ? "" : String(Math.round(parseFloat(m) * 1e6));

let ctl;
async function run(append = false) {
  if (!S.q && !S.category && !S.brand) {
    $("results").innerHTML = ""; $("status").textContent = ""; $("filters").hidden = true; $("more").hidden = true;
    $("examples").hidden = false; writeUrl(); return;
  }
  $("examples").hidden = true;
  if (!append) S.offset = 0;
  writeUrl();
  const u = new URLSearchParams({ q: S.q, limit: PAGE, offset: S.offset });
  if (S.category) u.set("category", S.category);
  if (S.brand) u.set("brand", S.brand);
  if (S.min) u.set("min", toman(S.min));
  if (S.max) u.set("max", toman(S.max));
  ctl?.abort(); ctl = new AbortController();
  $("status").textContent = "در حال جست‌وجو…";
  let d;
  try { d = await (await fetch(`/api/search?${u}`, { signal: ctl.signal })).json(); }
  catch (e) { if (e.name !== "AbortError") $("status").textContent = "خطا در جست‌وجو؛ دوباره تلاش کن."; return; }
  $("filters").hidden = false;
  renderFacets(d.facets);
  const html = d.items.map(card).join("");
  $("results").innerHTML = append ? $("results").innerHTML + html : html;
  $("status").textContent = d.total
    ? `${faNum(d.total)}${d.capped ? "+" : ""} محصول — مرتب‌شده بر اساس ارتباط و تعداد فروشنده`
    : "چیزی پیدا نشد. کلمه‌ها را کمتر کن یا فیلترها را بردار.";
  $("more").hidden = S.offset + PAGE >= d.total;
  syncTray();
}

function renderFacets(f) {
  const cats = [...f.categories];
  if (S.category && !cats.some(([c]) => c === S.category)) cats.unshift([S.category, null]);
  $("cats").innerHTML = `<button type="button" class="chip ${S.category ? "" : "on"}" data-cat="">همه دسته‌ها</button>` +
    cats.map(([c, n]) => `<button type="button" class="chip ${c === S.category ? "on" : ""}" data-cat="${esc(c)}">${esc(c)}${n ? ` <small>${faNum(n)}</small>` : ""}</button>`).join("");
  const brands = [...f.brands];
  if (S.brand && !brands.some(([b]) => b === S.brand)) brands.unshift([S.brand, null]);
  $("brand").innerHTML = `<option value="">همه</option>` +
    brands.map(([b]) => `<option ${b === S.brand ? "selected" : ""}>${esc(b)}</option>`).join("");
}

function card(p) {
  const price = p.min_price == null ? `<em class="unknown">قیمت نامشخص</em>`
    : p.max_price && p.max_price !== p.min_price
      ? `${faNum(p.min_price)} <span class="muted">تا</span> ${faNum(p.max_price)} <small>تومان</small>`
      : `${faNum(p.min_price)} <small>تومان</small>`;
  const age = priceAge(p.price_at);
  return `<article class="card pcard" data-id="${p.id}">
    <a class="thumb" href="/p/${p.id}">${p.image ? `<img src="${esc(p.image)}" alt="" loading="lazy">` : ""}</a>
    <div class="head">
      <a class="title" href="/p/${p.id}">${esc(p.title)}</a>
      <div class="meta"><span class="tag">${esc(p.category || "بدون دسته")}</span>
        <span class="tag">${faNum(p.n_shops || 0)} فروشگاه</span></div>
      <div class="ptag"><div class="price">${price}</div><div class="age ${age.cls}">${age.text}</div></div>
    </div>
    <div class="foot">
      ${p.why?.length ? `<ul class="why">${p.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div class="actions">
        <a class="btn" href="/nearby?product=${p.id}">فروشنده‌های نزدیک</a>
        <button type="button" class="ghost cmp" data-id="${p.id}" data-title="${esc(p.title)}">+ مقایسه</button>
      </div>
    </div>
  </article>`;
}

// Compare tray
const Tray = {
  get() { try { return JSON.parse(localStorage.getItem("cmp") || "[]"); } catch { return []; } },
  set(v) { try { localStorage.setItem("cmp", JSON.stringify(v)); } catch {} syncTray(); },
  toggle(id, title) {
    const t = Tray.get(), i = t.findIndex((x) => x.id === id);
    if (i >= 0) t.splice(i, 1); else if (t.length < 4) t.push({ id, title }); else return alertTray();
    Tray.set(t);
  },
};
function alertTray() { $("status").textContent = "حداکثر ۴ محصول را می‌شود مقایسه کرد؛ یکی را از سبد مقایسه بردار."; }
function syncTray() {
  const t = Tray.get();
  $("tray").hidden = !t.length;
  $("trayItems").innerHTML = t.map((x) => `<button type="button" class="chip on" data-rm="${x.id}" title="حذف">${esc(shortTitle(x.title))} ×</button>`).join("");
  $("trayGo").href = `/compare?ids=${t.map((x) => x.id).join(",")}`;
  $("trayGo").textContent = t.length > 1 ? `مقایسهٔ ${faNum(t.length)} محصول` : "یکی دیگر انتخاب کن";
  $("trayGo").classList.toggle("disabled", t.length < 2);
  document.querySelectorAll(".cmp").forEach((b) => {
    const on = t.some((x) => x.id === +b.dataset.id);
    b.textContent = on ? "✓ در مقایسه" : "+ مقایسه"; b.classList.toggle("on", on);
  });
}

let timer;
const later = () => { clearTimeout(timer); timer = setTimeout(() => run(), 350); };
document.addEventListener("DOMContentLoaded", () => {
  readUrl(); run();
  $("searchForm").addEventListener("submit", (e) => { e.preventDefault(); S.q = $("q").value.trim(); S.category = ""; S.brand = ""; run(); });
  $("q").addEventListener("input", () => { S.q = $("q").value.trim(); later(); });
  $("min").addEventListener("input", () => { S.min = $("min").value; later(); });
  $("max").addEventListener("input", () => { S.max = $("max").value; later(); });
  $("brand").addEventListener("change", () => { S.brand = $("brand").value; run(); });
  $("more").addEventListener("click", () => { S.offset += PAGE; run(true); });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button"); if (!t) return;
    if (t.dataset.q) { $("q").value = S.q = t.dataset.q; run(); }
    else if (t.dataset.cat !== undefined) { S.category = t.dataset.cat; run(); }
    else if (t.classList.contains("cmp")) Tray.toggle(+t.dataset.id, t.dataset.title);
    else if (t.dataset.rm) Tray.set(Tray.get().filter((x) => x.id !== +t.dataset.rm));
  });
  $("trayGo").addEventListener("click", (e) => { if (Tray.get().length < 2) e.preventDefault(); });
});
