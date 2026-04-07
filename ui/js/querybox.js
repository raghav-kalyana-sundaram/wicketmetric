const TOKEN_KEYS = [
  "player","runs","format","comp","year","years","from","to","opposition","opp",
  "team","venue","compare","pair","with","without","war","metric","out",
  "dismissed_by","standings","gender","notout","min_balls","min_partnerships",
];

const FORMAT_OK = new Set([
  "test", "tests", "odi", "odis", "odm", "t20i", "t20", "it20", "ipl", "wpl", "bbl", "wbbl", "wbb",
]);

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

export function highlightHTML(raw) {
  return tokenize(raw).map((t) => {
    if (t.type === "text") return escape(t.text);
    const cls = t.bad ? "token-pill token-bad" : "token-pill";
    const title = t.bad ? `Unknown ${t.key}. Try: test, odi, t20i, ipl, wpl, bbl, wbbl` : "";
    return `<span class="${cls}" title="${escape(title)}"><span class="k">${escape(t.key)}:</span><span class="v">${escape(t.val)}</span></span>`;
  }).join("");
}

export function heuristic(raw) {
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
