const FAV_KEY = "wm-favs";
const DENSITY_KEY = "wm-density";
const TRAY_KEY = "wm-tray";

export const GLOSSARY = [
  { id: "war", term: "WAR", body: "Wins above replacement in this warehouse. Replacement is the 20th-percentile qualifier in that competition-season-gender. More games count in the career total; WAR / game is the same pile divided by matches." },
  { id: "rae", term: "RAE", body: "Runs above expectation. Each ball is judged against the mean in that over-bucket, wickets down, innings, competition, and gender, then tilted by opposition strength. Not “runs added.”" },
  { id: "wpa", term: "WPA", body: "Win probability added. Change in the batting side’s chance of winning on that ball. Batter credit on scoring balls; bowler credit is the negative." },
  { id: "nrc", term: "NRC", body: "Net run contribution. Runs minus expected runs, plus a wicket price from the run-expectancy table. Not-outs keep value because that debit never fires." },
  { id: "wowy", term: "WOWY", body: "With or without you. Team results only from the player’s first XI for that side — matches before they existed don’t count as “without.”" },
  { id: "pressure", term: "Pressure", body: "0–1: required rate vs expected remaining rate in chases, and overs 16+ in the first innings. Impact = RAE × (1 + pressure)." },
  { id: "pct", term: "Percentile", body: "Share of the filtered set you sit above. A 92 vs 98 still means something — fat-tail innings are not pinned at 99." },
];

export const KEYS = [
  ["/", "Search"],
  ["⌘K", "Jump to a player or page"],
  ["T", "Fullscreen the table"],
  ["F", "Filter the table"],
  ["G", "Glossary"],
  ["C", "Add hovered player to compare"],
  ["*", "Favourite this player"],
  ["W / E", "Comfortable / compact rows"],
  ["?", "This list"],
  ["Esc", "Close overlays"],
];

function $(id) {
  return document.getElementById(id);
}

export function toast(msg) {
  let el = $("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 1800);
}

export async function copyText(s) {
  const text = String(s || "");
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  } catch {
    toast("Couldn’t copy");
  }
}

export function setDocTitle(bit) {
  document.title = bit ? `${bit} · Wicket Metric` : "Wicket Metric";
}

export function favList() {
  try {
    return JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
  } catch {
    return [];
  }
}

export function favHas(slug) {
  return favList().some((f) => f.slug === slug);
}

export function favToggle(slug, name) {
  if (!slug) return favList();
  let list = favList();
  if (list.some((f) => f.slug === slug)) list = list.filter((f) => f.slug !== slug);
  else list = [{ slug, name: name || slug }, ...list].slice(0, 24);
  localStorage.setItem(FAV_KEY, JSON.stringify(list));
  renderFavStar();
  renderTray();
  return list;
}

export function sparkline(values, { width = 168, height = 36 } = {}) {
  const nums = (values || []).map(Number).filter((n) => Number.isFinite(n));
  if (nums.length < 2) return "";
  const max = Math.max(...nums, 1);
  const min = Math.min(...nums, 0);
  const span = Math.max(max - min, 1);
  const step = width / (nums.length - 1);
  const pts = nums.map((n, i) => {
    const x = i * step;
    const y = height - 2 - ((n - min) / span) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = nums[nums.length - 1];
  const lx = (nums.length - 1) * step;
  const ly = height - 2 - ((last - min) / span) * (height - 4);
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-hidden="true">
    <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts.join(" ")}"/>
    <circle cx="${lx}" cy="${ly}" r="2.2" fill="currentColor"/>
  </svg>`;
}

export function formBlock(innings, { n = 10, careerAvg = null } = {}) {
  const last = (innings || []).slice(0, n);
  if (!last.length) return "";
  const runs = last.reduce((s, i) => s + Number(i.runs || 0), 0);
  const outs = last.filter((i) => !i.not_out).length;
  const avg = outs ? (runs / outs) : null;
  const values = last.slice().reverse().map((i) => Number(i.runs || 0));
  const avgBit = avg == null ? "not out through the lot" : avg.toFixed(1);
  const vs = careerAvg != null && avg != null
    ? (avg >= careerAvg ? ` ahead of career ${Number(careerAvg).toFixed(1)}` : ` behind career ${Number(careerAvg).toFixed(1)}`)
    : "";
  return `<div class="form-block">
    <div class="form-copy">
      <div class="form-kicker">Last ${last.length} innings</div>
      <div class="form-line">${runs} runs at ${avgBit}${vs}</div>
    </div>
    ${sparkline(values)}
  </div>`;
}

export function wowyVisual(rows) {
  const withR = (rows || []).find((r) => String(r.split || "").toLowerCase().includes("with"));
  const without = (rows || []).find((r) => String(r.split || "").toLowerCase().includes("without"));
  if (!withR || !without) return "";
  const a = Number(withR.win_pct || 0);
  const b = Number(without.win_pct || 0);
  const delta = a - b;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  return `<div class="wowy-visual">
    <div class="wowy-lane">
      <div class="wowy-lab">With · ${withR.matches} matches · ${a}% wins</div>
      <div class="wowy-track"><span class="wowy-fill with" style="width:${Math.min(a, 100)}%"></span></div>
    </div>
    <div class="wowy-lane">
      <div class="wowy-lab">Without · ${without.matches} matches · ${b}% wins</div>
      <div class="wowy-track"><span class="wowy-fill without" style="width:${Math.min(b, 100)}%"></span></div>
    </div>
    <p class="caption">Win rate ${sign}${Math.abs(delta).toFixed(1)} pts when they’re in the XI.</p>
  </div>`;
}

export function scatterSVG(rows, { xKey = "sr", yKey = "war", xLab = "Strike rate", yLab = "WAR", cap = 320 } = {}) {
  const pts = (rows || []).map((r) => ({
    x: Number(r[xKey]),
    y: Number(r[yKey]),
    slug: r.slug,
    name: r.player || r.display_name,
  })).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y)).slice(0, cap);
  if (pts.length < 8) return `<p class="caption">Not enough pairs for a scatter in this filter.</p>`;
  const w = 640, h = 280, pad = { l: 44, r: 16, t: 12, b: 32 };
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const xSpan = Math.max(x1 - x0, 0.01), ySpan = Math.max(y1 - y0, 0.01);
  const X = (x) => pad.l + ((x - x0) / xSpan) * (w - pad.l - pad.r);
  const Y = (y) => h - pad.b - ((y - y0) / ySpan) * (h - pad.t - pad.b);
  const mid = (arr) => {
    const s = arr.slice().sort((a, b) => a - b);
    const i = Math.floor(s.length / 2);
    return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
  };
  const mx = mid(xs), my = mid(ys);
  const dots = pts.map((p) =>
    `<a href="#/player/${encodeURIComponent(p.slug)}"><circle class="sc-dot" cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.2"><title>${p.name} · ${xLab} ${p.x} · ${yLab} ${p.y}</title></circle></a>`
  ).join("");
  return `<svg class="scatter" viewBox="0 0 ${w} ${h}" role="img" aria-label="${yLab} against ${xLab}">
    <text x="${pad.l}" y="12" class="sc-axis">${yLab}</text>
    <text x="${w - 4}" y="${h - 8}" text-anchor="end" class="sc-axis">${xLab}</text>
    <line x1="${pad.l}" y1="${h - pad.b}" x2="${w - pad.r}" y2="${h - pad.b}" class="sc-grid"/>
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${h - pad.b}" class="sc-grid"/>
    <line x1="${X(mx).toFixed(1)}" y1="${pad.t}" x2="${X(mx).toFixed(1)}" y2="${h - pad.b}" class="sc-median"/>
    <line x1="${pad.l}" y1="${Y(my).toFixed(1)}" x2="${w - pad.r}" y2="${Y(my).toFixed(1)}" class="sc-median"/>
    ${dots}
  </svg>
  <p class="caption">Each dot is a player in this sort (first ${pts.length} with both axes). Crosshairs are the median ${xLab.toLowerCase()} and ${yLab}. Click a dot or a name.</p>`;
}

export function fowBeads(parts) {
  const falls = (parts || []).filter((p) => p.end_reason && p.end_reason !== "end_of_innings");
  if (!falls.length) return "";
  const max = Math.max(...falls.map((p) => Number(p.runs) || 0), 1);
  return `<div class="fow-beads" aria-label="Fall of wickets">${falls.map((p) => {
    const left = Math.min(96, (Number(p.runs) / max) * 96);
    return `<span class="bead" style="left:${left}%" title="${p.wicket_number}–${p.runs}">${p.wicket_number}</span>`;
  }).join("")}</div>`;
}

export function pctBar(rank, of) {
  const n = Number(of) || 0;
  const r = Number(rank) || 0;
  if (!n || !r) return "";
  const pct = Math.max(0, Math.min(100, (1 - (r - 1) / n) * 100));
  return `<div class="pct-bar" aria-hidden="true"><span style="width:${pct.toFixed(1)}%"></span></div>`;
}

const tray = [];

export function trayItems() {
  return tray.slice();
}

export function trayAdd(slug, name) {
  if (!slug) return;
  const i = tray.findIndex((t) => t.slug === slug);
  if (i >= 0) return;
  if (tray.length >= 2) tray.shift();
  tray.push({ slug, name: name || slug });
  renderTray();
  toast(`${name || slug} in the compare tray`);
}

function persistTray() {
  try { sessionStorage.setItem(TRAY_KEY, JSON.stringify(tray)); } catch { /* ignore */ }
}

function restoreTray() {
  if (tray.length) return;
  try {
    const saved = JSON.parse(sessionStorage.getItem(TRAY_KEY) || "[]");
    if (Array.isArray(saved)) saved.slice(0, 2).forEach((t) => { if (t?.slug) tray.push(t); });
  } catch { /* ignore */ }
}

export function trayClear() {
  tray.length = 0;
  renderTray();
}

export function renderTray() {
  let el = $("compare-tray");
  if (!el) {
    el = document.createElement("div");
    el.id = "compare-tray";
    el.className = "compare-tray";
    document.body.appendChild(el);
  }
  persistTray();
  if (!tray.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  const ready = tray.length === 2;
  el.innerHTML = `
    <span class="tray-lab">Compare</span>
    ${tray.map((t) => `<span class="tray-chip">${esc(t.name)} <button type="button" data-drop="${esc(t.slug)}" aria-label="Remove">×</button></span>`).join("")}
    ${ready ? `<a class="btn primary" href="#/compare?a=${encodeURIComponent(tray[0].slug)}&b=${encodeURIComponent(tray[1].slug)}">Go</a>` : `<span class="caption">C on another name</span>`}
    <button type="button" class="btn-text" data-clear>Clear</button>`;
  el.querySelectorAll("[data-drop]").forEach((b) => {
    b.addEventListener("click", () => {
      const i = tray.findIndex((t) => t.slug === b.dataset.drop);
      if (i >= 0) tray.splice(i, 1);
      renderTray();
    });
  });
  el.querySelector("[data-clear]")?.addEventListener("click", trayClear);
}

export function renderFavStar(slug, name) {
  const btn = $("fav-star");
  if (!btn || !slug) return;
  const on = favHas(slug);
  btn.hidden = false;
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.onclick = () => {
    favToggle(slug, name);
    renderFavStar(slug, name);
    toast(favHas(slug) ? "Pinned" : "Unpinned");
  };
}

function ensureOverlay() {
  if ($("overlay-root")) return;
  const root = document.createElement("div");
  root.id = "overlay-root";
  root.innerHTML = `
    <div class="sheet" id="keys-sheet" hidden>
      <h2>Keys</h2>
      <table class="keys">${KEYS.map(([k, v]) => `<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`).join("")}</table>
    </div>
    <div class="sheet" id="glossary-sheet" hidden>
      <h2>Glossary</h2>
      ${GLOSSARY.map((g) => `<h3 id="gl-${g.id}">${g.term}</h3><p>${g.body}</p>`).join("")}
    </div>
    <div class="palette" id="palette" hidden>
      <input id="palette-input" type="text" placeholder="Player, team, or page" aria-label="Jump">
      <div id="palette-list" role="listbox"></div>
    </div>
    <div class="scrim" id="overlay-scrim" hidden></div>`;
  document.body.appendChild(root);
  $("overlay-scrim").addEventListener("click", closeOverlays);
}

export function closeOverlays() {
  ["keys-sheet", "glossary-sheet", "palette", "overlay-scrim"].forEach((id) => {
    const el = $(id);
    if (el) el.hidden = true;
  });
  document.body.classList.remove("overlay-open");
}

function openSheet(id) {
  ensureOverlay();
  closeOverlays();
  $(id).hidden = false;
  $("overlay-scrim").hidden = false;
  document.body.classList.add("overlay-open");
}

export function openKeys() { openSheet("keys-sheet"); }
export function openGlossary() { openSheet("glossary-sheet"); }

export async function openPalette() {
  ensureOverlay();
  closeOverlays();
  $("palette").hidden = false;
  $("overlay-scrim").hidden = false;
  document.body.classList.add("overlay-open");
  const input = $("palette-input");
  const list = $("palette-list");
  input.value = "";
  list.innerHTML = `<button type="button" data-hash="#/stats">Stats</button>
    <button type="button" data-hash="#/wowy">WOWY</button>
    <button type="button" data-hash="#/best">Best T20</button>
    <button type="button" data-hash="#/compare">Compare</button>`;
  bindPaletteButtons(list);
  requestAnimationFrame(() => input.focus());
  input.oninput = async () => {
    const q = input.value.trim();
    if (q.length < 2) return;
    const s = await (await fetch(`/api/suggest?q=${encodeURIComponent(q)}`)).json();
    let html = "";
    (s.people || []).slice(0, 8).forEach((p) => {
      const hint = p.unique_name && p.unique_name !== p.display_name ? ` <span class="hint">${esc(p.unique_name)}</span>` : "";
      html += `<button type="button" data-hash="#/player/${esc(p.slug)}">${esc(p.display_name)}${hint}</button>`;
    });
    (s.teams || []).slice(0, 4).forEach((t) => {
      const name = t.team || t;
      html += `<button type="button" data-hash="#/wowy?team=${encodeURIComponent(name)}">${esc(name)} <span class="hint">WOWY</span></button>`;
    });
    (s.destinations || []).slice(0, 4).forEach((d) => {
      html += `<button type="button" data-hash="#/${esc(d.id)}">${esc(d.label)} <span class="hint">${esc(d.hint)}</span></button>`;
    });
    list.innerHTML = html || `<p class="caption">Nothing matched.</p>`;
    bindPaletteButtons(list);
  };
}

function paletteButtons() {
  return [...($("palette-list")?.querySelectorAll("button[data-hash]") || [])];
}

function paletteSelect(dir) {
  const btns = paletteButtons();
  if (!btns.length) return;
  const i = btns.findIndex((b) => b.classList.contains("on"));
  const next = dir === 0 ? 0 : Math.max(0, Math.min(btns.length - 1, (i < 0 ? -1 : i) + dir));
  btns.forEach((b, n) => b.classList.toggle("on", n === next));
  btns[next]?.scrollIntoView({ block: "nearest" });
}

function paletteGo() {
  const on = $("palette-list")?.querySelector("button.on") || paletteButtons()[0];
  if (!on) return;
  closeOverlays();
  location.hash = on.dataset.hash;
}

function bindPaletteButtons(list) {
  list.querySelectorAll("[data-hash]").forEach((b) => {
    b.addEventListener("click", () => {
      closeOverlays();
      location.hash = b.dataset.hash;
    });
  });
  paletteSelect(0);
}

export function toggleFullscreen() {
  document.body.classList.toggle("table-focus");
  toast(document.body.classList.contains("table-focus") ? "Table focus · T to leave" : "Full layout");
}

export function applyDensity(mode) {
  document.body.classList.toggle("density-compact", mode === "compact");
  localStorage.setItem(DENSITY_KEY, mode);
}

export function toggleDensity(dir) {
  const compact = document.body.classList.contains("density-compact");
  if (dir === "in") applyDensity("compact");
  else if (dir === "out") applyDensity("comfortable");
  else applyDensity(compact ? "comfortable" : "compact");
}

function typing() {
  const tag = document.activeElement?.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.activeElement?.isContentEditable;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  ));
}

let hooks = {};

export function initChrome(h) {
  hooks = h || {};
  ensureOverlay();
  applyDensity(localStorage.getItem(DENSITY_KEY) || "comfortable");
  restoreTray();
  renderTray();
  $("keys-toggle")?.addEventListener("click", openKeys);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (document.body.classList.contains("overlay-open")) {
        closeOverlays();
        e.preventDefault();
      }
      return;
    }
    const meta = e.metaKey || e.ctrlKey;
    if (meta && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
      return;
    }
    if ($("palette") && !$("palette").hidden) {
      if (e.key === "ArrowDown") { e.preventDefault(); paletteSelect(1); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); paletteSelect(-1); return; }
      if (e.key === "Enter") { e.preventDefault(); paletteGo(); return; }
    }
    if (document.body.classList.contains("overlay-open")) return;
    if (typing()) return;
    if (e.key === "?") { e.preventDefault(); openKeys(); }
    else if (e.key === "g" || e.key === "G") { e.preventDefault(); openGlossary(); }
    else if (e.key === "t" || e.key === "T") { e.preventDefault(); toggleFullscreen(); }
    else if (e.key === "f" || e.key === "F") {
      e.preventDefault();
      if (hooks.focusFilter) hooks.focusFilter();
      else {
        const filter = document.querySelector(".table-filter");
        if (filter) { filter.hidden = false; filter.focus(); }
        else toast("No table to filter");
      }
    }
    else if (e.key === "w" || e.key === "W") { e.preventDefault(); toggleDensity("out"); }
    else if (e.key === "e" || e.key === "E") { e.preventDefault(); toggleDensity("in"); }
    else if (e.key === "c" || e.key === "C") {
      const row = document.querySelector("tr.is-hover[data-slug]");
      if (row?.dataset.slug) {
        e.preventDefault();
        trayAdd(row.dataset.slug, row.dataset.name);
      } else if (document.body.dataset.playerSlug) {
        e.preventDefault();
        trayAdd(document.body.dataset.playerSlug, document.body.dataset.playerName);
      }
    }
    else if (e.key === "*") {
      const slug = document.body.dataset.playerSlug;
      const name = document.body.dataset.playerName;
      if (slug) {
        e.preventDefault();
        favToggle(slug, name);
        renderFavStar(slug, name);
        toast(favHas(slug) ? "Pinned" : "Unpinned");
      }
    }
  });
}

export { hooks };
