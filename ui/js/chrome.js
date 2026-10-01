const FAV_KEY = "wm-favs";
const DENSITY_KEY = "wm-density";
const TRAY_KEY = "wm-tray";

export const GLOSSARY = [
  { id: "war", term: "WAR", body: "Wins above replacement in this application. Replacement is the 20th-percentile qualifier in that competition-season-gender. More games count in the career total; WAR / game is the same pile divided by matches." },
  { id: "rae", term: "RAE", body: "Runs above expectation. Each ball is judged against the mean in that over-bucket, wickets down, innings, competition, and gender, then tilted by opposition strength. Not “runs added.”" },
  { id: "wpa", term: "WPA", body: "Win probability added. Change in the batting side’s chance of winning on that ball. Batter credit on scoring balls; bowler credit is the negative." },
  { id: "nrc", term: "NRC", body: "Net run contribution. Runs minus expected runs, plus a wicket price from the run-expectancy table. Not-outs keep value because that debit never fires." },
  { id: "wowy", term: "WOWY", body: "With or without you. Team results only from the player’s first XI for that side — matches before they existed don’t count as “without.”" },
  { id: "pressure", term: "Pressure", body: "0–1: required rate vs expected remaining rate in chases, and overs 16+ in the first innings. Impact = RAE × (1 + pressure)." },
  { id: "pct", term: "Percentile", body: "Share of the filtered set you sit above. A 92 vs 98 still means something — fat-tail innings are not pinned at 99." },
  { id: "form", term: "Form", body: "A 0–10 Test rating among active players: recency-weighted RAA per Test, shrunk toward that player's own career. Median current regular is about 6.5; the best in the world sit around 9.3–9.6. Not comparable to overall (50–99)." },
  { id: "career", term: "Overall", body: "Test career value: 50/50 blend of accumulated RAA and a shrunk peak rate, linearly mapped so Bradman is 99 and a replacement regular is 50. Peak is the same scale over a window of at least 24 months and 20 innings." },
  { id: "records", term: "Records", body: "Records here are records in this application. Men's Tests from 1877 and ODIs from 1971 use Cricinfo scorecards where Cricsheet has no file; ball-by-ball (and fastest fifties/hundreds) is Cricsheet." },
  { id: "manhattan", term: "Manhattan", body: "One bar per over, height is runs off that over. A dot above the bar marks a wicket in it. Useful for finding where an innings turned." },
  { id: "chase_pct", term: "Chase %", body: "Share of decided matches at a ground won by the side batting second. Above 55% and the toss is worth having." },
  { id: "balls_to", term: "Balls to 50 / 100", body: "Balls the batter had faced when the milestone came up, counted from the ball-by-ball rows. No-balls faced count as balls." },
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
  ["R", "Records"],
  ["S", "Stats"],
  ["H", "Home"],
  ["Y", "Copy a link to this view"],
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
  const bg = dark ? "#2c2926" : "#e8ecf2";
  const fg = dark ? "#969390" : "#5c6578";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 64"><rect fill="${bg}" width="48" height="64"/><text x="24" y="38" text-anchor="middle" fill="${fg}" font-family="Georgia,serif" font-size="15">${ini}</text></svg>`;
  const alt = size === "lg" ? esc(name || "") : "";
  return `<img class="port port-${size}" alt="${alt}" width="48" height="64" data-port="${esc(slug)}" src="data:image/svg+xml,${encodeURIComponent(svg)}">`;
}

const portUrls = new Map();

function applyPortrait(root, slug, blob) {
  if (!blob || !(blob.type || "").includes("image/") || (blob.type || "").includes("svg")) return false;
  const prev = portUrls.get(slug);
  if (prev) URL.revokeObjectURL(prev);
  const url = URL.createObjectURL(blob);
  portUrls.set(slug, url);
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
    const label = cls === "duck" ? `Duck · ${i.opposition || ""}` : `${r}${star} v ${i.opposition || ""}`;
    const inner = `<span class="sbead ${cls}" title="${esc(label)}">${r}${star}</span>`;
    return i.match_id ? `<a class="sbead-link" href="#/match/${esc(i.match_id)}">${inner}</a>` : inner;
  }).join("")}</div>`;
}

export function spellBeads(rows, n = 10) {
  const last = (rows || []).slice(0, n);
  if (!last.length) return "";
  return `<div class="score-beads">${last.map((i) => {
    const w = Number(i.wickets || 0);
    const r = Number(i.runs || 0);
    const cls = w >= 5 ? "ton" : w >= 3 ? "fifty" : w === 0 ? "duck" : "";
    const label = `${w}/${r} v ${i.opposition || ""}`;
    const inner = `<span class="sbead ${cls}" title="${esc(label)}">${w}/${r}</span>`;
    return i.match_id ? `<a class="sbead-link" href="#/match/${esc(i.match_id)}">${inner}</a>` : inner;
  }).join("")}</div>`;
}

function yrLabel(y, years) {
  const s = String(y ?? "");
  if (s.length !== 4) return s;
  const list = (years || []).map((row) => String(row.year ?? row));
  const crosses = list.some((x) => x.startsWith("19")) && list.some((x) => x.startsWith("20"));
  return crosses ? s : `’${s.slice(2)}`;
}

function spanLink(r, prefix) {
  if (!r) return "";
  const body = `${prefix} ${fmtDateAlmanac(r.start_date)} · ${esc(r.team)} v ${esc(r.opposition)} · ${(r.competition || "").toUpperCase()}`;
  return r.match_id ? `<a href="#/match/${esc(r.match_id)}">${body}</a>` : body;
}

export function almanacBlock(a, { bowlFirst = false } = {}) {
  if (!a) return "";
  const conv = a.conversion || {};
  const roles = a.roles || {};
  const debut = a.debut;
  const latest = a.latest;
  const yearSlice = a.years || [];
  const pos = (a.positions || []).map((p) => ({ label: `#${p.position}`, n: p.n }));
  const notOuts = (a.dismissals || []).find((d) => String(d.label).toLowerCase() === "not out");
  const dis = (a.dismissals || [])
    .filter((d) => String(d.label).toLowerCase() !== "not out")
    .map((d) => ({ label: d.label, n: d.n }));
  const ha = a.home_away || [];
  const ch = a.chase || [];
  const fmts = (a.formats || []).map((r) => ({ label: r.label, n: r.matches }));
  const visibleYearMax = Math.max(1, ...yearSlice.map((y) => Number(y.runs) || 0));
  const yearRows = yearSlice.map((y) => {
    const runs = Number(y.runs || 0);
    return [
      yrLabel(y.year, yearSlice),
      y.inns ?? "–",
      `<span class="year-run"><span>${runs.toLocaleString()}</span><i><b style="width:${(runs / visibleYearMax * 100).toFixed(1)}%"></b></i></span>`,
      y.avg ?? "–",
      y.hundreds ?? 0,
    ];
  });
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
  const bowlYears = a.bowl_years || [];
  const bowlMax = Math.max(0, ...bowlYears.map((y) => Number(y.wickets) || 0));
  const bowlChart = (bowlFirst ? bowlYears.length >= 3 : bowlMax >= 8) ? bowlYears.map((y) => {
    const h = bowlMax ? (Number(y.wickets) / bowlMax * 100) : 0;
    return `<span class="yr" title="${y.year}: ${y.wickets} wickets, ${y.econ ?? "–"} econ"><i style="height:${Math.max(h, 3)}%"></i><em>${yrLabel(y.year, bowlYears)}</em></span>`;
  }).join("") : "";
  const bowlSpan = bowlYears.length
    ? `${bowlYears[0].year}–${bowlYears[bowlYears.length - 1].year} · all formats`
    : "";
  const roleBits = [
    roles.captain ? `${roles.captain} as captain` : "",
    roles.keeper ? `${roles.keeper} with the gloves` : "",
  ].filter(Boolean);
  const convPct = conv.conversion != null ? Math.min(100, Number(conv.conversion)) : 0;
  const hauls = a.hauls || {};
  const bowlYearMax = Math.max(1, ...bowlYears.map((y) => Number(y.wickets) || 0));
  const bowlYearRows = bowlYears.map((y) => {
    const wk = Number(y.wickets || 0);
    return [
      yrLabel(y.year, bowlYears),
      y.inns ?? "–",
      `<span class="year-run"><span>${wk.toLocaleString()}</span><i><b style="width:${(wk / bowlYearMax * 100).toFixed(1)}%"></b></i></span>`,
      y.avg ?? "–",
      y.econ ?? "–",
    ];
  });
  const bowlRow = (r) => [esc(r.split || r.opposition || r.venue), r.inns ?? "–", Number(r.wickets || 0).toLocaleString(), r.avg ?? "–", r.econ ?? "–"];
  const bowlHaRows = (a.bowl_home_away || []).map(bowlRow);
  const bowlWlRows = [...(a.bowl_win_loss || [])]
    .sort((x, y) => (wlOrder[x.split] ?? 9) - (wlOrder[y.split] ?? 9))
    .map(bowlRow);
  const bowlVsRows = (a.bowl_vs || []).map((r) => [
    esc(r.opposition), r.inns ?? "–", Number(r.wickets || 0).toLocaleString(), r.avg ?? "–", r.econ ?? "–",
  ]);
  const bowlVenueRows = (a.bowl_venues || []).map((r) => [
    esc(r.venue), r.inns ?? "–", Number(r.wickets || 0).toLocaleString(), r.avg ?? "–", r.econ ?? "–",
  ]);
  const bowlKinds = a.bowl_dismissals || [];
  const spanLine = debut || latest
    ? `<p class="almanac-span">${spanLink(debut, "Debut")}${debut && latest ? "<br>" : ""}${spanLink(latest, "Latest")}</p>`
    : "";
  const roleLine = roleBits.length ? `<p class="caption">${roleBits.join(" · ")}</p>` : "";

  if (bowlFirst) {
    const batInns = Number(conv.inns || 0);
    const batStrip = batInns > 0 || a.last5?.length ? `
      <div class="almanac-row"><h3>With the bat</h3>
        ${a.last5?.length ? `${scoreBeads(a.last5, 10)}<p class="caption">Each score opens that match</p>` : ""}
        ${conv.hundreds != null && (Number(conv.hundreds) || Number(conv.fifties) || Number(conv.runs)) ? `<p class="caption">${Number(conv.runs || 0).toLocaleString()} runs · HS ${conv.hs ?? "–"} · ${conv.hundreds || 0} hundreds · ${conv.fifties || 0} fifties</p>` : ""}
      </div>` : "";
    return `
    <section class="almanac" id="almanac">
      ${a.last_bowl?.length ? `<div class="almanac-row"><h3>Last spells</h3>${spellBeads(a.last_bowl, 10)}<p class="caption">Each figure opens that match</p></div>` : ""}
      ${spanLine}
      ${hauls.wickets != null ? `<div class="conv">
        <div><div class="conv-k">Five-fors</div><div class="conv-n">${hauls.five_fors ?? 0}</div></div>
        <div><div class="conv-k">Four-fors</div><div class="conv-n">${hauls.four_fors ?? 0}</div></div>
        <div><div class="conv-k">Average</div><div class="conv-n">${hauls.avg ?? "–"}</div></div>
        <div><div class="conv-k">Economy</div><div class="conv-n">${hauls.econ ?? "–"}</div></div>
        <div><div class="conv-k">Strike rate</div><div class="conv-n">${hauls.sr ?? "–"}</div></div>
      </div>` : ""}
      ${bowlYearRows.length ? `<div class="almanac-row"><h3>Wickets by year</h3>${ledger(["Year", "Inns", "Wkts", "Avg", "Econ"], bowlYearRows)}</div>` : ""}
      ${bowlChart ? `<div class="yr-chart">${bowlChart}</div>${bowlSpan ? `<p class="caption">${esc(bowlSpan)}</p>` : ""}` : ""}
      <div class="almanac-grid">
        ${bowlKinds.length ? `<div><h3>How they take wickets</h3>${mixBars(bowlKinds)}</div>` : ""}
        ${fmts.length ? `<div><h3>Formats</h3>${mixBars(fmts)}</div>` : ""}
        ${bowlHaRows.length ? `<div><h3>Home / away</h3>${ledger(["", "Inns", "Wkts", "Avg", "Econ"], bowlHaRows)}</div>` : ""}
        ${bowlWlRows.length ? `<div><h3>In wins and losses</h3>${ledger(["", "Inns", "Wkts", "Avg", "Econ"], bowlWlRows)}</div>` : ""}
        ${bowlVsRows.length ? `<div class="span-2"><h3>Vs opposition</h3>${ledger(["Opp", "Inns", "Wkts", "Avg", "Econ"], bowlVsRows)}</div>` : ""}
        ${bowlVenueRows.length ? `<div class="span-2"><h3>Grounds</h3>${ledger(["Ground", "Inns", "Wkts", "Avg", "Econ"], bowlVenueRows)}</div>` : ""}
      </div>
      ${batStrip}
      ${roleLine}
    </section>`;
  }

  return `
    <section class="almanac" id="almanac">
      ${a.last5?.length ? `<div class="almanac-row"><h3>Last knocks</h3>${scoreBeads(a.last5, 10)}<p class="caption">Each score opens that match</p></div>` : ""}
      ${spanLine}
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
      ${yearSlice.length ? `<div class="almanac-row"><h3>Runs by year</h3>${ledger(["Year", "Inns", "Runs", "Avg", "100"], yearRows)}</div>` : ""}
      ${bowlChart ? `<div class="almanac-row"><h3>Wickets by year</h3><div class="yr-chart">${bowlChart}</div>${bowlSpan ? `<p class="caption">${esc(bowlSpan)}</p>` : ""}</div>` : ""}
      <div class="almanac-grid">
        ${dis.length ? `<div><h3>Dismissals</h3>${mixBars(dis)}${notOuts ? `<p class="not-out-count"><span>Not out</span><strong>${notOuts.n}</strong></p>` : ""}</div>` : ""}
        ${pos.length ? `<div><h3>Batting order</h3>${mixBars(pos)}</div>` : ""}
        ${fmts.length ? `<div><h3>Formats</h3>${mixBars(fmts)}</div>` : ""}
        ${ha.length ? `<div><h3>Home / away</h3>${ledger(["", "Inns", "Runs", "Avg"], ha.map((r) => [esc(r.split), r.inns, Number(r.runs || 0).toLocaleString(), r.avg ?? "–"]))}</div>` : ""}
        ${ch.length ? `<div><h3>Set / chase</h3>${ledger(["", "Inns", "Runs", "Avg"], ch.map((r) => [esc(r.split), r.inns, Number(r.runs || 0).toLocaleString(), r.avg ?? "–"]))}</div>` : ""}
        ${wlRows.length ? `<div><h3>In wins and losses</h3>${ledger(["", "Inns", "Runs", "Avg"], wlRows)}</div>` : ""}
        ${phaseRows.length ? `<div><h3>Career phases</h3>${ledger(["", "Inns", "Runs", "Avg"], phaseRows)}</div>` : ""}
        ${vsRows.length ? `<div class="span-2"><h3>Vs opposition</h3>${ledger(["Opp", "Inns", "Runs", "Avg", "100"], vsRows)}</div>` : ""}
        ${venueRows.length ? `<div class="span-2"><h3>Grounds</h3>${ledger(["Ground", "Inns", "Runs", "Avg"], venueRows)}</div>` : ""}
      </div>
      ${roleLine}
    </section>`;
}

function fmtDateAlmanac(iso) {
  if (!iso) return "—";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  const d = new Date(iso);
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

export function sparkline(values, { width = 168, height = 36, key = "runs" } = {}) {
  const points = (values || []).map((value) => {
    if (typeof value === "object" && value !== null) {
      const n = Number(value[key] ?? value.runs);
      const label = key === "wickets"
        ? `${value.wickets ?? 0}/${value.runs ?? 0} v ${value.opposition || "—"} · ${fmtDateAlmanac(value.start_date)}`
        : `${value.runs}${value.not_out ? "*" : ""} v ${value.opposition || "—"} · ${fmtDateAlmanac(value.start_date)}`;
      return { n, label };
    }
    return { n: Number(value), label: String(value) };
  }).filter((p) => Number.isFinite(p.n));
  if (points.length < 2) return "";
  const nums = points.map((p) => p.n);
  const max = Math.max(...nums, 1);
  const min = Math.min(...nums, 0);
  const span = Math.max(max - min, 1);
  const step = width / (nums.length - 1);
  const pts = nums.map((n, i) => {
    const x = i * step;
    const y = height - 2 - ((n - min) / span) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const dots = points.map((p, i) => {
    const x = i * step;
    const y = height - 2 - ((p.n - min) / span) * (height - 4);
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.4"><title>${esc(p.label)}</title></circle>`;
  }).join("");
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="Last ${points.length} ${key === "wickets" ? "spells" : "innings"}">
    <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts.join(" ")}"/>
    ${dots}
  </svg>`;
}

function ovrTone(n) {
  const v = Number(n);
  if (v <= 10) {
    if (v >= 8.5) return "gold";
    if (v >= 7) return "hot";
    if (v >= 5.5) return "good";
    return "mid";
  }
  if (v >= 99) return "gold";
  if (v >= 90) return "hot";
  if (v >= 80) return "good";
  return "mid";
}

function fmtOvrDate(iso) {
  if (!iso) return "—";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return String(iso).slice(0, 10);
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function fmtOvr(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(1);
}

function ovrCard({ kicker, n, bat, bowl, rank, title }) {
  const ovr = Number(n);
  if (!Number.isFinite(ovr)) return "";
  return `<div class="ovr-badge ovr-${ovrTone(ovr)}" title="${esc(title || kicker)}">
    <div class="ovr-kicker">${esc(kicker)}</div>
    <div class="ovr-n">${fmtOvr(ovr)}</div>
    <div class="ovr-split">
      ${bat != null ? `<span>Bat ${fmtOvr(bat)}</span>` : ""}
      ${bowl != null ? `<span>Bowl ${fmtOvr(bowl)}</span>` : ""}
    </div>
    ${rank ? `<div class="ovr-rank">${esc(rank)}</div>` : ""}
  </div>`;
}

export function overallBadge(form) {
  const cur = form?.hero || form?.current;
  const peak = form?.peak;
  const career = form?.career;
  const rank = form.rank && form.field ? `#${form.rank} of ${form.field}` : "";
  const cards = [];
  const formN = cur?.form;
  const liveIsForm = formN != null && Number(formN) <= 10 && (career?.overall != null || cur?.overall > 10);
  if (form?.retired) {
    const peakSrc = peak?.form != null || peak?.overall != null ? peak : cur;
    const peakN = peakSrc?.overall ?? peakSrc?.form;
    const peakCard = ovrCard({
      kicker: "Peak",
      n: peakN,
      bat: career?.bat ?? cur?.bat,
      bowl: career?.bowl ?? cur?.bowl,
      title: form.caption || "Peak",
    });
    if (peakCard) cards.push(peakCard);
    const ovrN = career?.overall ?? career?.form;
    if (ovrN != null && Number(ovrN) !== Number(peakN)) {
      const ovrHtml = ovrCard({
        kicker: "Overall",
        n: ovrN,
        bat: career?.bat,
        bowl: career?.bowl,
        rank,
        title: "Career overall — Test RAA, Bradman = 99",
      });
      if (ovrHtml) cards.push(ovrHtml);
    }
  } else {
    if (liveIsForm) {
      const formCard = ovrCard({
        kicker: "Form",
        n: formN,
        bat: cur?.bat,
        bowl: cur?.bowl,
        title: form.caption || "Current Test form, 0–10",
      });
      if (formCard) cards.push(formCard);
    } else if (cur) {
      const live = ovrCard({
        kicker: "Overall",
        n: cur.form ?? cur.overall,
        bat: cur.bat,
        bowl: cur.bowl,
        rank,
        title: form.caption || "Form overall",
      });
      if (live) cards.push(live);
    }
    const careerN = career?.overall ?? career?.form;
    if (careerN != null) {
      const careerCard = ovrCard({
        kicker: "Overall",
        n: careerN,
        bat: career?.bat,
        bowl: career?.bowl,
        rank: liveIsForm ? rank : "",
        title: "Career overall — Test RAA, Bradman = 99",
      });
      if (careerCard) cards.push(careerCard);
    }
  }
  if (!cards.length) return "";
  return cards.length === 1 ? cards[0] : `<div class="ovr-stack">${cards.join("")}</div>`;
}

const OVR_LINES = [
  { key: "form", cls: "ovr", label: "Overall", fallback: "overall" },
  { key: "test", cls: "test", label: "Test" },
  { key: "odi", cls: "odi", label: "ODI" },
  { key: "t20i", cls: "t20i", label: "T20I" },
  { key: "t20", cls: "t20", label: "T20" },
];
const OVR_GAP_MS = 140 * 86400000;

function ovrVal(p, key, fallback) {
  const n = p?.[key] ?? (fallback ? p?.[fallback] : null);
  return n == null || n === "" ? null : Number(n);
}

function gappedPath(pts, key, fallback, X, Y) {
  let d = "";
  let prevT = null;
  for (const p of pts) {
    const n = ovrVal(p, key, fallback);
    if (n == null || !Number.isFinite(n)) {
      prevT = null;
      continue;
    }
    const t = new Date(p.as_of).getTime();
    const x = X(t).toFixed(1);
    const y = Y(n).toFixed(1);
    if (prevT != null && t - prevT <= OVR_GAP_MS) d += ` L${x} ${y}`;
    else d += `${d ? " " : ""}M${x} ${y}`;
    prevT = t;
  }
  return d;
}

export function overallChart(series, { width = 720, height = 220, career = null } = {}) {
  const pts = (series || []).filter((p) => p && p.as_of && (
    ovrVal(p, "form", "overall") != null || OVR_LINES.some((s) => ovrVal(p, s.key, s.fallback) != null)
  ));
  if (pts.length < 2) return "";
  const pad = { l: 36, r: 14, t: 16, b: 28 };
  const times = pts.map((p) => new Date(p.as_of).getTime());
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const span = Math.max(t1 - t0, 1);
  const yMin = 50;
  const yMax = 99.9;
  const X = (t) => pad.l + ((t - t0) / span) * (width - pad.l - pad.r);
  const Y = (n) => pad.t + (1 - (Math.max(yMin, Math.min(yMax, Number(n))) - yMin) / (yMax - yMin)) * (height - pad.t - pad.b);
  const years = [];
  const startY = new Date(t0).getFullYear();
  const endY = new Date(t1).getFullYear();
  const step = endY - startY > 16 ? 4 : endY - startY > 8 ? 2 : 1;
  for (let y = startY; y <= endY; y += step) years.push(y);
  const yTicks = [50, 70, 85, 99];
  const last = [...pts].reverse().find((p) => ovrVal(p, "form", "overall") != null) || pts[pts.length - 1];
  const lastN = ovrVal(last, "form", "overall");
  const payload = pts.map((p) => ({
    as_of: p.as_of,
    form: ovrVal(p, "form", "overall"),
    test: ovrVal(p, "test"),
    odi: ovrVal(p, "odi"),
    t20i: ovrVal(p, "t20i"),
    t20: ovrVal(p, "t20"),
    bat: ovrVal(p, "bat"),
    bowl: ovrVal(p, "bowl"),
    is_99: false,
  }));
  const active = OVR_LINES.filter((s) => payload.some((p) => p[s.key] != null));
  return `<figure class="ovr-chart" data-ovr="${esc(JSON.stringify({ pad, width, height, yMin, yMax, t0, t1, pts: payload }))}">
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Form against time">
      ${yTicks.map((t) => `<line class="ovr-grid" x1="${pad.l}" y1="${Y(t).toFixed(1)}" x2="${width - pad.r}" y2="${Y(t).toFixed(1)}"/>
        <text class="ovr-axis" x="${pad.l - 6}" y="${(Y(t) + 3).toFixed(1)}" text-anchor="end">${t}</text>`).join("")}
      ${years.map((y) => {
        const x = X(new Date(y, 0, 1).getTime());
        return `<text class="ovr-axis" x="${x.toFixed(1)}" y="${height - 8}" text-anchor="middle">${y}</text>`;
      }).join("")}
      <line class="ovr-nine" x1="${pad.l}" y1="${Y(99).toFixed(1)}" x2="${width - pad.r}" y2="${Y(99).toFixed(1)}"/>
      ${Number.isFinite(Number(career)) ? `<line class="ovr-career" x1="${pad.l}" y1="${Y(Number(career)).toFixed(1)}" x2="${width - pad.r}" y2="${Y(Number(career)).toFixed(1)}"/>` : ""}
      ${active.map((s) => {
        const d = gappedPath(payload, s.key, s.fallback, X, Y);
        return d ? `<path class="ovr-line ${s.cls}" fill="none" d="${d}"/>` : "";
      }).join("")}
      <line class="ovr-cross" x1="0" x2="0" y1="${pad.t}" y2="${height - pad.b}"/>
      <circle class="ovr-hover-dot" r="4"/>
      <rect class="ovr-hit" x="${pad.l}" y="${pad.t}" width="${width - pad.l - pad.r}" height="${height - pad.t - pad.b}" fill="transparent"/>
    </svg>
    <div class="ovr-tip" hidden></div>
    <figcaption class="ovr-cap">
      ${active.map((s) => `<span class="ovr-key ${s.cls}"><i></i>${s.label}</span>`).join("")}
      ${Number.isFinite(Number(career)) ? `<span class="caption ovr-latest">Career ${fmtOvr(career)}</span>` : ""}
      <span class="caption ovr-latest">Latest ${lastN != null ? fmtOvr(lastN) : "—"} on ${esc(fmtOvrDate(last.as_of))}</span>
    </figcaption>
  </figure>`;
}

export function bindOverallChart(root = document) {
  root.querySelectorAll("figure.ovr-chart").forEach((fig) => {
    if (fig.dataset.bound === "1") return;
    const raw = fig.dataset.ovr;
    if (!raw) return;
    let meta;
    try { meta = JSON.parse(raw); } catch { return; }
    const { pad, width, height, yMin, yMax, t0, t1, pts } = meta;
    if (!pts?.length) return;
    fig.dataset.bound = "1";
    const svg = fig.querySelector("svg");
    const hit = fig.querySelector(".ovr-hit");
    const cross = fig.querySelector(".ovr-cross");
    const dot = fig.querySelector(".ovr-hover-dot");
    const tip = fig.querySelector(".ovr-tip");
    const span = Math.max(t1 - t0, 1);
    const X = (t) => pad.l + ((t - t0) / span) * (width - pad.l - pad.r);
    const Y = (n) => pad.t + (1 - (Math.max(yMin, Math.min(yMax, Number(n))) - yMin) / (yMax - yMin)) * (height - pad.t - pad.b);
    const hide = () => {
      if (cross) { cross.style.visibility = "hidden"; }
      if (dot) { dot.style.visibility = "hidden"; }
      if (tip) { tip.hidden = true; tip.innerHTML = ""; }
    };
    const show = (event) => {
      const rect = svg.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * width;
      let best = pts[0];
      let bestD = Infinity;
      for (const p of pts) {
        const dx = Math.abs(X(new Date(p.as_of).getTime()) - x);
        if (dx < bestD) { best = p; bestD = dx; }
      }
      const t = new Date(best.as_of).getTime();
      const px = X(t);
      const py = Y(best.form ?? 70);
      if (cross) {
        cross.style.visibility = "visible";
        cross.setAttribute("x1", px.toFixed(1));
        cross.setAttribute("x2", px.toFixed(1));
      }
      if (dot && best.form != null) {
        dot.style.visibility = "visible";
        dot.setAttribute("cx", px.toFixed(1));
        dot.setAttribute("cy", py.toFixed(1));
      }
      const rows = [
        ["Overall", best.form],
        ["Test", best.test],
        ["ODI", best.odi],
        ["T20I", best.t20i],
        ["T20", best.t20],
        ["Bat", best.bat],
        ["Bowl", best.bowl],
      ].filter(([, n]) => n != null);
      if (tip) {
        tip.hidden = false;
        tip.innerHTML = `<strong>${esc(fmtOvrDate(best.as_of))}</strong>${rows.map(([lab, n]) =>
          `<span>${lab} <em>${fmtOvr(n)}</em></span>`).join("")}`;
        const figRect = fig.getBoundingClientRect();
        const left = (px / width) * fig.querySelector("svg").getBoundingClientRect().width;
        tip.style.left = `${Math.max(8, Math.min(left + 12, figRect.width - 168))}px`;
        tip.style.top = "8px";
      }
    };
    hit?.addEventListener("mousemove", show);
    hit?.addEventListener("mouseleave", hide);
    svg?.addEventListener("mouseleave", hide);
  });
}

export function overallBlock(form) {
  const cur = form?.hero || form?.current;
  const career = form?.career;
  if (!cur || (cur.form == null && cur.overall == null)) return "";
  const useCareerFmts = Boolean(form.retired && career);
  const src = useCareerFmts ? career : cur;
  const fmts = [
    ["Test", src.test, useCareerFmts ? null : src.bat_test, useCareerFmts ? null : src.bowl_test],
    ["ODI", src.odi, useCareerFmts ? null : src.bat_odi, useCareerFmts ? null : src.bowl_odi],
    ["T20I", src.t20i, useCareerFmts ? null : src.bat_t20i, useCareerFmts ? null : src.bowl_t20i],
    ["T20", src.t20, useCareerFmts ? null : src.bat_t20, useCareerFmts ? null : src.bowl_t20],
  ].filter(([, ovr, bat, bowl]) => ovr != null || bat != null || bowl != null);
  const careerLine = career && career.form != null
    ? `Career ${fmtOvr(career.form)}${career.span ? ` · ${career.span}` : ""}${career.kept && career.n ? ` · better half of ${career.n} months` : ""}${career.cause ? ` · ${career.cause}` : ""}`
    : "";
  const peak = form.peak && (form.peak.form ?? form.peak.overall) != null
    ? `Peak ${fmtOvr(form.peak.form ?? form.peak.overall)} in ${fmtOvrDate(form.peak.as_of)}`
    : "";
  const last = form.current && form.retired
    ? `Last window ${fmtOvr(form.current.form ?? form.current.overall)} on ${fmtOvrDate(form.current.as_of)}`
    : "";
  return `<section class="profile-section ovr-panel" id="profile-form">
    <h2 class="section">Form overall</h2>
    <p class="caption">${esc(form.caption || "")}</p>
    ${fmts.length ? `<div class="ovr-fmts">${fmts.map(([lab, ovr, bat, bowl]) =>
      `<span><strong>${lab}</strong> ${ovr != null ? fmtOvr(ovr) : ""}${bat != null ? ` · bat ${fmtOvr(bat)}` : ""}${bowl != null ? ` · bowl ${fmtOvr(bowl)}` : ""}</span>`
    ).join("")}</div>` : ""}
    ${careerLine ? `<p class="caption">${esc(careerLine)} · <a href="#/rankings?metric=career">Overalls</a></p>` : ""}
    ${peak ? `<p class="caption">${esc(peak)} · <a href="#/rankings?metric=peak">Peak overalls</a></p>` : ""}
    ${last ? `<p class="caption">${esc(last)}</p>` : ""}
    <p class="caption"><a href="#/rankings?metric=overall">Current overalls</a></p>
    ${overallChart(form.series || [], { career: career?.form })}
  </section>`;
}


export function formBlock(innings, { n = 10, careerAvg = null, kind = "bat", careerEcon = null } = {}) {
  const last = (innings || []).slice(0, n);
  if (!last.length) return "";
  if (kind === "bowl") {
    const wickets = last.reduce((s, i) => s + Number(i.wickets || 0), 0);
    const runs = last.reduce((s, i) => s + Number(i.runs || 0), 0);
    const balls = last.reduce((s, i) => s + Number(i.legal_balls || 0), 0);
    const econ = balls ? (runs * 6 / balls) : null;
    const vs = careerEcon != null && econ != null
      ? (econ <= careerEcon ? `, tighter than career ${Number(careerEcon).toFixed(2)}` : `, dearer than career ${Number(careerEcon).toFixed(2)}`)
      : "";
    return `<div class="form-block">
      <div class="form-copy">
        <div class="form-kicker">Last ${last.length} spells</div>
        <div class="form-line">${wickets} wickets · ${econ == null ? "—" : econ.toFixed(2)} econ${vs}</div>
      </div>
      ${sparkline(last.slice().reverse(), { key: "wickets" })}
    </div>`;
  }
  const runs = last.reduce((s, i) => s + Number(i.runs || 0), 0);
  const outs = last.filter((i) => !i.not_out).length;
  const avg = outs ? (runs / outs) : null;
  const values = last.slice().reverse();
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
    `<a href="#/player/${encodeURIComponent(p.slug)}"><circle class="sc-dot" cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.2"><title>${esc(p.name)} · ${esc(xLab)} ${p.x} · ${esc(yLab)} ${p.y}</title></circle></a>`
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

export function fowBeads(falls, maxOvers = 20) {
  falls = falls || [];
  if (!falls.length) return "";
  const overs = Math.max(Number(maxOvers) || 20, 1);
  const step = overs <= 10 ? 2 : overs <= 20 ? 5 : Math.ceil(overs / 5);
  const ticks = [];
  for (let over = 0; over <= overs; over += step) ticks.push(over);
  if (ticks.at(-1) !== overs) ticks.push(overs);
  return `<div class="fow-chart" aria-label="Wicket timeline by over">
    <div class="fow-beads">${falls.map((p, i) => {
      const at = Number(p.over || 0) + Number(p.ball_in_over || 0) / 6;
      const left = Math.max(1, Math.min(99, at / overs * 100));
      const detail = `${p.wicket_number}–${p.runs} · ${p.batter || "Wicket"} · ${p.over}.${p.ball_in_over}`;
      return `<span class="bead lane-${i % 2}" style="left:${left}%" title="${esc(detail)}">${p.wicket_number}</span>`;
    }).join("")}</div>
    <div class="fow-axis">${ticks.map((over) => `<span style="left:${over / overs * 100}%">${over}</span>`).join("")}</div>
  </div>`;
}

export function manhattan(overs, { maxOvers = 0, label = "" } = {}) {
  const rows = (overs || []).map((o) => ({
    over: Number(o.over) || 0,
    runs: Number(o.runs) || 0,
    wickets: Number(o.wickets) || 0,
  }));
  if (rows.length < 3) return "";
  const span = Math.max(maxOvers || 0, ...rows.map((r) => r.over + 1));
  const max = Math.max(...rows.map((r) => r.runs), 6);
  const byOver = new Map(rows.map((r) => [r.over, r]));
  const bars = [];
  for (let i = 0; i < span; i += 1) {
    const r = byOver.get(i);
    const runs = r ? r.runs : 0;
    const wk = r ? r.wickets : 0;
    const h = max ? (runs / max) * 100 : 0;
    const tip = r
      ? `Over ${i + 1}: ${runs} run${runs === 1 ? "" : "s"}${wk ? `, ${wk} wicket${wk === 1 ? "" : "s"}` : ""}`
      : `Over ${i + 1}: not bowled`;
    // A maiden still needs a visible stub, or the chart reads as missing overs.
    const height = r ? Math.max(h, runs ? 4 : 2) : 0;
    bars.push(`<span class="mh-bar${wk ? " has-wkt" : ""}${r ? "" : " empty"}" title="${esc(tip)}">
      <i style="height:${height.toFixed(1)}%"></i>
      ${wk ? `<em class="mh-wkt" aria-hidden="true">${wk > 1 ? wk : ""}</em>` : ""}
    </span>`);
  }
  const ticks = [];
  const step = span <= 20 ? 5 : span <= 50 ? 10 : 20;
  for (let o = step; o <= span; o += step) ticks.push(o);
  const wktOvers = rows.filter((r) => r.wickets).length;
  return `<figure class="manhattan" aria-label="Runs per over${label ? ` — ${esc(label)}` : ""}">
    <figcaption class="mh-cap">${label ? `${esc(label)} · ` : ""}runs per over<span class="mh-key"><i class="mh-swatch"></i>runs<i class="mh-swatch wkt"></i>wicket fell</span></figcaption>
    <div class="mh-plot" style="--mh-max:${max}">${bars.join("")}</div>
    <div class="mh-axis">${ticks.map((o) => `<span style="left:${(o / span) * 100}%">${o}</span>`).join("")}</div>
    <p class="caption">One bar per over, tallest is ${max} run${max === 1 ? "" : "s"}. ${
      wktOvers
        ? `Red bars and the dot above them are the ${wktOvers} over${wktOvers === 1 ? "" : "s"} that brought a wicket.`
        : "No wicket fell in this innings."
    } Hover a bar for the over.</p>
  </figure>`;
}

export function progression(series, { target = null } = {}) {
  const lanes = (series || []).filter((s) => (s.points || []).length > 2);
  if (!lanes.length) return "";
  const w = 640;
  const h = 220;
  const pad = { l: 46, r: 14, t: 12, b: 30 };
  const maxOver = Math.max(...lanes.flatMap((s) => s.points.map((p) => p.over)), 1);
  const maxRuns = Math.max(...lanes.flatMap((s) => s.points.map((p) => p.runs)), Number(target) || 0, 10);
  const X = (o) => pad.l + (o / maxOver) * (w - pad.l - pad.r);
  const Y = (r) => h - pad.b - (r / maxRuns) * (h - pad.t - pad.b);
  const paths = lanes.map((s, i) => {
    const pts = s.points.map((p) => `${X(p.over).toFixed(1)},${Y(p.runs).toFixed(1)}`).join(" ");
    const dots = s.points
      .filter((p) => p.wickets)
      .map((p) => `<circle class="pg-wkt" cx="${X(p.over).toFixed(1)}" cy="${Y(p.runs).toFixed(1)}" r="2.8"><title>${esc(s.team)} ${p.runs} after ${p.over} — wicket</title></circle>`)
      .join("");
    return `<polyline class="pg-line pg-${i}" fill="none" points="${pts}"/>${dots}`;
  }).join("");
  const targetLine = Number(target) > 0
    ? `<line class="pg-target" x1="${pad.l}" y1="${Y(target).toFixed(1)}" x2="${w - pad.r}" y2="${Y(target).toFixed(1)}"/>
       <text class="pg-axis" x="${w - pad.r}" y="${(Y(target) - 5).toFixed(1)}" text-anchor="end">target ${target}</text>`
    : "";
  const yTicks = [0, Math.round(maxRuns / 2), maxRuns];
  const xStep = maxOver <= 20 ? 5 : maxOver <= 50 ? 10 : 20;
  const xTicks = [];
  for (let o = xStep; o <= maxOver; o += xStep) xTicks.push(o);
  return `<figure class="progression">
    <figcaption class="mh-cap">Runs against overs${lanes.map((s, i) => `<span class="pg-key pg-${i}"><i></i>${esc(s.team)}</span>`).join("")}</figcaption>
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Cumulative runs by over for each innings">
      ${yTicks.map((t) => `<line class="pg-grid" x1="${pad.l}" y1="${Y(t).toFixed(1)}" x2="${w - pad.r}" y2="${Y(t).toFixed(1)}"/>
        <text class="pg-axis" x="${pad.l - 6}" y="${(Y(t) + 3).toFixed(1)}" text-anchor="end">${t}</text>`).join("")}
      ${xTicks.map((o) => `<text class="pg-axis" x="${X(o).toFixed(1)}" y="${h - 14}" text-anchor="middle">${o}</text>`).join("")}
      ${targetLine}
      ${paths}
      <text class="pg-axis" x="${w - pad.r}" y="${h - 2}" text-anchor="end">overs</text>
    </svg>
    <p class="caption">Each line is one innings, read left to right as the overs go by. Dots mark the overs where a wicket fell.</p>
  </figure>`;
}

export function performerCards(topBat, topBowl) {
  const bat = (topBat || [])[0];
  const bowl = (topBowl || [])[0];
  if (!bat && !bowl) return "";
  const card = (r, kind) => {
    if (!r) return "";
    const line = kind === "bat"
      ? `${r.line} off ${r.balls ?? "–"}`
      : `${r.line} in ${r.overs ?? "–"}`;
    const foot = kind === "bat"
      ? [r.sr != null ? `${r.sr} SR` : null, r.fours ? `${r.fours}×4` : null, r.sixes ? `${r.sixes}×6` : null]
      : [r.econ != null ? `${r.econ} econ` : null];
    return `<article class="performer">
      <div class="performer-kicker">${kind === "bat" ? "Top score" : "Best spell"}</div>
      <h3>${portrait(r.slug, r.player, "sm")}<a href="#/player/${esc(r.slug)}">${esc(r.player)}</a></h3>
      <div class="performer-line">${esc(line)}</div>
      <p class="caption">${esc(r.team || "")}${foot.filter(Boolean).length ? ` · ${foot.filter(Boolean).join(" · ")}` : ""}</p>
    </article>`;
  };
  return `<div class="performers">${card(bat, "bat")}${card(bowl, "bowl")}</div>`;
}

export function statCards(items) {
  const list = (items || []).filter(Boolean);
  if (!list.length) return "";
  return `<div class="stat-cards">${list.map((c) => `
    <article class="stat-card">
      <div class="sc-kicker">${esc(c.kicker || "")}</div>
      <div class="sc-figure">${c.value == null || c.value === "" ? "–" : c.value}</div>
      ${c.note ? `<p class="caption">${esc(c.note)}</p>` : ""}
      ${c.href ? `<a class="sc-link" href="${c.href}">${esc(c.linkLabel || "Open")}</a>` : ""}
    </article>`).join("")}</div>`;
}

const RECENT_KEY = "wm-recent";

export function recentList() {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function recentPush(slug, name) {
  if (!slug) return;
  const list = recentList().filter((r) => r.slug !== slug);
  list.unshift({ slug, name: name || slug });
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 12)));
  } catch { /* storage full or blocked */ }
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
  const keysBtn = $("keys-toggle");
  if (keysBtn) keysBtn.setAttribute("aria-expanded", "false");
}

function openSheet(id) {
  ensureOverlay();
  closeOverlays();
  $(id).hidden = false;
  $("overlay-scrim").hidden = false;
  document.body.classList.add("overlay-open");
}

export function openKeys() {
  openSheet("keys-sheet");
  $("keys-toggle")?.setAttribute("aria-expanded", "true");
}
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
  const recents = recentList().slice(0, 4);
  const defaults = `
    ${recents.length ? `<h4>Recently viewed</h4>${recents.map((r) => `<button type="button" data-hash="#/player/${esc(r.slug)}">${portrait(r.slug, r.name, "xs")}<span>${esc(r.name)}</span></button>`).join("")}<h4>Pages</h4>` : ""}
    <button type="button" data-hash="#/stats">Stats</button>
    <button type="button" data-hash="#/records">Record book</button>
    <button type="button" data-hash="#/rankings?metric=career">Overall</button>
    <button type="button" data-hash="#/rankings?metric=peak">Peak</button>
    <button type="button" data-hash="#/rankings?metric=overall">Current form</button>
    <button type="button" data-hash="#/rankings">Rankings</button>
    <button type="button" data-hash="#/standings">Standings</button>
    <button type="button" data-hash="#/grounds">Grounds</button>
    <button type="button" data-hash="#/wowy">WOWY</button>
    <button type="button" data-hash="#/best">Best T20</button>
    <button type="button" data-hash="#/compare">Compare</button>`;
  list.innerHTML = defaults;
  bindPaletteButtons(list);
  warmPortraits(list);
  requestAnimationFrame(() => input.focus());
  input.oninput = async () => {
    const q = input.value.trim();
    if (q.length < 2) {
      list.innerHTML = defaults;
      bindPaletteButtons(list);
      warmPortraits(list);
      return;
    }
    const innings = !/:\S/.test(q) && /[a-z]/i.test(q) ? q.match(/^(.*\S)\s+(\d{1,3})$/) : null;
    const s = await (await fetch(`/api/suggest?q=${encodeURIComponent(q)}`)).json();
    let html = "";
    const read = s.parsed?.interpretation || (innings ? `Find ${innings[2]} by ${innings[1]}` : "");
    if (read && (innings || s.parsed?.tokens?.opposition || s.parsed?.mode === "matches")) {
      html += `<button type="button" data-hash="#/q=${encodeURIComponent(q)}">${esc(read)} <span class="hint">search</span></button>`;
    }
    (s.people || []).slice(0, 8).forEach((p) => {
      const hint = p.unique_name && p.unique_name !== p.display_name ? ` <span class="hint">${esc(p.unique_name)}</span>` : "";
      html += `<button type="button" data-hash="#/player/${esc(p.slug)}">${portrait(p.slug, p.display_name, "xs")}<span>${esc(p.display_name)}${hint}</span></button>`;
    });
    (s.teams || []).slice(0, 4).forEach((t) => {
      const name = t.team || t;
      html += `<button type="button" data-hash="#/team?name=${encodeURIComponent(name)}">${esc(name)} <span class="hint">team record</span></button>`;
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

// The topbar wraps to two rows at some widths, so sticky sub-navs and anchor
// targets have to follow its measured height rather than a fixed guess.
function measureTopbar() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  const open = document.body.classList.contains("nav-open");
  const h = open ? 3.5 * 16 : bar.getBoundingClientRect().height;
  document.documentElement.style.setProperty("--topbar-h", `${Math.round(h)}px`);
}

export function initChrome(h) {
  hooks = h || {};
  ensureOverlay();
  applyDensity(localStorage.getItem(DENSITY_KEY) || "comfortable");
  restoreTray();
  renderTray();
  $("keys-toggle")?.addEventListener("click", openKeys);
  const navToggle = $("nav-toggle");
  navToggle?.addEventListener("click", () => {
    const open = document.body.classList.toggle("nav-open");
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    measureTopbar();
  });
  window.addEventListener("hashchange", () => {
    document.body.classList.remove("nav-open");
    navToggle?.setAttribute("aria-expanded", "false");
    measureTopbar();
  });
  measureTopbar();
  if (typeof ResizeObserver === "function") {
    const bar = document.querySelector(".topbar");
    if (bar) new ResizeObserver(measureTopbar).observe(bar);
  } else {
    window.addEventListener("resize", measureTopbar);
  }
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
    else if (e.key === "r" || e.key === "R") { e.preventDefault(); location.hash = "#/records"; }
    else if (e.key === "s" || e.key === "S") { e.preventDefault(); location.hash = "#/stats"; }
    else if (e.key === "h" || e.key === "H") { e.preventDefault(); location.hash = "#/"; }
    else if (e.key === "y" || e.key === "Y") { e.preventDefault(); copyText(location.href); }
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
