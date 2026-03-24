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
const queryShell = $("query-shell");
const searchToggle = $("search-toggle");
const searchScrim = $("search-scrim");

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

searchToggle?.addEventListener("click", () => {
  if (document.body.classList.contains("search-open")) closeSearch();
  else openSearch();
});
searchScrim?.addEventListener("click", closeSearch);

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
    if (document.body.classList.contains("search-open")) closeSearch();
    else input.blur();
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
    closeSearch();
    location.hash = `#/player/${item.slug}`;
    return;
  }
  if (item.kind === "team") {
    closeSearch();
    location.hash = `#/wowy?team=${encodeURIComponent(item.team)}`;
    return;
  }
  if (item.kind === "dest") {
    closeSearch();
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
  const tag = document.activeElement?.tagName;
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  if (e.key === "/" && !typing) {
    e.preventDefault();
    openSearch();
  }
  if (e.key === "Escape" && document.body.classList.contains("search-open")) {
    closeSearch();
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

function flattenCols(columns) {
  const out = [];
  for (const c of columns) {
    if (c.group) out.push(...c.cols);
    else out.push(c);
  }
  return out;
}

function tableHead(columns) {
  const th = (c, extra = "") => {
    const cls = [c.align === "right" || c.numeric ? "num" : "name", extra].filter(Boolean).join(" ");
    return `<th class="${cls}" scope="col"${c.rowspan ? ` rowspan="${c.rowspan}"` : ""}${c.colspan ? ` colspan="${c.colspan}"` : ""}>${esc(c.label)}</th>`;
  };
  if (!columns.some((c) => c.group)) {
    return `<tr>${columns.map((c) => th(c)).join("")}</tr>`;
  }
  const top = [];
  const bot = [];
  for (const c of columns) {
    if (c.group) {
      top.push(`<th class="num grp" colspan="${c.cols.length}" scope="colgroup">${esc(c.group)}</th>`);
      for (const s of c.cols) bot.push(th(s, "sub"));
    } else {
      top.push(th({ ...c, rowspan: 2 }));
    }
  }
  return `<tr>${top.join("")}</tr><tr>${bot.join("")}</tr>`;
}

function table(columns, rows, { pageIndex = 0, total = rows.length, query = "" } = {}) {
  const start = pageIndex * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  const cols = flattenCols(columns);
  const head = tableHead(columns);
  const body = slice.map((r) => {
    const milestone = (r.runs >= 100) || (r.wickets >= 5) || (r.hundreds >= 1 && r.kind === "x");
    const isHundred = Number(r.runs) >= 100 || String(r.runs_display || "").startsWith("100") || Number(r.runs) >= 100;
    const isFive = Number(r.wickets) >= 5;
    const cls = (isHundred || isFive) ? "milestone" : "";
    const cells = cols.map((c) => {
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
          const digits = c.digits ?? (c.key === "war_per_game" ? 3 : (c.key === "rae_bat" || c.key === "rae_bowl" ? 2 : (Number.isInteger(Number(raw)) ? 0 : 1)));
          if (c.delta && raw != null && raw !== "") {
            const n = Number(raw);
            const better = c.delta === "lower" ? n < 0 : n > 0;
            const dcls = n === 0 ? "" : better ? "pos" : "neg";
            val = `<span class="delta ${dcls}">${signed(n, digits)}</span>`;
          } else {
            val = num(raw, digits);
          }
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
        <thead>${head}</thead>
        <tbody>${body || `<tr><td colspan="${cols.length}" class="muted">No rows</td></tr>`}</tbody>
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
  queryWrap.classList.remove("slim");
  queryShell.classList.toggle("docked", !isHome);
  searchToggle.hidden = isHome;
  if (isHome) closeSearch();
  document.querySelectorAll(".util a").forEach((a) => {
    const href = a.getAttribute("href");
    const on = location.hash.startsWith(href) || (href === "#/compare" && ["#/teams", "#/twin", "#/shift"].some((p) => location.hash.startsWith(p)));
    a.classList.toggle("active", on);
  });
}

function openSearch() {
  if (!searchToggle.hidden) {
    document.body.classList.add("search-open");
    searchToggle.setAttribute("aria-expanded", "true");
    searchScrim.hidden = false;
  }
  requestAnimationFrame(() => input.focus());
}

function closeSearch() {
  document.body.classList.remove("search-open");
  searchToggle.setAttribute("aria-expanded", "false");
  searchScrim.hidden = true;
  ac.classList.remove("open");
  input.blur();
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
  const val = d.value || {};
  const order = bowlerFirst
    ? ["war", "war_per_game", "rae_bowl", "rae_bat", "wpa", "pressure"]
    : ["war", "war_per_game", "rae_bat", "rae_bowl", "wpa", "pressure"];
  const byKey = Object.fromEntries((val.metrics || []).map((m) => [m.key, m]));
  const fmtVal = (m) => {
    if (!m || m.value == null) return "–";
    const dec = { war: 2, war_per_game: 3, rae_bat: 2, rae_bowl: 2, wpa: 3, pressure: 1 }[m.key] ?? 1;
    const n = Number(m.value);
    const s = n.toFixed(dec);
    return (n > 0 && m.key !== "war_per_game" && m.key !== "war" ? "+" : "") + s;
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
      <p class="scope">Career · ${(val.games || 0).toLocaleString()} game${val.games === 1 ? "" : "s"} · ${esc(val.pool_label || "")} · ${val.n?.toLocaleString()} players in this pool</p>
      <div class="metric-row" id="val-cards">${order.map((k) => {
        const m = byKey[k];
        if (!m) return "";
        return `<div class="metric-card">
          <div class="name">${esc(m.label)} <span class="info" tabindex="0">i<span class="pop">${esc(m.copy)}</span></span></div>
          <div class="val ${Number(m.value) < 0 ? "neg" : ""}">${fmtVal(m)}</div>
          <div class="sc">#${m.rank} of ${Number(m.of).toLocaleString()}</div>
        </div>`;
      }).join("")}</div>
      <p class="caption">Career totals — more games count. WAR / game is the same pile, divided by matches in this pool. In this warehouse, not an official rating.</p>`;
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
    <p class="studio-links">
      <a href="#/compare?a=${encodeURIComponent(p.slug)}">Compare</a>
      · <a href="#/twin?player=${encodeURIComponent(p.slug)}">Profile twin</a>
      · <a href="#/shift?player=${encodeURIComponent(p.slug)}">Stat line shift</a>
    </p>
    ${cards}
    <h2 class="section">Best T20 ${bowlerFirst ? "bowling" : "batting"}</h2>
    <p class="caption">${esc(d.performances?.caption || "Focused on the heavier workload. Same-match work in the other discipline is in the line.")}</p>
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
  const paintPf = () => {
    const disc = bowlerFirst ? "bowl" : "bat";
    const rows = pf.filter((r) => !r.discipline || r.discipline === disc || r.discipline === "match").slice(0, 15).map((r) => ({
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
  paintPf();
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
      scope.textContent = `Career · ${(nv.games || 0).toLocaleString()} game${nv.games === 1 ? "" : "s"} · ${nv.pool_label || ""} · ${(nv.n || 0).toLocaleString()} players in this pool`;
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
            ${[["war","WAR"],["war_per_game","WAR / game"],["rae_bat","RAE bat / game"],["rae_bowl","RAE bowl / game"],["wpa","WPA"],["runs","Runs"],["wickets","Wickets"],["avg","Bat avg"],["sr","Strike rate"],["bowl_avg","Bowl avg"],["econ","Econ"]].map(([k,l]) => `<option value="${k}" ${state.sort===k?"selected":""}>${l}</option>`).join("")}
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
      { key: "war_per_game", label: "WAR/g", align: "right", numeric: true },
      { key: "rae_bat", label: "RAE bat/g", align: "right", numeric: true },
      { key: "rae_bowl", label: "RAE bowl/g", align: "right", numeric: true },
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
  const state = { mode: "composite", disc: "bowl", comp: "t20i_ipl", gender: "male", wtc: true };
  const paint = async () => {
    const qs = new URLSearchParams({ limit: "40", gender: state.gender, wtc: state.wtc ? "true" : "false", mode: state.mode });
    if (state.comp) qs.set("comp", state.comp);
    if (state.mode !== "composite") qs.set("discipline", state.disc);
    const d = await (await fetch(`/api/best?${qs}`)).json();
    main.innerHTML = `
      <h1 class="page-title">Best T20</h1>
      <p class="lede">Match composites by default — batting and bowling from the same night, balls-weighted. Tick WTC to drop associate internationals.</p>
      <div class="filters">
        <label>View
          <select id="bt-m">
            <option value="composite" ${state.mode==="composite"?"selected":""}>Match composite</option>
            <option value="single" ${state.mode==="single"?"selected":""}>Single innings / spell</option>
          </select>
        </label>
        ${state.mode === "single" ? `<label>Discipline
          <select id="bt-d">
            <option value="bat" ${state.disc==="bat"?"selected":""}>Batting</option>
            <option value="bowl" ${state.disc==="bowl"?"selected":""}>Bowling</option>
          </select>
        </label>` : ""}
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
        <label class="check"><input type="checkbox" id="bt-wtc" ${state.wtc?"checked":""}> WTC sides only</label>
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
    $("bt-m").addEventListener("change", (e) => { state.mode = e.target.value; paint(); });
    $("bt-d")?.addEventListener("change", (e) => { state.disc = e.target.value; paint(); });
    $("bt-c").addEventListener("change", (e) => { state.comp = e.target.value; paint(); });
    $("bt-g").addEventListener("change", (e) => { state.gender = e.target.value; paint(); });
    $("bt-wtc")?.addEventListener("change", (e) => { state.wtc = e.target.checked; paint(); });
  };
  await paint();
}

function hashParam(name) {
  const q = decodeURIComponent(location.hash).split("?")[1] || "";
  return new URLSearchParams(q).get(name) || "";
}

function pickList(people, side) {
  return `<div class="empty"><p>Several matches — pick ${side}.</p>${(people || []).map((p) =>
    `<button class="chip" data-go="${esc(p.slug)}">${esc(p.display_name)}</button>`).join(" ")}</div>`;
}

function compareFormats(female) {
  return female
    ? [["t20i_wpl", "T20I + WPL"], ["t20i", "T20I"], ["wpl", "WPL"], ["odi", "ODI"], ["test", "Tests"], ["t20", "All T20"]]
    : [["t20i_ipl", "T20I + IPL"], ["t20i", "T20I"], ["ipl", "IPL"], ["odi", "ODI"], ["test", "Tests"], ["t20", "All T20"]];
}

function formatSelect(id, current, female) {
  const opts = compareFormats(female);
  return `<label>Format
    <select id="${id}">
      ${opts.map(([k, l]) => `<option value="${k}" ${current === k ? "selected" : ""}>${l}</option>`).join("")}
    </select>
  </label>`;
}

function shiftFormats() {
  return [
    ["t20i_ipl", "T20I + IPL"],
    ["t20i_wpl", "T20I + WPL"],
    ["t20i", "T20I"],
    ["ipl", "IPL"],
    ["wpl", "WPL"],
    ["odi", "ODI"],
    ["test", "Tests"],
    ["t20", "All T20"],
  ];
}

function goCompare() {
  const a = $("c-a")?.value.trim() || hashParam("a");
  const b = $("c-b")?.value.trim() || hashParam("b");
  const comp = $("c-comp")?.value || hashParam("comp") || "t20i_ipl";
  if (!a || !b) return;
  location.hash = `#/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&comp=${encodeURIComponent(comp)}`;
}

function matchupBoard(batter, bowler, st, poolLabel, pool) {
  if (!st) return "";
  const overs = st.balls ? `${Math.floor(st.balls / 6)}.${st.balls % 6}` : "–";
  const avg = st.avg != null ? st.avg : (st.dismissals ? (st.runs / st.dismissals).toFixed(1) : "–");
  const tests = pool === "test";
  const stats = tests
    ? [
        { n: st.runs, k: "Runs" },
        { n: st.balls, k: "Balls" },
        { n: avg, k: "Avg", lead: true },
        { n: st.dismissals, k: "Out" },
      ]
    : [
        { n: st.runs, k: "Runs" },
        { n: st.balls, k: "Balls" },
        { n: st.sr ?? "–", k: "Strike rate" },
        { n: st.dismissals, k: "Out" },
      ];
  const footBits = tests
    ? [avg === "–" ? "Not dismissed" : null, st.sr != null ? `${st.sr} SR` : null, st.econ != null ? `${st.econ} econ` : null]
    : [avg !== "–" ? `${avg} per dismissal` : "Not dismissed", st.econ != null ? `${st.econ} econ` : null];
  return `
    <article class="matchup">
      <header class="matchup-head">
        <div>
          <div class="matchup-role">Batting</div>
          <h2 class="matchup-name"><a href="#/player/${esc(batter.slug)}">${esc(batter.display_name)}</a></h2>
        </div>
        <div class="matchup-vs" aria-hidden="true">vs</div>
        <div class="matchup-head-right">
          <div class="matchup-role">Bowling</div>
          <h2 class="matchup-name"><a href="#/player/${esc(bowler.slug)}">${esc(bowler.display_name)}</a></h2>
        </div>
      </header>
      <p class="matchup-kicker">${esc(poolLabel || "")}${st.matches ? ` · ${st.matches} match${st.matches === 1 ? "" : "es"}` : ""} · ${esc(overs)} overs</p>
      <div class="matchup-line">
        ${stats.map((s) => `<div class="matchup-stat${s.lead ? " lead" : ""}"><div class="n">${s.n ?? "–"}</div><div class="k">${s.k}</div></div>`).join("")}
      </div>
      <p class="matchup-foot">${footBits.filter(Boolean).join(" · ")}</p>
    </article>`;
}

function matchupStage(pa, pb, h, poolLabel, pool) {
  const ab = h.a_faced_b, ba = h.b_faced_a;
  if (!ab && !ba) {
    return `<article class="matchup matchup-empty">
      <header class="matchup-head">
        <div>
          <h2 class="matchup-name"><a href="#/player/${esc(pa.slug)}">${esc(pa.display_name)}</a></h2>
        </div>
        <div class="matchup-vs" aria-hidden="true">vs</div>
        <div class="matchup-head-right">
          <h2 class="matchup-name"><a href="#/player/${esc(pb.slug)}">${esc(pb.display_name)}</a></h2>
        </div>
      </header>
      <p class="matchup-kicker">No balls against each other in ${esc(poolLabel || "this format")}.</p>
    </article>`;
  }
  const first = (ab?.balls || 0) >= (ba?.balls || 0)
    ? matchupBoard(pa, pb, ab, poolLabel, pool)
    : matchupBoard(pb, pa, ba, poolLabel, pool);
  const second = (ab && ba)
    ? ((ab.balls || 0) >= (ba.balls || 0) ? matchupBoard(pb, pa, ba, poolLabel, pool) : matchupBoard(pa, pb, ab, poolLabel, pool))
    : "";
  return `<div class="matchup-stage">${first}${second}</div>`;
}

function xiImpactCards(pa, pb, pool) {
  const card = (person) => {
    const xi = person.xi;
    if (!xi?.ok) {
      return `<div class="duel-card">
        <h2><a href="#/player/${esc(person.slug)}">${esc(person.display_name)}</a></h2>
        <p class="caption">No teammate split in this format.</p>
      </div>`;
    }
    const bat = xi.bat || {}, bowl = xi.bowl || {};
    const bowlFirst = xi.primary_role === "bowl";
    const splitLine = (label, bucket) => {
      if (!bucket) return "";
      const b = bucket.bat || {};
      const d = b.avg_delta;
      const cls = d == null || d === 0 ? "" : d > 0 ? "pos" : "neg";
      return `<p class="xi-line">${label} ${b.avg_with ?? "–"} → ${b.avg_wo ?? "–"} <span class="${cls}">${d == null ? "" : signed(d, 1)}</span> · ${bucket.matches_with || 0} XI / ${bucket.matches_wo || 0} without</p>`;
    };
    const hero = xi.schedule_mix ? null : (bowlFirst ? bowl.econ_delta : bat.avg_delta);
    const heroLabel = xi.schedule_mix
      ? "schedule mix — not a teammate effect"
      : (bowlFirst ? "econ Δ with them in" : "avg Δ with them in");
    const digits = bowlFirst ? 2 : 1;
    const better = hero == null ? null : (bowlFirst ? hero < 0 : hero > 0);
    const hcls = hero == null || hero === 0 ? "" : better ? "pos" : "neg";
    const ahead = xi.lift > 0;
    return `
      <div class="duel-card${ahead ? " ahead" : ""}">
        <h2><a href="#/player/${esc(person.slug)}">${esc(person.display_name)}</a></h2>
        <p class="caption">${esc(xi.team || "")} · ${xi.matches_with || 0} XI · ${xi.matches_wo || 0} without</p>
        <p class="team-avg-line"><span class="fig ${hcls}">${hero == null ? (xi.schedule_mix ? "mix" : "–") : signed(hero, digits)}</span> <span class="caption">${heroLabel}</span></p>
        ${xi.home || xi.away ? `${splitLine("Home", xi.home)}${splitLine("Away", xi.away)}` : `<p class="xi-line">Batters ${bat.avg_with ?? "–"} avg · ${bat.sr_with ?? "–"} SR → ${bat.avg_wo ?? "–"} · ${bat.sr_wo ?? "–"}</p>`}
        <p class="xi-line">Bowlers ${bowl.econ_with ?? "–"} econ · ${bowl.avg_with ?? "–"} avg → ${bowl.econ_wo ?? "–"} · ${bowl.avg_wo ?? "–"}</p>
        <p class="xi-verdict">${esc(xi.verdict || "")}</p>
        <p class="caption"><a href="#/shift?player=${encodeURIComponent(person.slug)}&amp;team=${encodeURIComponent(xi.team || "")}&amp;comp=${encodeURIComponent(pool)}">Full teammate lines</a></p>
      </div>`;
  };
  return `
    <h2 class="section">Teammates in the XI</h2>
    <p class="caption">How the rest of the side bats and bowls with each of them vs without — same format, main team. Home and away are split by ground, not the raw mix of tours and home Tests.</p>
    <div class="duel">
      ${card(pa)}
      <div class="duel-mid caption">with<br>vs without</div>
      ${card(pb)}
    </div>`;
}

function sharedVsTable(rows, aName, bName, kind) {
  const noun = kind === "bowl" ? "batters" : "bowlers";
  if (!rows?.length) {
    return `<p class="caption">No ${noun} both faced in this format (12-ball floor).</p>`;
  }
  const deltaH = rows[0]?.delta_label || "";
  return `<table class="compare-grid shared-vs">
    <thead><tr>
      <th>${kind === "bowl" ? "Batter" : "Bowler"}</th>
      <th>${esc(aName)}</th>
      <th>${esc(bName)}</th>
      <th>Δ ${esc(deltaH)}</th>
      <th>Comp</th>
    </tr></thead>
    <tbody>${rows.map((r) => {
      const better = r.delta == null ? null : (kind === "bowl" ? r.delta < 0 : r.delta > 0);
      const cls = better == null || r.delta === 0 ? "" : (better ? "pos" : "neg");
      const d = r.delta == null ? "–" : `${r.delta > 0 ? "+" : ""}${r.delta}`;
      return `<tr>
        <td><a href="#/player/${esc(r.opp_slug || r.slug)}">${esc(r.opponent || r.player)}</a></td>
        <td>${esc(r.a_line)}</td>
        <td>${esc(r.b_line)}</td>
        <td class="delta ${cls}">${d}</td>
        <td>${esc(r.competition)}</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
}

async function showCompare() {
  setHero(false);
  main.classList.add("wide");
  const a = hashParam("a");
  const b = hashParam("b");
  const comp = hashParam("comp") || "t20i_ipl";
  if (!a || !b) {
    main.innerHTML = `
      <h1 class="page-title">Compare</h1>
      <p class="lede">Two players, two teams, a profile twin, or how a bowler shifts the attack around them.</p>
      <div class="launch">
        <a class="launch-card" href="#/compare"><h3>Players</h3><p>Same format, same bowlers — not two unrelated lists.</p></a>
        <a class="launch-card" href="#/teams"><h3>Teams</h3><p>Rank a side’s T20 value against another, same season.</p></a>
        <a class="launch-card" href="#/twin"><h3>Profile twin</h3><p>Closest T20 shape in this warehouse — WAR, RAE, WPA, pressure.</p></a>
        <a class="launch-card" href="#/shift"><h3>Stat line shift</h3><p>How teammates bowl and bat with you vs without you.</p></a>
      </div>
      <div class="filters">
        <label>Player A <input type="text" id="c-a" placeholder="Kohli" value="${esc(a)}"></label>
        <label>Player B <input type="text" id="c-b" placeholder="Root" value="${esc(b)}"></label>
        ${formatSelect("c-comp", comp, false)}
        <button class="btn primary" id="c-go">Compare</button>
      </div>`;
    $("c-go").addEventListener("click", goCompare);
    return;
  }
  const d = await (await fetch(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&comp=${encodeURIComponent(comp)}`)).json();
  if (d.kind === "pick") {
    main.innerHTML = pickList(d.people, d.side);
    main.querySelectorAll("[data-go]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qs = new URLSearchParams({ a, b, comp });
        qs.set(d.side, btn.dataset.go);
        location.hash = `#/compare?${qs}`;
      });
    });
    return;
  }
  if (!d.ok) {
    main.innerHTML = `<div class="error">${esc(d.error || "Need two players.")}</div>`;
    return;
  }
  const pa = d.a, pb = d.b;
  const female = pa.gender === "female" || pb.gender === "female";
  const pool = d.pool || comp;
  const h = d.h2h || {};
  const mixed = d.pairing === "mixed";
  const valRow = (r) => {
    const dec = r.digits != null
      ? r.digits
      : ({ war: 2, war_per_game: 3, rae_bat: 2, rae_bowl: 2, wpa: 3, pressure: 1 }[r.key] ?? 1);
    const fmt = (v) => (v == null ? "–" : Number(v).toFixed(dec));
    const lower = !!r.lower;
    const aWin = r.a != null && r.b != null && (lower ? r.a < r.b : r.a > r.b);
    const bWin = r.a != null && r.b != null && (lower ? r.b < r.a : r.b > r.a);
    const mag = (aWin || bWin) ? ` (+${Math.abs(r.a - r.b).toFixed(dec)})` : "";
    const cell = (v, rank, win) =>
      `<td class="num${win ? " win" : ""}">${fmt(v)}${win ? `<span class="margin">${mag}</span>` : ""}${rank ? `<div class="sc">#${rank}</div>` : ""}</td>`;
    return `<tr${pool === "test" && r.key === "avg" ? ' class="key-row"' : pool === "test" && r.key === "sr" ? ' class="quiet-row"' : ""}>
      ${cell(r.a, r.a_rank, aWin)}
      <td class="stat">${esc(r.label)}</td>
      ${cell(r.b, r.b_rank, bWin)}
    </tr>`;
  };
  const grid = (rows, extra = "") => !rows?.length ? "" : `<table class="compare-grid">
        <thead><tr><th>${esc(pa.display_name)}</th><th></th><th>${esc(pb.display_name)}</th></tr></thead>
        <tbody>${rows.map(valRow).join("")}</tbody>
      </table>${extra}`;
  const classicRows = [...(d.classic || [])];
  if (pool === "test") {
    const order = ["matches", "inns", "runs", "avg", "hs", "hundreds", "fifties", "sr", "wickets", "bowl_avg", "econ", "bowl_sr"];
    classicRows.sort((a, b) => (order.indexOf(a.key) + 99) - (order.indexOf(b.key) + 99));
  }
  const classicBlock = classicRows.length
    ? `<h2 class="section">${esc(d.pool_label || "Career")}</h2>${grid(classicRows)}`
    : "";
  const valueBlock = d.has_t20_value
    ? `<h2 class="section">T20 value</h2>${grid(d.rows)}`
    : "";
  const lede = mixed
    ? `${esc(d.pool_label || "")} — balls they faced each other, then career lines.`
    : `${esc(d.pool_label || "")} — career lines in this format. Same opponents below.`;
  main.innerHTML = `
    <h1 class="page-title">Player comparison</h1>
    <p class="lede">${lede}</p>
    <div class="filters">
      <label>Player A <input type="text" id="c-a" value="${esc(pa.display_name)}"></label>
      <label>Player B <input type="text" id="c-b" value="${esc(pb.display_name)}"></label>
      ${formatSelect("c-comp", pool, female)}
      <button class="btn primary" id="c-go">Compare</button>
    </div>
    ${classicBlock}
    ${valueBlock}
    ${mixed ? matchupStage(pa, pb, h, d.pool_label, pool) : ""}
    ${xiImpactCards(pa, pb, pool)}
    <h2 class="section">Vs the same bowlers</h2>
    <p class="caption">Only bowlers both faced in this format. 12-ball floor. Δ is ${pool === "test" ? "average" : "strike rate"}, ${esc(pa.display_name)} minus ${esc(pb.display_name)}.</p>
    ${sharedVsTable(d.shared_bowlers, pa.display_name, pb.display_name, "bat")}
    <h2 class="section">Vs the same batters</h2>
    <p class="caption">Only batters both bowled to in this format. Δ is ${pool === "test" ? "bowling average" : "economy"}, lower with ${esc(pa.display_name)} is green.</p>
    ${sharedVsTable(d.shared_batters, pa.display_name, pb.display_name, "bowl")}`;
  $("c-go").addEventListener("click", goCompare);
  $("c-comp")?.addEventListener("change", goCompare);
}

async function showTeamCompare() {
  setHero(false);
  main.classList.add("wide");
  const state = {
    a: hashParam("a") || "India",
    b: hashParam("b") || "Australia",
    comp: hashParam("comp") || "t20i",
    season: hashParam("season") || "",
    gender: hashParam("gender") || "male",
  };
  const qs = new URLSearchParams({ a: state.a, b: state.b, comp: state.comp, gender: state.gender });
  if (state.season) qs.set("season", state.season);
  const d = await (await fetch(`/api/team-compare?${qs}`)).json();
  const seasons = (d.seasons || []).map((s) => `<option ${s === (d.season || state.season) ? "selected" : ""}>${esc(s)}</option>`).join("");
  const dash = (v) => (v == null || v === "") ? "–" : v;
  const isTest = d.comp === "test";
  const isT20 = !!d.t20;
  const fmtW = (v) => (v == null || v === "") ? "–" : Number(v).toFixed(3);
  const t20Lane = (side) => `
    ${(side.players || []).map((p) => `
    <div class="team-row">
      <span class="rk">#${p.rank}</span>
      <a href="#/player/${esc(p.slug)}">${esc(p.display_name)}</a>
      <span class="caption">${esc(p.line || "")}</span>
      <span class="fig">${fmtW(p.war_per_game)}</span>
    </div>`).join("")}
    <div class="team-row tot">
      <span></span>
      <span>Squad</span>
      <span class="caption">WAR / game</span>
      <span class="fig">${fmtW(side.war_sum)}</span>
    </div>`;
  const compactLane = (side) => (side.players || []).map((p) => `
    <div class="team-row">
      <span class="rk">#${p.rank}</span>
      <a href="#/player/${esc(p.slug)}">${esc(p.display_name)}</a>
      <span class="caption">${esc(p.line || "")}</span>
      <span class="fig">${p.fig == null ? "–" : p.fig}</span>
    </div>`).join("");
  const testLane = (side) => `
    <div class="team-sheet">
      <div class="team-row head">
        <span></span><span></span>
        <span>I</span><span>Runs</span><span>HS</span><span>Avg</span><span>100</span><span>W</span><span>BAvg</span>
      </div>
      ${(side.players || []).map((p) => `
        <div class="team-row">
          <span class="rk">#${p.rank}</span>
          <a href="#/player/${esc(p.slug)}">${esc(p.display_name)}</a>
          <span class="num">${dash(p.inns)}</span>
          <span class="num">${dash(p.runs)}</span>
          <span class="num">${dash(p.hs)}</span>
          <span class="num">${dash(p.avg)}</span>
          <span class="num">${dash(p.hundreds)}</span>
          <span class="num">${dash(p.wickets)}</span>
          <span class="num">${dash(p.bowl_avg)}</span>
        </div>`).join("")}
      <div class="team-row tot">
        <span></span>
        <span>Team</span>
        <span></span>
        <span class="num">${dash(side.team_runs)}</span>
        <span></span>
        <span class="num">${dash(side.team_avg)}</span>
        <span></span>
        <span></span>
        <span class="num">${dash(side.bowl_avg)}</span>
      </div>
    </div>`;
  const lane = (side) => isTest ? testLane(side) : isT20 ? t20Lane(side) : compactLane(side);
  const rec = (side) => {
    const n = side.matches || 0, w = side.wins || 0;
    return `${w}–${Math.max(n - w, 0)} · ${side.win_pct ?? "–"}% · ${esc(d.season || "")}`;
  };
  const avgHero = (side) => {
    if (isTest) {
      return `<p class="team-avg-line"><span class="fig">${dash(side.team_avg)}</span> <span class="caption">team avg</span></p>`;
    }
    if (isT20) {
      return `<p class="team-avg-line"><span class="fig">${fmtW(side.war_sum)}</span> <span class="caption">WAR / game</span></p>`;
    }
    return "";
  };
  const lede = isTest
    ? "Typical XI in batting order. Inns, runs, average from every innings they played — team avg is runs per wicket."
    : isT20
      ? "Typical XI ranked by WAR per game this season. The number at the top is the whole squad’s WAR divided by matches — not 11 rates added as if everyone played every game."
      : "Batting order from the matches they actually played — first-innings positions, most-used XI.";
  const aSum = d.a?.war_sum, bSum = d.b?.war_sum;
  const aAhead = isT20 && aSum != null && bSum != null && aSum > bSum;
  const bAhead = isT20 && aSum != null && bSum != null && bSum > aSum;
  const mid = isTest
    ? `<div class="duel-mid">
        <p class="team-avg-line"><span class="fig">${dash(d.a?.team_avg)}</span></p>
        <p class="caption">team avg</p>
        <p class="caption" style="margin:10px 0 4px">vs</p>
        <p class="team-avg-line"><span class="fig">${dash(d.b?.team_avg)}</span></p>
      </div>`
    : isT20
      ? `<div class="duel-mid">
          <p class="team-avg-line"><span class="fig">${fmtW(aSum)}</span></p>
          <p class="caption">WAR / game</p>
          <p class="caption" style="margin:10px 0 4px">vs</p>
          <p class="team-avg-line"><span class="fig">${fmtW(bSum)}</span></p>
        </div>`
      : `<div class="duel-mid caption">Batting<br>order</div>`;
  main.innerHTML = `
    <h1 class="page-title">Team compare</h1>
    <p class="lede">${lede}</p>
    <div class="filters">
      <label>Side A <input type="text" id="tc-a" value="${esc(state.a)}"></label>
      <label>Side B <input type="text" id="tc-b" value="${esc(state.b)}"></label>
      <label>Format
        <select id="tc-c">${["t20i","ipl","odi","test"].map((c) => `<option value="${c}" ${state.comp===c?"selected":""}>${c.toUpperCase()}</option>`).join("")}</select>
      </label>
      <label>Gender
        <select id="tc-g">
          <option value="male" ${state.gender==="male"?"selected":""}>Men</option>
          <option value="female" ${state.gender==="female"?"selected":""}>Women</option>
        </select>
      </label>
      <label>Season <select id="tc-s"><option value="">Latest</option>${seasons}</select></label>
      <button class="btn primary" id="tc-go">Compare</button>
    </div>
    <div class="duel${isTest ? " duel-tests" : ""}">
      <div class="duel-card${aAhead ? " ahead" : ""}">
        <h2>${esc(d.a?.team)}</h2>
        <p class="caption">${rec(d.a || {})}</p>
        ${avgHero(d.a || {})}
        ${lane(d.a || {})}
      </div>
      ${mid}
      <div class="duel-card${bAhead ? " ahead" : ""}">
        <h2>${esc(d.b?.team)}</h2>
        <p class="caption">${rec(d.b || {})}</p>
        ${avgHero(d.b || {})}
        ${lane(d.b || {})}
      </div>
    </div>`;
  const go = () => {
    location.hash = `#/teams?a=${encodeURIComponent($("tc-a").value)}&b=${encodeURIComponent($("tc-b").value)}&comp=${$("tc-c").value}&gender=${$("tc-g").value}&season=${encodeURIComponent($("tc-s").value)}`;
  };
  $("tc-go").addEventListener("click", go);
}

async function showTwin() {
  setHero(false);
  const player = hashParam("player") || hashParam("q") || "";
  main.innerHTML = `
    <h1 class="page-title">Profile twin</h1>
    <p class="lede">Closest T20 shapes in this warehouse — league-relative WAR, RAE, WPA, and pressure. Not a clone, a neighbour.</p>
    <div class="filters">
      <label>Player <input type="text" id="tw-p" value="${esc(player)}" placeholder="Bumrah"></label>
      <button class="btn primary" id="tw-go">Find twin</button>
    </div>
    <div id="tw-out"></div>`;
  const run = async () => {
    const q = $("tw-p").value.trim();
    if (!q) return;
    location.hash = `#/twin?player=${encodeURIComponent(q)}`;
    const d = await (await fetch(`/api/twin?player=${encodeURIComponent(q)}`)).json();
    if (d.kind === "pick") {
      $("tw-out").innerHTML = pickList(d.people, "a player");
      $("tw-out").querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
        $("tw-p").value = b.dataset.go; run();
      }));
      return;
    }
    if (!d.ok) { $("tw-out").innerHTML = `<div class="error">${esc(d.error)}</div>`; return; }
    const twin = (d.twins || [])[0];
    const bars = (d.bars || []).map((bar) => {
      const max = Math.max(Math.abs(bar.a_rel || 0), Math.abs(bar.b_rel || 0), Math.abs(bar.league || 1), 1);
      const pct = (v) => 50 + 50 * (v / (max * 2 || 1));
      return `<div class="twin-row">
        <span>${esc(bar.label)}</span>
        <div class="twin-bars">
          <div class="twin-track"><div class="twin-fill a" style="width:${Math.min(100, Math.abs(bar.a_rel) / max * 50 + 50)}%"></div></div>
          <div class="twin-track"><div class="twin-fill b" style="width:${Math.min(100, Math.abs(bar.b_rel || 0) / max * 50 + 50)}%"></div></div>
        </div>
        <span class="fig">${bar.a}</span>
        <span class="fig">${bar.b ?? "–"}</span>
      </div>`;
    }).join("");
    $("tw-out").innerHTML = `
      <div class="duel">
        <div class="duel-card">
          <h2><a href="#/player/${esc(d.person.slug)}">${esc(d.person.display_name)}</a></h2>
          <p class="caption">${esc(d.anchor?.competition || "").toUpperCase()} ${esc(d.anchor?.season || "")} · ${d.anchor?.primary_role === "bowl" ? "Bowler" : "Batter"} first</p>
        </div>
        <div class="duel-mid"><p class="page-title">${twin ? twin.match : "–"}</p><p class="caption">match</p></div>
        <div class="duel-card">
          <h2>${twin ? `<a href="#/player/${esc(twin.slug)}">${esc(twin.display_name)}</a>` : "—"}</h2>
          <p class="caption">${twin ? `WAR ${twin.war}` : "No neighbour yet"}</p>
        </div>
      </div>
      <p class="caption">Left is ${esc(d.person.display_name)}; right is the twin. Values vs the ${esc(d.pool_label || "")} pool.</p>
      ${bars}
      <h2 class="section">Also close</h2>
      ${table(
        [{ key: "player", label: "Player", align: "left", link: "player" }, { key: "match", label: "Match", align: "right", numeric: true }, { key: "war", label: "WAR", align: "right", numeric: true }],
        (d.twins || []).map((t) => ({ ...t, player: t.display_name })),
      )}`;
  };
  $("tw-go").addEventListener("click", run);
  if (player) run();
}

async function showShift() {
  setHero(false);
  main.classList.add("wide");
  const player = hashParam("player") || "";
  const team = hashParam("team") || "";
  const comp = hashParam("comp") || "t20i";
  const formats = shiftFormats().map(([k, l]) =>
    `<option value="${k}" ${comp === k ? "selected" : ""}>${l}</option>`).join("");
  main.innerHTML = `
    <h1 class="page-title">Stat line shift</h1>
    <p class="lede">How teammates bowl and bat with you in the XI vs without you — from your first appearance in this format onward.</p>
    <div class="filters">
      <label>Player <input type="text" id="sh-p" value="${esc(player)}" placeholder="Bumrah"></label>
      <label>Team <input type="text" id="sh-t" value="${esc(team)}" placeholder="India (optional)"></label>
      <label>Format
        <select id="sh-c">${formats}</select>
      </label>
      <button class="btn primary" id="sh-go">Run shift</button>
    </div>
    <div id="sh-out"></div>`;
  const go = () => {
    const p = $("sh-p").value.trim();
    if (!p) return;
    const qs = new URLSearchParams({ player: p, comp: $("sh-c").value });
    if ($("sh-t").value.trim()) qs.set("team", $("sh-t").value.trim());
    location.hash = `#/shift?${qs}`;
  };
  $("sh-go").addEventListener("click", go);
  $("sh-c").addEventListener("change", go);
  if (!player) return;
  const qs = new URLSearchParams({ player });
  if (team) qs.set("team", team);
  if (comp) qs.set("comp", comp);
  const d = await (await fetch(`/api/shift?${qs}`)).json();
  if (d.kind === "pick") {
    $("sh-out").innerHTML = pickList(d.people, "a player");
    $("sh-out").querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
      $("sh-p").value = b.dataset.go; go();
    }));
    return;
  }
  if (!d.ok) { $("sh-out").innerHTML = `<div class="error">${esc(d.error)}</div>`; return; }
  const n = (k, l, extra = {}) => ({ key: k, label: l, align: "right", numeric: true, ...extra });
  const g = (label, cols) => ({ group: label, cols });
  const bowlCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("Matches", [n("m_with", "With"), n("m_wo", "W/o")]),
    g("Wickets", [n("wk_with", "With"), n("wk_wo", "W/o")]),
    g("Avg", [n("avg_with", "With"), n("avg_wo", "W/o"), n("avg_delta", "Δ", { delta: "lower", digits: 1 })]),
    g("Econ", [n("econ_with", "With", { digits: 2 }), n("econ_wo", "W/o", { digits: 2 }), n("econ_delta", "Δ", { delta: "lower", digits: 2 })]),
    g("SR", [n("sr_with", "With"), n("sr_wo", "W/o"), n("sr_delta", "Δ", { delta: "lower", digits: 1 })]),
  ];
  const batCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("Matches", [n("m_with", "With"), n("m_wo", "W/o")]),
    g("Inns", [n("inns_with", "With"), n("inns_wo", "W/o"), n("no_with", "NO")]),
    g("Runs", [n("runs_with", "With"), n("runs_wo", "W/o"), n("hs_with", "HS")]),
    g("Avg", [n("avg_with", "With"), n("avg_wo", "W/o"), n("avg_delta", "Δ", { delta: "higher", digits: 1 })]),
    g("SR", [n("sr_with", "With"), n("sr_wo", "W/o"), n("sr_delta", "Δ", { delta: "higher", digits: 1 })]),
    g("100s", [n("hundred_with", "With"), n("hundred_wo", "W/o")]),
    g("50s", [n("fifty_with", "With"), n("fifty_wo", "W/o")]),
  ];
  const advCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("RAE / game", [n("rae_with", "With", { digits: 2 }), n("rae_wo", "W/o", { digits: 2 }), n("rae_delta", "Δ", { delta: "higher", digits: 2 })]),
    g("WPA / game", [n("wpa_with", "With", { digits: 3 }), n("wpa_wo", "W/o", { digits: 3 }), n("wpa_delta", "Δ", { delta: "higher", digits: 3 })]),
    g("Press / game", [n("press_with", "With", { digits: 2 }), n("press_wo", "W/o", { digits: 2 })]),
    g("Score", [n("score_with", "With"), n("score_wo", "W/o"), n("score_delta", "Δ", { delta: "higher", digits: 1 })]),
  ];
  const bowlFirst = d.primary_role === "bowl";
  const bowlBlock = `
    <h2 class="section">Bowling partners</h2>
    <p class="caption">Average, economy, and strike rate with ${esc(d.person.display_name)} → without. Lower avg/econ/SR with them is green.</p>
    ${table(bowlCols, d.bowling || [])}`;
  const batBlock = `
    <h2 class="section">Batting partners</h2>
    <p class="caption">Matches, inns, runs, average, strike rate, hundreds, and fifties with ${esc(d.person.display_name)} in the XI → without. Higher avg/SR with them is green.</p>
    ${table(batCols, d.batting || [])}`;
  const advBowl = `
    <h2 class="section">T20 bowling value</h2>
    <p class="caption">Per game in each split. RAE, WPA, pressure, and 0–100 score from this warehouse (${esc(d.pool_label || "T20")}). Higher RAE/WPA with them is green.</p>
    ${table(advCols, d.bowling || [])}`;
  const advBat = `
    <h2 class="section">T20 batting value</h2>
    <p class="caption">Same model, batting. Higher strike-rate value and score with them is green.</p>
    ${table(advCols, d.batting || [])}`;
  const advBlock = d.t20 ? (bowlFirst ? advBowl + advBat : advBat + advBowl) : "";
  $("sh-out").innerHTML = `
    <p class="scope">${esc(d.caption || "")}</p>
    ${bowlFirst ? bowlBlock + batBlock : batBlock + bowlBlock}
    ${advBlock}`;
}

async function showMetrics() {
  setHero(false);
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
  const raw = decodeURIComponent(location.hash.replace(/^#/, "") || "/");
  const hash = raw.split("?")[0];
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
  if (head === "compare") return showCompare();
  if (head === "teams") return showTeamCompare();
  if (head === "twin") return showTwin();
  if (head === "shift") return showShift();
  if (head === "metrics" || head === "war") return showMetrics();
  if (head === "standings") {
    setQuery("standings comp:ipl");
    return showResults("standings comp:ipl");
  }
  if (head === "build") return showBuild();
  if (head === "sql") return showSQL();
  if (head === "docs" || head === "resources") return showDocs(parts[1] || "model");
  setHero(true);
  await showHomeSnapshot();
}

window.addEventListener("hashchange", () => { page = 0; closeSearch(); route(); });

(async function init() {
  renderChips();
  await loadSettings();
  await loadStatus();
  syncHighlight();
  await route();
})();
