// Shared client state: the user's location lives in localStorage so every page can use it.
const Loc = {
  get() { try { return JSON.parse(localStorage.getItem("loc") || "null"); } catch { return null; } },
  set(v) {
    try { localStorage.setItem("loc", JSON.stringify(v)); } catch {}
    Loc.render(); document.dispatchEvent(new CustomEvent("loc", { detail: v }));
  },
  render() {
    const v = Loc.get(), chip = document.getElementById("locChip");
    if (!chip) return;
    chip.classList.toggle("set", !!v);
    document.getElementById("locLabel").textContent = v ? `موقعیت: ${v.label}` : "موقعیت: نامشخص";
  },
};
const faNum = (n) => n == null ? "" : Number(n).toLocaleString("fa-IR");
document.addEventListener("DOMContentLoaded", Loc.render);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// How old a listed price is. Old prices are flagged: the shop must confirm before the visit.
function priceAge(iso) {
  if (!iso) return { text: "تاریخ قیمت نامشخص", cls: "unknown" };
  const d = Math.floor((Date.now() - Date.parse(iso)) / 864e5);
  const t = d < 1 ? "امروز" : d < 31 ? `${faNum(d)} روز پیش` : d < 365 ? `${faNum(Math.floor(d / 30))} ماه پیش` : `${faNum(Math.floor(d / 365))} سال پیش`;
  return { text: `قیمت به‌روز شده: ${t}`, cls: d > 90 ? "stale" : d > 30 ? "aging" : "fresh" };
}

// Leaflet is loaded only on pages that show a map: Neshan's Leaflet SDK when the server has a web key (Q-009),
// plain Leaflet with OSM tiles otherwise. The SDK bundles Leaflet 1.9.4, so the rest of the code is the same.
const NESHAN_SDK = "https://static.neshan.org/sdk/leaflet/v1.9.4/neshan-sdk/v1.0.8/index";
const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min";
let leafletP;
function loadLeaflet() {
  const base = window.NESHAN_WEB_KEY ? NESHAN_SDK : LEAFLET;
  return leafletP ||= new Promise((ok, fail) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = `${base}.css`;
    const js = document.createElement("script");
    js.src = `${base}.js`;
    js.onload = () => ok(window.L); js.onerror = fail;
    document.head.append(css, js);
  });
}
function newMap(L, el, at, zoom) {
  if (window.NESHAN_WEB_KEY) {
    const t = document.documentElement.dataset.theme;
    const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const m = new L.Map(el, { key: window.NESHAN_WEB_KEY, maptype: dark ? "standard-night" : "neshan", poi: true,
      traffic: false, zoomControl: false, center: at, zoom });
    m.getContainer().classList.add("neshan");  // has its own night style; skip the OSM invert
    return m;
  }
  const m = L.map(el, { zoomControl: false }).setView(at, zoom);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
  return m;
}
const TEHRAN_CENTER = [35.7, 51.4];

// Location sheet: GPS, a tap on the map, or a neighbourhood preset.
const LocSheet = {
  open() {
    const d = document.getElementById("locSheet");
    d.showModal(); LocSheet.err("");
    const box = document.getElementById("locAreas");
    if (!box.childElementCount) fetch("/api/areas").then((r) => r.json()).then((areas) => {
      box.innerHTML = areas.map((a) => `<button type="button" class="chip" data-lat="${a.lat}" data-lon="${a.lon}" data-label="${esc(a.label)}">${esc(a.label)}<small>${faNum(a.n)}</small></button>`).join("");
    });
  },
  done(v) { Loc.set(v); document.getElementById("locSheet").close(); },
  err(t) { const e = document.getElementById("locErr"); e.textContent = t; e.hidden = !t; },
  async label(lat, lon) {
    try { const r = await (await fetch(`/api/reverse?lat=${lat}&lon=${lon}`)).json(); return r.label || "نقطه‌ی انتخابی"; }
    catch { return "نقطه‌ی انتخابی"; }
  },
  gps() {
    if (!navigator.geolocation) return LocSheet.err("مرورگر موقعیت‌یابی را پشتیبانی نمی‌کند. از نقشه یا فهرست محله‌ها انتخاب کن.");
    const b = document.getElementById("locGps"); b.disabled = true;
    navigator.geolocation.getCurrentPosition(async (p) => {
      const lat = +p.coords.latitude.toFixed(5), lon = +p.coords.longitude.toFixed(5);
      b.disabled = false;
      if (lat < 35 || lat > 36.5 || lon < 50.5 || lon > 52.5) return LocSheet.err("موقعیتت بیرون از تهران است. یک نقطه در تهران انتخاب کن.");
      LocSheet.done({ lat, lon, label: await LocSheet.label(lat, lon) });
    }, () => { b.disabled = false; LocSheet.err("دسترسی به موقعیت داده نشد. از نقشه یا فهرست محله‌ها انتخاب کن."); },
    { enableHighAccuracy: true, timeout: 10000 });
  },
  async map() {
    const el = document.getElementById("locMap"), ok = document.getElementById("locMapOk");
    el.hidden = false; ok.hidden = false;
    const L = await loadLeaflet();
    if (LocSheet.m) return LocSheet.m.invalidateSize();
    const cur = Loc.get(), at = cur ? [cur.lat, cur.lon] : TEHRAN_CENTER;
    const m = LocSheet.m = newMap(L, el, at, cur ? 15 : 12);
    const pin = L.circleMarker(at, { radius: 9, color: "#fff", weight: 3, fillColor: "#e03153", fillOpacity: 1 }).addTo(m);
    m.on("click", (e) => pin.setLatLng(e.latlng));
    ok.onclick = async () => {
      const { lat, lng } = pin.getLatLng();
      ok.disabled = true;
      LocSheet.done({ lat: +lat.toFixed(5), lon: +lng.toFixed(5), label: await LocSheet.label(lat, lng) });
      ok.disabled = false;
    };
  },
};
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("locChip")?.addEventListener("click", LocSheet.open);
  document.getElementById("locGps")?.addEventListener("click", LocSheet.gps);
  document.getElementById("locMapBtn")?.addEventListener("click", LocSheet.map);
  document.getElementById("locAreas")?.addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (c) LocSheet.done({ lat: +c.dataset.lat, lon: +c.dataset.lon, label: c.dataset.label });
  });
});

// Seller-card pieces shared by the nearby list and the assistant.
const dist = (km) => km < 1 ? `${faNum(Math.round(km * 1000 / 10) * 10)} متر` : `${(+km.toFixed(1)).toLocaleString("fa-IR")} کیلومتر`;
const eta = (s) => s.eta_min == null ? "" : `${s.eta_src === "estimate" ? "حدود " : ""}${faNum(s.eta_min)} دقیقه`;
const naviUrl = (s) => `https://neshan.org/maps/@${s.lat},${s.lon},17z,0p`;

// Known facts as chips; everything the shop did not declare goes into one "unknown" chip, so gaps stay visible but quiet.
function extras(s) {
  const unknown = [];
  let out = "";
  if (!s.payments.length) unknown.push("اقساط");
  if (s.warranty_months) out += `<span class="pay">گارانتی ${faNum(s.warranty_months)} ماه</span>`; else unknown.push("گارانتی");
  if (s.fast_delivery === true) out += `<span class="pay">ارسال سریع دارد</span>`;
  else if (s.fast_delivery === false) out += `<span class="pay none">ارسال سریع ندارد</span>`;
  else unknown.push("ارسال سریع");
  return out + (unknown.length ? `<span class="pay none">نامعلوم: ${unknown.join("، ")}</span>` : "");
}

function hours(h) {
  if (h.state === "open") return `<span class="hrs open">باز است${h.today ? ` · ${esc(h.today)}` : ""}</span>`;
  if (h.state === "closed") return `<span class="hrs closed">الان بسته${h.today && h.today !== "امروز تعطیل" ? ` · امروز ${esc(h.today)}` : " · امروز تعطیل"}</span>`;
  return `<span class="hrs unknown">ساعت کاری اعلام نشده</span>`;
}

function pays(p) {
  if (!p.length) return "";
  return p.map((x) => `<span class="pay ${x.in_person ? "inp" : ""}" title="${x.in_person ? "برای خرید حضوری اعلام شده" : "کانال پرداخت مشخص نیست"}">${esc(x.name)}${x.in_person ? " · حضوری" : ""}</span>`).join("");
}

function where(s) {
  const bits = [s.passage, s.floor && `طبقه ${s.floor.replace(/^طبقه\s*/, "")}`, s.unit].filter(Boolean);
  return bits.length ? `<div class="where"><b>${bits.map(esc).join("، ")}</b><small class="muted">${esc(s.address || "")}</small></div>`
    : `<div class="where"><small class="muted">${esc(s.address || "آدرس ثبت نشده")}</small></div>`;
}

// Header badge: follow-ups still waiting for an answer (no uid yet means none were sent).
async function fuBadge() {
  let uid; try { uid = localStorage.getItem("uid"); } catch {}
  const b = document.getElementById("fuCount");
  if (!uid || !b) return;
  try {
    const n = (await (await fetch(`/api/inquiries?client=${encodeURIComponent(uid)}`)).json()).filter((q) => !q.outcome).length;
    b.textContent = faNum(n); b.hidden = !n;
  } catch {}
}
fuBadge();
