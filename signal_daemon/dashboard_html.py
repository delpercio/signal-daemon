"""The dashboard page.

Kept as a Python string rather than a data file so the PyInstaller binary
stays a single self-contained artifact with no package-data wiring.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal — Captured Activity</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='4' fill='%232a78d6'/%3E%3Crect x='4' y='8' width='2' height='4' fill='white'/%3E%3Crect x='7' y='5' width='2' height='7' fill='white'/%3E%3Crect x='10' y='3' width='2' height='9' fill='white'/%3E%3C/svg%3E">
<style>
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --plane: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --series-3: #1baf7a;
  --good: #0ca30c;
  --critical: #d03b3b;
  --warning: #fab219;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --plane: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--plane);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 24px 20px 64px; }

header { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline; justify-content: space-between; margin-bottom: 4px; }
h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
.sub { color: var(--text-secondary); font-size: 13px; margin: 0 0 20px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: baseline; }

.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 20px; }
label.f { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
select, input[type=search] {
  font: inherit; font-size: 13px; padding: 6px 9px;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 7px; min-width: 150px;
}
button.ghost {
  font: inherit; font-size: 13px; padding: 7px 12px; cursor: pointer;
  background: var(--surface-1); color: var(--text-secondary);
  border: 1px solid var(--border); border-radius: 7px; align-self: end;
}
button.ghost:hover { color: var(--text-primary); }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 12px; margin-bottom: 20px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile .k { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
.tile .v { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; margin-top: 3px; }
.tile .n { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px 12px; margin-bottom: 20px; }
.card h2 { font-size: 13px; font-weight: 600; margin: 0 0 2px; }
.card .cap { font-size: 12px; color: var(--text-secondary); margin: 0 0 14px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 20px; }

.scroll { overflow-x: auto; }
/* Recent events can run to hundreds of rows — keep it a pane, not a page. */
.scroll.tall { max-height: 460px; overflow-y: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: right; padding: 7px 10px; white-space: nowrap; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
th { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; font-weight: 500; }
.scroll.tall thead th { position: sticky; top: 0; background: var(--surface-1); z-index: 1; }
tbody tr:last-child td { border-bottom: none; }
td.num { font-variant-numeric: tabular-nums; }
tbody tr:hover { background: color-mix(in srgb, var(--text-primary) 4%, transparent); }
.swatch { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.est { color: var(--text-muted); }

svg text { font-family: system-ui, -apple-system, sans-serif; }
.tick { font-size: 10px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }
.bar { fill: var(--series-1); }
.bar:hover { fill: color-mix(in srgb, var(--series-1) 78%, var(--text-primary)); }
.chartwrap { position: relative; }
#tip {
  position: absolute; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 7px;
  padding: 7px 10px; font-size: 12px; white-space: nowrap; z-index: 5;
  box-shadow: 0 3px 12px rgba(0,0,0,0.14);
}
#tip .t { font-weight: 600; margin-bottom: 2px; }
#tip .r { color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.empty { color: var(--text-secondary); padding: 28px 0; text-align: center; }
.err { border-left: 3px solid var(--critical); padding-left: 12px; color: var(--text-secondary); }
.warnbar {
  background: color-mix(in srgb, var(--warning) 14%, var(--surface-1));
  border: 1px solid var(--border); border-radius: 8px;
  padding: 9px 13px; font-size: 13px; margin-bottom: 20px; color: var(--text-primary);
}
.foot { color: var(--text-muted); font-size: 12px; margin-top: 28px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Signal — Captured Activity</h1>
    <button class="ghost" id="theme" title="Toggle theme">Theme</button>
  </header>
  <p class="sub" id="sub">Loading…</p>

  <div id="warn"></div>

  <div class="controls">
    <label class="f">Range
      <select id="days">
        <option value="1">Today</option>
        <option value="7" selected>Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="90">Last 90 days</option>
        <option value="0">All time</option>
      </select>
    </label>
    <label class="f">Provider <select id="provider"><option value="">All</option></select></label>
    <label class="f">Project <select id="project"><option value="">All</option></select></label>
    <label class="f">Model <select id="model"><option value="">All</option></select></label>
    <label class="f">Search <input type="search" id="q" placeholder="session, tool, text…"></label>
    <button class="ghost" id="reload">Refresh</button>
  </div>

  <div class="tiles" id="tiles"></div>

  <div class="card">
    <h2>Daily activity</h2>
    <p class="cap" id="chartcap">Tokens captured per day</p>
    <div class="chartwrap">
      <svg id="chart" role="img" aria-label="Tokens captured per day"></svg>
      <div id="tip"></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>By provider</h2>
      <p class="cap">Which tool the activity came from</p>
      <div class="scroll"><table id="t-provider"></table></div>
    </div>
    <div class="card">
      <h2>By model</h2>
      <p class="cap">Token spend per model</p>
      <div class="scroll"><table id="t-model"></table></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>By project</h2>
      <p class="cap">Workspace the events were attributed to</p>
      <div class="scroll"><table id="t-project"></table></div>
    </div>
    <div class="card">
      <h2>Top tools</h2>
      <p class="cap">Tool calls seen in captured turns</p>
      <div class="scroll"><table id="t-tool"></table></div>
    </div>
  </div>

  <div class="card">
    <h2>Recent events</h2>
    <p class="cap" id="reccap">Most recent captured events</p>
    <div class="scroll tall"><table id="t-recent"></table></div>
  </div>

  <p class="foot" id="foot"></p>
</div>

<script>
const SERIES = ['--series-1','--series-2','--series-3'];
const $ = id => document.getElementById(id);
let LAST = null;

const nf = new Intl.NumberFormat();
const fmtInt = n => nf.format(Math.round(n || 0));
function fmtTokens(n) {
  n = n || 0;
  if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
  return String(n);
}
function fmtCost(n) {
  n = n || 0;
  if (n === 0) return '$0.00';
  if (n < 0.01) return '<$0.01';
  return '$' + n.toFixed(n < 100 ? 2 : 0);
}
function fmtBytes(n) {
  n = n || 0;
  const u = ['B','KB','MB','GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + ' ' + u[i];
}
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ---- theme toggle ----
const stored = localStorage.getItem('signal-theme');
if (stored) document.documentElement.setAttribute('data-theme', stored);
$('theme').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('signal-theme', next);
  if (LAST) drawChart(LAST.by_day);
};

// ---- fetch ----
function params() {
  const p = new URLSearchParams();
  const d = $('days').value; if (d !== '0') p.set('days', d);
  for (const k of ['provider','project','model','q']) {
    const v = $(k).value.trim(); if (v) p.set(k, v);
  }
  return p;
}

async function load() {
  $('sub').textContent = 'Loading…';
  try {
    const res = await fetch('/api/summary?' + params().toString());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    LAST = data;
    render(data);
  } catch (e) {
    $('sub').innerHTML = '<span class="err">Could not load data: ' + esc(e.message) + '</span>';
  }
}

function fillSelect(el, values) {
  const cur = el.value;
  el.innerHTML = '<option value="">All</option>' +
    values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  if (values.includes(cur)) el.value = cur;
}

function render(d) {
  const t = d.totals;
  $('sub').innerHTML =
    `<span class="dot" style="background:${t.events ? 'var(--good)' : 'var(--text-muted)'}"></span>` +
    `${esc(d.device_id || 'this device')} · queue ${fmtInt(d.queue.pending)} pending, ` +
    `${fmtInt(d.queue.delivered)} delivered · ${esc(d.range_label)}`;

  const warns = [];
  if (d.queue.stuck > 0) {
    warns.push(`${fmtInt(d.queue.stuck)} event(s) exhausted their delivery retries and are being skipped.`);
  }
  if (t.events && !t.events_with_usage) {
    warns.push('No token usage found in these events — cost figures are unavailable for this selection.');
  }
  $('warn').innerHTML = warns.length
    ? `<div class="warnbar">${warns.map(esc).join(' ')}</div>` : '';

  const estNote = t.estimated_cost_usd > 0.005
    ? `includes ${fmtCost(t.estimated_cost_usd)} at fallback rates` : 'list-price estimate';
  $('tiles').innerHTML = [
    ['Events', fmtInt(t.events), `${fmtInt(t.sessions)} session(s)`],
    ['Tokens', fmtTokens(t.total_tokens), `${fmtTokens(t.input_tokens)} in · ${fmtTokens(t.output_tokens)} out`],
    ['Cache reads', fmtTokens(t.cache_read_tokens), `${fmtTokens(t.cache_creation_tokens)} written`],
    ['Est. cost', fmtCost(t.cost_usd), estNote],
    ['Captured', fmtBytes(t.payload_bytes), `${fmtInt(t.events_with_usage)} with usage`],
  ].map(([k, v, n]) =>
    `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="n">${esc(n)}</div></div>`
  ).join('');

  fillSelect($('provider'), d.facets.providers);
  fillSelect($('project'), d.facets.projects);
  fillSelect($('model'), d.facets.models);

  drawChart(d.by_day);
  tokenTable('t-provider', 'Provider', d.by_provider, true);
  tokenTable('t-model', 'Model', d.by_model, false);
  tokenTable('t-project', 'Project', d.by_project, false);

  $('t-tool').innerHTML = d.by_tool.length
    ? '<thead><tr><th>Tool</th><th>Calls</th></tr></thead><tbody>' +
      d.by_tool.map(r =>
        `<tr><td>${esc(r.name)}</td><td class="num">${fmtInt(r.count)}</td></tr>`).join('') +
      '</tbody>'
    : '<tbody><tr><td class="empty">No tool calls in this selection.</td></tr></tbody>';

  $('reccap').textContent = `${d.recent.length} most recent of ${fmtInt(t.events)} matching event(s)`;
  $('t-recent').innerHTML = d.recent.length
    ? '<thead><tr><th>When</th><th>Provider</th><th>Project</th><th>Model</th>' +
      '<th>Type</th><th>In</th><th>Out</th><th>Cost</th></tr></thead><tbody>' +
      d.recent.map(r => `<tr>
        <td class="mono">${esc(r.time)}</td>
        <td>${esc(r.provider)}</td>
        <td>${esc(r.project || '—')}</td>
        <td class="mono">${esc(r.model || '—')}</td>
        <td>${esc(r.event_type)}</td>
        <td class="num">${r.input_tokens ? fmtTokens(r.input_tokens) : '—'}</td>
        <td class="num">${r.output_tokens ? fmtTokens(r.output_tokens) : '—'}</td>
        <td class="num${r.cost_is_estimate ? ' est' : ''}">${r.cost_usd ? fmtCost(r.cost_usd) : '—'}</td>
      </tr>`).join('') + '</tbody>'
    : '<tbody><tr><td class="empty">No events match these filters.</td></tr></tbody>';

  $('foot').textContent =
    'Costs are estimates from public list prices, not billing data. ' +
    'Greyed values used a fallback rate because the model was not recognised.';
}

function tokenTable(id, label, rows, swatch) {
  const el = $(id);
  if (!rows.length) {
    el.innerHTML = `<tbody><tr><td class="empty">Nothing captured in this selection.</td></tr></tbody>`;
    return;
  }
  el.innerHTML =
    `<thead><tr><th>${esc(label)}</th><th>Events</th><th>Tokens</th><th>Cost</th></tr></thead><tbody>` +
    rows.map((r, i) => {
      const sw = swatch
        ? `<span class="swatch" style="background:var(${SERIES[i % SERIES.length]})"></span>` : '';
      return `<tr><td>${sw}${esc(r.name)}</td>
        <td class="num">${fmtInt(r.events)}</td>
        <td class="num">${r.total_tokens ? fmtTokens(r.total_tokens) : '—'}</td>
        <td class="num">${r.cost_usd ? fmtCost(r.cost_usd) : '—'}</td></tr>`;
    }).join('') + '</tbody>';
}

// ---- daily bar chart (single series: no legend, title names it) ----
function niceMax(v) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag * 2) / 2 * mag;
}

function drawChart(days) {
  const svg = $('chart');
  const tip = $('tip');
  svg.innerHTML = '';
  const data = (days || []).filter(d => d.name !== 'unknown');
  if (!data.length) {
    svg.setAttribute('height', 0);
    $('chartcap').textContent = 'No dated activity in this selection.';
    return;
  }
  $('chartcap').textContent = 'Tokens captured per day';

  const W = svg.parentElement.clientWidth || 720;
  const H = 210, ml = 52, mr = 8, mt = 10, mb = 26;
  const iw = Math.max(10, W - ml - mr), ih = H - mt - mb;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', H);

  const max = niceMax(Math.max(...data.map(d => d.total_tokens), 0));
  const NS = 'http://www.w3.org/2000/svg';
  const add = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    svg.appendChild(e);
    return e;
  };

  // recessive gridlines + ticks
  for (let i = 0; i <= 4; i++) {
    const y = mt + ih - (ih * i / 4);
    add('line', { x1: ml, x2: ml + iw, y1: y, y2: y,
                  stroke: 'var(--grid)', 'stroke-width': 1 });
    add('text', { x: ml - 8, y: y + 3, 'text-anchor': 'end', class: 'tick' },
        fmtTokens(max * i / 4));
  }
  add('line', { x1: ml, x2: ml + iw, y1: mt + ih, y2: mt + ih,
                stroke: 'var(--axis)', 'stroke-width': 1 });

  // 2px surface gap between adjacent bars; 4px rounded data-end
  const slot = iw / data.length;
  const bw = Math.max(2, Math.min(38, slot - 2));
  data.forEach((d, i) => {
    const h = max > 0 ? (d.total_tokens / max) * ih : 0;
    const x = ml + i * slot + (slot - bw) / 2;
    const y = mt + ih - h;
    const r = add('rect', {
      x, y: h > 0 ? y : mt + ih - 1, width: bw,
      height: Math.max(h, h > 0 ? 1 : 0), rx: Math.min(4, bw / 2),
      class: 'bar'
    });
    r.addEventListener('mousemove', ev => {
      tip.innerHTML = `<div class="t">${esc(d.name)}</div>` +
        `<div class="r">${fmtTokens(d.total_tokens)} tokens · ${fmtCost(d.cost_usd)}</div>` +
        `<div class="r">${fmtInt(d.events)} event(s)</div>`;
      tip.style.opacity = 1;
      const box = svg.parentElement.getBoundingClientRect();
      let left = ev.clientX - box.left + 12;
      if (left + tip.offsetWidth > box.width) left = box.width - tip.offsetWidth - 4;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, ev.clientY - box.top - 46) + 'px';
    });
    r.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  });

  // selective date labels — never one per bar
  const step = Math.ceil(data.length / 8);
  data.forEach((d, i) => {
    if (i % step && i !== data.length - 1) return;
    add('text', {
      x: ml + i * slot + slot / 2, y: H - 8,
      'text-anchor': 'middle', class: 'tick'
    }, d.name.slice(5));
  });
}

for (const id of ['days','provider','project','model']) $(id).onchange = load;
$('reload').onclick = load;
let qt;
$('q').oninput = () => { clearTimeout(qt); qt = setTimeout(load, 280); };
addEventListener('resize', () => { if (LAST) drawChart(LAST.by_day); });
load();
</script>
</body>
</html>
"""
