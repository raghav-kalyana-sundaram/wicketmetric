import { highlightHTML, heuristic, upsertToken, trailingScore } from "./querybox.js";
import {
  initChrome, setDocTitle, favList, renderFavStar, trayAdd,
  formBlock, wowyVisual, scatterSVG, fowBeads, pctBar, copyText, toast,
  portrait, warmPortraits, ribbon, almanacBlock, mixBars,
  manhattan, progression, performerCards, statCards, recentList, recentPush, ledger,
} from "./chrome.js";

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
  try {
    const s = await (await fetch("/api/status")).json();
    $("data-date").textContent = s.last_pull_display && s.last_pull_display !== "—"
      ? `Data: ${s.last_pull_display}`
      : "Data: —";
    return s;
  } catch {
    $("data-date").textContent = "Data: —";
    return {};
  }
}

async function loadSettings() {
  try {
    settings = await (await fetch("/api/settings")).json();
  } catch {
    settings = { theme: "charcoal", weights: { rae: 0.45, wpa: 0.35, consistency: 0.20 } };
  }
  applyTheme(settings?.theme || "charcoal");
}

function applyTheme(theme) {
  settings.theme = theme === "paper" ? "paper" : "charcoal";
  document.documentElement.dataset.theme = settings.theme;
  const btn = $("theme-toggle");
  if (btn) {
    const next = settings.theme === "charcoal" ? "paper" : "charcoal";
    btn.textContent = `${next === "paper" ? "Paper" : "Charcoal"} theme`;
    btn.setAttribute("aria-label", `Switch to ${next} theme`);
  }
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
  setQuery(q, { run: Boolean(q) });
});

$("theme-toggle")?.addEventListener("click", () => {
  saveTheme(settings.theme === "charcoal" ? "paper" : "charcoal");
});

searchToggle?.addEventListener("click", () => {
  if (document.body.classList.contains("search-open")) closeSearch();
  else openSearch();
});
searchScrim?.addEventListener("click", closeSearch);

let suggestReq = 0;
input.addEventListener("input", async () => {
  syncHighlight();
  const v = input.value;
  const score = trailingScore(v);
  if (score) {
    renderInningsAC(score);
    return;
  }
  const word = v.split(/\s+/).pop() || "";
  if (/^\d{1,3}$/.test(word)) {
    ac.classList.remove("open");
    return;
  }
  if (word.endsWith(":") || word.length >= 2) {
    const current = ++suggestReq;
    const s = await fetch(`/api/suggest?q=${encodeURIComponent(word)}`).then((r) => r.json()).catch(() => ({}));
    if (current !== suggestReq) return;
    renderAC(s);
  } else {
    ac.classList.remove("open");
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const picked = ac.classList.contains("open") && acIndex >= 0 && acItems[acIndex];
    if (picked && acItems[acIndex].kind !== "innings") {
      acceptAC(acItems[acIndex]);
    } else {
      ac.classList.remove("open");
      closeSearch();
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
    acIndex = Math.max(-1, acIndex - 1);
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
      const hint = p.unique_name && p.unique_name !== p.display_name ? ` <span class="hint">${esc(p.unique_name)}</span>` : "";
      html += `<button type="button" data-i="${acItems.length - 1}">${portrait(p.slug, p.display_name, "xs")}<span>${esc(p.display_name)}${hint}</span></button>`;
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
  if (s.tokens?.length) {
    html += `<h4>Tokens</h4>`;
    s.tokens.forEach((t) => {
      acItems.push({ kind: "token", key: t.key });
      html += `<button type="button" data-i="${acItems.length - 1}">${esc(t.key)}: <span class="hint">${esc(t.hint || "")}</span></button>`;
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
  acIndex = -1;
  paintAC();
  warmPortraits(ac);
  ac.querySelectorAll("button").forEach((b) => {
    b.addEventListener("mousedown", (e) => {
      e.preventDefault();
      acceptAC(acItems[Number(b.dataset.i)]);
    });
  });
}

function renderInningsAC(score) {
  acItems = [{ kind: "innings", name: score.name, runs: score.runs }];
  ac.innerHTML = `<h4>Innings</h4>
    <button type="button" data-i="0">Find ${esc(score.runs)} by ${esc(score.name)} <span class="hint">Enter</span></button>`;
  ac.classList.add("open");
  acIndex = 0;
  paintAC();
  ac.querySelector("button")?.addEventListener("mousedown", (e) => {
    e.preventDefault();
    acceptAC(acItems[0]);
  });
}

function paintAC() {
  ac.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i === acIndex));
}

function acceptAC(item) {
  ac.classList.remove("open");
  if (item.kind === "innings") {
    closeSearch();
    runQuery();
    return;
  }
  if (item.kind === "person") {
    closeSearch();
    const score = trailingScore(input.value);
    if (score) {
      location.hash = `#/q=${encodeURIComponent(`${item.slug} ${score.runs}`)}`;
      return;
    }
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

function bindFieldAutocomplete(inputId, kind = "people") {
  const field = $(inputId);
  if (!field) return;
  field.setAttribute("autocomplete", "off");
  field.setAttribute("role", "combobox");
  field.setAttribute("aria-autocomplete", "list");
  const menu = document.createElement("div");
  menu.className = "field-ac";
  menu.hidden = true;
  field.parentElement.appendChild(menu);
  let request = 0;
  field.addEventListener("input", async () => {
    delete field.dataset.resolved;
    const q = field.value.trim();
    if (q.length < 2) { menu.hidden = true; return; }
    const current = ++request;
    const result = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`).then((r) => r.json()).catch(() => ({}));
    if (current !== request) return;
    const items = kind === "teams" ? (result.teams || []) : (result.people || []);
    menu.innerHTML = items.slice(0, 8).map((item, i) => {
      if (kind === "teams") {
        const name = item.team || item;
        return `<button type="button" data-i="${i}">${esc(name)}</button>`;
      }
      const detail = item.unique_name && item.unique_name !== item.display_name ? item.unique_name : "";
      return `<button type="button" data-i="${i}">${portrait(item.slug, item.display_name, "xs")}<span>${esc(item.display_name)}${detail ? `<small>${esc(detail)}</small>` : ""}</span></button>`;
    }).join("");
    menu.hidden = !items.length;
    menu.querySelectorAll("button").forEach((button) => button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const item = items[Number(button.dataset.i)];
      const name = kind === "teams" ? (item.team || item) : item.display_name;
      field.value = name;
      field.dataset.resolved = kind === "teams" ? name : item.slug;
      menu.hidden = true;
      field.focus();
    }));
    warmPortraits(menu);
  });
  field.addEventListener("blur", () => setTimeout(() => { menu.hidden = true; }, 100));
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
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function cricketOvers(balls, bp = 6) {
  const n = Number(balls) || 0;
  const base = Number(bp) || 6;
  return `${Math.floor(n / base)}.${n % base}`;
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
    if (c.group) out.push(...c.cols.map((sub, i) => ({ ...sub, groupStart: i === 0 })));
    else out.push(c);
  }
  return out;
}

function tableHead(columns, { sortKey = "", sortDir = "desc" } = {}) {
  const th = (c, extra = "") => {
    const rankCls = c.key === "rank" || c.key === "position" ? "col-rank" : "";
    const cls = [c.align === "right" || c.numeric ? "num" : "name", rankCls, extra, sortKey === c.key ? "sorted" : ""].filter(Boolean).join(" ");
    const key = c.key && c.sortable !== false ? ` data-key="${esc(c.key)}"` : "";
    const mark = sortKey === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : "";
    const help = c.help ? ` title="${esc(c.help)}" aria-label="${esc(`${c.label}: ${c.help}`)}"` : "";
    const info = c.info ? ` <span class="info" tabindex="0" aria-label="About ${esc(c.label)}">?<span class="pop">${esc(c.info)}</span></span>` : "";
    return `<th class="${cls}" scope="col"${key}${help}${c.rowspan ? ` rowspan="${c.rowspan}"` : ""}${c.colspan ? ` colspan="${c.colspan}"` : ""}>${esc(c.label)}${mark}${info}</th>`;
  };
  if (!columns.some((c) => c.group)) {
    return `<tr>${columns.map((c) => th(c)).join("")}</tr>`;
  }
  const top = [];
  const bot = [];
  for (const c of columns) {
    if (c.group) {
      top.push(`<th class="num grp" colspan="${c.cols.length}" scope="colgroup">${esc(c.group)}</th>`);
      for (const [i, s] of c.cols.entries()) bot.push(th(s, `sub${i === 0 ? " group-start" : ""}`));
    } else {
      top.push(th({ ...c, rowspan: 2 }));
    }
  }
  return `<tr>${top.join("")}</tr><tr>${bot.join("")}</tr>`;
}

const TABLE_STORE = new Map();
let tableSeq = 0;
const HEAT_LOW = new Set(["econ", "bowl_avg", "te", "twr_bat"]);

function table(columns, rows, opts = {}) {
  rows = Array.isArray(rows) ? rows : [];
  columns = columns || [];
  const {
    pageIndex = 0, total = rows.length, query = "", compact = false, heat = false, copyLine = false,
    sortKey = "", sortDir = "desc", filter = "", faces = false,
    searchable = false, searchLabel = "Filter this table", sticky = true,
  } = opts;
  const id = opts.id || `tbl-${++tableSeq}`;
  TABLE_STORE.set(id, { columns, rows, opts: { ...opts, id } });
  const needle = (filter || "").trim().toLowerCase();
  let view = rows;
  if (needle) {
    view = rows.filter((r) => Object.values(r).some((v) => String(v ?? "").toLowerCase().includes(needle)));
  }
  if (sortKey) {
    const hi = sortDir !== "asc";
    const compareRows = (a, b) => {
      let av = a[sortKey], bv = b[sortKey];
      if (opts.sortAbs && (sortKey === "delta" || String(sortKey).endsWith("_delta"))) {
        av = Math.abs(Number(av));
        bv = Math.abs(Number(bv));
      }
      const an = av == null || av === "" || av === "–" || av === "—";
      const bn = bv == null || bv === "" || bv === "–" || bv === "—";
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      const na = Number(String(av).replace("*", ""));
      const nb = Number(String(bv).replace("*", ""));
      if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return hi ? nb - na : na - nb;
      return hi ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    };
    if (opts.groupBy) {
      const grouped = new Map();
      for (const row of view) {
        const key = row[opts.groupBy] ?? Symbol();
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(row);
      }
      view = [...grouped.values()].sort((a, b) => compareRows(a[0], b[0])).flat();
    } else {
      view = view.slice().sort(compareRows);
    }
  }
  const maxPage = Math.max(0, Math.ceil(view.length / PAGE_SIZE) - 1);
  const safePage = Math.min(Math.max(0, pageIndex), maxPage);
  opts.pageIndex = safePage;
  const start = safePage * PAGE_SIZE;
  const slice = view.slice(start, start + PAGE_SIZE);
  const cols = flattenCols(columns);
  const head = tableHead(columns, { sortKey, sortDir });
  const deltaMax = Object.fromEntries(cols.filter((c) => c.deltaBar).map((c) => [
    c.key,
    Math.max(...view.map((r) => Math.abs(Number(r[c.key]) || 0)), 0),
  ]));
  const heatKeys = heat
    ? cols.filter((c) => c.numeric && c.key && c.key !== "rank" && (heat === true || heat === c.key)).map((c) => c.key)
    : [];
  const heatRanks = {};
  for (const k of heatKeys) {
    const nums = view.map((r) => Number(r[k])).filter((n) => Number.isFinite(n)).sort((a, b) => a - b);
    heatRanks[k] = nums;
  }
  const heatVal = (k, v) => {
    const nums = heatRanks[k];
    if (!nums?.length || v == null || !Number.isFinite(Number(v))) return "";
    const n = Number(v);
    const i = nums.findIndex((x) => x >= n);
    const pct = i < 0 ? 1 : i / Math.max(nums.length - 1, 1);
    const h = HEAT_LOW.has(k) ? 1 - pct : pct;
    return ` style="--heat:${(h * 42).toFixed(1)}%"`;
  };
  const body = slice.map((r, rowIndex) => {
    const groupKey = opts.groupBy ? r[opts.groupBy] : null;
    const previous = rowIndex > 0 ? slice[rowIndex - 1] : (start > 0 ? view[start - 1] : null);
    const next = rowIndex + 1 < slice.length ? slice[rowIndex + 1] : view[start + rowIndex + 1];
    const samePrevious = opts.groupBy && previous?.[opts.groupBy] === groupKey;
    const sameNext = opts.groupBy && next?.[opts.groupBy] === groupKey;
    const innings = Boolean(r.start_date || r.match_id);
    const batScore = r.runs_display != null
      ? Number(String(r.runs_display).replace("*", ""))
      : (r.balls != null ? Number(r.runs) : NaN);
    const isHundred = innings && batScore >= 100;
    const isFive = innings && Number(r.wickets) >= 5 && r.balls == null;
    const resultCls = opts.resultBorders === false ? "" : (r.result === "Won" ? "result-won" : r.result === "Lost" ? "result-lost" : "");
    const cls = [isHundred || isFive ? "milestone" : "", resultCls].filter(Boolean).join(" ");
    const slug = r.slug || r.person_id || "";
    const name = r.player || r.display_name || "";
    const cells = cols.map((c) => {
      let val = r[c.key];
      const repeatedGroupCell = samePrevious && c.groupOnce;
      if (repeatedGroupCell) {
        val = c.key === "start_date"
          ? `<span class="innings-cont">↳ Inn ${r.innings ?? ""}</span>`
          : "";
      } else if (c.key === "start_date") {
        val = fmtDate(r.start_date);
      }
      if (!repeatedGroupCell && c.key === "primary_role") val = val === "bowl" ? "Bowl" : val === "bat" ? "Bat" : val;
      if (repeatedGroupCell) {
        // The first row carries match-level context; continuation rows only show innings stats.
      } else if (c.link === "player") {
        const face = faces ? portrait(r.slug || r.person_id, r.player || r.display_name || val, "xs") : "";
        const tag = c.tagKey && r[c.tagKey] ? `<span class="row-tag">${esc(r[c.tagKey])}</span>` : "";
        val = `<span class="who">${face}<a class="player-link" href="#/player/${esc(r.slug || r.person_id)}">${esc(r.player || r.display_name || val)}</a>${tag}</span>`;
      } else if (c.key === "match" || (c.link === "match")) {
        val = `<a href="#/match/${esc(r.match_id)}">${esc(val || r.opposition || r.match_id)}</a>`;
      } else if (c.link === "venue" && val) {
        const clip = c.clip === false ? "" : ' class="cell-clip"';
        const target = r.venue || val;
        val = `<a${clip} title="${esc(target)}" href="#/venue?name=${encodeURIComponent(target)}">${esc(val)}</a>`;
      } else if (c.link === "team" && val) {
        val = `<a href="#/team?name=${encodeURIComponent(val)}">${esc(val)}</a>`;
      } else if (c.badge && val != null) {
        const badgeKey = String(val).toLowerCase().replace(/[^a-z0-9_-]/g, "");
        val = `<span class="comp-badge comp-${badgeKey}">${esc(String(val).toUpperCase())}</span>`;
      } else if (c.status && val != null) {
        const status = String(val);
        const icon = status === "Won" ? "✓" : status === "Lost" ? "×" : status === "Draw" ? "=" : "·";
        val = `<span class="result-status result-${status.toLowerCase()}"><span aria-hidden="true">${icon}</span> ${esc(status)}</span>`;
      } else if (c.numeric) {
        const raw = r[c.key];
        if (typeof raw === "string" && raw.endsWith("*")) {
          val = `<span class="fig not-out">${esc(raw)}</span>`;
        } else if (c.key === "runs_display") {
          val = `<span class="fig${String(raw || "").includes("*") ? " not-out" : ""}">${esc(raw ?? "–")}</span>`;
        } else {
          const digits = c.digits ?? (c.key === "war_per_game" ? 3 : (c.key === "rae_bat" || c.key === "rae_bowl" ? 2 : (Number.isInteger(Number(raw)) ? 0 : 1)));
          if (c.delta && raw != null && raw !== "") {
            const n = Number(raw);
            const better = c.delta === "lower" ? n < 0 : n > 0;
            const dcls = n === 0 ? "" : better ? "pos" : "neg";
            const bar = c.deltaBar && deltaMax[c.key]
              ? `<span class="delta-scale" style="--delta-size:${Math.abs(n) / deltaMax[c.key] * 100}%"></span>`
              : "";
            val = `${bar}<span class="delta ${dcls}">${signed(n, digits)}</span>`;
          } else {
            val = num(raw, digits);
          }
        }
      } else if (val == null || val === "") {
        val = `<span class="muted">–</span>`;
      } else {
        val = esc(val);
      }
      if (!repeatedGroupCell && (c.key === "opposition" || c.key === "result") && r.match_id && c.link !== false) {
        val = `<a href="#/match/${esc(r.match_id)}">${val}</a>`;
      }
      if (!repeatedGroupCell && copyLine && c.key === "runs_display") {
        const line = `${name} ${r.runs_display} (${r.balls || "–"}) vs ${r.opposition || ""} · ${r.competition || ""} · ${fmtDate(r.start_date)}`;
        val += ` <button type="button" class="copy-line" data-copy="${esc(line)}">copy</button>`;
      }
      const heatCls = heatKeys.includes(c.key) ? " heat" : "";
      const secondaryCls = c.roleGroup && r.primary_role && c.roleGroup !== r.primary_role ? " secondary-stat" : "";
      const title = c.help ? ` title="${esc(c.help)}"` : "";
      const columnCls = [
        c.align === "right" ? "num" : "",
        c.key === "rank" || c.key === "position" ? "col-rank" : "",
        c.groupStart ? "group-start" : "",
        c.supporting ? "supporting" : "",
        c.deltaPrimary ? "delta-primary" : "",
      ].filter(Boolean).join(" ");
      return `<td class="${columnCls}${heatCls}${secondaryCls}"${heatCls ? heatVal(c.key, r[c.key]) : ""}${title}>${val}</td>`;
    }).join("");
    const lowSample = opts.sampleFloor && Math.min(Number(r.m_with) || 0, Number(r.m_wo) || 0) < opts.sampleFloor ? " low-sample" : "";
    const groupCls = opts.groupBy
      ? samePrevious ? (sameNext ? " match-group-mid" : " match-group-end") : (sameNext ? " match-group-start" : " match-group-single")
      : "";
    return `<tr class="${cls}${lowSample}${groupCls}" data-slug="${esc(slug)}" data-name="${esc(name)}">${cells}</tr>`;
  }).join("");
  const shown = slice.length;
  const more = view.length > start + shown ? `Showing ${start + 1}–${start + shown} of ${view.length.toLocaleString()} — refine or export all` : "";
  const alwaysOpen = searchable || Boolean(filter);
  const hits = needle ? `<span class="filter-hits">${view.length.toLocaleString()} of ${rows.length.toLocaleString()}</span>` : "";
  return `
    <div class="table-block" id="${id}">
    <div class="table-tools${alwaysOpen ? "" : " bare"}">
      <input class="table-filter" data-tbl="${id}" type="search" placeholder="${esc(searchLabel)}" value="${esc(filter)}" ${alwaysOpen ? "" : "hidden"} aria-label="${esc(searchLabel)}">
      ${hits}
    </div>
    <div class="table-wrap${compact ? " compact" : ""}${sticky && slice.length > 24 ? " sticky-head" : ""}">
      <table class="data">
        <thead>${head}</thead>
        <tbody>${body || `<tr><td colspan="${cols.length}" class="muted">No rows${needle ? ` matching “${esc(filter)}”` : ""}</td></tr>`}</tbody>
      </table>
      <div class="table-foot">
        <span>${more}</span>
        <span>
          ${view.length > PAGE_SIZE ? `<button class="btn-text" data-page="prev">Prev</button> <button class="btn-text" data-page="next">Next</button>` : ""}
          ${query ? `<button class="btn-text" data-export="${esc(query)}">Export CSV</button>
          <button class="btn-text" data-sql>Open in SQL</button>` : ""}
        </span>
      </div>
    </div>
    </div>`;
}

function paintStoredTable(id) {
  const st = TABLE_STORE.get(id);
  if (!st) return;
  const block = document.getElementById(id);
  if (!block) return;
  block.outerHTML = table(st.columns, st.rows, { ...st.opts, id });
  bindTable(st.opts.query || "");
}

function bindTable(query) {
  if (query != null) main.dataset.exportQuery = query;
  if (main._live) return;
  main._live = true;
  main.addEventListener("click", (e) => {
    const pageBtn = e.target.closest("[data-page]");
    if (pageBtn) {
      const block = pageBtn.closest(".table-block");
      const st = TABLE_STORE.get(block?.id);
      if (st) {
        const idx = st.opts.pageIndex || 0;
        st.opts.pageIndex = pageBtn.dataset.page === "next" ? idx + 1 : Math.max(0, idx - 1);
        paintStoredTable(block.id);
        return;
      }
      if (pageBtn.dataset.page === "next") page += 1;
      else page = Math.max(0, page - 1);
      route();
      return;
    }
    if (e.target.closest("[data-export]")) {
      location.href = `/api/export?q=${encodeURIComponent(main.dataset.exportQuery || "")}`;
      return;
    }
    if (e.target.closest("[data-sql]")) {
      location.hash = "#/sql";
      return;
    }
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      e.preventDefault();
      copyText(copy.dataset.copy);
      return;
    }
    const th = e.target.closest("th[data-key]");
    if (th) {
      const block = th.closest(".table-block");
      const st = TABLE_STORE.get(block?.id);
      if (!st) return;
      const key = th.dataset.key;
      if (st.opts.onSort) {
        st.opts.onSort(key);
        return;
      }
      const dir = st.opts.sortKey === key && st.opts.sortDir === "desc" ? "asc" : "desc";
      st.opts.sortKey = key;
      st.opts.sortDir = dir;
      st.opts.pageIndex = 0;
      page = 0;
      paintStoredTable(block.id);
    }
  });
  main.addEventListener("input", (e) => {
    const filter = e.target.closest(".table-filter");
    if (!filter) return;
    const id = filter.dataset.tbl;
    const st = TABLE_STORE.get(id);
    if (!st) return;
    st.opts.filter = filter.value;
    st.opts.pageIndex = 0;
    page = 0;
    paintStoredTable(id);
    const nf = document.querySelector(`#${CSS.escape(id)} .table-filter`);
    if (nf) {
      nf.hidden = false;
      nf.focus();
      nf.selectionStart = nf.value.length;
    }
  });
  main.addEventListener("mouseover", (e) => {
    const block = e.target.closest(".table-block");
    if (block) main.dataset.hoverTbl = block.id;
    const tr = e.target.closest("tbody tr[data-slug]");
    if (!tr) return;
    tr.closest(".table-block")?.querySelectorAll("tr.is-hover").forEach((x) => x.classList.remove("is-hover"));
    tr.classList.add("is-hover");
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
  const navAliases = {
    "#/compare": ["#/teams", "#/twin", "#/shift"],
    "#/grounds": ["#/venue"],
    "#/stats": ["#/metrics", "#/war"],
    "#/resources": ["#/docs", "#/model"],
  };
  document.querySelectorAll(".util a").forEach((a) => {
    const href = a.getAttribute("href");
    const on = location.hash.startsWith(href)
      || (navAliases[href] || []).some((p) => location.hash.startsWith(p));
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

const PULSE_TIER_KEY = "wm-pulse-tier";
const PULSE_TIERS = [
  ["top", "Full members + leagues"],
  ["internationals", "Internationals"],
  ["leagues", "Leagues"],
  ["all", "Everything"],
];

function personRail(title, items, hint = "") {
  if (!items.length) return "";
  return `<div class="fav-rail"><h3>${esc(title)}${hint ? ` <span class="caption">${esc(hint)}</span>` : ""}</h3>${
    items.map((f) => `<a class="chip fav-chip" href="#/player/${esc(f.slug)}">${portrait(f.slug, f.name, "xs")}${esc(f.name)}</a>`).join(" ")
  }</div>`;
}

async function showHomeSnapshot() {
  const gen = routeGen;
  setDocTitle("");
  let tier = "top";
  try { tier = localStorage.getItem(PULSE_TIER_KEY) || "top"; } catch { /* blocked */ }
  if (!PULSE_TIERS.some(([id]) => id === tier)) tier = "top";
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const [snap, otd] = await Promise.all([
    fetch("/api/snapshot").then((r) => r.json()).catch(() => ({ rows: [] })),
    fetch("/api/onthisday?limit=5").then((r) => r.json()).catch(() => ({ matches: [], innings: [] })),
  ]);
  if (gen !== routeGen) return;
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
  const favs = favList();
  const recent = recentList().filter((r) => !favs.some((f) => f.slug === r.slug)).slice(0, 8);
  const today = new Date();
  const dayLabel = today.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
  const otdBlock = (otd.matches?.length || otd.innings?.length)
    ? `<section class="otd">
        <h2 class="section">On this day · ${esc(dayLabel)}</h2>
        <div class="otd-grid">
          <div>
            <h3>Matches</h3>
            ${(otd.matches || []).map((r) => `<a class="otd-row" href="#/match/${esc(r.match_id)}">
              <span class="otd-year">${esc(r.year)}</span>
              <span class="otd-body"><strong>${esc(r.team_home)}</strong> v <strong>${esc(r.team_away)}</strong>
                <span class="caption">${esc(r.comp || "")} · ${esc(r.result || "")}</span></span>
            </a>`).join("") || `<p class="caption">Nothing on this date.</p>`}
          </div>
          <div>
            <h3>Hundreds</h3>
            ${(otd.innings || []).map((r) => `<a class="otd-row" href="#/match/${esc(r.match_id)}">
              <span class="otd-year">${esc(r.year)}</span>
              <span class="otd-body"><strong>${esc(r.display_name)}</strong> ${esc(r.line)}
                <span class="caption">${esc(r.comp || "")} v ${esc(r.opposition || "")}</span></span>
            </a>`).join("") || `<p class="caption">No hundreds on this date.</p>`}
          </div>
        </div>
      </section>`
    : "";
  main.innerHTML = `
    ${personRail("Pinned", favs)}
    ${personRail("Recently viewed", recent)}
    <nav class="home-jump" aria-label="Browse">
      <a href="#/records">Record book</a>
      <a href="#/stats">Stats table</a>
      <a href="#/rankings">Rankings</a>
      <a href="#/best">Best T20</a>
      <a href="#/standings">Standings</a>
      <a href="#/grounds">Grounds</a>
      <a href="#/compare">Compare two players</a>
    </nav>
    <div class="pulse-head">
      <h2 class="section">Latest</h2>
      <div class="fmt-row" id="pulse-tier" role="group" aria-label="Which cricket to show">
        <span class="fmt-label">Show</span>
        ${PULSE_TIERS.map(([id, label]) => `<button type="button" class="tab ${id === tier ? "active" : ""}" data-tier="${id}">${label}</button>`).join("")}
      </div>
    </div>
    <div id="pulse-box"><div class="skel"></div></div>
    ${otdBlock}
    <h2 class="section">In the warehouse</h2>
    <p class="scope">${snap.deliveries?.toLocaleString()} deliveries across ${snap.rows.reduce((s, r) => s + Number(r.matches || 0), 0).toLocaleString()} matches</p>
    ${table(cols, snap.rows, { query: "", compact: true })}`;
  const pulseItem = (r, line) =>
    `<div class="pulse-row">
      ${portrait(r.slug, r.display_name, "sm")}
      <div>
        <a class="pulse-player" href="#/player/${esc(r.slug)}">${esc(r.display_name)}</a>
        <a href="#/match/${esc(r.match_id)}"><span class="kicker">${fmtDate(r.start_date)} · ${esc(r.comp || r.competition || "")}</span> ${esc(line)} v ${esc(r.opposition || "")}</a>
      </div>
    </div>`;
  const paintPulse = async (which) => {
    const box = $("pulse-box");
    box.innerHTML = `<div class="skel"></div>`;
    const pulse = await fetch(`/api/pulse?tier=${encodeURIComponent(which)}`)
      .then((r) => r.json())
      .catch(() => ({ hundreds: [], five_fors: [], matches: [] }));
    box.innerHTML = `<div class="pulse">
      <div>
        <h3>Hundreds</h3>
        ${(pulse.hundreds || []).map((r) => pulseItem(r, r.line)).join("") || `<p class="caption">None in this filter.</p>`}
      </div>
      <div>
        <h3>Five-fors</h3>
        ${(pulse.five_fors || []).map((r) => pulseItem(r, r.line)).join("") || `<p class="caption">None in this filter.</p>`}
      </div>
      <div>
        <h3>Matches</h3>
        ${(pulse.matches || []).map((r) =>
          `<a class="pulse-match" href="#/match/${esc(r.match_id)}"><span class="kicker">${fmtDate(r.start_date)} · ${esc(r.comp || "")}</span><br><strong>${esc(r.team_home)}</strong> v <strong>${esc(r.team_away)}</strong><br><span class="caption">${esc(r.result || "")}</span></a>`
        ).join("") || `<p class="caption">None in this filter.</p>`}
      </div>
    </div>`;
    warmPortraits(box);
  };
  await paintPulse(tier);
  $("pulse-tier")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tier]");
    if (!btn) return;
    $("pulse-tier").querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
    try { localStorage.setItem(PULSE_TIER_KEY, btn.dataset.tier); } catch { /* blocked */ }
    paintPulse(btn.dataset.tier);
  });
  bindTable("");
  warmPortraits(main);
}

async function showResults(q) {
  const gen = routeGen;
  setHero(false);
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  let res;
  try {
    const r = await fetch(`/api/query?q=${encodeURIComponent(q)}`);
    if (gen !== routeGen) return;
    res = await r.json();
    if (!r.ok && res.ok !== false) {
      const detail = res.detail;
      const msg = typeof detail === "string" ? detail : (res.error || `Query failed (${r.status})`);
      res = { ok: false, error: msg };
    }
  } catch (err) {
    main.innerHTML = `<div class="error">${esc(err.message || "Query failed")}</div>`;
    return;
  }
  if (!res.ok) {
    main.innerHTML = `<div class="error">${esc(res.error || "Query failed")}</div>`;
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
    ${table(res.columns || [], res.rows || [], { pageIndex: page, total: (res.rows || []).length, query: q, faces: res.kind === "innings", copyLine: res.kind === "innings" })}
    ${res.kind === "standings" && res.playoffs?.length ? playoffBlock(res.playoffs) : ""}
    ${res.kind === "innings" ? `<p class="caption">Date opens the scorecard.</p>` : ""}
    ${res.wpa != null ? `<p class="caption">WPA when present in T20s: ${signed(res.wpa, 2)} in this warehouse.</p>` : ""}
  `;
  bindTable(q);
  main.querySelectorAll("[data-slug]").forEach((b) => {
    b.addEventListener("click", () => setQuery(upsertToken(q, "player", b.dataset.slug), { run: true }));
  });
}

// Four pages answer "who is best at X" in different ways. Without a link
// between them, Rankings in particular is only reachable from the palette.
const LEADERBOARD_PAGES = [
  ["stats", "Stats table", "/stats"],
  ["rankings", "Rankings", "/rankings"],
  ["records", "Record book", "/records"],
  ["best", "Best T20", "/best"],
  ["model", "Model", "/model"],
];

function leaderboardNav(active) {
  return `<nav class="browse" aria-label="Leaderboards">${
    LEADERBOARD_PAGES.map(([id, label, href]) =>
      id === active
        ? `<span class="browse-here" aria-current="page">${label}</span>`
        : `<a href="#${href}">${label}</a>`
    ).join("")
  }</nav>`;
}

function titleCase(v) {
  const s = String(v ?? "").trim();
  if (!s) return s;
  return s.replace(/\b[a-z]/g, (m) => m.toUpperCase());
}

function playoffBlock(playoffs) {
  const cols = [
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "event_stage", label: "Stage", align: "left" },
    { key: "team_home", label: "Home", align: "left", link: "team" },
    { key: "team_away", label: "Away", align: "left", link: "team" },
    { key: "winner", label: "Winner", align: "left", link: "team" },
  ];
  const rows = (playoffs || []).map((r) => ({
    ...r,
    event_stage: titleCase(r.event_stage),
  }));
  return `<h2 class="section">Playoffs</h2>` + table(cols, rows, { resultBorders: false });
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
  if (!id) {
    main.innerHTML = `<div class="empty"><p>No match selected.</p><button type="button" class="chip" data-home>Back to search</button></div>`;
    main.querySelector("[data-home]")?.addEventListener("click", () => { location.hash = "#/"; });
    return;
  }
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const gen = routeGen;
  const [r, extrasRes, valueRes] = await Promise.all([
    fetch(`/api/match/${encodeURIComponent(id)}`),
    fetch(`/api/match/${encodeURIComponent(id)}/extras`).catch(() => null),
    fetch(`/api/match/${encodeURIComponent(id)}/value`).catch(() => null),
  ]);
  if (gen !== routeGen) return;
  const d = await r.json().catch(() => ({}));
  const extras = extrasRes ? await extrasRes.json().catch(() => ({})) : {};
  const value = valueRes ? await valueRes.json().catch(() => ({})) : {};
  const m = d.match;
  if (!r.ok || !m) {
    const msg = typeof d.detail === "string" ? d.detail : "Match not found";
    main.innerHTML = `<div class="empty"><p>${esc(msg)}.</p><button type="button" class="chip" data-home>Back to search</button></div>`;
    main.querySelector("[data-home]")?.addEventListener("click", () => { location.hash = "#/"; });
    return;
  }
  setDocTitle(`${m.team_home} v ${m.team_away}`);
  const badges = [];
  if (m.result_method === "dls") badges.push("DLS");
  if (m.result_method === "super_over") badges.push("Super Over");
  if (m.result_method === "no_result") badges.push("No result");
  if (m.result_method === "tie") badges.push("Tie");
  if (m.source === "cricinfo") badges.push("Scorecard");
  const result = m.winner
    ? `${m.winner} won` + (
        m.win_by_innings
          ? ` by an innings${m.win_by_runs ? ` and ${m.win_by_runs} runs` : ""}`
          : m.win_by_runs
            ? ` by ${m.win_by_runs} runs`
            : m.win_by_wickets
              ? ` by ${m.win_by_wickets} wickets`
              : ""
      )
    : (m.result || "No result");
  const scoreLine = (d.innings || [])
    .filter((inn) => inn.innings_kind !== "super_over")
    .map((inn) => `${esc(inn.batting_team)} ${inn.runs}/${inn.wickets}`)
    .join(" · ");
  const battingOrder = (d.innings || []).filter((inn) => inn.innings_kind !== "super_over").map((inn) => inn.batting_team);
  const xiTeams = [...new Set([...battingOrder, ...(d.xi || []).map((x) => x.team)])];
  const xiHtml = xiTeams.length
    ? `<details class="playing-xi"><summary>Playing XIs</summary><div class="xi-sheets">${xiTeams.map((team) => {
      const side = (d.xi || []).filter((x) => x.team === team);
      return `<div class="xi-sheet"><h3>${esc(team)}</h3><ol>${side.map((x) => {
        const mark = [x.is_captain ? "c" : "", x.is_keeper ? "†" : ""].filter(Boolean).join("");
        return `<li><a href="#/player/${esc(x.slug)}">${esc(x.display_name)}</a>${mark ? ` <span class="caption">${mark}</span>` : ""}</li>`;
      }).join("")}</ol></div>`;
    }).join("")}</div></details>`
    : "";
  const dismissalText = (b) => {
    const kind = String(b.dismissal_kind || "").toLowerCase();
    const bowler = b.bowler_name || "";
    const fielder = b.fielder_name || "";
    if (!kind) return "not out";
    if (kind === "caught") return `c ${fielder || "—"} b ${bowler || "—"}`;
    if (kind === "caught and bowled") return `c & b ${bowler || fielder || "—"}`;
    if (kind === "bowled") return `b ${bowler || "—"}`;
    if (kind === "lbw") return `lbw b ${bowler || "—"}`;
    if (kind === "stumped") return `st ${fielder || "—"} b ${bowler || "—"}`;
    if (kind === "hit wicket") return `hit wicket b ${bowler || "—"}`;
    if (kind === "run out") return `run out (${fielder || "—"})`;
    return kind.replaceAll("_", " ");
  };
  const endLabel = (reason, closed) => {
    if (reason === "end_of_innings") return closed ? "Innings closed" : "Not out";
    return String(reason || "—").replaceAll("_", " ");
  };
  const regularInns = (d.innings || []).filter((inn) => inn.innings_kind !== "super_over");
  const bpo = Number(m.balls_per_over) || 6;
  const oversByInnings = new Map();
  for (const row of extras.overs || []) {
    if (row.innings_kind !== "regular") continue;
    if (!oversByInnings.has(row.innings)) oversByInnings.set(row.innings, []);
    oversByInnings.get(row.innings).push(row);
  }
  const limitedOvers = m.competition !== "test";
  const progressionBlock = (() => {
    if (!limitedOvers || regularInns.length < 2) return "";
    const lanes = regularInns.slice(0, 2).map((inn) => {
      const rows = (oversByInnings.get(inn.innings) || []).slice().sort((a, b) => a.over - b.over);
      let runs = 0;
      const points = [{ over: 0, runs: 0, wickets: 0 }];
      for (const o of rows) {
        runs += Number(o.runs) || 0;
        points.push({ over: Number(o.over) + 1, runs, wickets: Number(o.wickets) || 0 });
      }
      return { team: inn.batting_team, points };
    });
    const target = regularInns[1]?.target_runs || (Number(regularInns[0]?.runs) || 0) + 1;
    return lanes.some((l) => l.points.length > 3)
      ? `<h2 class="section">How it unfolded</h2>${progression(lanes, { target })}`
      : "";
  })();
  const performers = performerCards(extras.top_bat, extras.top_bowl);
  // A chase that wins with overs to spare shows a one-run margin on the
  // scoreboard. Valuing the balls and wickets left unused says how far apart the
  // sides actually were.
  const marginBlock = (() => {
    const rows = value?.rows || [];
    if (rows.length !== 2 || value.margin == null) return "";
    const [first, second] = rows;
    const lead = Number(value.margin) >= 0 ? first : second;
    const gap = Math.abs(Number(value.margin));
    return `<h2 class="section">Resource-adjusted margin</h2>
      <p class="caption">Each innings is worth its runs plus the value of whatever balls and wickets it left unused. Unlike the scoreboard margin, this does not compress a
      chase that finished early.</p>
      ${ledger(
        ["Innings", "Score", "Unused resources", "Innings value"],
        rows.map((row) => {
          const unused = Number(row.resource_value) - Number(row.runs);
          return [
            esc(row.batting_team),
            `${row.runs}/${row.wickets_used} <span class="caption">${cricketOvers(row.legal_balls, bpo)} ov</span>`,
            signed(unused, 1),
            Number(row.resource_value).toFixed(1),
          ];
        }),
      )}
      <p class="caption">${esc(lead.batting_team)} ahead by ${gap.toFixed(1)} model runs.
      ${gap > 0 ? `At the calibrated exchange rate that is the gap the batting and bowling sides created between them.` : ""}
      <a href="#/model">How this is built</a>.</p>`;
  })();
  const stageBits = [
    m.event_name || (m.competition || "").toUpperCase(),
    m.season || "",
    m.event_stage ? String(m.event_stage).replaceAll("_", " ") : "",
  ].filter(Boolean).join(" · ");
  let html = `
    <div class="page-head">
      <h1 class="page-title">${esc(m.team_home)} v ${esc(m.team_away)}</h1>
      <button type="button" class="copy-view" id="share-match" title="Copy a link to this scorecard">Copy link</button>
    </div>
    ${scoreLine ? `<p class="match-scores">${scoreLine}</p>` : ""}
    <p class="match-result">${esc(result)}</p>
    <p class="meta-line">${fmtDate(m.start_date)} · <a href="#/venue?name=${encodeURIComponent(m.venue || "")}">${esc(m.venue || "")}</a> · ${esc(stageBits)}${m.toss_winner ? ` · Toss: ${esc(m.toss_winner)} ${esc(m.toss_decision || "")}` : ""}
      ${badges.map((b) => `<span class="badge">${b}</span>`).join(" ")}</p>
    ${m.source === "cricinfo" ? `<p class="caption">Cricinfo scorecard — no ball-by-ball for this match. Deliveries start in late 2001.</p>` : ""}
    <p class="meta-line"><a href="#/team?name=${encodeURIComponent(m.team_home)}">${esc(m.team_home)}</a> · <a href="#/team?name=${encodeURIComponent(m.team_away)}">${esc(m.team_away)}</a> team records</p>
    ${performers}
    ${progressionBlock}
    ${marginBlock}
    ${xiHtml}
  `;
  for (const inn of d.innings || []) {
    const label = inn.innings_kind === "super_over" ? "Super Over" : `Innings ${inn.innings}`;
    const ov = cricketOvers(inn.legal_balls, m.balls_per_over || 6);
    const rr = inn.legal_balls ? (inn.runs * 6 / inn.legal_balls).toFixed(2) : "–";
    html += `<h2 class="section">${label} — ${esc(inn.batting_team)} ${inn.runs}/${inn.wickets} (${ov} overs, RR ${rr})</h2>
      <p class="inn-meta">${inn.declared ? "<span>Declared</span>" : ""}${inn.all_out ? "<span>All out</span>" : ""}</p>`;
    const bats = (d.batting || []).filter((b) => b.innings === inn.innings);
    const bowls = (d.bowling || []).filter((b) => b.innings === inn.innings);
    const parts = (d.partnerships || []).filter((p) => p.innings === inn.innings);
    const lastFallenWicket = Math.max(0, ...parts.filter((p) => p.end_reason !== "end_of_innings").map((p) => Number(p.wicket_number) || 0));
    const balls = (d.deliveries || []).filter((ball) => ball.innings === inn.innings && ball.innings_kind === inn.innings_kind);
    const extrasByType = {};
    for (const ball of balls) {
      if (ball.extra_type && Number(ball.runs_extras)) {
        extrasByType[ball.extra_type] = (extrasByType[ball.extra_type] || 0) + Number(ball.runs_extras);
      }
    }
    let runningScore = 0;
    let wicketNumber = 0;
    const nonWickets = new Set(["retired hurt", "retired not out", "absent hurt", "absent ill"]);
    const falls = [];
    for (const ball of balls) {
      runningScore += Number(ball.runs_total) || 0;
      if (ball.wicket_kind && !nonWickets.has(String(ball.wicket_kind).toLowerCase())) {
        wicketNumber += 1;
        falls.push({
          wicket_number: wicketNumber,
          runs: runningScore,
          over: Number(ball.over) || 0,
          ball_in_over: Number(ball.ball_in_over) || 0,
          batter: ball.player_out_name || "",
        });
      }
    }
    html += table(
      [
        { key: "display_name", label: "Batter", align: "left", link: "player", tagKey: "milestone_tag" },
        { key: "dismissal", label: "Dismissal", align: "left" },
        { key: "runs_display", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "fours", label: "4s", align: "right", numeric: true },
        { key: "sixes", label: "6s", align: "right", numeric: true },
        { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
      ],
      bats.map((b) => ({
        ...b,
        player: b.display_name,
        slug: b.slug,
        dismissal: dismissalText(b),
        milestone_tag: b.runs >= 100 ? "Century" : "",
        runs_display: b.not_out ? `${b.runs}*` : String(b.runs),
        sr: b.balls ? (b.runs * 100 / b.balls).toFixed(1) : "–",
      })),
      { copyLine: true, faces: true },
    );
    const batted = new Set(bats.map((b) => b.person_id));
    const dnb = (d.xi || []).filter((x) => x.team === inn.batting_team && !batted.has(x.person_id));
    if (dnb.length) {
      html += `<p class="dnb">Did not bat: ${dnb.map((x) => `<a href="#/player/${esc(x.slug)}">${esc(x.display_name)}</a>`).join(", ")}</p>`;
    }
    const extrasLabels = { byes: "b", legbyes: "lb", wides: "w", noballs: "nb", penalty: "p" };
    const extrasLine = Object.entries(extrasByType)
      .filter(([, value]) => value)
      .map(([key, value]) => `${extrasLabels[key] || key} ${value}`)
      .join(", ");
    html += `<div class="scorecard-totals">
      <div><span>Extras</span><strong>${inn.extras ?? "–"}</strong><small>${extrasLine ? `(${esc(extrasLine)})` : ""}</small></div>
      <div><span>Total</span><strong>${inn.runs}/${inn.wickets}</strong><small>${ov} overs · RR ${rr}</small></div>
    </div>`;
    html += table(
      [
        { key: "display_name", label: "Bowler", align: "left", link: "player", tagKey: "milestone_tag" },
        { key: "overs", label: "O", align: "right", numeric: true, digits: 1 },
        { key: "maidens", label: "M", align: "right", numeric: true },
        { key: "dots", label: "Dots", align: "right", numeric: true },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "econ", label: "Econ", align: "right", numeric: true, digits: 1 },
        { key: "wides", label: "Wd", align: "right", numeric: true },
        { key: "noballs", label: "Nb", align: "right", numeric: true },
      ],
      bowls.map((b) => {
        const o = Math.floor((b.legal_balls || 0) / (m.balls_per_over || 6));
        const r = (b.legal_balls || 0) % (m.balls_per_over || 6);
        const balls = b.legal_balls || 0;
        return {
          ...b,
          player: b.display_name,
          slug: b.slug,
          milestone_tag: b.wickets >= 5 ? "5-for" : "",
          overs: `${o}.${r}`,
          econ: balls ? (b.runs * 6 / balls).toFixed(1) : "–",
        };
      }),
      { faces: true },
    );
    const innOvers = oversByInnings.get(inn.innings) || [];
    if (inn.innings_kind === "regular" && innOvers.length >= 3) {
      const scheduled = Number(m.revised_overs || m.scheduled_overs || 0);
      html += manhattan(innOvers, {
        maxOvers: limitedOvers ? Math.max(scheduled, Math.ceil(Number(inn.legal_balls || 0) / bpo)) : 0,
        label: inn.batting_team,
      });
    }
    const fow = falls.map((fall) => `${fall.wicket_number}-${fall.runs}`).join(", ");
    if (fow) html += `${fowBeads(falls, Math.ceil(Number(inn.legal_balls || 0) / Number(m.balls_per_over || 6)))}<p class="fow">FoW: ${esc(fow)}</p>`;
    html += `<h3 class="section">Partnerships</h3>`;
    html += table(
      [
        { key: "wicket_number", label: "Wkt", align: "right", numeric: true },
        { key: "pair", label: "Pair", align: "left" },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "end_reason", label: "End", align: "left" },
      ],
      parts.map((p) => ({
        ...p,
        wicket_number: p.end_reason === "end_of_innings" && Number(p.wicket_number) <= lastFallenWicket
          ? Number(p.wicket_number) + 1
          : p.wicket_number,
        pair: `${p.name_1} / ${p.name_2}`,
        end_reason: endLabel(p.end_reason, inn.all_out || inn.declared),
      })),
    );
  }
  const n = (d.deliveries || []).length;
  html += `<button class="drawer" id="del-toggle">Ball-by-ball (${n} deliveries) ▸</button>
    <div id="del-table" hidden></div>`;
  main.innerHTML = html;
  bindTable("");
  warmPortraits(main);
  bindShare("share-match");
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
      (d.deliveries || []).map((x) => ({ ...x, ball: `${x.over}.${x.ball_in_over}` })),
    );
  });
}

async function showPlayer(key) {
  const gen = routeGen;
  setHero(false);
  main._profileObserver?.disconnect();
  if (!key) {
    main.innerHTML = `<div class="empty"><p>No player selected.</p><button type="button" class="chip" data-home>Back to search</button></div>`;
    main.querySelector("[data-home]")?.addEventListener("click", () => { location.hash = "#/"; });
    return;
  }
  const res = await fetch(`/api/player/${encodeURIComponent(key)}`);
  if (gen !== routeGen) return;
  const d = await res.json();
  if (!res.ok || d.detail) {
    const s = await (await fetch(`/api/suggest?q=${encodeURIComponent(key)}`)).json();
    const people = s.people || [];
    if (people.length === 1 && people[0].slug && people[0].slug !== key) {
      location.replace(`#/player/${people[0].slug}`);
      return;
    }
    if (people.length > 1) {
      const top = people[0];
      const nxt = people[1];
      const apps = Number(top.apps || 0);
      const n2 = Number(nxt.apps || 0);
      if (apps >= 15 && apps >= 3 * Math.max(n2, 1) && top.slug !== key) {
        location.replace(`#/player/${top.slug}`);
        return;
      }
      main.innerHTML = `<div class="empty"><p>${people.length} players match “${esc(key)}”. Pick one.</p>
        ${people.map((p) => `<button type="button" class="chip" data-go="${esc(p.slug)}">${esc(p.display_name)} <span class="hint">${esc(p.unique_name)}</span></button>`).join(" ")}</div>`;
      main.querySelectorAll("[data-go]").forEach((b) => {
        b.addEventListener("click", () => { location.hash = `#/player/${b.dataset.go}`; });
      });
      return;
    }
    main.innerHTML = `<div class="empty">
      <p>No player matching “${esc(key)}”.</p>
      <p class="caption">Try a last name in search, or a query chip from home.</p>
      <button type="button" class="chip" data-home>Back to search</button>
    </div>`;
    main.querySelector("[data-home]")?.addEventListener("click", () => { location.hash = "#/"; });
    return;
  }
  const p = d.person;
  const bowlerFirst = d.primary_role === "bowl";
  const val = d.value || {};
  const order = bowlerFirst
    ? ["war", "war_per_game", "raa_bowl", "te", "raa_bat", "tsr"]
    : ["war", "war_per_game", "raa_bat", "tsr", "raa_bowl", "te"];
  const byKey = Object.fromEntries((val.metrics || []).map((m) => [m.key, m]));
  const fmtVal = (m) => {
    if (!m || m.value == null) return "–";
    const dec = {
      war: 2, war_per_game: 3, war_bat: 2, war_bowl: 2,
      raa_bat: 0, raa_bowl: 0, tsr: 2, te: 2, twr_bat: 2, twr_bowl: 2,
    }[m.key] ?? 1;
    const n = Number(m.value);
    const s = n.toFixed(dec);
    const signedKeys = new Set(["raa_bat", "raa_bowl", "tsr", "te", "twr_bat", "twr_bowl"]);
    return (n > 0 && signedKeys.has(m.key) ? "+" : "") + s;
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
          ${pctBar(m.rank, m.of)}
        </div>`;
      }).join("")}</div>
      <p class="caption">Career totals — more games count. TSR and TE are strike rate and economy against the same situation, not the raw rates. In this warehouse, not an official rating.</p>`;
  } else {
    cards = `<p class="caption">${bowlerFirst ? "Bowler first — more balls bowled than faced in this warehouse." : "Ball-derived T20 metrics appear when T20I / IPL rows exist (see MODEL.md)."}</p>`;
  }
  const pf = d.performances?.rows || [];
  const h2h = d.matchups || { as_batter: [], as_bowler: [] };
  const compOrder = ["test", "odi", "t20i", "ipl", "wpl", "bbl", "wbbl"];
  const byCompOrder = (a, b) => {
    const ai = compOrder.indexOf(a);
    const bi = compOrder.indexOf(b);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || String(a).localeCompare(String(b));
  };
  const h2hComps = [...new Set([...(h2h.as_batter || []), ...(h2h.as_bowler || [])].map((r) => r.competition))].sort(byCompOrder);
  const comps = [...new Set([
    ...d.summary.map((s) => s.competition),
    ...d.bowling_summary.map((s) => s.competition),
  ])].sort(byCompOrder);
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
      { key: "competition", label: "Comp", align: "left", badge: true },
      { key: "matches", label: "M", align: "right", numeric: true },
      { key: "overs", label: "O", align: "right", numeric: true },
      { key: "maidens", label: "Mdns", align: "right", numeric: true },
      { key: "runs", label: "R", align: "right", numeric: true },
      { key: "wickets", label: "W", align: "right", numeric: true },
      { key: "avg", label: "Avg", align: "right", numeric: true },
      { key: "econ", label: "Econ", align: "right", numeric: true },
      { key: "dots", label: "Dots", align: "right", numeric: true },
      { key: "extras", label: "Ex", align: "right", numeric: true },
    ],
    bowlRows,
  );
  const batTable = `<h2 class="section">Batting</h2>` + table(
    [
      { key: "competition", label: "Comp", align: "left", badge: true },
      { key: "matches", label: "M", align: "right", numeric: true },
      { key: "inns", label: "Inns", align: "right", numeric: true },
      { key: "runs", label: "Runs", align: "right", numeric: true },
      { key: "hs", label: "HS", align: "right", numeric: true },
      { key: "avg", label: "Avg", align: "right", numeric: true },
      { key: "sr", label: "SR", align: "right", numeric: true },
      { key: "hundreds", label: "100s", align: "right", numeric: true },
      { key: "fifties", label: "50s", align: "right", numeric: true },
      { key: "fours", label: "4s", align: "right", numeric: true },
      { key: "sixes", label: "6s", align: "right", numeric: true },
    ],
    batRows,
  );
  const batOuts = d.innings.filter((i) => !i.not_out).length;
  const batRuns = d.innings.reduce((s, i) => s + Number(i.runs || 0), 0);
  const careerAvg = batOuts ? batRuns / batOuts : null;
  const totM = batRows.reduce((s, r) => s + Number(r.matches || 0), 0) || Number(d.span?.matches || 0);
  const totInns = batRows.reduce((s, r) => s + Number(r.inns || 0), 0);
  const totBalls = batRows.reduce((s, r) => s + Number(r.balls || 0), 0);
  const totHs = batRows.reduce((s, r) => Math.max(s, Number(r.hs || 0)), 0);
  const totSr = totBalls ? (batRuns * 100 / totBalls).toFixed(1) : "–";
  const totW = bowlRows.reduce((s, r) => s + Number(r.wickets || 0), 0);
  const totBowlRuns = bowlRows.reduce((s, r) => s + Number(r.runs || 0), 0);
  const totLegal = bowlRows.reduce((s, r) => s + Number(r.legal_balls || 0), 0);
  const totEcon = totLegal ? (totBowlRuns * 6 / totLegal).toFixed(2) : "–";
  const totHundreds = batRows.reduce((s, r) => s + Number(r.hundreds || 0), 0);
  const almanac = d.almanac || {};
  const cricinfo = p.key_cricinfo
    ? `<a class="ext" href="https://www.espncricinfo.com/ci/content/player/${encodeURIComponent(p.key_cricinfo)}.html" rel="noreferrer">Cricinfo</a>`
    : "";
  const teamChips = (d.teams || []).length
    ? `<div class="team-chips">${d.teams.map((t) =>
      `<a href="#/wowy?team=${encodeURIComponent(t.team)}&player=${encodeURIComponent(p.slug)}">${esc(t.team)}<span class="n">${t.matches}</span></a>`
    ).join("")}</div>`
    : "";
  const totAvg = batOuts ? (batRuns / batOuts).toFixed(1) : null;
  const totFifties = batRows.reduce((s, r) => s + Number(r.fifties || 0), 0);
  const bestBowlInn = (d.bowling_innings || []).reduce((best, i) => {
    if (!best) return i;
    const bw = Number(i.wickets || 0), cw = Number(best.wickets || 0);
    if (bw !== cw) return bw > cw ? i : best;
    return Number(i.runs || 0) < Number(best.runs || 0) ? i : best;
  }, null);
  const bestBat = d.innings.reduce((best, i) => (!best || Number(i.runs || 0) > Number(best.runs || 0) ? i : best), null);
  const bestPair = (d.pairs || [])[0];
  const bestYear = (almanac.years || []).reduce((best, y) => (!best || Number(y.runs || 0) > Number(best.runs || 0) ? y : best), null);
  const heroStats = bowlerFirst
    ? [
        ["Matches", d.span?.matches || totM || "–"],
        ["Wickets", totW || "–"],
        ["Econ", totEcon],
        ["Best", bestBowlInn ? `${bestBowlInn.wickets}/${bestBowlInn.runs}` : "–"],
        ["Runs", batRuns ? batRuns.toLocaleString() : "–"],
        ["Bat avg", totAvg ?? "–"],
      ]
    : [
        ["Matches", d.span?.matches || totM || "–"],
        ["Runs", batRuns ? batRuns.toLocaleString() : "–"],
        ["Average", totAvg ?? "–"],
        ["Strike rate", totSr],
        ["HS", totHs || "–"],
        ["100s / 50s", `${totHundreds || 0} / ${totFifties || 0}`],
      ];
  const milestoneCards = statCards([
    bestBat && Number(bestBat.runs) > 0 ? {
      kicker: "Highest score",
      value: `${bestBat.runs}${bestBat.not_out ? "*" : ""}`,
      note: `v ${esc(bestBat.opposition || "—")} · ${fmtDate(bestBat.start_date)}`,
      href: bestBat.match_id ? `#/match/${encodeURIComponent(bestBat.match_id)}` : "",
      linkLabel: "Scorecard",
    } : null,
    bestBowlInn && Number(bestBowlInn.wickets) > 0 ? {
      kicker: "Best bowling",
      value: `${bestBowlInn.wickets}/${bestBowlInn.runs}`,
      note: `v ${esc(bestBowlInn.opposition || "—")} · ${fmtDate(bestBowlInn.start_date)}`,
      href: bestBowlInn.match_id ? `#/match/${encodeURIComponent(bestBowlInn.match_id)}` : "",
      linkLabel: "Scorecard",
    } : null,
    bestYear ? {
      kicker: "Best year with the bat",
      value: Number(bestYear.runs || 0).toLocaleString(),
      note: `${bestYear.year} · ${bestYear.inns ?? "–"} innings at ${bestYear.avg ?? "–"}`,
    } : null,
    bestPair ? {
      kicker: "Most productive partner",
      value: Number(bestPair.runs || 0).toLocaleString(),
      note: `with ${esc(bestPair.partner)} · ${bestPair.inns} stands`,
      href: bestPair.partner_slug ? `#/player/${encodeURIComponent(bestPair.partner_slug)}` : "",
      linkLabel: "Profile",
    } : null,
  ]);
  const formatCardRows = batRows
    .map((s) => {
      const bowlRow = bowlRows.find((b) => b.competition === s.competition) || {};
      return { ...s, wickets: bowlRow.wickets, bowl_econ: bowlRow.econ };
    })
    .sort((a, b) => Number(b.matches || 0) - Number(a.matches || 0))
    .slice(0, 5);
  const formatCards = formatCardRows.length
    ? `<div class="format-cards">${formatCardRows.map((s) => `
        <article class="format-card">
          <div class="fc-comp"><span class="comp-badge comp-${esc(String(s.competition).toLowerCase())}">${esc(String(s.competition).toUpperCase())}</span><span class="caption">${s.matches} matches</span></div>
          <div class="fc-line"><strong>${Number(s.runs || 0).toLocaleString()}</strong> runs at ${esc(String(s.avg))}</div>
          <div class="caption">${esc(String(s.sr))} SR · HS ${s.hs ?? "–"} · ${s.hundreds || 0}×100 · ${s.fifties || 0}×50</div>
          ${s.wickets ? `<div class="caption">${s.wickets} wickets at ${esc(String(s.bowl_econ ?? "–"))} econ</div>` : ""}
        </article>`).join("")}</div>`
    : "";
  main.innerHTML = `
    <div class="player-hero">
      ${portrait(p.slug, p.display_name, "lg")}
      <div>
        <div class="page-head">
          <h1 class="page-title">${esc(p.display_name)}</h1>
          <button type="button" class="fav-star" id="fav-star" aria-pressed="false">Pin</button>
          <button type="button" class="copy-view" id="share-player" title="Copy a link to this profile">Copy link</button>
          <button type="button" class="btn-text" id="print-player">Print card</button>
        </div>
        <p class="meta-line">${esc(p.unique_name)} · ${bowlerFirst ? "Bowler" : "Batter"} first · ${esc(d.span.line)}${cricinfo ? ` · ${cricinfo}` : ""}</p>
        ${teamChips}
        ${ribbon(heroStats)}
      </div>
    </div>
    <nav class="jump player-jump" aria-label="Player profile sections">
      <button type="button" class="btn-text active" data-jump="profile-almanac">Almanac</button>
      <button type="button" class="btn-text" data-jump="profile-value">Value</button>
      <button type="button" class="btn-text" data-jump="profile-resource">Value model</button>
      <button type="button" class="btn-text" data-jump="profile-best">Best</button>
      <button type="button" class="btn-text" data-jump="profile-matchups">Matchups</button>
      <button type="button" class="btn-text" data-jump="profile-formats">By format</button>
      <button type="button" class="btn-text" data-jump="profile-innings">Innings</button>
    </nav>
    <p class="studio-links">
      <a href="#/compare?a=${encodeURIComponent(p.slug)}">Compare</a>
      · <a href="#/twin?player=${encodeURIComponent(p.slug)}">Profile twin</a>
      · <a href="#/shift?player=${encodeURIComponent(p.slug)}">Stat line shift</a>
      · <button type="button" class="btn-text" id="add-tray">C — compare tray</button>
    </p>
    <section class="profile-section" id="profile-almanac">
      ${formatCards}
      ${milestoneCards}
      ${formBlock(d.innings, { n: 10, careerAvg })}
      ${almanacBlock(almanac)}
    </section>
    <section class="profile-section profile-scope" id="profile-value">
      <h2 class="section">Utility index</h2>
      ${cards}
    </section>
    <section class="profile-section" id="profile-resource">
      <h2 class="section">Value model</h2>
      <div id="rv-box"><p class="caption">Loading…</p></div>
    </section>
    <section class="profile-section" id="profile-best">
      <h2 class="section">Best T20 ${bowlerFirst ? "bowling" : "batting"}</h2>
      <p class="caption">${esc(d.performances?.caption || "Focused on the heavier workload. Same-match work in the other discipline is shown separately.")}</p>
      <div id="pf-box"></div>
    </section>
    <section class="profile-section profile-scope" id="profile-matchups">
      <h2 class="section">Batter vs bowler</h2>
      <p class="caption">Balls they actually faced each other. Twelve-ball floor. Tables are sorted by balls.</p>
      <div class="fmt-row scoped-tabs" id="h2h-tabs">${["all", ...h2hComps].map((c, i) => `<button class="tab ${i === 0 ? "active" : ""}" data-h2h="${c}">${c === "all" ? "All" : c.toUpperCase()}</button>`).join("")}</div>
      <div id="h2h-box"></div>
    </section>
    <section class="profile-section" id="profile-formats">
      <h2 class="section">Career by format</h2>
      ${bowlerFirst ? bowlTable + batTable : batTable + bowlTable}
      <div class="fielding-strip">
        <span><strong>${d.fielding?.catches ?? 0}</strong> catches</span>
        <span><strong>${d.fielding?.run_outs ?? 0}</strong> run-outs</span>
        <span><strong>${d.fielding?.stumpings ?? 0}</strong> stumpings</span>
      </div>
    </section>
    <section class="profile-section profile-scope" id="profile-innings">
      <h2 class="section">Innings</h2>
      <div class="fmt-row scoped-tabs" id="p-tabs">${tabs}</div>
      <h3 class="section">${bowlerFirst ? "Bowling innings" : "Batting innings"}</h3>
      <div id="inn-box"></div>
      ${bowlerFirst ? `<h3 class="section">Batting innings</h3><div id="bat-box"></div>` : (d.bowling_innings?.length ? `<h3 class="section">Bowling innings</h3><div id="bowl-box"></div>` : "")}
      <h3 class="section">Partnerships</h3>
      ${table(
        [
          { key: "player", label: "Partner", align: "left", link: "player" },
          { key: "inns", label: "Stands", align: "right", numeric: true, help: "Partnership innings together" },
          { key: "runs", label: "Runs", align: "right", numeric: true },
          { key: "avg", label: "Avg", align: "right", numeric: true },
          { key: "hundreds", label: "100-stands", align: "right", numeric: true },
        ],
        (d.pairs || []).map((r) => ({ ...r, player: r.partner, slug: r.partner_slug })),
      )}
    </section>
  `;
  const matchResult = (row) => {
    if (row.winner === row.team) return "Won";
    if (row.winner) return "Lost";
    const result = String(row.result || "").toLowerCase();
    if (result === "draw") return "Draw";
    if (result === "tie") return "Tie";
    if (result === "no result") return "No result";
    return "—";
  };
  const paintBat = (comp, el) => {
    const rows = d.innings.filter((i) => comp === "all" || i.competition === comp).map((i) => ({
      ...i,
      runs_display: i.not_out ? `${i.runs}*` : String(i.runs),
      sr: i.balls ? (i.runs * 100 / i.balls).toFixed(1) : "–",
      result: matchResult(i),
      player: p.display_name,
      slug: p.slug,
    }));
    el.innerHTML = table(
      [
        { key: "start_date", label: "Date", align: "left", link: "match", groupOnce: true },
        { key: "opposition", label: "Opp", align: "left", groupOnce: true },
        { key: "competition", label: "Comp", align: "left", badge: true, groupOnce: true },
        { key: "runs_display", label: "R", align: "right", numeric: true },
        { key: "balls", label: "B", align: "right", numeric: true },
        { key: "sr", label: "SR", align: "right", numeric: true },
        { key: "dismissal_kind", label: "Dismissal", align: "left" },
        { key: "result", label: "Result", align: "left", status: true, link: false, groupOnce: true },
      ],
      rows,
      { copyLine: true, resultBorders: false, groupBy: "match_id" },
    );
  };
  const paintBowl = (comp, el) => {
    const rows = (d.bowling_innings || []).filter((i) => comp === "all" || i.competition === comp).map((i) => {
      const overs = i.legal_balls ? `${Math.floor(i.legal_balls / 6)}.${i.legal_balls % 6}` : "–";
      const econ = i.legal_balls ? (i.runs * 6 / i.legal_balls).toFixed(2) : "–";
      return { ...i, overs, econ, result: matchResult(i), player: p.display_name, slug: p.slug };
    });
    el.innerHTML = table(
      [
        { key: "start_date", label: "Date", align: "left", link: "match", groupOnce: true },
        { key: "opposition", label: "Opp", align: "left", groupOnce: true },
        { key: "competition", label: "Comp", align: "left", badge: true, groupOnce: true },
        { key: "overs", label: "O", align: "right", numeric: true },
        { key: "maidens", label: "M", align: "right", numeric: true },
        { key: "runs", label: "R", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "econ", label: "Econ", align: "right", numeric: true },
        { key: "result", label: "Result", align: "left", status: true, link: false, groupOnce: true },
      ],
      rows,
      { resultBorders: false, groupBy: "match_id" },
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
        { key: "rank", label: "Rank", align: "right", numeric: true, sortable: false },
        { key: "composite", label: "Composite", align: "right", numeric: true, digits: 1, sortable: false, help: "The same uncapped composite used on the Best T20 page" },
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "competition", label: "Comp", align: "left", badge: true },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "bat_line", label: "Bat", align: "left" },
        { key: "bowl_line", label: "Bowl", align: "left" },
        { key: "venue", label: "Venue", align: "left" },
        { key: "result", label: "Result", align: "left", status: true, link: false },
      ],
      rows,
      { resultBorders: false },
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
        { key: "competition", label: "Comp", align: "left", badge: true },
        { key: "balls", label: "Balls", align: "right", numeric: true },
        { key: "line", label: "Line", align: "left", help: "Runs scored off balls faced, with dismissals in parentheses" },
        { key: "sr", label: "SR", align: "right", numeric: true },
        { key: "dismissals", label: "Out", align: "right", numeric: true },
      ],
      bat,
      { sortKey: "balls", sortDir: "desc" },
    );
    const bowlT = table(
      [
        { key: "player", label: "Batter", align: "left", link: "player" },
        { key: "competition", label: "Comp", align: "left", badge: true },
        { key: "balls", label: "Balls", align: "right", numeric: true },
        { key: "line", label: "Line", align: "left", help: "Dismissals and runs conceded off legal balls" },
        { key: "econ", label: "Econ", align: "right", numeric: true },
        { key: "dismissals", label: "W", align: "right", numeric: true },
      ],
      bowl,
      { sortKey: "balls", sortDir: "desc" },
    );
    $("h2h-box").innerHTML = `<div class="h2h">${bowlerFirst
      ? `<section class="h2h-panel"><h3 class="section">Bowled to</h3>${bowlT}</section><section class="h2h-panel"><h3 class="section">Faced</h3>${batT}</section>`
      : `<section class="h2h-panel"><h3 class="section">Faced</h3>${batT}</section><section class="h2h-panel"><h3 class="section">Bowled to</h3>${bowlT}</section>`
    }</div>`;
  };
  paintH2h("all");
  // The resource model is a second request so the profile paints immediately
  // rather than waiting on the heavier slice aggregation.
  (async () => {
    const box = $("rv-box");
    if (!box) return;
    try {
      const rv = await (await fetch(`/api/player/${encodeURIComponent(p.slug)}/resource`)).json();
      box.innerHTML = resourcePanel(rv);
    } catch {
      box.innerHTML = `<p class="caption">Couldn’t load the value model.</p>`;
    }
  })();
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
        ${pctBar(m.rank, m.of)}
      </div>`;
    }).join("");
  });
  setDocTitle(p.display_name);
  document.body.dataset.playerSlug = p.slug;
  document.body.dataset.playerName = p.display_name;
  recentPush(p.slug, p.display_name);
  renderFavStar(p.slug, p.display_name);
  $("add-tray")?.addEventListener("click", () => trayAdd(p.slug, p.display_name));
  $("print-player")?.addEventListener("click", () => window.print());
  bindShare("share-player");
  main.querySelectorAll("[data-jump]").forEach((b) => {
    b.addEventListener("click", () => {
      main.querySelectorAll(".player-jump [data-jump]").forEach((button) => button.classList.toggle("active", button === b));
      $(b.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  const jumpNav = main.querySelector(".player-jump");
  const jumpSections = [...main.querySelectorAll(".profile-section[id]")].filter((section) =>
    jumpNav?.querySelector(`[data-jump="${section.id}"]`)
  );
  if (jumpNav && jumpSections.length) {
    let scheduled = false;
    const updateJump = () => {
      scheduled = false;
      const probe = jumpNav.getBoundingClientRect().bottom + 48;
      const current = jumpSections.find((section) => {
        const rect = section.getBoundingClientRect();
        return rect.top <= probe && rect.bottom > probe;
      }) || jumpSections.reduce((best, section) => (
        Math.abs(section.getBoundingClientRect().top - probe) < Math.abs(best.getBoundingClientRect().top - probe) ? section : best
      ));
      jumpNav.querySelectorAll("[data-jump]").forEach((button) => {
        button.classList.toggle("active", button.dataset.jump === current.id);
      });
    };
    main._profileScroll = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(updateJump);
    };
    window.addEventListener("scroll", main._profileScroll, { passive: true });
    updateJump();
  }
  bindTable("");
  warmPortraits(main);
}

const SLICE_TITLES = {
  phase: "By phase",
  inn_type: "Setting a target or chasing",
  entry_role: "By the state they walked into",
  position_bucket: "By batting position",
  press_band: "By target pressure",
  set_state: "New at the crease or set",
};

// Runs above average, split by situation. A bar per slice, signed from a centre
// line, because the question is always "better or worse than average here".
function sliceBars(block) {
  const rows = (block.rows || []).filter((r) => r.rate != null);
  if (!rows.length) return "";
  const span = Math.max(...rows.map((r) => Math.abs(Number(r.rate))), 0.5);
  const bars = rows.map((r) => {
    const v = Number(r.rate);
    const width = (Math.abs(v) / span * 50).toFixed(1);
    const good = v > 0;
    return `<div class="slice-row">
      <span class="slice-lab">${esc(titleCase(r.key))}</span>
      <span class="slice-track">
        <span class="slice-mid" aria-hidden="true"></span>
        <span class="slice-fill ${good ? "pos" : "neg"}" style="${good ? "left:50%" : `right:50%`};width:${width}%"></span>
      </span>
      <span class="slice-val ${good ? "pos" : "neg"}">${signed(v, 2)}</span>
      <span class="slice-exp">${Number(r.exposure).toLocaleString()}</span>
    </div>`;
  }).join("");
  return `<article class="slice-block">
    <h4 class="slice-title">${esc(SLICE_TITLES[block.kind] || titleCase(block.kind))}</h4>
    <div class="slice-bars">${bars}</div>
  </article>`;
}

function resourcePanel(d) {
  if (!d?.ok || !d.panels?.length) {
    return `<p class="caption">No resource-model value yet. It covers men's and women's T20 and IT20 — T20Is, the IPL, WPL, BBL and WBBL. Rebuild metrics if this looks wrong.</p>`;
  }
  const c = d.career;
  const label = d.war_label === "WAR" ? "WAR" : "Wins-equivalent";
  const fmt = (v, dec) => (v == null ? "–" : signed(Number(v), dec));
  const panels = d.panels.map((p) => `
    <article class="value-panel">
      <header>
        <h3>${esc(p.title)}</h3>
        <span class="caption">${Number(p.exposure).toLocaleString()} ${esc(p.exposure_label)}</span>
      </header>
      <div class="value-grid">${p.items.map((i) => `
        <div class="value-cell">
          <div class="name">${esc(i.label)} <span class="info" tabindex="0">i<span class="pop">${esc(i.copy)}</span></span></div>
          <div class="val ${Number(i.value) < 0 ? "neg" : ""}">${i.kind === "wins" ? Number(i.value ?? 0).toFixed(3) : fmt(i.value, i.kind === "runs" ? 0 : 2)}</div>
        </div>`).join("")}</div>
    </article>`).join("");
  const skills = d.skills?.length
    ? `<h3 class="section">Where the value comes from</h3>
       <p class="caption">Each line is measured against what the same situation produces on average, so a low total is a real shortfall rather than a hard match.</p>
       <div class="skill-list">${d.skills.map((s) => `
         <div class="skill-row">
           <span class="skill-lab">${esc(s.label)}</span>
           <span class="skill-val ${s.good ? "pos" : "neg"}">${signed(Number(s.value), 2)}</span>
           <span class="skill-unit">${esc(s.unit)}</span>
           <span class="info" tabindex="0">i<span class="pop">${esc(s.copy)}</span></span>
         </div>`).join("")}</div>`
    : "";
  const blocks = (d.slices || []);
  const batBlocks = blocks.filter((b) => b.discipline === "bat").map(sliceBars).join("");
  const bowlBlocks = blocks.filter((b) => b.discipline === "bowl").map(sliceBars).join("");
  const sliceSection = (batBlocks || bowlBlocks)
    ? `<h3 class="section">Runs above average by situation</h3>
       <p class="caption">Batting is per 100 balls faced, bowling per over. The number on the right is the exposure behind each bar. Twenty-ball floor.</p>
       ${batBlocks ? `<h4 class="slice-head">Batting</h4><div class="slice-grid">${batBlocks}</div>` : ""}
       ${bowlBlocks ? `<h4 class="slice-head">Bowling</h4><div class="slice-grid">${bowlBlocks}</div>` : ""}`
    : "";
  const total = (c.war_bat ?? 0) + (c.war_bowl ?? 0);
  const batMix = mixBars(d.dismissals?.bat);
  const bowlMix = mixBars(d.dismissals?.bowl);
  const phase = (d.phase_share || []).filter((r) => r.share > 0);
  const phaseBlock = phase.length
    ? `<article class="slice-block">
        <h4 class="slice-title">Bowling workload, % of balls</h4>
        ${mixBars(phase.map((r) => ({ label: titleCase(r.phase), n: Math.round(Number(r.share)) })))}
        <p class="caption">${phase.map((r) => `${Number(r.exposure).toLocaleString()} ${r.phase}`).join(" · ")}</p>
      </article>`
    : "";
  const mixSection = (batMix || bowlMix || phaseBlock)
    ? `<h3 class="section">How they get out, and how they take wickets</h3>
       <p class="caption">T20 only. Caught stays separate from caught-and-bowled. Counts, not rates.</p>
       <div class="slice-grid">
         ${batMix ? `<article class="slice-block"><h4 class="slice-title">Dismissed</h4>${batMix}</article>` : ""}
         ${bowlMix ? `<article class="slice-block"><h4 class="slice-title">Wickets taken</h4>${bowlMix}</article>` : ""}
         ${phaseBlock}
       </div>`
    : "";
  return `
    <p class="lede">${label} from the resource model: every ball is valued by what it did to the runs and wickets the side had left, then compared with an average player in the same position.</p>
    ${ribbon([
      [`${label}`, total.toFixed(2)],
      ["Batting", (c.war_bat ?? 0).toFixed(2)],
      ["Bowling", (c.war_bowl ?? 0).toFixed(2)],
      ["Runs above average", signed((c.raa_bat ?? 0) + (c.raa_bowl ?? 0), 0)],
      ["Balls faced", Number(c.bf || 0).toLocaleString()],
      ["Balls bowled", Number(c.lb || 0).toLocaleString()],
    ])}
    <div class="value-panels">${panels}</div>
    ${skills}
    ${mixSection}
    ${sliceSection}
    <p class="caption">Runs above replacement subtracts what a fringe player in the same batting position or bowling phase would have produced, and wins divide that by the runs-per-win figure calibrated for this competition. <a href="#/model">How the model works</a>.</p>`;
}

// Rate stats (average, strike rate, economy) get the WTC-sides filter, because
// associate-level T20Is otherwise fill the top of every rate table.
const STAT_PRESETS = [
  { label: "T20 value", hint: "Career WAR across T20Is and the IPL", state: { comp: "t20i_ipl", role: "all", sort: "war", min_inns: 8, wtc: false } },
  { label: "Batting value", hint: "Batting runs above average per 100 balls, Test nations", state: { comp: "t20i_ipl", role: "bat", sort: "raa100_bat", min_inns: 20, wtc: true } },
  { label: "Bowling value", hint: "Bowling runs above average per over, Test nations", state: { comp: "t20i_ipl", role: "bowl", sort: "raa_over_bowl", min_inns: 20, wtc: true } },
  { label: "Run scorers", hint: "Most runs in T20Is and the IPL", state: { comp: "t20i_ipl", role: "bat", sort: "runs", min_inns: 20, wtc: false } },
  { label: "Wicket takers", hint: "Most wickets in T20Is and the IPL", state: { comp: "t20i_ipl", role: "bowl", sort: "wickets", min_inns: 20, wtc: false } },
  { label: "Best average", hint: "Batting average, Test nations, 40-innings floor", state: { comp: "t20i_ipl", role: "bat", sort: "avg", min_inns: 40, wtc: true } },
  { label: "Fastest scoring", hint: "Strike rate, Test nations, 40-innings floor", state: { comp: "t20i_ipl", role: "bat", sort: "sr", min_inns: 40, wtc: true } },
  { label: "Scoring vs situation", hint: "True strike-rate residual, Test nations", state: { comp: "t20i_ipl", role: "bat", sort: "tsr", min_inns: 20, wtc: true } },
  { label: "Tightest bowling", hint: "Economy rate, Test nations, 40-wicket floor", state: { comp: "t20i_ipl", role: "bowl", sort: "econ", min_inns: 40, wtc: true } },
  { label: "Bowling vs situation", hint: "True economy residual, Test nations", state: { comp: "t20i_ipl", role: "bowl", sort: "te", min_inns: 20, wtc: true } },
  { label: "Test batting", hint: "Test runs, 20-innings floor", state: { comp: "test", role: "bat", sort: "runs", min_inns: 20, wtc: false } },
  { label: "Test bowling", hint: "Test wickets, 20-wicket floor", state: { comp: "test", role: "bowl", sort: "wickets", min_inns: 20, wtc: false } },
];

async function showStats() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Stats");
  const hp = new URLSearchParams((decodeURIComponent(location.hash).split("?")[1] || ""));
  const state = {
    comp: hp.get("comp") || "t20i_ipl",
    gender: hp.get("gender") || "male",
    role: hp.get("role") || "all",
    sort: hp.get("sort") || "war",
    min_inns: Number(hp.get("min") || 8),
    wtc: hp.get("wtc") === "true",
    scatter: hp.get("scatter") === "1",
  };
  const syncHash = () => {
    const qs = new URLSearchParams({
      comp: state.comp, gender: state.gender, role: state.role, sort: state.sort, min: String(state.min_inns),
    });
    if (state.wtc) qs.set("wtc", "true");
    if (state.scatter) qs.set("scatter", "1");
    history.replaceState(null, "", `#/stats?${qs}`);
  };
  const paint = async () => {
    if (state.gender === "female" && state.comp === "t20i_ipl") state.comp = "t20i_wpl";
    if (state.gender === "male" && state.comp === "t20i_wpl") state.comp = "t20i_ipl";
    syncHash();
    const qs = new URLSearchParams({ role: state.role, sort: state.sort, min_inns: String(state.min_inns), wtc: state.wtc ? "true" : "false" });
    if (state.comp) qs.set("comp", state.comp);
    if (state.gender) qs.set("gender", state.gender);
    const d = await (await fetch(`/api/stats?${qs}`)).json();
    const fmtOpts = state.gender === "female"
      ? [["t20i_wpl","T20I + WPL"],["t20i","T20I"],["wpl","WPL"],["odi","ODI"],["test","Tests"],["wbbl","WBBL"],["","All"]]
      : [["t20i_ipl","T20I + IPL"],["t20i","T20I"],["ipl","IPL"],["odi","ODI"],["test","Tests"],["bbl","BBL"],["","All"]];
    const naturalSortDir = HEAT_LOW.has(state.sort) ? "asc" : "desc";
    const activePreset = STAT_PRESETS.find((p) =>
      Object.entries(p.state).every(([k, v]) => String(state[k]) === String(v))
    );
    main.innerHTML = `
      <h1 class="page-title">Stats</h1>
      <p class="lede">Counting stats and T20 value in one table. Click a header to sort. C on a row to compare. T for table focus.</p>
      ${leaderboardNav("stats")}
      <div class="record-tabs" id="st-presets" role="group" aria-label="Quick views">
        <span class="fmt-label">Quick views</span>
        ${STAT_PRESETS.map((p, i) => `<button type="button" class="chip ${activePreset === p ? "on" : ""}" data-preset="${i}" title="${esc(p.hint)}">${esc(p.label)}</button>`).join("")}
      </div>
      <div class="stats-toolbar">
        <div class="filters stats-filters" aria-label="Filters">
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
              <option value="all">All roles</option>
              <option value="bat" ${state.role==="bat"?"selected":""}>Batters</option>
              <option value="bowl" ${state.role==="bowl"?"selected":""}>Bowlers</option>
            </select>
          </label>
          <label>Min innings / wickets
            <input type="number" id="st-min" min="1" max="999" step="1" value="${state.min_inns}" inputmode="numeric">
          </label>
          <label class="check"><input type="checkbox" id="st-wtc" ${state.wtc?"checked":""}> WTC sides only</label>
        </div>
        <div class="view-options" aria-label="View options">
          <span class="view-label">View</span>
          <button type="button" class="view-toggle" id="st-sc" aria-pressed="${state.scatter}">WAR vs strike rate</button>
          <button type="button" class="copy-view" id="st-share" title="Copy a link to these filters">Copy view</button>
        </div>
      </div>
      <p class="scope">${esc(d.scope || "")}</p>
      <div id="st-scatter">${state.scatter ? scatterSVG(d.rows || [], { xKey: "sr", yKey: "war", xLab: "Strike rate", yLab: "WAR" }) : ""}</div>
      <div class="heat-legend"><span>Cell shading</span><i aria-hidden="true"></i><span>higher percentile in sorted column</span></div>
      <div id="st-table"></div>`;
    const coreCols = [
      { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
      { key: "player", label: "Player", align: "left", link: "player", sortable: false },
      { key: "primary_role", label: "Role", align: "left", sortable: false },
      { key: "matches", label: "M", align: "right", numeric: true, sortable: false, help: "Matches played" },
      { key: "war", label: "WAR", align: "right", numeric: true, help: "Career wins above replacement in this filtered pool" },
      { key: "war_per_game", label: "WAR/g", align: "right", numeric: true, help: "WAR per match; shown after 20 matches" },
    ];
    const batCols = [
      { key: "runs", label: "Runs", align: "right", numeric: true, roleGroup: "bat", help: "Career runs" },
      { key: "hs", label: "HS", align: "right", numeric: true, sortable: false, roleGroup: "bat", help: "Highest score" },
      { key: "avg", label: "Avg", align: "right", numeric: true, roleGroup: "bat", help: "Batting average: runs per dismissal" },
      { key: "sr", label: "SR", align: "right", numeric: true, roleGroup: "bat", help: "Batting strike rate: runs per 100 balls" },
      { key: "tsr", label: "TSR", align: "right", numeric: true, digits: 2, roleGroup: "bat", help: "True strike-rate residual: runs per 100 balls above what the same situation usually yields. Needs 60 balls in this pool" },
      { key: "hundreds", label: "100s", align: "right", numeric: true, sortable: false, roleGroup: "bat", help: "Innings of 100 or more" },
      { key: "raa_bat", label: "RAA", align: "right", numeric: true, digits: 0, roleGroup: "bat", help: "Runs above average with the bat, judged ball by ball against the same balls remaining, wickets in hand and target pressure" },
      { key: "raa100_bat", label: "RAA/100", align: "right", numeric: true, digits: 2, roleGroup: "bat", help: "Batting runs above average per 100 balls faced. Needs 300 balls in this pool" },
      { key: "war_bat", label: "bWAR", align: "right", numeric: true, digits: 2, roleGroup: "bat", help: "Batting wins above replacement from the resource model" },
    ];
    const bowlCols = [
      { key: "wickets", label: "W", align: "right", numeric: true, roleGroup: "bowl", help: "Career wickets" },
      { key: "bowl_avg", label: "BAvg", align: "right", numeric: true, roleGroup: "bowl", help: "Bowling average: runs conceded per wicket" },
      { key: "econ", label: "Econ", align: "right", numeric: true, roleGroup: "bowl", help: "Economy rate: runs conceded per six legal balls" },
      { key: "te", label: "TE", align: "right", numeric: true, digits: 2, roleGroup: "bowl", help: "True economy residual: runs per over conceded above expectation. Negative is good. Needs 60 balls in this pool" },
      { key: "raa_bowl", label: "RAA", align: "right", numeric: true, digits: 0, roleGroup: "bowl", help: "Runs above average with the ball, counting runs conceded and wickets taken against the same match state" },
      { key: "raa_over_bowl", label: "RAA/ov", align: "right", numeric: true, digits: 2, roleGroup: "bowl", help: "Bowling runs above average per over. Needs 300 balls in this pool" },
      { key: "war_bowl", label: "pWAR", align: "right", numeric: true, digits: 2, roleGroup: "bowl", help: "Bowling wins above replacement from the resource model" },
    ];
    const cols = [...coreCols];
    if (state.role !== "bowl") cols.push({ group: "Batting", cols: batCols });
    if (state.role !== "bat") cols.push({ group: "Bowling", cols: bowlCols });
    $("st-table").innerHTML = table(cols, d.rows || [], {
      heat: state.sort,
      sortKey: state.sort,
      sortDir: naturalSortDir,
      searchable: true,
      searchLabel: "Find a player in this table",
      onSort: (key) => {
        if (["rank", "player", "primary_role", "matches", "hs", "hundreds"].includes(key)) return;
        state.sort = key;
        paint();
      },
    });
    bindTable("");
    $("st-presets")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-preset]");
      if (!btn) return;
      const preset = STAT_PRESETS[Number(btn.dataset.preset)];
      if (!preset) return;
      Object.assign(state, preset.state);
      paint();
    });
    const bind = (id, key) => $(id)?.addEventListener("change", (e) => { state[key] = e.target.value; paint(); });
    bind("st-comp", "comp");
    bind("st-g", "gender");
    bind("st-role", "role");
    $("st-wtc")?.addEventListener("change", (e) => { state.wtc = e.target.checked; paint(); });
    $("st-sc")?.addEventListener("click", () => { state.scatter = !state.scatter; paint(); });
    $("st-min")?.addEventListener("change", (e) => { state.min_inns = Number(e.target.value); paint(); });
    $("st-share")?.addEventListener("click", () => copyText(location.href));
  };
  await paint();
}

async function showWowy() {
  setHero(false);
  setDocTitle("WOWY");
  const qteam = hashParam("team") || "India";
  const qplayer = hashParam("player");
  const qcomp = hashParam("comp");
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
          ${["test","odi","t20i","ipl","wpl","bbl","wbbl"].map((c) => `<option value="${c}" ${qcomp===c?"selected":""}>${c.toUpperCase()}</option>`).join("")}
        </select>
      </label>
      <button class="btn primary" id="wy-go">Run split</button>
    </div>
    <div id="wy-out"></div>`;
  const run = async () => {
    const team = $("wy-team").value.trim();
    const player = $("wy-player").dataset.resolved || $("wy-player").value.trim();
    if (!team || !player) {
      $("wy-out").innerHTML = `<p class="caption">Pick a team and a player.</p>`;
      return;
    }
    const qs = new URLSearchParams({ team, player });
    const comp = $("wy-comp").value;
    if (comp) qs.set("comp", comp);
    history.replaceState(null, "", `#/wowy?${qs}`);
    const d = await (await fetch(`/api/wowy?${qs}`)).json();
    if (d.people?.length > 1 && !d.rows?.length) {
      $("wy-out").innerHTML = `<p>${esc(d.message || "Several matches")}</p>` +
        d.people.map((p) => `<button class="chip" data-p="${esc(p.slug)}">${portrait(p.slug, p.display_name, "xs")}${esc(p.display_name)}</button>`).join(" ");
      $("wy-out").querySelectorAll("[data-p]").forEach((b) => {
        b.addEventListener("click", () => { $("wy-player").value = b.dataset.p; run(); });
      });
      warmPortraits($("wy-out"));
      return;
    }
    $("wy-out").innerHTML = `<div class="wowy-head">${portrait(d.person?.slug || player, d.person?.display_name || player, "sm")}<p class="scope">${esc(d.scope || "")}</p></div>` +
      wowyVisual(d.rows || []) +
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
    bindTable("");
    warmPortraits($("wy-out"));
  };
  $("wy-go").addEventListener("click", run);
  bindFieldAutocomplete("wy-team", "teams");
  bindFieldAutocomplete("wy-player", "people");
  if (qplayer) run();
}

async function showBest() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Best T20");
  const state = {
    mode: hashParam("mode") || "composite",
    disc: hashParam("discipline") || "bowl",
    comp: hashParam("comp") || "t20i_ipl",
    gender: hashParam("gender") || "male",
    wtc: hashParam("wtc") === "true",
  };
  const paint = async () => {
    if (state.gender === "female" && (state.comp === "t20i_ipl" || state.comp === "ipl")) state.comp = "t20i_wpl";
    if (state.gender === "male" && (state.comp === "t20i_wpl" || state.comp === "wpl")) state.comp = "t20i_ipl";
    const qs = new URLSearchParams({ limit: "40", gender: state.gender, wtc: state.wtc ? "true" : "false", mode: state.mode });
    if (state.comp) qs.set("comp", state.comp);
    if (state.mode !== "composite") qs.set("discipline", state.disc);
    const d = await (await fetch(`/api/best?${qs}`)).json();
    const compositeInfo = "NRC contributes 55%, WPA translated to runs 35%, and pressure 10%. Each component is standardized within competition, gender, and discipline. Batting and bowling blends from the same match are added. The index is unbounded: 100 is the reference line and each 10 points is one blended standard deviation. It is not raw runs added.";
    main.innerHTML = `
      <h1 class="page-title">Best T20</h1>
      <p class="lede">The strongest T20 performances in this warehouse, with batting and bowling from the same match counted together.</p>
      ${leaderboardNav("best")}
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
            ${(state.gender === "female"
              ? [["t20i_wpl","T20I + WPL"],["t20i","T20I"],["wpl","WPL"],["t20","All T20"]]
              : [["t20i_ipl","T20I + IPL"],["t20i","T20I"],["ipl","IPL"],["t20","All T20"]]
            ).map(([k,l]) => `<option value="${k}" ${state.comp===k?"selected":""}>${l}</option>`).join("")}
          </select>
        </label>
        <label>Gender
          <select id="bt-g">
            <option value="male" ${state.gender==="male"?"selected":""}>Men</option>
            <option value="female" ${state.gender==="female"?"selected":""}>Women</option>
          </select>
        </label>
        <label class="check" title="Drops associate internationals; domestic league matches are unchanged."><input type="checkbox" id="bt-wtc" ${state.wtc?"checked":""}> WTC sides only</label>
      </div>
      <p class="performance-scale"><strong>Reading the composite:</strong> 100 is the reference line; a great all-round night lands in the 130s; the all-time top performances clear 180. A 2-for raises a hundred—it does not average it down.</p>
      <div id="bt-table"></div>`;
    $("bt-table").innerHTML = table(
      [
        { key: "rank", label: "Rank", align: "right", numeric: true, sortable: false },
        { key: "composite", label: "Composite", align: "right", numeric: true, digits: 1, sortable: false, info: compositeInfo },
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "competition", label: "Comp", align: "left", badge: true },
        { key: "opposition", label: "Opp", align: "left" },
        { key: "bat_line", label: "Bat", align: "left" },
        { key: "bowl_line", label: "Bowl", align: "left" },
        { key: "venue", label: "Venue", align: "left" },
        { key: "result", label: "Result", align: "left", status: true, link: false },
      ],
      d.rows || [],
      { faces: true, resultBorders: false },
    );
    bindTable("");
    warmPortraits(main);
    $("bt-m").addEventListener("change", (e) => { state.mode = e.target.value; paint(); });
    $("bt-d")?.addEventListener("change", (e) => { state.disc = e.target.value; paint(); });
    $("bt-c").addEventListener("change", (e) => { state.comp = e.target.value; paint(); });
    $("bt-g").addEventListener("change", (e) => {
      state.gender = e.target.value;
      if (state.gender === "female" && (state.comp === "t20i_ipl" || state.comp === "ipl")) state.comp = "t20i_wpl";
      if (state.gender === "male" && (state.comp === "t20i_wpl" || state.comp === "wpl")) state.comp = "t20i_ipl";
      paint();
    });
    $("bt-wtc")?.addEventListener("change", (e) => { state.wtc = e.target.checked; paint(); });
  };
  await paint();
}

function hashParam(name) {
  try {
    const i = location.hash.indexOf("?");
    if (i < 0) return "";
    return new URLSearchParams(location.hash.slice(i + 1)).get(name) || "";
  } catch {
    return "";
  }
}

function shareButton(id = "share-view") {
  return `<button type="button" class="copy-view" id="${id}" title="Copy a link to this view">Copy link</button>`;
}

function bindShare(id = "share-view") {
  $(id)?.addEventListener("click", () => copyText(location.href));
}

const COMP_CHOICES = [
  ["", "All competitions"],
  ["test", "Tests"],
  ["odi", "ODI"],
  ["t20i", "T20I"],
  ["ipl", "IPL"],
  ["wpl", "WPL"],
  ["bbl", "BBL"],
  ["wbbl", "WBBL"],
  ["internationals", "All internationals"],
  ["leagues", "All leagues"],
];

const RECORD_COLUMNS = {
  high_scores: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "runs_display", label: "Runs", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
    { key: "fours", label: "4s", align: "right", numeric: true },
    { key: "sixes", label: "6s", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  best_bowling: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "figures", label: "Figures", align: "left" },
    { key: "overs", label: "O", align: "right", numeric: true },
    { key: "econ", label: "Econ", align: "right", numeric: true, digits: 2 },
    { key: "maidens", label: "Mdns", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  partnerships: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "runs", label: "Runs", align: "right", numeric: true },
    { key: "pair", label: "Pair", align: "left" },
    { key: "wicket_number", label: "Wkt", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "team", label: "For", align: "left" },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  team_totals: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "total", label: "Total", align: "left" },
    { key: "team", label: "Side", align: "left", link: "team" },
    { key: "overs", label: "O", align: "right", numeric: true },
    { key: "rr", label: "RR", align: "right", numeric: true, digits: 2 },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  low_totals: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "total", label: "Total", align: "left" },
    { key: "team", label: "Side", align: "left", link: "team" },
    { key: "overs", label: "O", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  most_sixes: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "sixes", label: "6s", align: "right", numeric: true },
    { key: "runs_display", label: "Runs", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  fast_hundreds: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "balls_to", label: "Balls to 100", align: "right", numeric: true, help: "Balls faced when the hundred came up" },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "runs_display", label: "Finished", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "sixes", label: "6s", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  fast_fifties: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "balls_to", label: "Balls to 50", align: "right", numeric: true, help: "Balls faced when the fifty came up" },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "runs_display", label: "Finished", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "sixes", label: "6s", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  big_wins: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "margin", label: "Margin", align: "left" },
    { key: "winner", label: "Winner", align: "left", link: "team" },
    { key: "loser", label: "Beat", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  ducks: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
  carried_bat: [
    { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
    { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
    { key: "player", label: "Player", align: "left", link: "player" },
    { key: "runs_display", label: "Runs", align: "right", numeric: true },
    { key: "balls", label: "B", align: "right", numeric: true },
    { key: "sixes", label: "6s", align: "right", numeric: true },
    { key: "opposition", label: "Opp", align: "left" },
    { key: "comp", label: "Comp", align: "left", badge: true },
    { key: "start_date", label: "Date", align: "left", link: "match" },
    { key: "venue", label: "Ground", align: "left", link: "venue" },
  ],
};

async function showRecords() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Records");
  const state = {
    kind: hashParam("kind") || "high_scores",
    comp: hashParam("comp") || "",
    gender: hashParam("gender") || "male",
    wtc: hashParam("wtc") === "true",
  };
  const paint = async () => {
    const qs = new URLSearchParams({ kind: state.kind, gender: state.gender, limit: "60" });
    if (state.comp) qs.set("comp", state.comp);
    if (state.wtc) qs.set("wtc", "true");
    history.replaceState(null, "", `#/records?${qs}`);
    main.innerHTML = `
      <h1 class="page-title">Record book</h1>
      <p class="lede">The extremes this warehouse holds. Tests from 1877 and ODIs from 1971 are on the card; fastest fifties and hundreds still need the ball-by-ball era.</p>
      ${leaderboardNav("records")}
      <div id="rec-body"><div class="skel"></div><div class="skel"></div></div>`;
    const d = await fetch(`/api/records?${qs}`).then((r) => r.json()).catch(() => ({ rows: [], kinds: [] }));
    const kinds = d.kinds || [];
    const rows = (d.rows || []).map((r, i) => ({ ...r, rank: i + 1, player: r.display_name || r.player }));
    const cols = RECORD_COLUMNS[state.kind] || RECORD_COLUMNS.high_scores;
    $("rec-body").innerHTML = `
      <div class="record-tabs" role="group" aria-label="Record type">
        ${kinds.map((k) => `<button type="button" class="chip ${k.id === state.kind ? "on" : ""}" data-kind="${esc(k.id)}">${esc(k.label)}</button>`).join("")}
      </div>
      <div class="stats-toolbar">
        <div class="filters" aria-label="Filters">
          <label>Competition
            <select id="rc-comp">${COMP_CHOICES.map(([k, l]) => `<option value="${k}" ${state.comp === k ? "selected" : ""}>${l}</option>`).join("")}</select>
          </label>
          <label>Gender
            <select id="rc-g">
              <option value="male" ${state.gender === "male" ? "selected" : ""}>Men</option>
              <option value="female" ${state.gender === "female" ? "selected" : ""}>Women</option>
              <option value="" ${state.gender === "" ? "selected" : ""}>Both</option>
            </select>
          </label>
          <label class="check" title="Drops associate internationals; leagues are unchanged."><input type="checkbox" id="rc-wtc" ${state.wtc ? "checked" : ""}> Full members only</label>
        </div>
        <div class="view-options">${shareButton("rc-share")}</div>
      </div>
      <h2 class="section">${esc(d.label || "")}</h2>
      <p class="caption">${esc(d.blurb || "")}</p>
      <p class="scope">${esc(d.scope || "")}</p>
      ${table(cols, rows, { searchable: true, searchLabel: "Filter these records" })}`;
    bindTable("");
    warmPortraits(main);
    bindShare("rc-share");
    $("rec-body").querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
      state.kind = b.dataset.kind;
      paint();
    }));
    $("rc-comp")?.addEventListener("change", (e) => { state.comp = e.target.value; paint(); });
    $("rc-g")?.addEventListener("change", (e) => { state.gender = e.target.value; paint(); });
    $("rc-wtc")?.addEventListener("change", (e) => { state.wtc = e.target.checked; paint(); });
  };
  await paint();
}

async function showGrounds() {
  setHero(false);
  setDocTitle("Grounds");
  const q = hashParam("q") || "";
  main.innerHTML = `
    <h1 class="page-title">Grounds</h1>
    <p class="lede">Which venues favour the chase, what a par first-innings score looks like, and who scores runs there.</p>
    <div class="filters">
      <label>Find a ground <input type="text" id="gr-q" value="${esc(q)}" placeholder="Eden Gardens"></label>
    </div>
    <div id="gr-out"><div class="skel"></div></div>`;
  const paint = async (needle) => {
    const d = await fetch(`/api/venues?q=${encodeURIComponent(needle || "")}&limit=60`)
      .then((r) => r.json()).catch(() => ({ venues: [] }));
    $("gr-out").innerHTML = table(
      [
        { key: "ground", label: "Ground", align: "left", link: "venue", clip: false },
        { key: "city", label: "City", align: "left" },
        { key: "matches", label: "Matches", align: "right", numeric: true },
        { key: "range", label: "Span", align: "left" },
      ],
      d.venues || [],
      { sortKey: "matches", sortDir: "desc", searchable: true, searchLabel: "Filter grounds" },
    );
    bindTable("");
  };
  await paint(q);
  let timer;
  $("gr-q")?.addEventListener("input", (e) => {
    clearTimeout(timer);
    const v = e.target.value.trim();
    timer = setTimeout(() => {
      history.replaceState(null, "", v ? `#/grounds?q=${encodeURIComponent(v)}` : "#/grounds");
      paint(v);
    }, 220);
  });
}

async function showVenue(name) {
  setHero(false);
  main.classList.add("wide");
  const ground = name || hashParam("name") || "";
  if (!ground) return showGrounds();
  setDocTitle(ground);
  const comp = hashParam("comp") || "";
  const gender = hashParam("gender") || "";
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const qs = new URLSearchParams({ name: ground });
  if (comp) qs.set("comp", comp);
  if (gender) qs.set("gender", gender);
  const d = await fetch(`/api/venue?${qs}`).then((r) => r.json()).catch(() => ({ ok: false }));
  if (!d.ok) {
    main.innerHTML = `<div class="empty"><p>${esc(d.error || "Ground not found.")}</p>
      <a class="chip" href="#/grounds">All grounds</a></div>`;
    return;
  }
  const fi = d.first_innings || {};
  const res = d.results || {};
  const toss = d.toss || {};
  const tossTotal = (toss.bat || 0) + (toss.field || 0);
  main.innerHTML = `
    <div class="page-head">
      <h1 class="page-title">${esc(d.venue)}</h1>
      ${shareButton("vn-share")}
    </div>
    <p class="meta-line">${esc(d.city || "")} · ${d.matches.toLocaleString()} matches · ${esc(d.range || "")}</p>
    <div class="stats-toolbar">
      <div class="filters">
        <label>Competition
          <select id="vn-comp">${COMP_CHOICES.map(([k, l]) => `<option value="${k}" ${comp === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        </label>
        <label>Gender
          <select id="vn-g">
            <option value="" ${gender === "" ? "selected" : ""}>Both</option>
            <option value="male" ${gender === "male" ? "selected" : ""}>Men</option>
            <option value="female" ${gender === "female" ? "selected" : ""}>Women</option>
          </select>
        </label>
      </div>
    </div>
    ${comp ? "" : `<p class="caption">Showing every format together — a Test innings and a T20 innings are in the same average. Pick a competition for a number you can use.</p>`}
    ${statCards([
      { kicker: "Par first innings", value: fi.avg == null ? "–" : num(fi.avg, 1), note: fi.run_rate != null ? `${fi.run_rate} run rate` : "" },
      { kicker: "Highest first innings", value: fi.max == null ? "–" : num(fi.max, 0) },
      { kicker: "Chase wins", value: res.chase_pct == null ? "–" : `${res.chase_pct}%`, note: `${res.chasing || 0} chasing · ${res.defending || 0} defending` },
      { kicker: "Captains who batted", value: tossTotal ? `${Math.round((toss.bat || 0) * 100 / tossTotal)}%` : "–", note: `${toss.bat || 0} bat · ${toss.field || 0} field at the toss` },
    ])}
    <h2 class="section">By competition</h2>
    ${table(
      [
        { key: "comp", label: "Competition", align: "left" },
        { key: "matches", label: "Matches", align: "right", numeric: true },
        { key: "first_date", label: "First", align: "left" },
        { key: "last_date", label: "Latest", align: "left" },
      ],
      d.by_comp || [],
    )}
    <h2 class="section">Most runs here</h2>
    ${table(
      [
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "inns", label: "Inns", align: "right", numeric: true },
        { key: "runs", label: "Runs", align: "right", numeric: true },
        { key: "hs", label: "HS", align: "right", numeric: true },
        { key: "avg", label: "Avg", align: "right", numeric: true, digits: 1 },
        { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
        { key: "hundreds", label: "100s", align: "right", numeric: true },
        { key: "fifties", label: "50s", align: "right", numeric: true },
      ],
      d.top_bat || [],
      { faces: true, sortKey: "runs", sortDir: "desc" },
    )}
    <h2 class="section">Most wickets here</h2>
    ${table(
      [
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "inns", label: "Inns", align: "right", numeric: true },
        { key: "overs", label: "O", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "best", label: "Best", align: "right", numeric: true },
        { key: "avg", label: "Avg", align: "right", numeric: true, digits: 1 },
        { key: "econ", label: "Econ", align: "right", numeric: true, digits: 2 },
      ],
      d.top_bowl || [],
      { faces: true, sortKey: "wickets", sortDir: "desc" },
    )}
    <h2 class="section">Latest matches here</h2>
    ${table(
      [
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "fixture", label: "Match", align: "left" },
        { key: "comp", label: "Comp", align: "left", badge: true },
        { key: "result", label: "Result", align: "left" },
      ],
      d.recent || [],
    )}`;
  bindTable("");
  warmPortraits(main);
  bindShare("vn-share");
  const reload = () => {
    const qsx = new URLSearchParams({ name: d.venue });
    if ($("vn-comp").value) qsx.set("comp", $("vn-comp").value);
    if ($("vn-g").value) qsx.set("gender", $("vn-g").value);
    location.hash = `#/venue?${qsx}`;
  };
  $("vn-comp")?.addEventListener("change", reload);
  $("vn-g")?.addEventListener("change", reload);
}

async function showTeam(name) {
  setHero(false);
  main.classList.add("wide");
  const side = name || hashParam("name") || "";
  if (!side) {
    main.innerHTML = `<h1 class="page-title">Teams</h1>
      <p class="lede">Pick a side for its record, its head-to-head ledger, and the players who did the work.</p>
      <div class="filters"><label>Side <input type="text" id="tm-q" placeholder="India"></label>
      <button class="btn primary" id="tm-go">Open</button></div>`;
    bindFieldAutocomplete("tm-q", "teams");
    const go = () => {
      const v = $("tm-q").dataset.resolved || $("tm-q").value.trim();
      if (v) location.hash = `#/team?name=${encodeURIComponent(v)}`;
    };
    $("tm-go").addEventListener("click", go);
    return;
  }
  setDocTitle(side);
  const comp = hashParam("comp") || "";
  const gender = hashParam("gender") || "";
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const qs = new URLSearchParams({ name: side });
  if (comp) qs.set("comp", comp);
  if (gender) qs.set("gender", gender);
  const d = await fetch(`/api/team?${qs}`).then((r) => r.json()).catch(() => ({ ok: false }));
  if (!d.ok) {
    main.innerHTML = `<div class="empty"><p>${esc(d.error || "Side not found.")}</p></div>`;
    return;
  }
  main.innerHTML = `
    <div class="page-head">
      <h1 class="page-title">${esc(d.team)}</h1>
      ${shareButton("tm-share")}
    </div>
    <p class="meta-line">${d.matches.toLocaleString()} matches · ${esc(d.range || "")} · <a href="#/wowy?team=${encodeURIComponent(d.team)}">WOWY for this side</a></p>
    <div class="stats-toolbar">
      <div class="filters">
        <label>Competition
          <select id="tm-comp">${COMP_CHOICES.map(([k, l]) => `<option value="${k}" ${comp === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        </label>
        <label>Gender
          <select id="tm-g">
            <option value="" ${gender === "" ? "selected" : ""}>Both</option>
            <option value="male" ${gender === "male" ? "selected" : ""}>Men</option>
            <option value="female" ${gender === "female" ? "selected" : ""}>Women</option>
          </select>
        </label>
      </div>
    </div>
    ${statCards([
      { kicker: "Record", value: `${d.wins}–${d.losses}`, note: d.undecided ? `${d.undecided} drawn or no result` : "" },
      { kicker: "Win rate", value: d.win_pct == null ? "–" : `${d.win_pct}%`, note: "of decided matches" },
      { kicker: "Matches", value: d.matches.toLocaleString() },
      { kicker: "Span", value: esc(d.range || "–") },
    ])}
    <h2 class="section">By competition</h2>
    ${table(
      [
        { key: "comp", label: "Competition", align: "left" },
        { key: "matches", label: "P", align: "right", numeric: true },
        { key: "wins", label: "W", align: "right", numeric: true },
        { key: "losses", label: "L", align: "right", numeric: true },
        { key: "win_pct", label: "Win %", align: "right", numeric: true, digits: 1 },
      ],
      d.by_comp || [],
    )}
    <h2 class="section">Head to head</h2>
    <p class="caption">Every side they have met in this filter. Win % counts decided matches only.</p>
    ${table(
      [
        { key: "opposition", label: "Opponent", align: "left", link: "team" },
        { key: "matches", label: "P", align: "right", numeric: true },
        { key: "wins", label: "W", align: "right", numeric: true },
        { key: "losses", label: "L", align: "right", numeric: true },
        { key: "undecided", label: "D / NR", align: "right", numeric: true },
        { key: "win_pct", label: "Win %", align: "right", numeric: true, digits: 1 },
        { key: "last_met", label: "Last met", align: "left" },
      ],
      d.h2h || [],
      { sortKey: "matches", sortDir: "desc", searchable: true, searchLabel: "Filter opponents" },
    )}
    <h2 class="section">Most runs for ${esc(d.team)}</h2>
    ${table(
      [
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "inns", label: "Inns", align: "right", numeric: true },
        { key: "runs", label: "Runs", align: "right", numeric: true },
        { key: "hs", label: "HS", align: "right", numeric: true },
        { key: "avg", label: "Avg", align: "right", numeric: true, digits: 1 },
        { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 },
        { key: "hundreds", label: "100s", align: "right", numeric: true },
      ],
      d.top_bat || [],
      { faces: true, sortKey: "runs", sortDir: "desc" },
    )}
    <h2 class="section">Most wickets for ${esc(d.team)}</h2>
    ${table(
      [
        { key: "player", label: "Player", align: "left", link: "player" },
        { key: "inns", label: "Inns", align: "right", numeric: true },
        { key: "wickets", label: "W", align: "right", numeric: true },
        { key: "best", label: "Best", align: "right", numeric: true },
        { key: "avg", label: "Avg", align: "right", numeric: true, digits: 1 },
        { key: "econ", label: "Econ", align: "right", numeric: true, digits: 2 },
      ],
      d.top_bowl || [],
      { faces: true, sortKey: "wickets", sortDir: "desc" },
    )}
    <h2 class="section">Latest matches</h2>
    ${table(
      [
        { key: "start_date", label: "Date", align: "left", link: "match" },
        { key: "opposition", label: "Opponent", align: "left" },
        { key: "comp", label: "Comp", align: "left", badge: true },
        { key: "outcome", label: "Result", align: "left", status: true, link: false },
        { key: "result", label: "Margin", align: "left" },
        { key: "venue", label: "Ground", align: "left", link: "venue" },
      ],
      d.recent || [],
      { resultBorders: false },
    )}`;
  bindTable("");
  warmPortraits(main);
  bindShare("tm-share");
  const reload = () => {
    const qsx = new URLSearchParams({ name: d.team });
    if ($("tm-comp").value) qsx.set("comp", $("tm-comp").value);
    if ($("tm-g").value) qsx.set("gender", $("tm-g").value);
    location.hash = `#/team?${qsx}`;
  };
  $("tm-comp")?.addEventListener("change", reload);
  $("tm-g")?.addEventListener("change", reload);
}

const RANK_METRICS = [
  ["runs", "Most runs"],
  ["wickets", "Most wickets"],
  ["avg", "Best batting average"],
  ["sr", "Best strike rate"],
  ["tsr", "Best scoring vs situation"],
  ["econ", "Best economy"],
  ["te", "Best bowling vs situation"],
  ["hundreds", "Most hundreds"],
  ["war", "Most WAR"],
  ["raa_bat", "Most batting RAA"],
  ["raa_bowl", "Most bowling RAA"],
];

async function showRankings() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Rankings");
  const state = {
    metric: hashParam("metric") || "runs",
    comp: hashParam("comp") || "t20i",
    gender: hashParam("gender") || "male",
    min: Number(hashParam("min") || 20),
  };
  const paint = async () => {
    const qs = new URLSearchParams({
      metric: state.metric, gender: state.gender, min_inns: String(state.min),
    });
    if (state.comp) qs.set("comp", state.comp);
    history.replaceState(null, "", `#/rankings?${qs}`);
    main.innerHTML = `
      <h1 class="page-title">Rankings</h1>
      <p class="lede">One leaderboard at a time. Pick the metric, the competition, and the qualifying floor.</p>
      ${leaderboardNav("rankings")}
      <div id="rk-body"><div class="skel"></div><div class="skel"></div></div>`;
    const d = await fetch(`/api/rankings?${qs}`).then((r) => r.json()).catch(() => ({ rows: [] }));
    const rows = (d.rows || []).map((r, i) => ({ ...r, rank: i + 1, player: r.player || r.display_name }));
    const extra = {
      runs: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "avg", label: "Avg", align: "right", numeric: true, digits: 1 }, { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 }],
      hundreds: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "runs", label: "Runs", align: "right", numeric: true }],
      avg: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "runs", label: "Runs", align: "right", numeric: true }],
      sr: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "runs", label: "Runs", align: "right", numeric: true }],
      tsr: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "sr", label: "SR", align: "right", numeric: true, digits: 1 }],
      wickets: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "econ", label: "Econ", align: "right", numeric: true, digits: 2 }],
      econ: [{ key: "wickets", label: "W", align: "right", numeric: true }],
      te: [{ key: "wickets", label: "W", align: "right", numeric: true }, { key: "econ", label: "Econ", align: "right", numeric: true, digits: 2 }],
      war: [{ key: "matches", label: "M", align: "right", numeric: true }],
      raa_bat: [{ key: "inns", label: "Inns", align: "right", numeric: true }, { key: "tsr", label: "TSR", align: "right", numeric: true, digits: 2 }],
      raa_bowl: [{ key: "wickets", label: "W", align: "right", numeric: true }, { key: "te", label: "TE", align: "right", numeric: true, digits: 2 }],
    }[state.metric] || [];
    const metricCol = {
      key: state.metric,
      label: (RANK_METRICS.find(([k]) => k === state.metric) || ["", state.metric])[1].replace(/^(Most|Best) /, ""),
      align: "right",
      numeric: true,
      digits: ["avg", "sr"].includes(state.metric) ? 1 : ["econ", "tsr", "te", "war", "raa_bat", "raa_bowl"].includes(state.metric) ? 2 : 0,
    };
    $("rk-body").innerHTML = `
      <div class="record-tabs" role="group" aria-label="Metric">
        ${RANK_METRICS.map(([k, l]) => `<button type="button" class="chip ${k === state.metric ? "on" : ""}" data-metric="${k}">${l}</button>`).join("")}
      </div>
      <div class="stats-toolbar">
        <div class="filters">
          <label>Competition
            <select id="rk-comp">${COMP_CHOICES.slice(0, 8).map(([k, l]) => `<option value="${k}" ${state.comp === k ? "selected" : ""}>${l || "All"}</option>`).join("")}</select>
          </label>
          <label>Gender
            <select id="rk-g">
              <option value="male" ${state.gender === "male" ? "selected" : ""}>Men</option>
              <option value="female" ${state.gender === "female" ? "selected" : ""}>Women</option>
            </select>
          </label>
          <label>Min innings <input type="number" id="rk-min" min="1" max="500" value="${state.min}"></label>
        </div>
        <div class="view-options">${shareButton("rk-share")}</div>
      </div>
      <p class="scope">${esc(d.scope || "")}</p>
      ${table(
        [
          { key: "rank", label: "#", align: "right", numeric: true, sortable: false },
          { key: "player", label: "Player", align: "left", link: "player" },
          metricCol,
          ...extra,
        ],
        rows,
        { faces: true, heat: state.metric, searchable: true, searchLabel: "Find a player" },
      )}`;
    bindTable("");
    warmPortraits(main);
    bindShare("rk-share");
    $("rk-body").querySelectorAll("[data-metric]").forEach((b) => b.addEventListener("click", () => {
      state.metric = b.dataset.metric;
      paint();
    }));
    $("rk-comp")?.addEventListener("change", (e) => { state.comp = e.target.value; paint(); });
    $("rk-g")?.addEventListener("change", (e) => { state.gender = e.target.value; paint(); });
    $("rk-min")?.addEventListener("change", (e) => { state.min = Number(e.target.value) || 1; paint(); });
  };
  await paint();
}

const STANDINGS_COMPS = [["ipl", "IPL"], ["wpl", "WPL"], ["bbl", "BBL"], ["wbbl", "WBBL"], ["t20i", "T20 World Cup"]];

async function showStandings() {
  setHero(false);
  setDocTitle("Standings");
  const state = {
    comp: hashParam("comp") || "ipl",
    season: hashParam("season") || "",
    gender: hashParam("gender") || (hashParam("comp") === "t20i" ? "male" : ""),
  };
  const paint = async () => {
    const qs = new URLSearchParams({ comp: state.comp });
    if (state.season) qs.set("season", state.season);
    if (state.gender) qs.set("gender", state.gender);
    main.innerHTML = `
      <h1 class="page-title">Standings</h1>
      <p class="lede">Points tables and the knockouts that followed, season by season.</p>
      <div id="sd-body"><div class="skel"></div><div class="skel"></div></div>`;
    const d = await fetch(`/api/standings?${qs}`).then((r) => r.json()).catch(() => ({ rows: [] }));
    if (!state.season && d.season) state.season = d.season;
    history.replaceState(null, "", `#/standings?comp=${state.comp}&season=${encodeURIComponent(state.season || "")}`);
    const cols = [
      { key: "position", label: "#", align: "right", numeric: true },
      { key: "team", label: "Team", align: "left", link: "team" },
      { key: "played", label: "P", align: "right", numeric: true },
      { key: "won", label: "W", align: "right", numeric: true },
      { key: "lost", label: "L", align: "right", numeric: true },
      { key: "no_result", label: "NR", align: "right", numeric: true },
      { key: "points", label: "Pts", align: "right", numeric: true },
      { key: "nrr", label: "NRR", align: "right", numeric: true, digits: 3 },
    ].filter((c) => (d.rows || []).some((r) => r[c.key] != null) || c.key === "position");
    $("sd-body").innerHTML = `
      <div class="stats-toolbar">
        <div class="filters">
          <label>Competition
            <select id="sd-comp">${STANDINGS_COMPS.map(([k, l]) => `<option value="${k}" ${state.comp === k ? "selected" : ""}>${l}</option>`).join("")}</select>
          </label>
          <label>Season
            <select id="sd-season">${(d.seasons || []).map((s) => `<option ${s === state.season ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
          </label>
        </div>
        <div class="view-options">${shareButton("sd-share")}</div>
      </div>
      ${(d.rows || []).length ? `<h2 class="section">Points table</h2>${table(cols, d.rows)}` : `<p class="caption">No points table stored for this season.</p>`}
      ${(d.playoffs || []).length ? playoffBlock(d.playoffs) : ""}`;
    bindTable("");
    bindShare("sd-share");
    $("sd-comp")?.addEventListener("change", (e) => { state.comp = e.target.value; state.season = ""; paint(); });
    $("sd-season")?.addEventListener("change", (e) => { state.season = e.target.value; paint(); });
  };
  await paint();
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
  const a = $("c-a")?.dataset.resolved || $("c-a")?.value.trim() || hashParam("a");
  const b = $("c-b")?.dataset.resolved || $("c-b")?.value.trim() || hashParam("b");
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
        { n: st.dismissals, k: "Dismissals" },
      ]
    : [
        { n: st.runs, k: "Runs" },
        { n: st.balls, k: "Balls" },
        { n: st.sr ?? "–", k: "Strike rate" },
        { n: st.dismissals, k: "Dismissals" },
      ];
  const footBits = tests
    ? [avg === "–" ? "Not dismissed" : null, st.sr != null ? `${st.sr} SR` : null, st.econ != null ? `${st.econ} econ` : null]
    : [avg !== "–" ? `${avg} per dismissal` : "Not dismissed", st.econ != null ? `${st.econ} econ` : null];
  return `
    <article class="matchup">
      <header class="matchup-head">
        <div>
          <div class="matchup-role">Batting</div>
          <h2 class="matchup-name">${portrait(batter.slug, batter.display_name, "sm")}<a href="#/player/${esc(batter.slug)}">${esc(batter.display_name)}</a></h2>
        </div>
        <div class="matchup-vs" aria-hidden="true">vs</div>
        <div class="matchup-head-right">
          <div class="matchup-role">Bowling</div>
          <h2 class="matchup-name">${portrait(bowler.slug, bowler.display_name, "sm")}<a href="#/player/${esc(bowler.slug)}">${esc(bowler.display_name)}</a></h2>
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
  const bothAdj = pa.xi?.pitch?.ok_adj && pb.xi?.pitch?.ok_adj;
  const fig = (v, d) => (v == null ? "–" : signed(v, d));
  const card = (person) => {
    const xi = person.xi;
    if (!xi?.ok) {
      return `<div class="duel-card">
        <h2>${portrait(person.slug, person.display_name, "sm")}<a href="#/player/${esc(person.slug)}">${esc(person.display_name)}</a></h2>
        <p class="caption">No teammate split in this format.</p>
      </div>`;
    }
    const bat = xi.bat || {}, bowl = xi.bowl || {};
    const pitch = xi.pitch || {};
    const bowlFirst = xi.primary_role === "bowl";
    const residOnly = Boolean(pitch.ok_with) && (xi.matches_wo || 0) < 8;
    const useAdj = Boolean(pitch.ok_adj) && (xi.matches_with || 0) >= 8 && (xi.matches_wo || 0) >= 8;
    let hero;
    let heroLabel;
    let digits = bowlFirst ? 2 : 1;
    if (residOnly) {
      hero = bowlFirst ? bowl.econ_resid_with : bat.sr_resid_with;
      heroLabel = bowlFirst ? "econ vs pitch par" : "SR vs pitch par";
    } else if (useAdj) {
      hero = bowlFirst ? bowl.econ_delta_adj : bat.sr_delta_adj;
      heroLabel = bowlFirst ? "econ Δ adj" : "SR Δ adj";
    } else if (xi.schedule_mix) {
      hero = null;
      heroLabel = "schedule mix — not a teammate effect";
    } else {
      hero = bowlFirst ? bowl.econ_delta : bat.avg_delta;
      heroLabel = bowlFirst ? "econ Δ with them in" : "avg Δ with them in";
    }
    const better = hero == null ? null : (bowlFirst ? hero < 0 : hero > 0);
    const dead = bowlFirst ? 0.08 : 1.5;
    const hcls = hero == null || Math.abs(hero) < dead ? "" : better ? "pos" : "neg";
    const ahead = bothAdj && xi.lift > 0;
    const mixWarn = xi.schedule_mix && !useAdj && !residOnly;
    const n1 = (v) => (v == null || v === "" ? "–" : Number(v).toFixed(1));
    const n2 = (v) => (v == null || v === "" ? "–" : Number(v).toFixed(2));
    const wo = (xi.matches_wo || 0) > 0;
    const batRaw = wo
      ? `Batters ${n1(bat.avg_with)} avg · ${n1(bat.sr_with)} SR → ${n1(bat.avg_wo)} · ${n1(bat.sr_wo)} raw`
      : `Batters ${n1(bat.avg_with)} avg · ${n1(bat.sr_with)} SR`;
    const bowlRaw = wo
      ? `Bowlers ${n2(bowl.econ_with)} econ · ${n1(bowl.avg_with)} avg → ${n2(bowl.econ_wo)} · ${n1(bowl.avg_wo)} raw`
      : `Bowlers ${n2(bowl.econ_with)} econ · ${n1(bowl.avg_with)} avg`;
    const batExp = bat.sr_exp_with != null
      ? `<p class="xi-line exp">exp ${n1(bat.avg_exp_with)} · ${n1(bat.sr_exp_with)}<span class="xi-pipe">|</span>Δ ${fig(bat.avg_resid_with, 1)} avg · ${fig(bat.sr_resid_with, 1)} SR</p>`
      : "";
    const bowlExp = bowl.econ_exp_with != null
      ? `<p class="xi-line exp">exp ${n2(bowl.econ_exp_with)} · ${n1(bowl.avg_exp_with)}<span class="xi-pipe">|</span>Δ ${fig(bowl.econ_resid_with, 2)} econ</p>`
      : (pitch.reason ? `<p class="xi-line exp">${esc(pitch.reason)}</p>` : "");
    const batSupport = bat.balls_with
      ? `<p class="xi-support">${Number(bat.balls_with).toLocaleString("en-US")} balls · ${Number(bat.outs_with || 0).toLocaleString("en-US")} dismissals with them</p>`
      : "";
    return `
      <div class="duel-card${ahead ? " ahead" : ""}">
        <h2>${portrait(person.slug, person.display_name, "sm")}<a href="#/player/${esc(person.slug)}">${esc(person.display_name)}</a></h2>
        <p class="caption">${esc(xi.team || "")} · ${xi.matches_with || 0} XI · ${xi.matches_wo || 0} without</p>
        <p class="team-avg-line"><span class="fig ${hcls}${mixWarn ? " mix-warning" : ""}">${hero == null ? (mixWarn ? "schedule mix" : "–") : signed(hero, digits)}</span> <span class="caption">${heroLabel}</span></p>
        <p class="xi-line">${batRaw}</p>
        ${batExp}
        <p class="xi-line">${bowlRaw}</p>
        ${bowlExp}
        ${batSupport}
        <p class="xi-verdict">${esc(xi.verdict || "")}</p>
        <p class="caption"><a href="#/shift?player=${encodeURIComponent(person.slug)}&amp;team=${encodeURIComponent(xi.team || "")}&amp;comp=${encodeURIComponent(pool)}">Full teammate lines</a></p>
      </div>`;
  };
  return `
    <h2 class="section">Teammates in the XI</h2>
    <p class="caption">Green/red is residual vs pitch par, not raw with minus without. Each card is judged on its own schedule first; a head-to-head only when both have a without-sample. Home and away are still split by ground.</p>
    <div class="duel">
      ${card(pa)}
      <div class="duel-mid caption">vs<br>pitch par</div>
      ${card(pb)}
    </div>`;
}

function sharedVsTable(rows, aName, bName, kind) {
  const noun = kind === "bowl" ? "batters" : "bowlers";
  if (!rows?.length) {
    return `<p class="caption">No ${noun} both faced in this format (12-ball floor).</p>`;
  }
  const deltaH = rows[0]?.delta_label || "";
  return table(
    [
      { key: "player", label: kind === "bowl" ? "Batter" : "Bowler", align: "left", link: "player" },
      { key: "a_line", label: aName, align: "left" },
      { key: "b_line", label: bName, align: "left" },
      {
        key: "delta",
        label: `Δ ${deltaH}`,
        align: "right",
        numeric: true,
        digits: deltaH === "econ" ? 2 : 1,
        delta: kind === "bowl" ? "lower" : "higher",
        info: `Player A minus Player B. Green means the result favors ${aName}.`,
      },
      { key: "competition", label: "Comp", align: "left", badge: true },
    ],
    rows.map((row) => ({
      ...row,
      player: row.opponent || row.player,
      slug: row.opp_slug || row.slug,
    })),
    { sortKey: "delta", sortDir: "desc", sortAbs: true },
  );
}

const CLASSIC_DUELS = [
  { a: "v-kohli", b: "je-root", comp: "test", label: "Kohli v Root", note: "The Fab Four question, in whites" },
  { a: "v-kohli", b: "spd-smith", comp: "test", label: "Kohli v Smith", note: "Two ways to bat for a decade" },
  { a: "jc-buttler", b: "ms-dhoni", comp: "t20i_ipl", label: "Buttler v Dhoni", note: "Keeper-batters who finished" },
  { a: "jj-bumrah", b: "rashid-khan", comp: "t20i_ipl", label: "Bumrah v Rashid Khan", note: "Best T20 bowler alive" },
  { a: "ra-jadeja", b: "r-ashwin", comp: "test", label: "Jadeja v Ashwin", note: "The spin twins, split apart" },
  { a: "ch-gayle", b: "ab-de-villiers", comp: "ipl", label: "Gayle v de Villiers", note: "Chinnaswamy, two ways" },
];

const COMPARE_METRIC_HELP = {
  war: "Wins above a replacement player. Career total — more games count for more.",
  war_per_game: "Career WAR divided by matches in this pool (20-game floor).",
  raa_bat: "Runs above average with the bat, judged ball by ball against the same balls remaining, wickets in hand and target pressure.",
  raa_bowl: "Runs above average with the ball, counting runs conceded and wickets taken against the same situation.",
  tsr: "True strike-rate residual: runs per 100 balls above what the same situation usually yields. Scoring only — dismissals sit in TWR.",
  te: "True economy residual: runs per over conceded above expectation. Negative is good.",
  war_bat: "Batting wins above replacement from the resource model.",
  war_bowl: "Bowling wins above replacement, on the same run scale as batting.",
  twr_bat: "True wicket-rate residual: dismissals per 100 balls above expectation. Negative means harder to get out than the situation implies.",
  twr_bowl: "True wicket-rate residual: wickets per 100 balls above expectation. Positive is good.",
  matches: "Matches played in this format in this warehouse.",
  inns: "Innings batted.",
  runs: "Career runs.",
  hs: "Highest score.",
  avg: "Batting average: runs per dismissal.",
  sr: "Strike rate: runs per 100 balls faced.",
  hundreds: "Innings of 100 or more.",
  fifties: "Innings of 50 or more that were not hundreds.",
  wickets: "Career wickets.",
  bowl_avg: "Bowling average: runs conceded per wicket. Lower is better.",
  econ: "Economy: runs conceded per six legal balls. Lower is better.",
  bowl_sr: "Bowling strike rate: balls per wicket. Lower is better.",
};

async function showCompare() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Compare");
  const a = hashParam("a");
  const b = hashParam("b");
  const comp = hashParam("comp") || "t20i_ipl";
  if (!a || !b) {
    const pinned = [...favList(), ...recentList()]
      .filter((v, i, arr) => arr.findIndex((x) => x.slug === v.slug) === i)
      .slice(0, 8);
    const yours = pinned.length >= 2
      ? `<h2 class="section">From your list</h2>
         <p class="caption">Two clicks: pick the left name, then the right.</p>
         <div class="chips" id="c-mine">${pinned.map((f) =>
            `<button type="button" class="chip" data-mine="${esc(f.slug)}" data-name="${esc(f.name)}">${portrait(f.slug, f.name, "xs")}${esc(f.name)}</button>`
          ).join("")}</div>`
      : "";
    main.innerHTML = `
      <h1 class="page-title">Compare</h1>
      <p class="lede">Same format, same opponents. Pick two names, or jump to teams, a profile twin, or a stat-line shift.</p>
      <nav class="browse">
        <a href="#/compare">Players</a>
        <a href="#/teams">Teams</a>
        <a href="#/twin">Profile twin</a>
        <a href="#/shift">Stat line shift</a>
      </nav>
      <div class="filters">
        <label>Player A <input type="text" id="c-a" placeholder="Kohli" value="${esc(a)}"></label>
        <label>Player B <input type="text" id="c-b" placeholder="Root" value="${esc(b)}"></label>
        ${formatSelect("c-comp", comp, false)}
        <button class="btn primary" id="c-go">Compare</button>
      </div>
      ${yours}
      <h2 class="section">Arguments worth having</h2>
      <p class="caption">Ready-made pairs. Each opens in the format where they overlap most.</p>
      <div class="suggest-grid">${CLASSIC_DUELS.map((duel) => `
        <a class="suggest-card" href="#/compare?a=${encodeURIComponent(duel.a)}&b=${encodeURIComponent(duel.b)}&comp=${encodeURIComponent(duel.comp)}">
          <span class="suggest-names">${esc(duel.label)}</span>
          <span class="caption">${esc(duel.note)}</span>
        </a>`).join("")}</div>`;
    $("c-go").addEventListener("click", goCompare);
    bindFieldAutocomplete("c-a", "people");
    bindFieldAutocomplete("c-b", "people");
    $("c-mine")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-mine]");
      if (!btn) return;
      const fieldA = $("c-a");
      const fieldB = $("c-b");
      const target = fieldA.value.trim() && !fieldB.value.trim() ? fieldB : (fieldA.value.trim() ? fieldB : fieldA);
      target.value = btn.dataset.name;
      target.dataset.resolved = btn.dataset.mine;
      if (fieldA.dataset.resolved && fieldB.dataset.resolved) goCompare();
    });
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
  const showMinor = hashParam("minor") === "1";
  const disciplineFor = (key) => {
    if (["wickets", "bowl_avg", "econ", "bowl_sr", "rae_bowl", "raa_bowl", "te", "war_bowl", "twr_bowl"].includes(key)) return "bowl";
    if (["inns", "runs", "hs", "avg", "sr", "hundreds", "fifties", "rae_bat", "raa_bat", "tsr", "war_bat", "twr_bat"].includes(key)) return "bat";
    return null;
  };
  const valRow = (r, kind) => {
    const dec = r.digits != null
      ? r.digits
      : ({
        war: 2, war_per_game: 3, war_bat: 2, war_bowl: 2,
        raa_bat: 1, raa_bowl: 1, tsr: 2, te: 2, twr_bat: 2, twr_bowl: 2,
        rae_bat: 2, rae_bowl: 2, wpa: 3, pressure: 1,
      }[r.key] ?? 1);
    const fmt = (v) => (v == null ? "–" : Number(v).toFixed(dec));
    const lower = !!r.lower;
    const discipline = disciplineFor(r.key);
    const bothRelevant = !discipline || (pa.primary_role === discipline && pb.primary_role === discipline);
    const classicRate = ["avg", "bowl_avg", "econ", "bowl_sr"].includes(r.key) || (r.key === "sr" && pool !== "test");
    const valueRate = ["war", "war_per_game", "raa_bat", "raa_bowl", "tsr", "te", "war_bat", "war_bowl", "twr_bat", "twr_bowl"].includes(r.key) || (discipline && bothRelevant);
    const colorable = kind === "value" ? valueRate : classicRate && bothRelevant;
    const aWin = colorable && r.a != null && r.b != null && (lower ? r.a < r.b : r.a > r.b);
    const bWin = colorable && r.a != null && r.b != null && (lower ? r.b < r.a : r.b > r.a);
    const cell = (v, other, rank, win, minor) => {
      const margin = win ? ` <span class="margin">(${signed(Number(v) - Number(other), dec)})</span>` : "";
      return `<td class="num${win ? " win" : ""}${minor ? " minor" : ""}">${fmt(v)}${margin}${rank ? `<div class="sc">#${rank}</div>` : ""}</td>`;
    };
    const rowClass = pool === "test" && r.key === "avg" ? "key-row" : pool === "test" && r.key === "sr" ? "quiet-row" : "";
    let help = r.copy || COMPARE_METRIC_HELP[r.key] || "";
    if (pool === "test" && r.key === "avg") {
      help = (help ? `${help} ` : "") + "Emphasized here because batting average is the primary Test batting rate.";
    } else if (pool === "test" && r.key === "sr") {
      help = (help ? `${help} ` : "") + "Shown for context and not scored as an advantage.";
    }
    const hint = help
      ? `<span class="hint" tabindex="0" aria-label="About ${esc(r.label)}">${esc(r.label)}<span class="pop">${esc(help)}</span></span>`
      : esc(r.label);
    return `<tr class="${rowClass}">
      <td class="stat">${hint}</td>
      ${cell(r.a, r.b, r.a_rank, aWin, !showMinor && discipline && pa.primary_role !== discipline)}
      ${cell(r.b, r.a, r.b_rank, bWin, !showMinor && discipline && pb.primary_role !== discipline)}
    </tr>`;
  };
  const grid = (rows, kind, extra = "") => !rows?.length ? "" : `<table class="compare-grid">
        <thead><tr><th>Metric</th><th>${esc(pa.display_name)}</th><th>${esc(pb.display_name)}</th></tr></thead>
        <tbody>${rows.map((row) => valRow(row, kind)).join("")}</tbody>
      </table>${extra}`;
  const classicRows = [...(d.classic || [])];
  if (pool === "test") {
    const order = ["matches", "inns", "runs", "avg", "hs", "hundreds", "fifties", "sr", "wickets", "bowl_avg", "econ", "bowl_sr"];
    classicRows.sort((a, b) => (order.indexOf(a.key) + 99) - (order.indexOf(b.key) + 99));
  }
  const focusedClassicRows = showMinor
    ? classicRows
    : classicRows.filter((row) => {
        if (d.pairing === "bat_bat") return disciplineFor(row.key) !== "bowl";
        if (d.pairing === "bowl_bowl") return row.key === "matches" || disciplineFor(row.key) !== "bat";
        return true;
      });
  const classicBlock = focusedClassicRows.length
    ? `<h2 class="section">${esc(d.pool_label || "Career")} <span class="section-qualifier">(career)</span></h2>${grid(focusedClassicRows, "classic")}`
    : "";
  const focusedValueRows = showMinor
    ? (d.rows || [])
    : (d.rows || []).filter((row) => {
        if (d.pairing === "bat_bat") return disciplineFor(row.key) !== "bowl";
        if (d.pairing === "bowl_bowl") return disciplineFor(row.key) !== "bat";
        return true;
      });
  const valueBlock = d.has_t20_value
    ? `<h2 class="section">T20 value</h2>${grid(focusedValueRows, "value")}`
    : "";
  const hasH2h = Boolean(h.a_faced_b || h.b_faced_a);
  const h2hBlock = hasH2h ? matchupStage(pa, pb, h, d.pool_label, pool) : "";
  const hasSharedBowlers = Boolean(d.shared_bowlers?.length);
  const hasSharedBatters = Boolean(d.shared_batters?.length);
  const sharedBlock = !hasSharedBowlers && !hasSharedBatters
    ? `<h2 class="section">Shared opponents</h2><p class="caption">No shared opponents in this format (12-ball floor).</p>`
    : `
      <p class="comparison-legend"><span class="pos">Green</span> = advantage ${esc(pa.display_name)}. <span class="neg">Red</span> = advantage ${esc(pb.display_name)}. Δ is ${esc(pa.display_name)} minus ${esc(pb.display_name)}.</p>
      ${hasSharedBowlers ? `<h2 class="section">Vs the same bowlers</h2><p class="caption">Test average deltas require at least three dismissals for each player; limited-overs comparisons use strike rate.</p>${sharedVsTable(d.shared_bowlers, pa.display_name, pb.display_name, "bat")}` : ""}
      ${hasSharedBatters ? `<h2 class="section">Vs the same batters</h2><p class="caption">Test bowling-average deltas require at least three dismissals for each player; limited-overs comparisons use economy.</p>${sharedVsTable(d.shared_batters, pa.display_name, pb.display_name, "bowl")}` : ""}`;
  const lede = hasH2h
    ? `${esc(d.pool_label || "")} — direct head-to-head, then value and career lines.`
    : `${esc(d.pool_label || "")} — value and career lines, then shared opponents.`;
  main.innerHTML = `
    <h1 class="page-title">Player comparison</h1>
    <p class="lede">${lede}</p>
    <div class="filters">
      <label>Player A <input type="text" id="c-a" value="${esc(pa.display_name)}"></label>
      <label>Player B <input type="text" id="c-b" value="${esc(pb.display_name)}"></label>
      ${formatSelect("c-comp", pool, female)}
      <button type="button" class="view-toggle" id="c-minor" aria-pressed="${showMinor}">Show minor discipline</button>
      <button class="btn primary" id="c-go">Compare</button>
    </div>
    ${h2hBlock}
    ${valueBlock}
    ${classicBlock}
    ${xiImpactCards(pa, pb, pool)}
    ${sharedBlock}`;
  $("c-go").addEventListener("click", goCompare);
  $("c-comp")?.addEventListener("change", goCompare);
  $("c-minor")?.addEventListener("click", () => {
    const qs = new URLSearchParams({ a: pa.slug, b: pb.slug, comp: pool });
    if (!showMinor) qs.set("minor", "1");
    location.hash = `#/compare?${qs}`;
  });
  bindFieldAutocomplete("c-a", "people");
  bindFieldAutocomplete("c-b", "people");
  bindTable("");
  warmPortraits(main);
}

async function showTeamCompare() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Team compare");
  const state = {
    a: hashParam("a") || "India",
    b: hashParam("b") || "Australia",
    comp: hashParam("comp") || "t20i",
    season_a: hashParam("season_a") || hashParam("season") || "",
    season_b: hashParam("season_b") || hashParam("season") || "",
    gender: hashParam("gender") || "male",
  };
  const qs = new URLSearchParams({ a: state.a, b: state.b, comp: state.comp, gender: state.gender });
  if (state.season_a) qs.set("season_a", state.season_a);
  if (state.season_b) qs.set("season_b", state.season_b);
  const d = await (await fetch(`/api/team-compare?${qs}`)).json();
  const seasonOptions = (items, selected) =>
    (items || []).map((s) => `<option value="${esc(s)}" ${s === selected ? "selected" : ""}>${esc(s)}</option>`).join("");
  const seasonsA = seasonOptions(d.seasons_a, d.season_a || state.season_a);
  const seasonsB = seasonOptions(d.seasons_b, d.season_b || state.season_b);
  const dash = (v) => (v == null || v === "") ? "–" : v;
  const isTest = d.comp === "test";
  const isT20 = !!d.t20;
  const fmtW = (v) => (v == null || v === "") ? "–" : Number(v).toFixed(3);
  const t20Lane = (side) => `
    <div class="team-row lane-head">
      <span>Rank</span><span>Player</span><span>Role · XIs</span><span>WAR/G</span>
    </div>
    ${(side.players || []).map((p) => `
    <div class="team-row">
      <span class="rk" title="Ranked by WAR per game">${p.rank}</span>
      <a href="#/player/${esc(p.slug)}">${esc(p.display_name)}</a>
      <span class="caption">${esc(p.line || "")}</span>
      <span class="fig ${Number(p.war_per_game) < 0 ? "neg" : ""}">${fmtW(p.war_per_game)}</span>
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
    return `${n} GP · ${w}–${Math.max(n - w, 0)} · ${side.win_pct ?? "–"}% · ${esc(side.season || "")}`;
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
  const edgeTeam = aAhead ? d.a?.team : bAhead ? d.b?.team : null;
  const mid = isTest
    ? `<div class="duel-mid">
        <p class="team-avg-line"><span class="fig">${dash(d.a?.team_avg)}</span></p>
        <p class="caption">team avg</p>
        <p class="caption" style="margin:10px 0 4px">vs</p>
        <p class="team-avg-line"><span class="fig">${dash(d.b?.team_avg)}</span></p>
      </div>`
    : isT20
      ? `<div class="duel-mid">
          <p class="team-edge">${edgeTeam ? `${esc(edgeTeam)} <span class="fig pos">+${Math.abs(d.edge).toFixed(3)}</span>` : "Even"}</p>
          <p class="caption">WAR / game edge</p>
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
      <label>Side A season
        <select id="tc-sa"><option value="">Latest</option>${seasonsA}</select>
      </label>
      <label>Side B season
        <select id="tc-sb"><option value="">Latest</option>${seasonsB}</select>
      </label>
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
    const a = $("tc-a").dataset.resolved || $("tc-a").value;
    const b = $("tc-b").dataset.resolved || $("tc-b").value;
    location.hash = `#/teams?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&comp=${$("tc-c").value}&gender=${$("tc-g").value}&season_a=${encodeURIComponent($("tc-sa").value)}&season_b=${encodeURIComponent($("tc-sb").value)}`;
  };
  $("tc-go").addEventListener("click", go);
  bindFieldAutocomplete("tc-a", "teams");
  bindFieldAutocomplete("tc-b", "teams");
}

async function showTwin() {
  setHero(false);
  setDocTitle("Profile twin");
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
    const q = $("tw-p").dataset.resolved || $("tw-p").value.trim();
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
    $("tw-p").value = d.person?.display_name || q;
    const twin = (d.twins || [])[0];
    const profileBar = (value, max, who) => {
      if (value == null) return `<div class="twin-track twin-axis"></div>`;
      const magnitude = max ? Math.abs(Number(value)) / max * 50 : 0;
      return `<div class="twin-track twin-axis">
        <span class="twin-zero"></span>
        <span class="twin-fill ${who} ${Number(value) < 0 ? "neg" : "pos"}" style="--mag:${magnitude}%"></span>
      </div>`;
    };
    const bars = (d.bars || []).map((bar) => {
      const max = Math.max(Math.abs(Number(bar.a) || 0), Math.abs(Number(bar.b) || 0));
      return `<div class="twin-row">
        <span>${esc(bar.label)}</span>
        <div class="twin-bars">
          ${profileBar(bar.a, max, "a")}
          ${profileBar(bar.b, max, "b")}
        </div>
        <span class="fig">${bar.a}</span>
        <span class="fig">${bar.b ?? "–"}</span>
      </div>`;
    }).join("");
    $("tw-out").innerHTML = `
      <div class="duel">
        <div class="duel-card twin-card">
          <h2>${portrait(d.person.slug, d.person.display_name, "sm")}<a href="#/player/${esc(d.person.slug)}">${esc(d.person.display_name)}</a></h2>
          <p class="caption"><span class="series-swatch a"></span>${esc(d.pool_label || "")} · ${d.anchor?.primary_role === "bowl" ? "Bowler" : "Batter"} · WAR ${d.anchor?.war ?? "–"}</p>
        </div>
        <div class="duel-mid"><p class="page-title">${twin ? `${twin.match}%` : "–"}</p><p class="caption">profile match<br>100% = identical shape</p></div>
        <div class="duel-card twin-card">
          <h2>${twin ? `${portrait(twin.slug, twin.display_name, "sm")}<a href="#/player/${esc(twin.slug)}">${esc(twin.display_name)}</a>` : "—"}</h2>
          <p class="caption">${twin ? `<span class="series-swatch b"></span>${esc(d.pool_label || "")} · ${twin.primary_role === "bowl" ? "Bowler" : "Batter"} · WAR ${twin.war}` : "No neighbour yet"}</p>
        </div>
      </div>
      <p class="caption">Bars plot the displayed career-profile values on a shared zero axis within each metric. Shape can match even when overall quality differs.</p>
      ${bars}
      <h2 class="section">Also close</h2>
      <table class="data twin-neighbours">
        <thead><tr><th>Player</th><th>Role</th><th class="num">Match</th><th class="num">WAR</th><th>Action</th></tr></thead>
        <tbody>${(d.twins || []).map((t) => `<tr>
          <td><a href="#/player/${esc(t.slug)}">${esc(t.display_name)}</a></td>
          <td>${t.primary_role === "bowl" ? "Bowler" : "Batter"}</td>
          <td class="num">${t.match}%</td>
          <td class="num">${t.war}</td>
          <td><a href="#/compare?a=${encodeURIComponent(d.person.slug)}&b=${encodeURIComponent(t.slug)}&pool=${encodeURIComponent(d.pool || "")}">Compare</a></td>
        </tr>`).join("")}</tbody>
      </table>`;
    bindTable("");
    warmPortraits($("tw-out"));
  };
  $("tw-go").addEventListener("click", run);
  bindFieldAutocomplete("tw-p", "people");
  if (player) run();
}

async function showShift() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Stat line shift");
  const player = hashParam("player") || "";
  const team = hashParam("team") || "";
  const comp = hashParam("comp") || "t20i";
  const minGames = Math.max(1, Number(hashParam("min")) || 5);
  const compactShift = hashParam("compact") === "1";
  const formats = shiftFormats().map(([k, l]) =>
    `<option value="${k}" ${comp === k ? "selected" : ""}>${l}</option>`).join("");
  main.innerHTML = `
    <h1 class="page-title">Stat line shift</h1>
    <p class="lede">How teammates bowl and bat with you in the XI vs without you — from your first appearance in this format onward.</p>
    <div class="filters">
      <label>Player <input type="text" id="sh-p" value="${esc(player)}" placeholder="Bumrah"></label>
      <label>Team (optional) <input type="text" id="sh-t" value="${esc(team)}" placeholder="India"></label>
      <label>Format
        <select id="sh-c">${formats}</select>
      </label>
      <label>Min games each split
        <input type="number" id="sh-min" min="1" max="50" value="${minGames}">
      </label>
      <button type="button" class="view-toggle" id="sh-compact" aria-pressed="${compactShift}">Δ only</button>
      <button class="btn primary" id="sh-go">Run shift</button>
    </div>
    <div id="sh-out"></div>`;
  const go = () => {
    const p = $("sh-p").dataset.resolved || $("sh-p").value.trim();
    if (!p) return;
    const qs = new URLSearchParams({ player: p, comp: $("sh-c").value });
    const selectedTeam = $("sh-t").dataset.resolved || $("sh-t").value.trim();
    if (selectedTeam) qs.set("team", selectedTeam);
    qs.set("min", String(Math.max(1, Number($("sh-min").value) || 1)));
    if ($("sh-compact").getAttribute("aria-pressed") === "true") qs.set("compact", "1");
    location.hash = `#/shift?${qs}`;
  };
  $("sh-go").addEventListener("click", go);
  bindFieldAutocomplete("sh-p", "people");
  bindFieldAutocomplete("sh-t", "teams");
  $("sh-c").addEventListener("change", go);
  $("sh-compact").addEventListener("click", () => {
    $("sh-compact").setAttribute("aria-pressed", $("sh-compact").getAttribute("aria-pressed") !== "true");
    if (player) go();
  });
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
  const support = { supporting: true };
  const deltaCol = (key, label, delta, digits, info = "") => n(key, label, {
    delta, digits, deltaPrimary: true, deltaBar: true, ...(info ? { info } : {}),
  });
  const fullBowlCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("Matches", [n("m_with", "With", support), n("m_wo", "W/o", support)]),
    g("Wickets", [n("wk_with", "With", support), n("wk_wo", "W/o", support)]),
    g("Avg", [n("avg_with", "With", support), n("avg_wo", "W/o", support), deltaCol("avg_delta", "Δ", "lower", 1)]),
    g("Econ", [n("econ_with", "With", { ...support, digits: 2 }), n("econ_wo", "W/o", { ...support, digits: 2 }), deltaCol("econ_delta", "Δ", "lower", 2)]),
    g("SR", [n("sr_with", "With", support), n("sr_wo", "W/o", support), deltaCol("sr_delta", "Δ", "lower", 1)]),
  ];
  const fullBatCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("Matches", [n("m_with", "With", support), n("m_wo", "W/o", support)]),
    g("Inns", [n("inns_with", "With", support), n("inns_wo", "W/o", support), n("no_with", "NO", support)]),
    g("Runs", [n("runs_with", "With", support), n("runs_wo", "W/o", support), n("hs_with", "HS", support)]),
    g("Avg", [n("avg_with", "With", support), n("avg_wo", "W/o", support), deltaCol("avg_delta", "Δ", "higher", 1)]),
    g("SR", [n("sr_with", "With", support), n("sr_wo", "W/o", support), deltaCol("sr_delta", "Δ", "higher", 1)]),
    g("100s", [n("hundred_with", "With", support), n("hundred_wo", "W/o", support)]),
    g("50s", [n("fifty_with", "With", support), n("fifty_wo", "W/o", support)]),
  ];
  const fullAdvCols = [
    { key: "player", label: "Partner", align: "left", link: "player" },
    g("RAE / game", [n("rae_with", "With", { ...support, digits: 2 }), n("rae_wo", "W/o", { ...support, digits: 2 }), deltaCol("rae_delta", "Δ", "higher", 2)]),
    g("WPA / game", [n("wpa_with", "With", { ...support, digits: 3 }), n("wpa_wo", "W/o", { ...support, digits: 3 }), deltaCol("wpa_delta", "Δ", "higher", 3)]),
    g("Pressure / game", [n("press_with", "With", { ...support, digits: 2 }), n("press_wo", "W/o", { ...support, digits: 2 }), deltaCol("press_delta", "Δ", "higher", 2)]),
    g("Score", [
      n("score_with", "With", { ...support, info: "Ball-weighted 0–100 performance percentile within this competition pool." }),
      n("score_wo", "W/o", support),
      deltaCol("score_delta", "Δ", "higher", 1, "Change in ball-weighted 0–100 performance percentile."),
    ]),
  ];
  const sampleCol = { key: "sample", label: "Games W / W-O", align: "right" };
  const compactBowlCols = [
    { key: "player", label: "Partner", align: "left", link: "player" }, sampleCol,
    deltaCol("avg_delta", "AVG Δ", "lower", 1),
    deltaCol("econ_delta", "ECON Δ", "lower", 2),
    deltaCol("sr_delta", "SR Δ", "lower", 1),
  ];
  const compactBatCols = [
    { key: "player", label: "Partner", align: "left", link: "player" }, sampleCol,
    deltaCol("avg_delta", "AVG Δ", "higher", 1),
    deltaCol("sr_delta", "SR Δ", "higher", 1),
  ];
  const compactAdvCols = [
    { key: "player", label: "Partner", align: "left", link: "player" }, sampleCol,
    deltaCol("rae_delta", "RAE Δ", "higher", 2),
    deltaCol("wpa_delta", "WPA Δ", "higher", 3),
    deltaCol("press_delta", "PRESS Δ", "higher", 2),
    deltaCol("score_delta", "SCORE Δ", "higher", 1, "Change in ball-weighted 0–100 performance percentile."),
  ];
  const prepare = (rows) => (rows || [])
    .filter((r) => Math.min(Number(r.m_with) || 0, Number(r.m_wo) || 0) >= minGames)
    .map((r) => ({ ...r, sample: `${r.m_with} / ${r.m_wo}` }));
  const bowlRows = prepare(d.bowling);
  const batRows = prepare(d.batting);
  const bowlCols = compactShift ? compactBowlCols : fullBowlCols;
  const batCols = compactShift ? compactBatCols : fullBatCols;
  const advCols = compactShift ? compactAdvCols : fullAdvCols;
  const bowlFirst = d.primary_role === "bowl";
  const tableOpts = (sortKey) => ({ sortKey, sortDir: "desc", sortAbs: true, sampleFloor: minGames });
  const bowlBlock = `
    <section id="shift-bowling" class="profile-section">
    <h2 class="section">Bowling partners</h2>
    <p class="caption">Average, economy, and strike rate with ${esc(d.person.display_name)} → without.</p>
    ${table(bowlCols, bowlRows, tableOpts("avg_delta"))}</section>`;
  const batBlock = `
    <section id="shift-batting" class="profile-section">
    <h2 class="section">Batting partners</h2>
    <p class="caption">Matches, innings, runs, average, and strike rate with ${esc(d.person.display_name)} in the XI → without.</p>
    ${table(batCols, batRows, tableOpts("avg_delta"))}</section>`;
  const advBowl = `
    <section id="shift-bowling-value" class="profile-section">
    <h2 class="section">T20 bowling value</h2>
    <p class="caption">Per game in each split. Score is ball-weighted performance percentile in ${esc(d.pool_label || "T20")}.</p>
    ${table(advCols, bowlRows, tableOpts("score_delta"))}</section>`;
  const advBat = `
    <section id="shift-batting-value" class="profile-section">
    <h2 class="section">T20 batting value</h2>
    <p class="caption">Same value model, batting. Score is ball-weighted performance percentile in ${esc(d.pool_label || "T20")}.</p>
    ${table(advCols, batRows, tableOpts("score_delta"))}</section>`;
  const advBlock = d.t20 ? (bowlFirst ? advBowl + advBat : advBat + advBowl) : "";
  $("sh-out").innerHTML = `
    <p class="scope">${esc(d.caption || "")}</p>
    <nav class="jump player-jump shift-jump" aria-label="Stat line shift sections">
      <button data-jump="shift-batting">Batting partners</button>
      <button data-jump="shift-bowling">Bowling partners</button>
      ${d.t20 ? `<button data-jump="shift-batting-value">T20 batting value</button><button data-jump="shift-bowling-value">T20 bowling value</button>` : ""}
    </nav>
    <p class="shift-legend"><span class="pos">Green</span> = teammates perform better with ${esc(d.person.display_name)} in the XI. <span class="neg">Red</span> = worse. Showing partners with at least ${minGames} games in both splits; click any header to sort.</p>
    ${bowlFirst ? bowlBlock + batBlock : batBlock + bowlBlock}
    ${advBlock}`;
  $("sh-out").querySelectorAll("[data-jump]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById(button.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  const shiftSections = [...$("sh-out").querySelectorAll(".profile-section")];
  const setShiftActive = (id) => {
    $("sh-out").querySelectorAll("[data-jump]").forEach((button) => button.classList.toggle("active", button.dataset.jump === id));
  };
  if (shiftSections[0]) setShiftActive(shiftSections[0].id);
  main._sectionObserver?.disconnect();
  main._sectionObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!visible) return;
    setShiftActive(visible.target.id);
  }, { rootMargin: "-110px 0px -65% 0px" });
  shiftSections.forEach((section) => main._sectionObserver.observe(section));
  bindTable("");
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
  setDocTitle("Build");
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
    <button class="btn primary" id="do-build">Build warehouse</button>
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
  $("do-build").addEventListener("click", (e) => run("build", e.target));
  $("do-metrics").addEventListener("click", (e) => run("metrics", e.target));
}

async function showSQL() {
  setHero(false);
  const views = await fetch("/api/views").then((r) => r.json()).catch(() => ({ views: [] }));
  const list = views.views || [];
  main.innerHTML = `
    <h1 class="page-title">SQL</h1>
    <p class="caption">Read-only · documented views only</p>
    <div class="sql-layout">
      <div class="sql-views">${list.map((v) => `<button type="button" data-v="${esc(v)}">${esc(v)}</button>`).join("")}</div>
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
  setDocTitle("Resources");
  const r = await fetch(`/api/docs/${encodeURIComponent(name || "model")}`);
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.html) {
    main.innerHTML = `<div class="empty"><p>Doc not found.</p></div>`;
    return;
  }
  main.innerHTML = `<article class="docs-body">${d.html}</article>`;
}

// A resource surface as a grid of cells: balls remaining down, wickets in hand
// across, shaded by expected runs. Reading a monotone surface is the fastest way
// to see whether the fit is sane.
function resourceHeat(grid, { title, sub, xLab, yLab, maxCells = 21 } = {}) {
  if (!grid?.length) return "";
  const balls = [...new Set(grid.map((r) => r.balls))].sort((a, b) => b - a);
  const wickets = [...new Set(grid.map((r) => r.wickets))].sort((a, b) => a - b);
  const step = Math.max(1, Math.ceil(balls.length / maxCells));
  const rows = balls.filter((_, i) => i % step === 0 || i === balls.length - 1);
  const lookup = new Map(grid.map((r) => [`${r.balls}:${r.wickets}`, r]));
  const max = Math.max(...grid.map((r) => Number(r.value) || 0), 1);
  const head = `<tr><th class="l">${esc(yLab)}</th>${wickets.map((w) => `<th class="n">${w}</th>`).join("")}</tr>`;
  const body = rows.map((b) => `<tr><th class="l">${b}</th>${wickets.map((w) => {
    const cell = lookup.get(`${b}:${w}`);
    const v = cell ? Number(cell.value) : null;
    if (v == null) return `<td class="n empty-cell"></td>`;
    // Square-rooting the share spreads the low end, where a linear ramp leaves
    // most of the surface reading as one flat dark block.
    const share = Math.sqrt(Math.max(v, 0) / max);
    const thin = cell.n != null && Number(cell.n) < 30;
    return `<td class="n heat-cell${thin ? " thin" : ""}" style="--fill:${(share * 62).toFixed(1)}%"
      title="${b} balls, ${w} wickets in hand → ${v.toFixed(1)} runs${cell.n != null ? ` · ${Number(cell.n).toLocaleString()} observations` : ""}">${v.toFixed(0)}</td>`;
  }).join("")}</tr>`).join("");
  return `<figure class="heatmap">
    <figcaption><strong>${esc(title)}</strong><span class="caption">${esc(sub || "")}</span></figcaption>
    <div class="heat-scroll"><table class="heat"><thead>${head}</thead><tbody>${body}</tbody></table></div>
    <p class="caption heat-axis">Columns: ${esc(xLab)}. Faint cells rest on fewer than thirty observations and lean on the smoother.</p>
  </figure>`;
}

async function showModel() {
  setHero(false);
  main.classList.add("wide");
  setDocTitle("Model");
  const state = { gender: hashParam("gender") || "male", need: Number(hashParam("need") || 60) };
  const paint = async () => {
    history.replaceState(null, "", `#/model?gender=${state.gender}&need=${state.need}`);
    main.innerHTML = `<h1 class="page-title">Model</h1><p class="caption">Loading the value model…</p>`;
    const d = await (await fetch(`/api/model?gender=${encodeURIComponent(state.gender)}`)).json();
    if (!d.ok || !d.grid?.length) {
      main.innerHTML = `<h1 class="page-title">Model</h1>
        <div class="empty"><p>The value model has not been built yet.</p>
        <p class="caption">Run a metrics rebuild from <a href="#/build">Build</a>.</p></div>`;
      return;
    }
    const meta = d.meta?.resource_model || {};
    const rpwRows = (d.rpw || []).filter((r) => r.gender === state.gender);
    const separated = rpwRows.some((r) => r.match_separated);
    const needs = [...new Set((d.chase || []).map((r) => Number(r.need)))].sort((a, b) => a - b);
    const nearest = needs.reduce((best, n) => (Math.abs(n - state.need) < Math.abs(best - state.need) ? n : best), needs[0] ?? 60);
    const chaseSlice = (d.chase || []).filter((r) => Number(r.need) === nearest);
    const audit = d.audit || [];
    const fails = audit.filter((a) => a.status !== "pass");
    main.innerHTML = `
      <h1 class="page-title">Model</h1>
      <p class="lede">How a ball becomes a number. Every delivery is priced by what it did to the runs and wickets a side had left, and everything below is the machinery that makes that price.</p>
      ${leaderboardNav("model")}
      <div class="filters" aria-label="Model filters">
        <label>Gender
          <select id="mo-g">
            <option value="male" ${state.gender === "male" ? "selected" : ""}>Men</option>
            <option value="female" ${state.gender === "female" ? "selected" : ""}>Women</option>
          </select>
        </label>
        <label>Runs required
          <select id="mo-need">${needs.map((n) => `<option value="${n}" ${n === nearest ? "selected" : ""}>${n}</option>`).join("")}</select>
        </label>
        <span class="check-note">${d.audit_summary.pass} of ${d.audit_summary.total} checks pass</span>
      </div>

      <h2 class="section">Resource surfaces</h2>
      <p class="caption">Left: runs a side still expects with those balls and wickets left, when there is no target. Right: the same question in a chase, where value is capped at the runs actually required.</p>
      <div class="heat-pair">
        ${resourceHeat(d.grid, {
          title: "Expected remaining runs",
          sub: "First innings · R(balls, wickets)",
          xLab: "wickets in hand",
          yLab: "Balls",
        })}
        ${resourceHeat(chaseSlice, {
          title: `Chase value, ${nearest} to get`,
          sub: "Second innings · R2(balls, wickets, runs required)",
          xLab: "wickets in hand",
          yLab: "Balls",
        })}
      </div>

      <h2 class="section">Runs per win</h2>
      <p class="caption">The exchange rate between runs and wins. Runs above replacement divided by this number is a player's wins above replacement.</p>
      <div id="mo-rpw"></div>
      ${separated ? `<div class="callout">
        <h3>Why this is fitted on seasons, not matches</h3>
        <p>The methodology asks for a match-level fit of the result on the resource-adjusted margin. Fitted that way here, the margin's sign agrees with the result on
        ${(Math.max(...rpwRows.map((r) => Number(r.match_sign_agreement || 0))) * 100).toFixed(1)}% of matches — a completed pair of innings mechanically encodes who won, so the
        slope measures that tautology rather than the value of a run, and it collapses to
        ${rpwRows.map((r) => r.match_runs_per_win).filter((v) => v != null)[0] ?? "–"} runs per win.</p>
        <p>The same regression one level up is well behaved: a side's realised margin across a season does not determine its win count. Both coefficients are in the table
        above so the departure is visible rather than assumed.</p>
      </div>` : ""}

      <h2 class="section">Replacement level</h2>
      <p class="caption">What a fringe player produces in the same role, in runs per ball. Value above replacement is measured from here, not from average.</p>
      <div id="mo-rep"></div>

      <h2 class="section">Validation</h2>
      <p class="caption">${fails.length ? `${fails.length} check${fails.length === 1 ? "" : "s"} failing.` : "Every invariant holds on the current build."} These run on every rebuild against the full delivery table.</p>
      <div id="mo-audit"></div>

      <h2 class="section">What the model cannot see</h2>
      <p class="caption">Play that carries no value, by season. Shortened and target-revised innings are excluded from fitting, and rather than drop them quietly the unvalued share is published.</p>
      <div id="mo-exp"></div>

      <h3 class="section">Chase distortion</h3>
      <p class="caption">Chase deliveries valued against the target-aware surface, next to the same balls valued as if no target existed. The gap is what a target-neutral model would have got wrong.</p>
      <div id="mo-dist"></div>

      ${Object.keys(meta).length ? `<h2 class="section">Settings</h2>${ledger(["Setting", "Value"], Object.entries(meta)
        .filter(([, v]) => v != null && typeof v !== "object")
        .map(([k, v]) => [esc(titleCase(k)), esc(String(v))]))}` : ""}
      <p class="caption">Full write-up in <a href="#/docs/model">MODEL.md</a>. Model version ${esc(String(d.meta?.model_version || ""))}.</p>`;

    $("mo-rpw").innerHTML = table(
      [
        { key: "competition", label: "Competition", align: "left", badge: true },
        { key: "runs_per_win", label: "Runs per win", align: "right", numeric: true, digits: 1, help: "Runs of aggregate margin worth one win" },
        { key: "beta_margin", label: "Slope", align: "right", numeric: true, digits: 4, help: "Logistic coefficient on margin per match" },
        { key: "beta_margin_no_strength", label: "Slope, no strength", align: "right", numeric: true, digits: 4, help: "The same fit without the team-strength covariate, to check attenuation" },
        { key: "team_seasons", label: "Team seasons", align: "right", numeric: true },
        { key: "matches", label: "Matches", align: "right", numeric: true },
        { key: "match_runs_per_win", label: "Match-level", align: "right", numeric: true, digits: 2, help: "The methodology's match-level estimate, retained as a diagnostic" },
        { key: "match_sign_agreement", label: "Sign agreement", align: "right", numeric: true, digits: 4, help: "Share of matches where the margin's sign matches the result. Near one means the match-level fit is separated" },
        { key: "variant", label: "Source", align: "left" },
      ],
      rpwRows,
      { sortKey: "runs_per_win", sortDir: "desc" },
    );
    $("mo-rep").innerHTML = table(
      [
        { key: "competition", label: "Competition", align: "left", badge: true },
        { key: "discipline", label: "Side", align: "left" },
        { key: "role", label: "Role", align: "left" },
        { key: "rho", label: "Runs per ball", align: "right", numeric: true, digits: 4 },
        { key: "pools", label: "Seasons", align: "right", numeric: true },
        { key: "fallbacks", label: "On fallback", align: "right", numeric: true, help: "Seasons scored by the shrunk-percentile fallback because the marginal cohort was too thin or implausible" },
      ],
      d.replacement || [],
      { searchable: true, searchLabel: "Find a role" },
    );
    $("mo-audit").innerHTML = table(
      [
        { key: "status", label: "Status", align: "left", status: true },
        { key: "check_name", label: "Check", align: "left" },
        { key: "scope", label: "Scope", align: "left" },
        { key: "value", label: "Value", align: "right", numeric: true, digits: 4 },
        { key: "note", label: "What it means", align: "left" },
      ],
      audit.map((a) => ({ ...a, status: a.status === "pass" ? "Pass" : "Fail" })),
      { searchable: true, searchLabel: "Find a check" },
    );
    $("mo-exp").innerHTML = table(
      [
        { key: "competition", label: "Competition", align: "left", badge: true },
        { key: "season", label: "Season", align: "left" },
        { key: "deliveries", label: "Deliveries", align: "right", numeric: true },
        { key: "unscored", label: "Unvalued", align: "right", numeric: true },
        { key: "unscored_share", label: "Share", align: "right", numeric: true, digits: 3 },
        { key: "top_reason", label: "Main reason", align: "left" },
      ],
      d.exposure || [],
      { sortKey: "unscored_share", sortDir: "desc" },
    );
    $("mo-dist").innerHTML = table(
      [
        { key: "competition", label: "Competition", align: "left", badge: true },
        { key: "entry_state", label: "Pressure", align: "left" },
        { key: "opportunities", label: "Balls", align: "right", numeric: true },
        { key: "raa_chase_table", label: "Target-aware", align: "right", numeric: true, digits: 0 },
        { key: "raa_target_neutral", label: "Target-neutral", align: "right", numeric: true, digits: 0 },
        { key: "gap_per_100", label: "Gap / 100 balls", align: "right", numeric: true, digits: 3 },
      ],
      d.distortion || [],
      { sortKey: "gap_per_100", sortDir: "desc" },
    );
    bindTable("");
    $("mo-g")?.addEventListener("change", (e) => { state.gender = e.target.value; paint(); });
    $("mo-need")?.addEventListener("change", (e) => { state.need = Number(e.target.value); paint(); });
  };
  await paint();
}

let routeGen = 0;

async function route() {
  const gen = ++routeGen;
  try {
    await routeInner(gen);
  } catch (err) {
    if (gen !== routeGen) return;
    main.innerHTML = `<div class="empty"><p>Couldn’t open this page.</p><p class="caption">${esc(err.message || err)}</p></div>`;
  }
}

async function routeInner(gen = routeGen) {
  if (main._profileScroll) {
    window.removeEventListener("scroll", main._profileScroll);
    main._profileScroll = null;
  }
  main._profileObserver?.disconnect();
  main._sectionObserver?.disconnect();
  main.classList.remove("wide");
  document.body.classList.remove("table-focus");
  delete document.body.dataset.playerSlug;
  delete document.body.dataset.playerName;
  const star = $("fav-star");
  if (star) star.hidden = true;
  const hashRaw = location.hash.replace(/^#/, "") || "/";
  const qIndex = hashRaw.indexOf("?");
  const pathEnc = qIndex < 0 ? hashRaw : hashRaw.slice(0, qIndex);
  let hash = pathEnc;
  try { hash = decodeURIComponent(pathEnc); } catch { /* keep encoded path */ }
  if (hash.startsWith("/q=")) {
    const q = hash.slice(3);
    input.value = q;
    syncHighlight();
    setHero(false);
    setDocTitle(q);
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
  if (head === "rankings") return showRankings();
  if (head === "records") return showRecords();
  if (head === "grounds") return showGrounds();
  if (head === "venue") return showVenue(parts[1] ? decodeURIComponent(parts[1]) : "");
  if (head === "team") return showTeam(parts[1] ? decodeURIComponent(parts[1]) : "");
  if (head === "best") return showBest();
  if (head === "compare") return showCompare();
  if (head === "teams") return showTeamCompare();
  if (head === "twin") return showTwin();
  if (head === "shift") return showShift();
  if (head === "metrics" || head === "war") return showMetrics();
  if (head === "model") return showModel();
  if (head === "standings") return showStandings();
  if (head === "build") return showBuild();
  if (head === "sql") return showSQL();
  if (head === "docs" || head === "resources") return showDocs(parts[1] || "model");
  if (gen !== routeGen) return;
  setHero(false);
  setDocTitle("Not found");
  main.innerHTML = `<div class="empty"><p>No page at #/${esc(head)}.</p><a class="chip" href="#/">Home</a></div>`;
}

let lastRoutePath = null;

// Hash routing leaves the old scroll position behind, so a new page can open
// halfway down. Anchors within the same page (the player jump bar) must keep it.
function resetScrollForNewRoute() {
  const path = location.hash.replace(/^#/, "").split("?")[0] || "/";
  if (path !== lastRoutePath) window.scrollTo(0, 0);
  lastRoutePath = path;
}

window.addEventListener("hashchange", () => {
  page = 0;
  closeSearch();
  resetScrollForNewRoute();
  route();
});

(async function init() {
  initChrome({
    openSearch,
    setQuery,
    focusFilter() {
      const id = main.dataset.hoverTbl;
      const filter = (id && document.querySelector(`#${CSS.escape(id)} .table-filter`)) || document.querySelector(".table-filter");
      if (filter) { filter.hidden = false; filter.focus(); }
      else toast("No table to filter");
    },
  });
  bindTable("");
  renderChips();
  await loadSettings();
  await loadStatus();
  syncHighlight();
  lastRoutePath = location.hash.replace(/^#/, "").split("?")[0] || "/";
  await route();
})();
