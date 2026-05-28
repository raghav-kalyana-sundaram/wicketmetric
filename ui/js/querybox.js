const TOKEN_KEYS = [
  "player","runs","format","comp","year","years","from","to","opposition","opp",
  "team","venue","compare","pair","with","without","war","metric","out",
  "dismissed_by","standings","gender","notout","min_balls","min_partnerships",
  "side","event","home","away",
];

const FORMAT_OK = new Set([
  "test", "tests", "odi", "odis", "odm", "t20i", "t20", "it20", "ipl", "wpl", "bbl", "wbbl", "wbb",
]);

const TEAM_PHRASES = [
  "new zealand", "south africa", "west indies", "sri lanka", "australia", "england",
  "pakistan", "bangladesh", "afghanistan", "zimbabwe", "ireland", "india",
  "chennai super kings", "mumbai indians", "royal challengers bengaluru",
  "royal challengers bangalore", "kolkata knight riders", "sunrisers hyderabad",
  "rajasthan royals", "delhi capitals", "punjab kings", "gujarat titans",
  "lucknow super giants",
].sort((a, b) => b.length - a.length);

const TEAM_SHORT = new Set([
  "nz", "sa", "wi", "sl", "aus", "eng", "pak", "ban", "afg", "zim", "ire", "ind",
  "csk", "mi", "rcb", "kkr", "srh", "rr", "dc", "pbks", "gt", "lsg",
]);

const VS = /\s+v(?:s)?\.?\s+/i;
const YEAR = /^(?:(\d{4})(?:\s*[-–]\s*(\d{2,4}))?|'(\d{2}))$/;
const SCORE = /^\d{1,3}$/;

export function tokenize(raw) {
  const tokens = [];
  const re = /([a-z_]+):("[^"]+"|\S+)/gi;
  let last = 0;
  let m;
  while ((m = re.exec(raw))) {
    if (m.index > last) tokens.push({ type: "text", text: raw.slice(last, m.index) });
    const key = m[1].toLowerCase();
    const val = m[2].replace(/^"|"$/g, "");
    let bad = !TOKEN_KEYS.includes(key);
    if ((key === "format" || key === "comp") && !FORMAT_OK.has(val.toLowerCase())) bad = true;
    tokens.push({ type: "token", key, val, raw: m[0], bad });
    last = m.index + m[0].length;
  }
  if (last < raw.length) tokens.push({ type: "text", text: raw.slice(last) });
  return tokens;
}

export function parseBare(raw) {
  const q = String(raw || "").trim();
  const empty = { player: "", runs: "", year: "", opp: "", team: "", format: "", venue: "", event: "", home: "", away: "", mode: "" };
  if (!q || /:\S/.test(q)) {
    const score = trailingScore(q);
    return score ? { ...empty, player: score.name, runs: score.runs } : { ...empty, player: q };
  }
  const out = { ...empty };
  const vs = q.split(VS);
  if (vs.length === 2 && vs[0].trim() && vs[1].trim()) {
    const left = peel(vs[0].trim());
    const right = peel(vs[1].trim());
    Object.assign(out, pickFilters(left), pickFilters(right));
    if (left.player && right.opp) {
      out.player = left.player;
      out.opp = right.opp;
    } else if (right.player && left.opp) {
      out.player = right.player;
      out.opp = left.opp;
    } else if (left.opp && right.opp && !left.player && !right.player) {
      out.home = left.opp;
      out.away = right.opp;
      out.mode = "matches";
    } else if (left.player && right.player) {
      out.player = left.player;
      out.mode = "compare";
    } else {
      out.player = left.player || right.player;
      out.opp = right.opp || left.opp;
    }
    return out;
  }
  return Object.assign(out, peel(q));
}

function pickFilters(p) {
  return { year: p.year, runs: p.runs, format: p.format, venue: p.venue, event: p.event };
}

function peel(text) {
  const words = text.split(/\s+/);
  const player = [];
  const out = { player: "", runs: "", year: "", opp: "", team: "", format: "", venue: "", event: "" };
  let pending = "";
  for (let i = 0; i < words.length; i += 1) {
    const w = words[i];
    const wl = w.toLowerCase().replace(/[.,]$/, "");
    if (YEAR.test(wl) && !out.year) {
      const m = wl.match(YEAR);
      out.year = m[3] ? yearFromTwo(m[3]) : m[1];
      pending = "";
      continue;
    }
    if (/^(vs|v|versus|against)$/.test(wl)) { pending = "opp"; continue; }
    if (wl === "for") { pending = "team"; continue; }
    if (wl === "at") { pending = "venue"; continue; }
    if (/^(the|of|and|in|on)$/.test(wl)) continue;
    if (FORMAT_OK.has(wl) && !out.format) { out.format = wl; pending = ""; continue; }
    const team = matchTeam(words, i);
    if (team) {
      if (pending === "team") out.team = team.name;
      else out.opp = team.name;
      i += team.words - 1;
      pending = "";
      continue;
    }
    if (SCORE.test(wl) && !out.runs) { out.runs = wl; pending = ""; continue; }
    player.push(w);
    pending = "";
  }
  out.player = player.filter((w) => !SCORE.test(w)).join(" ").trim();
  return out;
}

function matchTeam(words, i) {
  const rest = words.slice(i).join(" ").toLowerCase();
  for (const phrase of TEAM_PHRASES) {
    if (rest === phrase || rest.startsWith(`${phrase} `)) {
      return { name: title(phrase), words: phrase.split(" ").length };
    }
  }
  const one = words[i].toLowerCase().replace(/[.,]$/, "");
  if (TEAM_SHORT.has(one)) return { name: one.toUpperCase(), words: 1 };
  return null;
}

function title(s) {
  return s.replace(/\b[a-z]/g, (m) => m.toUpperCase());
}

function yearFromTwo(yy) {
  const n = Number(yy);
  return String(n <= 30 ? 2000 + n : 1900 + n);
}

export function highlightHTML(raw) {
  return tokenize(raw).map((t) => {
    if (t.type === "text") return highlightBare(t.text);
    const cls = t.bad ? "token-pill token-bad" : "token-pill";
    const titleAttr = t.bad ? `Unknown ${t.key}. Try: test, odi, t20i, ipl, wpl, bbl, wbbl` : "";
    return `<span class="${cls}" title="${escape(titleAttr)}"><span class="k">${escape(t.key)}:</span><span class="v">${escape(t.val)}</span></span>`;
  }).join("");
}

function highlightBare(text) {
  if (!text) return "";
  const parsed = parseBare(text);
  const marks = [];
  const push = (val, cls) => {
    if (!val) return;
    const i = text.toLowerCase().indexOf(String(val).toLowerCase());
    if (i >= 0) marks.push({ i, n: String(val).length, cls });
  };
  push(parsed.opp, "token-entity");
  push(parsed.team, "token-entity");
  push(parsed.home, "token-entity");
  push(parsed.away, "token-entity");
  push(parsed.year, "token-entity");
  push(parsed.runs, "token-score");
  push(parsed.format, "token-entity");
  marks.sort((a, b) => a.i - b.i);
  let out = "";
  let cursor = 0;
  for (const m of marks) {
    if (m.i < cursor) continue;
    out += escape(text.slice(cursor, m.i));
    out += `<span class="${m.cls}">${escape(text.slice(m.i, m.i + m.n))}</span>`;
    cursor = m.i + m.n;
  }
  return out + escape(text.slice(cursor));
}

export function heuristic(raw) {
  const parsed = parseBare(raw);
  if (parsed.opp || parsed.year || parsed.home) {
    const bits = [];
    if (parsed.player) bits.push(parsed.player);
    if (parsed.home && parsed.away) bits.push(`${parsed.home} v ${parsed.away}`);
    else if (parsed.opp) bits.push(`vs ${parsed.opp}`);
    if (parsed.year) bits.push(parsed.year);
    if (parsed.runs && parsed.opp && String(parsed.runs).length <= 2) {
      bits.push(`${parsed.runs} runs or ${yearFromTwo(String(parsed.runs).padStart(2, "0"))}`);
    } else if (parsed.runs) {
      bits.push(`${parsed.runs} runs`);
    }
    if (parsed.format) bits.push(parsed.format);
    return bits.length > 1 ? bits.join(" · ") : "";
  }
  const hasPlayer = /player:|\b[a-z][a-z.'-]+/i.test(raw);
  const m = raw.match(/\s(\d{1,3})\s*$/);
  if (hasPlayer && m && !/runs:/.test(raw)) return `→ runs:${m[1]} (exact)`;
  return "";
}

/** Bare “kohli 89” / “v kohli 183” — name plus a score, not a token query. */
export function trailingScore(raw) {
  const q = String(raw || "").trim();
  if (!q || /runs:/i.test(q) || /:\S/.test(q)) return null;
  const m = q.match(/^(.*\S)\s+(\d{1,3})$/);
  if (!m || /^\d+$/.test(m[1].trim())) return null;
  if (!/[a-z]/i.test(m[1])) return null;
  return { name: m[1].trim(), runs: m[2] };
}

export function inningsIntent(raw) {
  const parsed = parseBare(raw);
  if (parsed.runs && parsed.player) {
    return {
      name: parsed.player,
      runs: parsed.runs,
      opp: parsed.opp,
      year: parsed.year,
    };
  }
  return trailingScore(raw);
}

export function upsertToken(raw, key, value) {
  const re = new RegExp(`${key}:("[^"]+"|\\S+)`, "i");
  if (!value) return raw.replace(re, "").replace(/\s+/g, " ").trim();
  if (re.test(raw)) return raw.replace(re, `${key}:${value}`).replace(/\s+/g, " ").trim();
  return `${raw} ${key}:${value}`.trim();
}

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  ));
}
