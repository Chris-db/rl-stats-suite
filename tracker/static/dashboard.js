"use strict";

const COLORS = {
  blue: "#2f8bff",
  orange: "#ff8b32",
  green: "#34d399",
  red: "#f87171",
  grid: "rgba(255,255,255,0.06)",
  text: "#8a97aa",
};

Chart.defaults.color = COLORS.text;
Chart.defaults.font.family = "Segoe UI, system-ui, sans-serif";
Chart.defaults.borderColor = COLORS.grid;

const charts = {};
const pct = (x) => `${(x * 100).toFixed(0)}%`;
const fmt = (x, d = 1) => Number(x).toFixed(d);

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function shortTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const kid of kids) node.append(kid);
  return node;
}

function renderCards(o) {
  const wr = o.matches ? o.win_rate : 0;
  const cards = [
    { label: "Matches", value: o.matches, cls: "" },
    { label: "Win rate", value: pct(wr), cls: wr >= 0.5 ? "good" : "bad" },
    { label: "Record", value: `${o.wins}-${o.losses}`, cls: "" },
    { label: "Goals", value: o.goals, cls: "accent" },
    { label: "Avg saves", value: fmt(o.avg_saves, 1), cls: "" },
    { label: "Shooting %", value: pct(o.shooting_pct), cls: "" },
  ];
  const wrap = document.getElementById("cards");
  wrap.replaceChildren(
    ...cards.map((c) =>
      el("div", { class: "card" },
        el("div", { class: `value ${c.cls}` }, String(c.value)),
        el("div", { class: "label" }, c.label),
      )
    )
  );
}

function lineChart(id, labels, datasets, opts = {}) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: opts.legend ?? false } },
      scales: {
        y: { beginAtZero: true, ...(opts.y || {}) },
        x: { ticks: { maxTicksLimit: 8 } },
      },
      ...opts.root,
    },
  });
}

function renderWinRate(rows) {
  lineChart(
    "winRateChart",
    rows.map((r) => `#${r.n}`),
    [{
      data: rows.map((r) => +(r.cumulative_win_rate * 100).toFixed(1)),
      borderColor: COLORS.blue,
      backgroundColor: "rgba(47,139,255,0.15)",
      fill: true,
      tension: 0.3,
      pointRadius: rows.length > 30 ? 0 : 3,
    }],
    { y: { max: 100, ticks: { callback: (v) => v + "%" } } }
  );
}

function renderSaves(rows) {
  const avg = rows.length
    ? rows.reduce((s, r) => s + r.saves, 0) / rows.length
    : 0;
  lineChart(
    "savesChart",
    rows.map((r) => `#${r.n}`),
    [
      {
        label: "Saves",
        data: rows.map((r) => r.saves),
        borderColor: COLORS.green,
        backgroundColor: "rgba(52,211,153,0.15)",
        fill: true,
        tension: 0.25,
        pointRadius: rows.length > 30 ? 0 : 3,
      },
      {
        label: "Average",
        data: rows.map(() => +avg.toFixed(2)),
        borderColor: COLORS.orange,
        borderDash: [6, 6],
        pointRadius: 0,
        fill: false,
      },
    ],
    { legend: true }
  );
}

function renderArenas(rows) {
  if (charts.arenaChart) charts.arenaChart.destroy();
  charts.arenaChart = new Chart(document.getElementById("arenaChart"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.arena || "—"),
      datasets: [{
        label: "Win rate",
        data: rows.map((r) => +(r.win_rate * 100).toFixed(1)),
        backgroundColor: rows.map((r) =>
          r.win_rate >= 0.5 ? "rgba(52,211,153,0.7)" : "rgba(248,113,113,0.7)"),
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterLabel: (ctx) => {
              const r = rows[ctx.dataIndex];
              return `${r.matches} matches · ${fmt(r.avg_goals)} g · ${fmt(r.avg_saves)} sv`;
            },
          },
        },
      },
      scales: { x: { max: 100, ticks: { callback: (v) => v + "%" } } },
    },
  });
}

function table(node, headers, rows) {
  node.replaceChildren(
    el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", {}, h)))),
    el("tbody", {}, ...rows.map((cells) =>
      el("tr", {}, ...cells.map((c) =>
        typeof c === "object" && c?.node ? el("td", {}, c.node) : el("td", {}, String(c))
      ))
    ))
  );
}

const winPill = (won) =>
  el("span", { class: `pill ${won ? "win" : "loss"}` }, won ? "W" : "L");

function renderSessions(rows) {
  table(
    document.getElementById("sessionsTable"),
    ["Session", "Matches", "W-L", "Win %", "Goals", "Saves"],
    rows.map((s) => [
      shortTime(s.start),
      s.matches,
      `${s.wins}-${s.losses}`,
      pct(s.win_rate),
      s.goals,
      s.saves,
    ])
  );
}

function renderRecent(rows) {
  table(
    document.getElementById("recentTable"),
    ["When", "Result", "Score", "Arena", "Playlist", "G", "A", "Sv", "Sh", "Demos"],
    rows.map((m) => [
      shortTime(m.played_at),
      { node: winPill(m.won) },
      `${m.team_score}-${m.opponent_score}`,
      m.arena || "—",
      m.playlist || "—",
      m.goals, m.assists, m.saves, m.shots, m.demos,
    ])
  );
}

async function load() {
  try {
    const overview = await getJSON("/api/overview");
    const isEmpty = !overview.matches;
    document.getElementById("empty").classList.toggle("hidden", !isEmpty);
    document.querySelectorAll("main > section").forEach((s) =>
      s.classList.toggle("hidden", isEmpty));
    if (isEmpty) return;

    renderCards(overview);
    const [winRate, saves, arenas, sessions, recent] = await Promise.all([
      getJSON("/api/win-rate"),
      getJSON("/api/saves-trend"),
      getJSON("/api/arenas"),
      getJSON("/api/sessions"),
      getJSON("/api/recent"),
    ]);
    renderWinRate(winRate);
    renderSaves(saves);
    renderArenas(arenas);
    renderSessions(sessions);
    renderRecent(recent);
  } catch (err) {
    console.error(err);
  }
}

document.getElementById("refresh").addEventListener("click", load);
load();
