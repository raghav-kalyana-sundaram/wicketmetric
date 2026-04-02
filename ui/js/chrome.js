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

function initialsOf(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  const s = (parts[0] || "?").replace(/[^A-Za-z]/g, "");
  return (s.slice(0, 2) || "?").toUpperCase();
}

export function portrait(slug, name, size = "sm") {
  if (!slug) return "";
  const ini = initialsOf(name);
  const dark = document.documentElement.getAttribute("data-theme") !== "paper";
  const bg = dark ? "#2c2926" : "#edf1f5";
  const fg = dark ? "#969390" : "#57647a";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 64"><rect fill="${bg}" width="48" height="64"/><text x="24" y="38" text-anchor="middle" fill="${fg}" font-family="Georgia,serif" font-size="15">${ini}</text></svg>`;
  const alt = size === "lg" ? esc(name || "") : "";
  return `<img class="port port-${size}" alt="${alt}" width="48" height="64" data-port="${esc(slug)}" src="data:image/svg+xml,${encodeURIComponent(svg)}">`;
}

function applyPortrait(root, slug, blob) {
  if (!blob || !(blob.type || "").includes("image/") || (blob.type || "").includes("svg")) return false;
  const url = URL.createObjectURL(blob);
  root.querySelectorAll(`img.port[data-port="${CSS.escape(slug)}"]`).forEach((el) => {
    el.src = url;
    el.dataset.ready = "1";
  });
  return true;
}

export function warmPortraits(root = document) {
  const seen = new Set();
  const queue = [];
  root.querySelectorAll("img.port[data-port]").forEach((img) => {
    const slug = img.dataset.port;
    if (!slug || img.dataset.ready || seen.has(slug)) return;
    seen.add(slug);
    queue.push(slug);
  });
  const fill = (slug) => {
    fetch(`/api/portrait/${encodeURIComponent(slug)}`)
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((b) => { if (!applyPortrait(root, slug, b)) throw 0; })
      .catch(() => {
        fetch(`/api/portrait/${encodeURIComponent(slug)}?warm=1`)
          .then((r) => (r.ok ? r.blob() : null))
          .then((b) => applyPortrait(root, slug, b))
          .catch(() => {});
      });
  };
  queue.slice(0, 10).forEach(fill);
  if (queue.length > 10) setTimeout(() => queue.slice(10).forEach(fill), 280);
}

export function ribbon(items) {
  return `<dl class="ribbon">${items.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v == null || v === "" ? "–" : v}</dd></div>`).join("")}</dl>`;
}

export function mixBars(rows, { lab = "label", n = "n" } = {}) {
  const list = (rows || []).filter((r) => r[lab] != null);
  if (!list.length) return "";
  const max = Math.max(...list.map((r) => Number(r[n]) || 0), 1);
  return `<div class="mix">${list.map((r) => `
    <div class="mix-row">
      <span class="mix-lab">${esc(r[lab])}</span>
      <span class="mix-track"><span style="width:${((Number(r[n]) || 0) / max * 100).toFixed(1)}%"></span></span>
      <span class="mix-n">${r[n] ?? "–"}</span>
    </div>`).join("")}</div>`;
}

export function ledger(headers, rows) {
  const body = (rows || []).filter(Boolean);
  if (!body.length) return "";
  return `<table class="ledger"><thead><tr>${headers.map((h, i) => `<th class="${i ? "n" : "l"}">${h}</th>`).join("")}</tr></thead>
    <tbody>${body.map((row) => `<tr>${row.map((c, i) => `<td class="${i ? "n" : "l"}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

export function scoreBeads(rows, n = 10) {
  const last = (rows || []).slice(0, n);
  if (!last.length) return "";
  return `<div class="score-beads">${last.map((i) => {
    const r = Number(i.runs || 0);
    const star = i.not_out ? "*" : "";
    const cls = r >= 100 ? "ton" : r >= 50 ? "fifty" : r === 0 && !i.not_out ? "duck" : "";
    const inner = `<span class="sbead ${cls}" title="${r}${star} v ${i.opposition || ""}">${r}${star}</span>`;
    return i.match_id ? `<a class="sbead-link" href="#/match/${esc(i.match_id)}">${inner}</a>` : inner;
  }).join("")}</div>`;
}

function yrLabel(y) {
  const s = String(y ?? "");
  return s.length === 4 ? `’${s.slice(2)}` : s;
}

function splitLine(r) {
  if (!r) return "–";
  const avg = r.avg != null ? r.avg : "–";
  return `${r.inns} inns · ${Number(r.runs || 0).toLocaleString()} · ${avg} avg`;
}

function spanLink(r, prefix) {
  if (!r) return "";
  const body = `${prefix} ${fmtDateAlmanac(r.start_date)} · ${esc(r.team)} v ${esc(r.opposition)} · ${(r.competition || "").toUpperCase()}`;
  return r.match_id ? `<a href="#/match/${esc(r.match_id)}">${body}</a>` : body;
}

export function almanacBlock(a) {
  if (!a) return "";
  const conv = a.conversion || {};
  const roles = a.roles || {};
  const debut = a.debut;
  const latest = a.latest;
  const yearMax = Math.max(0, ...(a.years || []).map((y) => Number(y.runs) || 0));
  const yearSlice = (a.years || []).slice(-12);
  const years = yearSlice.map((y) => {
    const h = yearMax ? (Number(y.runs) / yearMax * 100) : 0;
    return `<span class="yr" title="${y.year}: ${Number(y.runs || 0).toLocaleString()} runs, ${y.avg ?? "–"} avg"><i style="height:${Math.max(h, 3)}%"></i><em>${yrLabel(y.year)}</em></span>`;
  }).join("");
  const pos = (a.positions || []).map((p) => ({ label: `#${p.position}`, n: p.n }));
  const dis = (a.dismissals || []).map((d) => ({ label: d.label, n: d.n }));
  const ha = a.home_away || [];
  const ch = a.chase || [];
  const fmts = (a.formats || []).map((r) => ({ label: r.label, n: r.matches }));
  const yearRows = yearSlice.map((y) => [
    yrLabel(y.year),
    y.inns ?? "–",
    Number(y.runs || 0).toLocaleString(),
    y.avg ?? "–",
    y.hundreds ?? 0,
  ]);
  const vsRows = (a.vs || []).map((r) => [
    esc(r.opposition),
    r.inns ?? "–",
    Number(r.runs || 0).toLocaleString(),
    r.avg ?? "–",
    r.hundreds ?? 0,
  ]);
  const venueRows = (a.venues || []).map((r) => [
    esc(r.venue),
    r.inns ?? "–",
    Number(r.runs || 0).toLocaleString(),
    r.avg ?? "–",
  ]);
  const phaseOrder = { "First 50": 0, Middle: 1, "Last 50": 2, Career: 3 };
  const phaseRows = [...(a.phases || [])]
    .filter((r) => r.split !== "Career")
    .sort((x, y) => (phaseOrder[x.split] ?? 9) - (phaseOrder[y.split] ?? 9))
    .map((r) => [esc(r.split), r.inns ?? "–", Number(r.runs || 0).toLocaleString(), r.avg ?? "–"]);
  const wlOrder = { Won: 0, Lost: 1, "Draw / NR": 2 };
  const wlRows = [...(a.win_loss || [])]
    .sort((x, y) => (wlOrder[x.split] ?? 9) - (wlOrder[y.split] ?? 9))
    .map((r) => [esc(r.split), r.inns ?? "–", Number(r.runs || 0).toLocaleString(), r.avg ?? "–"]);
  const bowlMax = Math.max(0, ...(a.bowl_years || []).map((y) => Number(y.wickets) || 0));
  const bowlSlice = (a.bowl_years || []).slice(-12);
  const bowlChart = bowlMax >= 8 ? bowlSlice.map((y) => {
    const h = bowlMax ? (Number(y.wickets) / bowlMax * 100) : 0;
    return `<span class="yr" title="${y.year}: ${y.wickets} wickets, ${y.econ ?? "–"} econ"><i style="height:${Math.max(h, 3)}%"></i><em>${yrLabel(y.year)}</em></span>`;
  }).join("") : "";
  const roleBits = [
    roles.captain ? `${roles.captain} as captain` : "",
    roles.keeper ? `${roles.keeper} with the gloves` : "",
  ].filter(Boolean);
  const convPct = conv.conversion != null ? Math.min(100, Number(conv.conversion)) : 0;
  return `
    <section class="almanac" id="almanac">
      ${a.last5?.length ? `<div class="almanac-row"><h3>Last knocks</h3>${scoreBeads(a.last5, 10)}</div>` : ""}
      ${debut || latest ? `<p class="almanac-span">${spanLink(debut, "Debut")}${debut && latest ? "<br>" : ""}${spanLink(latest, "Latest")}</p>` : ""}
      ${conv.hundreds != null ? `<div class="conv">
        <div><div class="conv-k">Hundreds</div><div class="conv-n">${conv.hundreds}</div></div>
        <div><div class="conv-k">Fifties</div><div class="conv-n">${conv.fifties ?? "–"}</div></div>
        <div class="conv-bar-wrap">
          <div class="conv-k">Fifty-plus that became hundreds</div>
          <div class="conv-track"><span style="width:${convPct}%"></span></div>
          <div class="conv-n">${conv.conversion != null ? `${conv.conversion}%` : "–"}</div>
        </div>
        <div><div class="conv-k">Ducks</div><div class="conv-n">${conv.ducks ?? "–"}</div></div>
        <div><div class="conv-k">Boundary %</div><div class="conv-n">${conv.boundary_pct ?? "–"}</div></div>
      </div>` : ""}
      ${years ? `<div class="almanac-row"><h3>Runs by year</h3><div class="yr-chart">${years}</div>${ledger(["Year", "Inns", "Runs", "Avg", "100"], yearRows)}</div>` : ""}
      ${bowlChart ? `<div class="almanac-row"><h3>Wickets by year</h3><div class="yr-chart">${bowlChart}</div></div>` : ""}
      <div class="almanac-grid">
        ${dis.length ? `<div><h3>How out</h3>${mixBars(dis)}</div>` : ""}
        ${pos.length ? `<div><h3>Batting order</h3>${mixBars(pos)}</div>` : ""}
        ${fmts.length ? `<div><h3>Formats</h3>${mixBars(fmts)}</div>` : ""}
        ${ha.length ? `<div><h3>Home / away</h3>${ha.map((r) => `<p class="xi-line"><strong>${esc(r.split)}</strong> · ${splitLine(r)}</p>`).join("")}</div>` : ""}
        ${ch.length ? `<div><h3>Set / chase</h3>${ch.map((r) => `<p class="xi-line"><strong>${esc(r.split)}</strong> · ${splitLine(r)}</p>`).join("")}</div>` : ""}
        ${wlRows.length ? `<div><h3>In wins and losses</h3>${ledger(["", "Inns", "Runs", "Avg"], wlRows)}</div>` : ""}
        ${phaseRows.length ? `<div><h3>Career phases</h3>${ledger(["", "Inns", "Runs", "Avg"], phaseRows)}</div>` : ""}
        ${vsRows.length ? `<div class="span-2"><h3>Vs opposition</h3>${ledger(["Opp", "Inns", "Runs", "Avg", "100"], vsRows)}</div>` : ""}
        ${venueRows.length ? `<div class="span-2"><h3>Grounds</h3>${ledger(["Ground", "Inns", "Runs", "Avg"], venueRows)}</div>` : ""}
      </div>
      ${roleBits.length ? `<p class="caption">${roleBits.join(" · ")}</p>` : ""}
    </section>`;
}

function fmtDateAlmanac(iso) {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
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
  warmPortraits(list);
  requestAnimationFrame(() => input.focus());
  input.oninput = async () => {
    const q = input.value.trim();
    if (q.length < 2) return;
    const s = await (await fetch(`/api/suggest?q=${encodeURIComponent(q)}`)).json();
    let html = "";
    (s.people || []).slice(0, 8).forEach((p) => {
      const hint = p.unique_name && p.unique_name !== p.display_name ? ` <span class="hint">${esc(p.unique_name)}</span>` : "";
      html += `<button type="button" data-hash="#/player/${esc(p.slug)}">${portrait(p.slug, p.display_name, "xs")}<span>${esc(p.display_name)}${hint}</span></button>`;
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
    warmPortraits(list);
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
