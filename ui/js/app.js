import { highlightHTML, heuristic, upsertToken } from "./querybox.js";

const $ = (id) => document.getElementById(id);
const input = $("query-input");
const highlight = $("query-highlight");
const ghost = $("query-ghost");
const ac = $("ac");
const main = $("main");
const chipsEl = $("chips");
const homeHero = $("home-hero");
const homeExtras = $("home-extras");
const queryWrap = $("query-wrap");

const CHIPS = [
  "kohli",
  "bumrah",
  "kohli 89",
  "compare:smith,root years:2021-2026",
  "pair:* comp:ipl",
  "standings comp:ipl year:2025",
];

let acItems = [];
let acIndex = -1;
let settings = { theme: "charcoal", weights: { rae: 0.45, wpa: 0.35, consistency: 0.20 } };
let page = 0;
const PAGE_SIZE = 100;

function syncHighlight() {
  highlight.innerHTML = highlightHTML(input.value) || "";
  const h = heuristic(input.value);
  ghost.hidden = !h;
  ghost.textContent = h;
}

async function loadStatus() {
  const s = await (await fetch("/api/status")).json();
  $("data-date").textContent = s.last_pull_display && s.last_pull_display !== "—"
    ? `Data: ${s.last_pull_display}`
    : "Data: —";
  return s;
}

async function loadSettings() {
  settings = await (await fetch("/api/settings")).json();
  applyTheme(settings.theme || "charcoal");
}

function applyTheme(theme) {
  settings.theme = theme === "paper" ? "paper" : "charcoal";
  document.documentElement.dataset.theme = settings.theme;
  const btn = $("theme-toggle");
  if (btn) btn.textContent = settings.theme === "charcoal" ? "Light" : "Dark";
}

async function saveTheme(theme) {
  applyTheme(theme);
  await fetch("/api/settings", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ theme: settings.theme }),
  });
}

function setQuery(q, { run = false } = {}) {
  input.value = q;
  syncHighlight();
  if (run) runQuery();
}

function currentQuery() {
  return input.value.trim();
}

async function runQuery() {
  const q = currentQuery();
  location.hash = q ? `#/q=${encodeURIComponent(q)}` : "#/";
}

function renderChips() {
  chipsEl.innerHTML = CHIPS.map((c) => `<button class="chip" type="button">${esc(c)}</button>`).join("");
  chipsEl.querySelectorAll(".chip").forEach((b) => {
    b.addEventListener("click", () => setQuery(b.textContent, { run: true }));
  });
}

$("fmt-row")?.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-fmt]");
  if (!btn) return;
  $("fmt-row").querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
  const fmt = btn.dataset.fmt;
  let q = currentQuery();
  q = upsertToken(q, "format", fmt || "");
  setQuery(q);
});

$("theme-toggle")?.addEventListener("click", () => {
  saveTheme(settings.theme === "charcoal" ? "paper" : "charcoal");
});

input.addEventListener("input", async () => {
  syncHighlight();
  const v = input.value;
  const word = v.split(/\s+/).pop() || "";
  if (word.endsWith(":") || word.length >= 2) {
    const s = await (await fetch(`/api/suggest?q=${encodeURIComponent(word)}`)).json();
    renderAC(s);
  } else {
    ac.classList.remove("open");
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    if (ac.classList.contains("open") && acIndex >= 0 && acItems[acIndex]) {
      acceptAC(acItems[acIndex]);
    } else {
      ac.classList.remove("open");
      runQuery();
    }
  } else if (e.key === "Escape") {
    ac.classList.remove("open");
    input.blur();
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    acIndex = Math.min(acItems.length - 1, acIndex + 1);
    paintAC();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    acIndex = Math.max(0, acIndex - 1);
    paintAC();
  } else if (e.key === "Tab" && ac.classList.contains("open") && acItems[acIndex]) {
    e.preventDefault();
    acceptAC(acItems[acIndex]);
  }
});

function renderAC(s) {
  acItems = [];
  let html = "";
  if (s.people?.length) {
    html += `<h4>People</h4>`;
    s.people.forEach((p) => {
      acItems.push({ kind: "person", slug: p.slug, name: p.display_name, unique: p.unique_name });
      html += `<button type="button" data-i="${acItems.length - 1}">${esc(p.display_name)} <span class="hint">${esc(p.unique_name)}</span></button>`;
    });
  }
  if (s.teams?.length) {
    html += `<h4>Teams</h4>`;
    s.teams.forEach((t) => {
      const name = t.team || t;
      acItems.push({ kind: "team", team: name });
      html += `<button type="button" data-i="${acItems.length - 1}">${esc(name)} <span class="hint">WOWY</span></button>`;
    });
  }
  if (s.destinations?.length) {
    html += `<h4>Go to</h4>`;
    s.destinations.forEach((d) => {
      acItems.push({ kind: "dest", id: d.id });
      html += `<button type="button" data-i="${acItems.length - 1}">${esc(d.label)} <span class="hint">${esc(d.hint)}</span></button>`;
    });
  }
  ac.innerHTML = html;
  ac.classList.toggle("open", acItems.length > 0);
  acIndex = acItems.length ? 0 : -1;
  paintAC();
  ac.querySelectorAll("button").forEach((b) => {
    b.addEventListener("mousedown", (e) => {
      e.preventDefault();
      acceptAC(acItems[Number(b.dataset.i)]);
    });
  });
}

function paintAC() {
  ac.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === acIndex));
}

function acceptAC(item) {
  ac.classList.remove("open");
  if (item.kind === "person") {
    location.hash = `#/player/${item.slug}`;
    return;
  }
  if (item.kind === "team") {
    location.hash = `#/wowy?team=${encodeURIComponent(item.team)}`;
    return;
  }
  if (item.kind === "dest") {
    location.hash = `#/${item.id}`;
    return;
  }
  const parts = input.value.split(/\s+/);
  parts.pop();
  if (item.kind === "token") parts.push(`${item.key}:`);
  input.value = parts.join(" ").replace(/\s+/g, " ");
  syncHighlight();
  input.focus();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== input) {
    e.preventDefault();
    input.focus();
  }
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  ));
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }).replace(/ /g, " ");
}

function num(v, d = 0) {
  if (v == null || v === "") return `<span class="muted">–</span>`;
  const n = Number(v);
  if (Number.isNaN(n)) return esc(v);
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function signed(v, d = 1) {
  if (v == null) return `<span class="muted">–</span>`;
  const n = Number(v);
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return s + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function table(columns, rows, { pageIndex = 0, total = rows.length, query = "" } = {}) {
  const start = pageIndex * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  const head = columns.map((c) => `<th class="${c.align === "right" ? "num" : ""}" scope="col">${esc(c.label)}</th>`).join("");
  const body = slice.map((r) => {
    const milestone = (r.runs >= 100) || (r.wickets >= 5) || (r.hundreds >= 1 && r.kind === "x");
    const isHundred = Number(r.runs) >= 100 || String(r.runs_display || "").startsWith("100") || Number(r.runs) >= 100;
    const isFive = Number(r.wickets) >= 5;
    const cls = (isHundred || isFive) ? "milestone" : "";
    const cells = columns.map((c) => {
      let val = r[c.key];
      if (c.key === "start_date") val = fmtDate(r.start_date);
      if (c.key === "primary_role") val = val === "bowl" ? "Bowl" : val === "bat" ? "Bat" : val;
      if (c.link === "player") {
        val = `<a href="#/player/${esc(r.slug || r.person_id)}">${esc(r.player || r.display_name || val)}</a>`;
      } else if (c.key === "match" || (c.link === "match")) {
        val = `<a href="#/match/${esc(r.match_id)}">${esc(val || r.opposition || r.match_id)}</a>`;
      } else if (c.numeric) {
        const raw = r[c.key];
        if (typeof raw === "string" && raw.endsWith("*")) {
          val = `<span class="fig">${esc(raw)}</span>`;
        } else if (c.key === "runs_display") {
          val = `<span class="fig">${esc(raw ?? "–")}</span>`;
        } else {
          val = num(raw, Number.isInteger(Number(raw)) ? 0 : 1);
        }
      } else if (val == null || val === "") {
        val = `<span class="muted">–</span>`;
      } else {
        val = esc(val);
      }
      if (c.key === "opposition" || c.key === "result") {
        val = `<a href="#/match/${esc(r.match_id)}">${val}</a>`;
      }
      return `<td class="${c.align === "right" ? "num" : ""}">${val}</td>`;
    }).join("");
    return `<tr class="${cls}">${cells}</tr>`;
  }).join("");
  const shown = slice.length;
  const more = total > start + shown ? `Showing ${start + 1}–${start + shown} of ${total.toLocaleString()} — refine or export all` : "";
  return `
    <div class="table-wrap">
      <table class="data">
        <thead><tr>${head}</tr></thead>
        <tbody>${body || `<tr><td colspan="${columns.length}" class="muted">No rows</td></tr>`}</tbody>
      </table>
      <div class="table-foot">
        <span>${more}</span>
        <span>
          ${total > PAGE_SIZE ? `<button class="btn-text" data-page="prev">Prev</button> <button class="btn-text" data-page="next">Next</button>` : ""}
          <button class="btn-text" data-export="${esc(query)}">Export CSV</button>
          <button class="btn-text" data-sql>Open in SQL</button>
        </span>
      </div>
    </div>`;
}

function bindTable(query) {
  main.querySelectorAll("[data-page]").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.page === "next") page += 1;
      else page = Math.max(0, page - 1);
      route();
    });
  });
  main.querySelector("[data-export]")?.addEventListener("click", () => {
    location.href = `/api/export?q=${encodeURIComponent(query)}`;
  });
  main.querySelector("[data-sql]")?.addEventListener("click", () => {
    location.hash = "#/sql";
  });
}

function setHero(isHome) {
  homeHero.hidden = !isHome;
  homeExtras.hidden = !isHome;
  queryWrap.classList.toggle("hero", isHome);
  queryWrap.classList.toggle("slim", !isHome);
  document.querySelectorAll(".util a").forEach((a) => {
    a.classList.toggle("active", location.hash.startsWith(a.getAttribute("href")));
  });
}

async function showHomeSnapshot() {
  const snap = await (await fetch("/api/snapshot")).json();
  if (!snap.rows?.length) {
    main.innerHTML = `<div class="error">Warehouse not built yet. Run: <code class="cmd">python -m cricwarehouse pull && python -m cricwarehouse build</code> — or open the <a href="#/build">Build</a> page.</div>`;
    return;
  }
  const cols = [
    { key: "competition", label: "Competition", align: "left" },
    { key: "gender", label: "Gender", align: "left" },
    { key: "matches", label: "Matches", align: "right", numeric: true },
    { key: "range", label: "Date range", align: "left" },
  ];
  main.innerHTML = `<p class="scope">${snap.deliveries?.toLocaleString()} deliveries in warehouse</p>` +
    table(cols, snap.rows, { query: "" });
}

async function showResults(q) {
  setHero(false);
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const res = await (await fetch(`/api/query?q=${encodeURIComponent(q)}`)).json();
  if (!res.ok) {
    main.innerHTML = `<div class="error">${esc(res.error)} <button class="btn-text" data-copy>Copy</button></div>`;
    return;
  }
  if (res.kind === "goto_player" && res.person?.slug) {
    location.hash = `#/player/${res.person.slug}`;
    return;
  }
  if (res.kind === "goto_page" && res.hash) {
    location.hash = `#${res.hash}`;
    return;
  }
  if (res.kind === "pick_player") {
    main.innerHTML = `<div class="empty"><p>${esc(res.message || "Several players match.")}</p>
      ${(res.people || []).map((p) => `<button class="chip" data-go="${esc(p.slug)}">${esc(p.display_name)} <span class="hint">${esc(p.unique_name)}</span></button>`).join(" ")}</div>`;
    main.querySelectorAll("[data-go]").forEach((b) => {
      b.addEventListener("click", () => { location.hash = `#/player/${b.dataset.go}`; });
    });
    return;
  }
  if (res.kind === "compare") return renderCompare(res);
  if (res.kind === "empty") {
    main.innerHTML = `<div class="empty"><p>${esc(res.message || res.empty_hint?.message || "Nothing matched.")}</p>
      ${(res.empty_hint?.chips || []).map((c) => `<button class="chip">${esc(c)}</button>`).join(" ")}</div>`;
    main.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => setQuery(b.textContent, { run: true })));
    return;
  }
  const ignored = (res.parsed?.ignored || []).map((t) => `ignored: ${t}`).join(" · ");
  const people = res.people || [];
  let disamb = "";
  if (people.length > 1) {
    disamb = `<div class="scope">${people.length} players match — ${people.map((p) =>
      `<button class="chip" data-slug="${esc(p.slug)}">${esc(p.display_name)}</button>`).join(" ")}</div>`;
  }
  main.innerHTML = `
    ${disamb}
    <p class="scope">${esc(res.scope || "")}${ignored ? ` · <span class="ignored">${esc(ignored)}</span>` : ""}</p>
    ${res.kind === "standings" && res.playoffs?.length ? `<h2 class="section">Points table</h2>` : ""}
    ${table(res.columns || [], res.rows || [], { pageIndex: page, total: (res.rows || []).length, query: q })}
    ${res.kind === "standings" && res.playoffs?.length ? playoffBlock(res.playoffs) : ""}
    ${res.wpa != null ? `<p class="caption">WPA when present in T20s: ${signed(res.wpa, 2)} in this warehouse.</p>` : ""}
  `;
  bindTable(q);
  main.querySelectorAll("[data-slug]").forEach((b) => {
    b.addEventListener("click", () => setQuery(upsertToken(q, "player", b.dataset.slug), { run: true }));
  });
}

function playoffBlock(playoffs) {
  const cols = [
    { key: "start_date", label: "Date", align: "left" },
    { key: "event_stage", label: "Stage", align: "left" },
    { key: "team_home", label: "Home", align: "left" },
    { key: "team_away", label: "Away", align: "left" },
    { key: "winner", label: "Winner", align: "left" },
  ];
  return `<h2 class="section">Playoffs</h2>` + table(cols, playoffs);
}

function renderCompare(res) {
  const rows = res.rows.map((r, i) => {
    const lb = r.lower_better;
    let dcls = "";
    if (r.delta != null) {
      const favLeft = lb ? r.delta < 0 : r.delta > 0;
      dcls = r.delta === 0 ? "" : favLeft ? "pos" : "neg";
    }
    const note = lb && i === res.rows.findIndex((x) => x.lower_better) ? ` <span class="caption">↓ better</span>` : "";
    return `<tr>
      <td class="stat">${esc(r.stat)}${note}</td>
      <td class="num">${r.left == null ? "–" : esc(r.left)}</td>
      <td class="delta ${dcls}">${r.delta == null ? "" : signed(r.delta, Number.isInteger(r.delta) ? 0 : 1)}</td>
      <td class="num">${r.right == null ? "–" : esc(r.right)}</td>
    </tr>`;
  }).join("");
  main.innerHTML = `
    <p class="scope">${esc(res.scope)}</p>
    <table class="compare-grid">
      <thead><tr>
        <th></th>
        <th><a href="#/player/${esc(res.left.slug)}">${esc(res.left.display_name)}</a></th>
        <th>Δ</th>
        <th><a href="#/player/${esc(res.right.slug)}">${esc(res.right.display_name)}</a></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="caption">${esc(res.caption)}</p>
  `;
}

async function showMatch(id) {
  setHero(false);
  setQuery("");
  main.classList.add("wide");
  const d = await (await fetch(`/api/match/${id}`)).json();
  const m = d.match;
  const badges = [];
  if (m.result_method === "dls") badges.push("DLS");
  if (m.result_method === "super_over") badges.push("Super Over");
  if (m.result_method === "no_result") badges.push("No result");
  if (m.result_method === "tie") badges.push("Tie");
  const result = m.winner
    ? `${m.winner} won` + (m.win_by_runs ? ` by ${m.win_by_runs} runs` : m.win_by_wickets ? ` by ${m.win_by_wickets} wickets` : "")
    : (m.result || "No result");
  let html = `
    <h1 class="page-title">${esc(m.team_home)} v ${esc(m.team_away)}</h1>
    <p>${esc(result)}</p>
    <p class="meta-line">${fmtDate(m.start_date)} · ${esc(m.venue || "")} · ${esc(m.competition?.toUpperCase())} · Toss: ${esc(m.toss_winner)} ${esc(m.toss_decision || "")}
      ${badges.map((b) => `<span class="badge">${b}</span>`).join(" ")}</p>
  `;
  for (const inn of d.innings) {
    const label = inn.innings_kind === "super_over" ? "Super Over" : `Innings ${inn.innings}`;
    const ov = (inn.legal_balls / (m.balls_per_over || 6)).toFixed(1);
    html += `<h2 class="section">${label} — ${esc(inn.batting_team)} ${inn.runs}/${inn.wickets} (${ov})</h2>`;
    const bats = d.batting.filter((b) => b.innings === inn.innings);
    const bowls = d.bowling.filter((b) => b.innings === inn.innings);
    const parts = d.partnerships.filter((p) => p.innings === inn.innings);
    html += table(
      [
        { key: "display_name", label: "Batter", align: "left", link: "player" },
        { key: "dismissal_kind", label: "Dismissal", align: "left" },
        { key: "runs_display", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "fours", label: "4s", align: "right", numeric: true },
        { key: "sixes", label: "6s", align: "right", numeric: true },
        { key: "sr", label: "SR", align: "right", numeric: true },
      ],
      bats.map((b) => ({
        ...b,
        player: b.display_name,
        slug: b.slug,
        runs_display: b.not_out ? `${b.runs}*` : String(b.runs),
        sr: b.balls ? (b.runs * 100 / b.balls).toFixed(1) : "–",
      })),
    );
    html += table(
      [
        { key: "display_name", label: "Bowler", align: "left", link: "player" },
        { key: "overs", label: "O", align: "right", numeric: true },
        { key: "maidens", label: "M", align: "right", numeric: true },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "econ", label: "Econ", align: "right", numeric: true },
        { key: "extras", label: "Extras", align: "right", numeric: true },
      ],
      bowls.map((b) => {
        const o = Math.floor((b.legal_balls || 0) / (m.balls_per_over || 6));
        const r = (b.legal_balls || 0) % (m.balls_per_over || 6);
        const balls = b.legal_balls || 0;
        return {
          ...b,
          player: b.display_name,
          slug: b.slug,
          overs: `${o}.${r}`,
          econ: balls ? (b.runs * 6 / balls).toFixed(2) : "–",
        };
      }),
    );
    const fow = parts.filter((p) => p.end_reason && p.end_reason !== "end_of_innings")
      .map((p) => `${p.wicket_number}-${p.runs}`).join(", ");
    if (fow) html += `<p class="fow">Fall of wickets: ${esc(fow)}</p>`;
    html += `<h3 class="section">Partnerships</h3>`;
    html += table(
      [
        { key: "wicket_number", label: "Wkt", align: "right", numeric: true },
        { key: "pair", label: "Pair", align: "left" },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "end_reason", label: "End", align: "left" },
      ],
      parts.map((p) => ({ ...p, pair: `${p.name_1} / ${p.name_2}` })),
    );
  }
  const n = d.deliveries.length;
  html += `<button class="drawer" id="del-toggle">Show ${n} deliveries ▸</button>
    <div id="del-table" hidden></div>`;
  main.innerHTML = html;
  $("del-toggle")?.addEventListener("click", () => {
    const box = $("del-table");
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = table(
      [
        { key: "ball", label: "Over.Ball", align: "left" },
        { key: "bowler_name", label: "Bowler", align: "left" },
        { key: "striker_name", label: "Striker", align: "left" },
        { key: "runs_total", label: "Runs", align: "right", numeric: true },
        { key: "extra_type", label: "Extras", align: "left" },
        { key: "wicket_kind", label: "Wicket", align: "left" },
      ],
      d.deliveries.map((x) => ({ ...x, ball: `${x.over}.${x.ball_in_over}` })),
    );
  });
}

async function showPlayer(key) {
  setHero(false);
  const d = await (await fetch(`/api/player/${key}`)).json();
  if (d.detail) {
    main.innerHTML = `<div class="empty"><p>No player ${esc(key)}.</p></div>`;
    return;
  }
  const p = d.person;
  const bowlerFirst = d.primary_role === "bowl";
  setQuery(p.display_name);
  const val = d.value || {};
  const order = bowlerFirst
    ? ["war", "war_per_season", "rae_bowl", "rae_bat", "wpa", "pressure"]
    : ["war", "war_per_season", "rae_bat", "rae_bowl", "wpa", "pressure"];
  const byKey = Object.fromEntries((val.metrics || []).map((m) => [m.key, m]));
  const fmtVal = (m) => {
    if (!m || m.value == null) return "–";
    const dec = { war: 2, war_per_season: 2, rae_bat: 1, rae_bowl: 1, wpa: 3, pressure: 1 }[m.key] ?? 1;
    const n = Number(m.value);
    const s = n.toFixed(dec);
    return (n > 0 && m.key !== "war_per_season" && m.key !== "war" ? "+" : "") + (m.key === "war" || m.key === "war_per_season" || n < 0 ? (n > 0 && (m.key === "war" || m.key === "war_per_season") ? s : s) : s);
  };
  const pools = (d.person?.gender === "female" || (d.summary || []).some((s) => s.competition === "wpl"))
    ? [["t20i_wpl", "T20I + WPL"], ["t20i", "T20I"], ["wpl", "WPL"], ["t20", "All T20"]]
    : [["t20i_ipl", "T20I + IPL"], ["t20i", "T20I"], ["ipl", "IPL"], ["t20", "All T20"]];
  const poolBtns = pools.map(([id, lab]) =>
    `<button class="tab ${val.pool === id ? "active" : ""}" data-pool="${id}">${lab}</button>`
  ).join("");
  let cards = "";
  if (val.metrics?.length) {
    cards = `
      <div class="fmt-row" id="val-pools">${poolBtns}</div>
      <p class="scope">Career · ${val.seasons} season${val.seasons === 1 ? "" : "s"} · ${esc(val.pool_label || "")} · ${val.n?.toLocaleString()} players in this pool</p>
      <div class="metric-row" id="val-cards">${order.map((k) => {
        const m = byKey[k];
        if (!m) return "";
        return `<div class="metric-card">
          <div class="name">${esc(m.label)} <span class="info" tabindex="0">i<span class="pop">${esc(m.copy)}</span></span></div>
          <div class="val ${Number(m.value) < 0 ? "neg" : ""}">${fmtVal(m)}</div>
          <div class="sc">#${m.rank} of ${Number(m.of).toLocaleString()}</div>
        </div>`;
      }).join("")}</div>
      <p class="caption">Career totals — more games count. WAR / season is the same pile, divided. In this warehouse, not an official rating.</p>`;
  } else {
    cards = `<p class="caption">${bowlerFirst ? "Bowler first — more balls bowled than faced in this warehouse." : "Ball-derived T20 metrics appear when T20I / IPL rows exist (see MODEL.md)."}</p>`;
  }
  const pf = d.performances?.rows || [];
  const h2h = d.matchups || { as_batter: [], as_bowler: [] };
  const h2hComps = [...new Set([...(h2h.as_batter || []), ...(h2h.as_bowler || [])].map((r) => r.competition))];
  const comps = [...new Set([
    ...d.summary.map((s) => s.competition),
    ...d.bowling_summary.map((s) => s.competition),
  ])];
  const tabs = ["all", ...comps].map((c) => `<button class="tab ${c === "all" ? "active" : ""}" data-comp="${c}">${c === "all" ? "All" : c.toUpperCase()}</button>`).join("");
  const batRows = d.summary.map((s) => {
    const avg = s.outs ? (s.runs / s.outs).toFixed(1) : "—";
    const sr = s.balls ? (s.runs * 100 / s.balls).toFixed(1) : "—";
    return { ...s, avg, sr, hs: s.hs };
  });
  const bowlRows = d.bowling_summary.map((s) => {
    const overs = s.legal_balls ? `${Math.floor(s.legal_balls / 6)}.${s.legal_balls % 6}` : "–";
    const avg = s.wickets ? (s.runs / s.wickets).toFixed(1) : "—";
    const econ = s.legal_balls ? (s.runs * 6 / s.legal_balls).toFixed(2) : "—";
    return { ...s, overs, avg, econ };
  });
  const bowlTable = `<h2 class="section">Bowling</h2>` + table(
    [
      { key: "competition", label: "Comp", align: "left" },
      { key: "matches", label: "M", align: "right", numeric: true },
      { key: "overs", label: "O", align: "right", numeric: true },
      { key: "maidens", label: "Mdns", align: "right", numeric: true },
      { key: "runs", label: "R", align: "right", numeric: true },
      { key: "wickets", label: "W", align: "right", numeric: true },
      { key: "avg", label: "Avg", align: "right", numeric: true },
      { key: "econ", label: "Econ", align: "right", numeric: true },
    ],
    bowlRows,
  );
  const batTable = `<h2 class="section">Batting</h2>` + table(
    [
      { key: "competition", label: "Comp", align: "left" },
      { key: "matches", label: "M", align: "right", numeric: true },
      { key: "inns", label: "Inns", align: "right", numeric: true },
      { key: "runs", label: "Runs", align: "right", numeric: true },
      { key: "hs", label: "HS", align: "right", numeric: true },
      { key: "avg", label: "Avg", align: "right", numeric: true },
      { key: "sr", label: "SR", align: "right", numeric: true },
      { key: "hundreds", label: "100s", align: "right", numeric: true },
      { key: "fifties", label: "50s", align: "right", numeric: true },
    ],
    batRows,
  );
  main.innerHTML = `
    <h1 class="page-title">${esc(p.display_name)}</h1>
    <p class="meta-line">${esc(p.unique_name)} · ${bowlerFirst ? "Bowler" : "Batter"} first · ${esc(d.span.line)}</p>
    ${cards}
    <h2 class="section">Best T20</h2>
    <p class="caption">0–100 percentile within that competition’s history. NRC, WPA, and pressure blended — not raw runs added.</p>
    <div class="fmt-row" id="pf-tabs">
      <button class="tab ${bowlerFirst ? "" : "active"}" data-disc="bat">Batting</button>
      <button class="tab ${bowlerFirst ? "active" : ""}" data-disc="bowl">Bowling</button>
    </div>
    <div id="pf-box"></div>
    <h2 class="section">Batter vs bowler</h2>
    <p class="caption">Balls they actually faced each other. Twelve-ball floor. Every format they share.</p>
    <div class="fmt-row" id="h2h-tabs">${["all", ...h2hComps].map((c, i) => `<button class="tab ${i === 0 ? "active" : ""}" data-h2h="${c}">${c === "all" ? "All" : c.toUpperCase()}</button>`).join("")}</div>
    <div id="h2h-box"></div>
    <div class="fmt-row" id="p-tabs">${tabs}</div>
    ${bowlerFirst ? bowlTable + batTable : batTable + bowlTable}
    <p class="caption">Fielding in this warehouse: ${d.fielding.catches} catches · ${d.fielding.run_outs} run-outs · ${d.fielding.stumpings} stumpings</p>
    <h2 class="section">${bowlerFirst ? "Bowling innings" : "Batting innings"}</h2>
    <div id="inn-box"></div>
    ${bowlerFirst ? `<h2 class="section">Batting innings</h2><div id="bat-box"></div>` : (d.bowling_innings?.length ? `<h2 class="section">Bowling innings</h2><div id="bowl-box"></div>` : "")}
    <h2 class="section">Partnerships</h2>
    ${table(
      [
        { key: "partner", label: "Pair", align: "left" },
        { key: "inns", label: "Inns", align: "right", numeric: true },
        { key: "runs", label: "Runs", align: "right", numeric: true },
        { key: "avg", label: "Avg", align: "right", numeric: true },
        { key: "hundreds", label: "100-stands", align: "right", numeric: true },
      ],
      d.pairs,
    )}
  `;
  const paintBat = (comp, el) => {
    const rows = d.innings.filter((i) => comp === "all" || i.competition === comp).map((i) => ({
      ...i,
      runs_display: i.not_out ? `${i.runs}*` : String(i.runs),
      sr: i.balls ? (i.runs * 100 / i.balls).toFixed(1) : "–",
      result: i.winner === i.team ? "Won" : i.winner ? "Lost" : "—",
      player: p.display_name,
      slug: p.slug,
    }));
    el.innerHTML = table(
      [
        { key: "start_date", label: "Date", align: "left" },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "runs_display", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "sr", label: "SR", align: "right", numeric: true },
        { key: "dismissal_kind", label: "Dismissal", align: "left" },
        { key: "result", label: "Result", align: "left" },
      ],
      rows,
    );
  };
  const paintBowl = (comp, el) => {
    const rows = (d.bowling_innings || []).filter((i) => comp === "all" || i.competition === comp).map((i) => {
      const overs = i.legal_balls ? `${Math.floor(i.legal_balls / 6)}.${i.legal_balls % 6}` : "–";
      const econ = i.legal_balls ? (i.runs * 6 / i.legal_balls).toFixed(2) : "–";
      return { ...i, overs, econ, player: p.display_name, slug: p.slug };
    });
    el.innerHTML = table(
      [
        { key: "start_date", label: "Date", align: "left" },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "overs", label: "O", align: "right", numeric: true },
        { key: "maidens", label: "M", align: "right", numeric: true },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "econ", label: "Econ", align: "right", numeric: true },
      ],
      rows,
    );
  };
  const paint = (comp) => {
    if (bowlerFirst) {
      paintBowl(comp, $("inn-box"));
      if ($("bat-box")) paintBat(comp, $("bat-box"));
    } else {
      paintBat(comp, $("inn-box"));
      if ($("bowl-box")) paintBowl(comp, $("bowl-box"));
    }
  };
  paint("all");
  $("p-tabs")?.addEventListener("click", (e) => {
    const t = e.target.closest("[data-comp]");
    if (!t) return;
    $("p-tabs").querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    paint(t.dataset.comp);
  });
  const paintPf = (disc) => {
    const rows = pf.filter((r) => r.discipline === disc).slice(0, 15).map((r) => ({
      ...r,
      player: p.display_name,
      slug: p.slug,
    }));
    $("pf-box").innerHTML = table(
      [
        { key: "score", label: "Score", align: "right", numeric: true },
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "line", label: "Line", align: "left" },
        { key: "venue", label: "Venue", align: "left" },
        { key: "result", label: "Result", align: "left" },
      ],
      rows,
    );
  };
  paintPf(bowlerFirst ? "bowl" : "bat");
  $("pf-tabs")?.addEventListener("click", (e) => {
    const t = e.target.closest("[data-disc]");
    if (!t) return;
    $("pf-tabs").querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    paintPf(t.dataset.disc);
  });
  const paintH2h = (comp) => {
    const filt = (rows) => (rows || []).filter((r) => comp === "all" || r.competition === comp).slice(0, 12);
    const bat = filt(h2h.as_batter).map((r) => ({ ...r, player: r.opponent, slug: r.opp_slug }));
    const bowl = filt(h2h.as_bowler).map((r) => ({ ...r, player: r.opponent, slug: r.opp_slug }));
    const batT = table(
      [
        { key: "player", label: "Bowler", align: "left", link: "player" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "line", label: "Line", align: "left" },
        { key: "sr", label: "SR", align: "right", numeric: true },
        { key: "dismissals", label: "Out", align: "right", numeric: true },
      ],
      bat,
    );
    const bowlT = table(
      [
        { key: "player", label: "Batter", align: "left", link: "player" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "line", label: "Line", align: "left" },
        { key: "econ", label: "Econ", align: "right", numeric: true },
        { key: "dismissals", label: "W", align: "right", numeric: true },
      ],
      bowl,
    );
    $("h2h-box").innerHTML = `<div class="h2h">${bowlerFirst ? `<div><h3 class="section">Bowled to</h3>${bowlT}</div><div><h3 class="section">Faced</h3>${batT}</div>` : `<div><h3 class="section">Faced</h3>${batT}</div><div><h3 class="section">Bowled to</h3>${bowlT}</div>`}</div>`;
  };
  paintH2h("all");
  $("h2h-tabs")?.addEventListener("click", (e) => {
    const t = e.target.closest("[data-h2h]");
    if (!t) return;
    $("h2h-tabs").querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    paintH2h(t.dataset.h2h);
  });
  $("val-pools")?.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-pool]");
    if (!t) return;
    $("val-pools").querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    const nv = await (await fetch(`/api/player/${p.slug}/value?pool=${encodeURIComponent(t.dataset.pool)}`)).json();
    const map = Object.fromEntries((nv.metrics || []).map((m) => [m.key, m]));
    const scope = $("val-pools")?.nextElementSibling;
    if (scope && scope.classList.contains("scope")) {
      scope.textContent = `Career · ${nv.seasons || 0} season${nv.seasons === 1 ? "" : "s"} · ${nv.pool_label || ""} · ${(nv.n || 0).toLocaleString()} players in this pool`;
    }
    const row = $("val-cards");
    if (!row) return;
    row.innerHTML = order.map((k) => {
      const m = map[k];
      if (!m) return "";
      return `<div class="metric-card">
        <div class="name">${esc(m.label)} <span class="info" tabindex="0">i<span class="pop">${esc(m.copy)}</span></span></div>
        <div class="val ${Number(m.value) < 0 ? "neg" : ""}">${fmtVal(m)}</div>
        <div class="sc">#${m.rank} of ${Number(m.of).toLocaleString()}</div>
      </div>`;
    }).join("");
  });
}

async function showStats() {
  setHero(false);
  main.classList.add("wide");
  const state = { comp: "t20i_ipl", gender: "male", role: "all", sort: "war", min_inns: 8, wtc: false };
  const paint = async () => {
    if (state.gender === "female" && state.comp === "t20i_ipl") state.comp = "t20i_wpl";
    if (state.gender === "male" && state.comp === "t20i_wpl") state.comp = "t20i_ipl";
    const qs = new URLSearchParams({ role: state.role, sort: state.sort, min_inns: String(state.min_inns), wtc: state.wtc ? "true" : "false" });
    if (state.comp) qs.set("comp", state.comp);
    if (state.gender) qs.set("gender", state.gender);
    const d = await (await fetch(`/api/stats?${qs}`)).json();
    const fmtOpts = state.gender === "female"
      ? [["t20i_wpl","T20I + WPL"],["t20i","T20I"],["wpl","WPL"],["odi","ODI"],["test","Tests"],["wbbl","WBBL"],["","All"]]
      : [["t20i_ipl","T20I + IPL"],["t20i","T20I"],["ipl","IPL"],["odi","ODI"],["test","Tests"],["bbl","BBL"],["","All"]];
    main.innerHTML = `
      <h1 class="page-title">Stats</h1>
      <p class="lede">Counting stats and T20 value in one table. Default pool is T20I plus the main T20 league. Percentiles are within this filtered set.</p>
      <div class="filters">
        <label>Format
          <select id="st-comp">
            ${fmtOpts.map(([k,l]) => `<option value="${k}" ${state.comp===k?"selected":""}>${l}</option>`).join("")}
          </select>
        </label>
        <label>Gender
          <select id="st-g">
            <option value="male" ${state.gender==="male"?"selected":""}>Men</option>
            <option value="female" ${state.gender==="female"?"selected":""}>Women</option>
          </select>
        </label>
        <label>Role
          <select id="st-role">
            <option value="all">All</option>
            <option value="bat" ${state.role==="bat"?"selected":""}>Batters first</option>
            <option value="bowl" ${state.role==="bowl"?"selected":""}>Bowlers first</option>
          </select>
        </label>
        <label>Sort
          <select id="st-sort">
            ${[["war","WAR"],["war_per_season","WAR / season"],["rae_bat","RAE bat"],["rae_bowl","RAE bowl"],["wpa","WPA"],["runs","Runs"],["wickets","Wickets"],["avg","Bat avg"],["sr","Strike rate"],["bowl_avg","Bowl avg"],["econ","Econ"]].map(([k,l]) => `<option value="${k}" ${state.sort===k?"selected":""}>${l}</option>`).join("")}
          </select>
        </label>
        <label class="check"><input type="checkbox" id="st-wtc" ${state.wtc?"checked":""}> WTC sides only</label>
      </div>
      <p class="scope">${esc(d.scope || "")}</p>
      <div id="st-table"></div>`;
    const cols = [
      { key: "rank", label: "#", align: "right", numeric: true },
      { key: "player", label: "Player", align: "left", link: "player" },
      { key: "primary_role", label: "Role", align: "left" },
      { key: "matches", label: "M", align: "right", numeric: true },
      { key: "war", label: "WAR", align: "right", numeric: true },
      { key: "war_per_season", label: "WAR/yr", align: "right", numeric: true },
      { key: "rae_bat", label: "RAE bat", align: "right", numeric: true },
      { key: "rae_bowl", label: "RAE bowl", align: "right", numeric: true },
      { key: "runs", label: "Runs", align: "right", numeric: true },
      { key: "avg", label: "Avg", align: "right", numeric: true },
      { key: "wickets", label: "W", align: "right", numeric: true },
      { key: "econ", label: "Econ", align: "right", numeric: true },
    ];
    $("st-table").innerHTML = table(cols, d.rows || []);
    const bind = (id, key) => $(id)?.addEventListener("change", (e) => { state[key] = e.target.value; paint(); });
    bind("st-comp", "comp");
    bind("st-g", "gender");
    bind("st-role", "role");
    bind("st-sort", "sort");
    $("st-wtc")?.addEventListener("change", (e) => { state.wtc = e.target.checked; paint(); });
  };
  await paint();
}

async function showWowy() {
  setHero(false);
  const hash = decodeURIComponent(location.hash);
  const qteam = /[?&]team=([^&]+)/.exec(hash)?.[1] || "India";
  const qplayer = /[?&]player=([^&]+)/.exec(hash)?.[1] || "";
  const teams = await (await fetch("/api/teams")).json();
  main.innerHTML = `
    <h1 class="page-title">WOWY</h1>
    <p class="lede">With or without you — only from the player’s first XI for that side. Matches before they existed don’t count as “without”.</p>
    <div class="filters">
      <label>Team
        <input type="text" id="wy-team" list="wy-teams" value="${esc(qteam)}" placeholder="India">
        <datalist id="wy-teams">${(teams.teams || []).map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
      </label>
      <label>Player
        <input type="text" id="wy-player" value="${esc(qplayer)}" placeholder="Bumrah">
      </label>
      <label>Format
        <select id="wy-comp">
          <option value="">All</option>
          ${["test","odi","t20i","ipl"].map((c) => `<option value="${c}">${c.toUpperCase()}</option>`).join("")}
        </select>
      </label>
      <button class="btn primary" id="wy-go">Run split</button>
    </div>
    <div id="wy-out"></div>`;
  const run = async () => {
    const team = $("wy-team").value.trim();
    const player = $("wy-player").value.trim();
    if (!team || !player) {
      $("wy-out").innerHTML = `<p class="caption">Pick a team and a player.</p>`;
      return;
    }
    const qs = new URLSearchParams({ team, player });
    const comp = $("wy-comp").value;
    if (comp) qs.set("comp", comp);
    const d = await (await fetch(`/api/wowy?${qs}`)).json();
    if (d.people?.length > 1 && !d.rows?.length) {
      $("wy-out").innerHTML = `<p>${esc(d.message || "Several matches")}</p>` +
        d.people.map((p) => `<button class="chip" data-p="${esc(p.slug)}">${esc(p.display_name)}</button>`).join(" ");
      $("wy-out").querySelectorAll("[data-p]").forEach((b) => {
        b.addEventListener("click", () => { $("wy-player").value = b.dataset.p; run(); });
      });
      return;
    }
    $("wy-out").innerHTML = `<p class="scope">${esc(d.scope || "")}</p>` +
      table(
        [
          { key: "split", label: "Split", align: "left" },
          { key: "matches", label: "N", align: "right", numeric: true },
          { key: "wins", label: "Wins", align: "right", numeric: true },
          { key: "win_pct", label: "Win %", align: "right", numeric: true },
          { key: "runs_for", label: "Runs for", align: "right", numeric: true },
          { key: "runs_against", label: "Runs against", align: "right", numeric: true },
          { key: "wickets", label: "Wkts taken", align: "right", numeric: true },
        ],
        d.rows || [],
      ) + `<p class="disclaimer">${esc(d.caption || "")}</p>`;
  };
  $("wy-go").addEventListener("click", run);
  if (qplayer) run();
}

async function showBest() {
  setHero(false);
  main.classList.add("wide");
  const state = { discipline: "bat", comp: "t20i_ipl", gender: "male" };
  const paint = async () => {
    const qs = new URLSearchParams({ discipline: state.discipline, limit: "40", gender: state.gender });
    if (state.comp) qs.set("comp", state.comp);
    const d = await (await fetch(`/api/best?${qs}`)).json();
    main.innerHTML = `
      <h1 class="page-title">Best T20</h1>
      <p class="lede">Highest-scoring innings and spells in this warehouse. Scores are percentiles within each competition’s history.</p>
      <div class="filters">
        <label>Discipline
          <select id="bt-d">
            <option value="bat" ${state.discipline==="bat"?"selected":""}>Batting</option>
            <option value="bowl" ${state.discipline==="bowl"?"selected":""}>Bowling</option>
          </select>
        </label>
        <label>Format
          <select id="bt-c">
            ${[["t20i_ipl","T20I + IPL"],["t20i","T20I"],["ipl","IPL"],["t20","All T20"]].map(([k,l]) => `<option value="${k}" ${state.comp===k?"selected":""}>${l}</option>`).join("")}
          </select>
        </label>
        <label>Gender
          <select id="bt-g">
            <option value="male" ${state.gender==="male"?"selected":""}>Men</option>
            <option value="female" ${state.gender==="female"?"selected":""}>Women</option>
          </select>
        </label>
      </div>
      <p class="caption">${esc(d.caption || "")}</p>
      <div id="bt-table"></div>`;
    $("bt-table").innerHTML = table(
      [
        { key: "score", label: "Score", align: "right", numeric: true },
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "competition", label: "Comp", align: "left" },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "line", label: "Line", align: "left" },
        { key: "venue", label: "Venue", align: "left" },
        { key: "result", label: "Result", align: "left" },
      ],
      d.rows || [],
    );
    $("bt-d").addEventListener("change", (e) => { state.discipline = e.target.value; paint(); });
    $("bt-c").addEventListener("change", (e) => { state.comp = e.target.value; paint(); });
    $("bt-g").addEventListener("change", (e) => { state.gender = e.target.value; paint(); });
  };
  await paint();
}

async function showMetrics() {
  setHero(false);
  setQuery("war");
  const state = { comp: "ipl", gender: "male", season: "", role: "", qual: true, weights: { ...settings.weights } };
  const paint = async () => {
    const qs = new URLSearchParams({ comp: state.comp, gender: state.gender, qualifiers: state.qual });
    if (state.season) qs.set("season", state.season);
    if (state.role) qs.set("role", state.role);
    const d = await (await fetch(`/api/metrics?${qs}`)).json();
    if (!state.season && d.season) state.season = d.season;
    const seasons = (d.seasons || []).map((s) => `<option ${s === state.season ? "selected" : ""}>${esc(s)}</option>`).join("");
    const rows = d.rows.map((r) => {
      const overall = recomputeOverall(r, state.weights);
      return { ...r, player: r.display_name, overall_live: overall };
    });
    main.innerHTML = `
      <div class="metrics-layout">
        <aside class="rail">
          <fieldset>
            <legend>Competition</legend>
            ${["t20i","ipl","wpl","bbl","wbbl"].map((c) =>
              `<label><input type="radio" name="comp" value="${c}" ${state.comp===c?"checked":""}> ${c.toUpperCase()}</label>`).join("")}
          </fieldset>
          <fieldset>
            <legend>Season</legend>
            <select id="m-season">${seasons}</select>
          </fieldset>
          <fieldset>
            <legend>Gender</legend>
            <label><input type="radio" name="gender" value="male" ${state.gender==="male"?"checked":""}> Men</label>
            <label><input type="radio" name="gender" value="female" ${state.gender==="female"?"checked":""}> Women</label>
          </fieldset>
          <fieldset>
            <legend>Qualifier</legend>
            <label><input type="checkbox" id="m-qual" ${state.qual?"checked":""}> Qualifiers only</label>
          </fieldset>
          <fieldset>
            <legend>Weights</legend>
            ${slider("rae","RAE", state.weights.rae)}
            ${slider("wpa","WPA", state.weights.wpa)}
            ${slider("consistency","Consistency", state.weights.consistency)}
            <p class="caption" id="w-sum">${state.weights.rae.toFixed(2)} / ${state.weights.wpa.toFixed(2)} / ${state.weights.consistency.toFixed(2)}</p>
            <button class="btn-text" id="w-reset">Reset to defaults</button>
            <button class="btn-text" id="w-save">Save preset…</button>
            <p class="disclaimer">A utility function you control — not an official rating.</p>
          </fieldset>
          <button class="btn primary" id="rerank">Re-rank by Overall</button>
        </aside>
        <div>
          <h2 class="section">${esc(d.scope || "WAR")}</h2>
          <div id="m-table"></div>
        </div>
      </div>`;
    const draw = (sortOverall = false) => {
      const view = rows.map((r) => ({ ...r, overall: r.overall_live }));
      if (sortOverall) view.sort((a, b) => b.overall - a.overall);
      view.forEach((r, i) => { r.rank = i + 1; });
      $("m-table").innerHTML = table(
        [
          { key: "rank", label: "#", align: "right", numeric: true },
          { key: "player", label: "Player", align: "left", link: "player" },
          { key: "role", label: "Role", align: "left" },
          { key: "balls", label: "Balls", align: "right", numeric: true },
          { key: "rae_bat", label: "RAE", align: "right", numeric: true },
          { key: "wpa", label: "WPA", align: "right", numeric: true },
          { key: "pressure_impact", label: "Pressure", align: "right", numeric: true },
          { key: "overall", label: "Overall", align: "right", numeric: true },
          { key: "war", label: "WAR", align: "right", numeric: true },
        ],
        view,
        { query: `war comp:${state.comp}` },
      );
    };
    draw(false);
    main.querySelectorAll("[name=comp]").forEach((el) => el.addEventListener("change", () => { state.comp = el.value; paint(); }));
    main.querySelectorAll("[name=gender]").forEach((el) => el.addEventListener("change", () => { state.gender = el.value; paint(); }));
    $("m-season")?.addEventListener("change", (e) => { state.season = e.target.value; paint(); });
    $("m-qual")?.addEventListener("change", (e) => { state.qual = e.target.checked; paint(); });
    main.querySelectorAll("input[type=range]").forEach((el) => {
      el.addEventListener("input", () => {
        const key = el.dataset.k;
        const next = Number(el.value);
        const others = Object.keys(state.weights).filter((k) => k !== key);
        const remain = Math.max(0.01, 1 - next);
        const sumO = others.reduce((a, k) => a + state.weights[k], 0) || 1;
        state.weights[key] = next;
        others.forEach((k) => { state.weights[k] = remain * (state.weights[k] / sumO); });
        main.querySelectorAll("input[type=range]").forEach((r) => { r.value = state.weights[r.dataset.k]; });
        main.querySelectorAll(".w").forEach((w) => { w.textContent = state.weights[w.dataset.k].toFixed(2); });
        $("w-sum").textContent = `${state.weights.rae.toFixed(2)} / ${state.weights.wpa.toFixed(2)} / ${state.weights.consistency.toFixed(2)}`;
        rows.forEach((r) => { r.overall_live = recomputeOverall(r, state.weights); });
        draw(false);
      });
    });
    $("w-reset")?.addEventListener("click", () => {
      state.weights = { rae: 0.45, wpa: 0.35, consistency: 0.20 };
      paint();
    });
    $("w-save")?.addEventListener("click", async () => {
      const name = prompt("Preset name");
      if (!name) return;
      await fetch("/api/presets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, weights: state.weights }) });
    });
    $("rerank")?.addEventListener("click", () => draw(true));
  };
  await paint();
}

function slider(key, label, val) {
  return `<label>${label}</label>
    <div class="slider">
      <input type="range" min="0" max="1" step="0.05" value="${val}" data-k="${key}">
      <span class="w" data-k="${key}">${val.toFixed(2)}</span>
    </div>`;
}

function recomputeOverall(r, w) {
  const base = Number(r.overall_default) || 70;
  const tilt = (w.rae - 0.45) * (Number(r.rae_bat) || 0) / 50 + (w.wpa - 0.35) * (Number(r.wpa) || 0) * 4;
  return Math.max(40, Math.min(99, +(base + tilt).toFixed(1)));
}

async function showBuild() {
  setHero(false);
  const s = await (await fetch("/api/status")).json();
  const snap = await (await fetch("/api/snapshot")).json();
  const mb = (s.warehouse_bytes / (1024 * 1024)).toFixed(1);
  main.innerHTML = `
    <h1 class="page-title">Build</h1>
    <h2 class="section">Status</h2>
    <p>Last pull: ${esc(s.last_pull_display)} · Source: Cricsheet · Warehouse: ${mb} MB on disk · model ${esc(s.model_version)}</p>
    <h2 class="section">Counts</h2>
    ${table(
      [
        { key: "competition", label: "Competition", align: "left" },
        { key: "gender", label: "Gender", align: "left" },
        { key: "matches", label: "Matches", align: "right", numeric: true },
        { key: "range", label: "Date range", align: "left" },
      ],
      snap.rows || [],
    )}
    <h2 class="section">Actions</h2>
    <button class="btn primary" id="do-pull">Pull updates</button>
    <button class="btn primary" id="do-metrics">Rebuild metrics</button>
    <div class="log" id="job-log"></div>
  `;
  const run = (kind, btn) => {
    btn.disabled = true;
    const log = $("job-log");
    log.textContent = "";
    const es = new EventSource(`/api/job/${kind}`);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.done) { es.close(); btn.disabled = false; loadStatus(); return; }
        log.textContent += data + "\n";
        log.scrollTop = log.scrollHeight;
      } catch {
        log.textContent += ev.data + "\n";
      }
    };
    es.onerror = () => { es.close(); btn.disabled = false; };
  };
  $("do-pull").addEventListener("click", (e) => run("pull", e.target));
  $("do-metrics").addEventListener("click", (e) => run("metrics", e.target));
}

async function showSQL() {
  setHero(false);
  const views = await (await fetch("/api/views")).json();
  main.innerHTML = `
    <h1 class="page-title">SQL</h1>
    <p class="caption">Read-only · documented views only</p>
    <div class="sql-layout">
      <div class="sql-views">${views.views.map((v) => `<button data-v="${v}">${v}</button>`).join("")}</div>
      <div style="flex:1">
        <textarea class="sql-editor" id="sql">SELECT * FROM v_matches LIMIT 100</textarea>
        <p><button class="btn primary" id="run-sql">Run</button></p>
        <div id="sql-out"></div>
      </div>
    </div>`;
  main.querySelectorAll("[data-v]").forEach((b) => {
    b.addEventListener("click", () => { $("sql").value = `SELECT * FROM ${b.dataset.v} LIMIT 100`; });
  });
  $("run-sql").addEventListener("click", async () => {
    const res = await (await fetch("/api/sql", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ sql: $("sql").value }),
    })).json();
    if (!res.ok) {
      $("sql-out").innerHTML = `<pre class="log">${esc(res.error)}</pre>`;
      return;
    }
    $("sql-out").innerHTML = table(res.columns, res.rows);
  });
}

async function showDocs(name = "model") {
  setHero(false);
  const d = await (await fetch(`/api/docs/${name}`)).json();
  main.innerHTML = `<article class="docs-body">${d.html}</article>`;
}

async function route() {
  main.classList.remove("wide");
  const hash = decodeURIComponent(location.hash.replace(/^#/, "") || "/");
  if (hash.startsWith("/q=")) {
    const q = hash.slice(3);
    input.value = q;
    syncHighlight();
    setHero(false);
    await showResults(q);
    return;
  }
  const parts = hash.split("/").filter(Boolean);
  const head = parts[0] || "";
  if (!head) {
    setHero(true);
    setQuery("");
    await showHomeSnapshot();
    return;
  }
  if (head === "match") return showMatch(parts[1]);
  if (head === "player") return showPlayer(parts[1]);
  if (head === "stats") return showStats();
  if (head.startsWith("wowy")) return showWowy();
  if (head === "rankings") return showStats();
  if (head === "best") return showBest();
  if (head === "metrics" || head === "war") return showMetrics();
  if (head === "standings") {
    setQuery("standings comp:ipl");
    return showResults("standings comp:ipl");
  }
  if (head === "build") return showBuild();
  if (head === "sql") return showSQL();
  if (head === "docs") return showDocs(parts[1] || "model");
  setHero(true);
  await showHomeSnapshot();
}

window.addEventListener("hashchange", () => { page = 0; route(); });

(async function init() {
  renderChips();
  await loadSettings();
  await loadStatus();
  syncHighlight();
  await route();
})();
