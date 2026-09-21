"use strict";

// ---------------------------------------------------------------------------
// Config: where to connect, and optional overrides via query string.
//   ?ws=ws://host:port   force a push-socket URL (else read /config.json)
//   ?demo=1              fire sample alerts on a loop (no server needed)
//   ?hud=0              hide the connection indicator (use this in OBS)
// ---------------------------------------------------------------------------
const params = new URLSearchParams(location.search);
const DEMO = params.get("demo") === "1";
const stack = document.getElementById("stack");
const hud = document.getElementById("hud");
const dot = document.getElementById("dot");
const statusEl = document.getElementById("status");

if (params.get("hud") === "0") hud.classList.add("hidden");

// ---------------------------------------------------------------------------
// Audio: synthesize built-in sounds so no audio files are required. A custom
// "sound" value containing "/" or "." is treated as an audio file URL instead.
// ---------------------------------------------------------------------------
let audioCtx = null;
function ac() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function tone(freq, start, dur, type = "sine", gain = 0.25) {
  const ctx = ac();
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
  g.gain.setValueAtTime(0.0001, ctx.currentTime + start);
  g.gain.exponentialRampToValueAtTime(gain, ctx.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + start);
  osc.stop(ctx.currentTime + start + dur + 0.02);
}

function noiseSweep(start, dur) {
  const ctx = ac();
  const buffer = ctx.createBuffer(1, ctx.sampleRate * dur, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  const filter = ctx.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.setValueAtTime(400, ctx.currentTime + start);
  filter.frequency.exponentialRampToValueAtTime(4000, ctx.currentTime + start + dur);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.18, ctx.currentTime + start);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  src.connect(filter).connect(g).connect(ctx.destination);
  src.start(ctx.currentTime + start);
  src.stop(ctx.currentTime + start + dur);
}

const SOUNDS = {
  chime:   () => { tone(659.25, 0, 0.18, "sine"); tone(987.77, 0.12, 0.3, "sine"); },
  ding:    () => tone(1318.5, 0, 0.35, "sine", 0.3),
  airhorn: () => { tone(220, 0, 0.5, "sawtooth", 0.22); tone(277, 0.05, 0.5, "sawtooth", 0.18); },
  pop:     () => tone(880, 0, 0.08, "square", 0.25),
  buzz:    () => { tone(120, 0, 0.3, "sawtooth", 0.25); tone(90, 0.05, 0.3, "square", 0.2); },
  coin:    () => { tone(987.77, 0, 0.08, "square", 0.2); tone(1318.5, 0.08, 0.25, "square", 0.2); },
  whoosh:  () => noiseSweep(0, 0.4),
  sad:     () => { tone(392, 0, 0.25, "sine", 0.22); tone(311, 0.2, 0.4, "sine", 0.22); },
};

function playSound(name) {
  if (!name) return;
  try {
    if (/[\/.]/.test(name)) {
      new Audio(name).play().catch(() => {});
    } else if (SOUNDS[name]) {
      SOUNDS[name]();
    }
  } catch (_) { /* audio not allowed yet */ }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function showAlert(alert) {
  const accent = alert.color || "#2f8bff";
  const anim = alert.animation || "pop";
  const duration = Math.max(800, alert.duration_ms || 4000);

  const card = document.createElement("div");
  card.className = `alert enter-${anim}`;
  card.style.setProperty("--accent", accent);
  card.innerHTML = `
    <div class="icon">${alert.icon || "🔔"}</div>
    <div class="body">
      <div class="title">${escapeHtml(alert.title || "")}</div>
      ${alert.subtitle ? `<div class="subtitle">${escapeHtml(alert.subtitle)}</div>` : ""}
    </div>`;
  stack.prepend(card);

  if (anim === "flash") {
    const burst = document.createElement("div");
    burst.className = "flash-burst";
    burst.style.setProperty("--accent", accent);
    document.body.appendChild(burst);
    setTimeout(() => burst.remove(), 800);
  }

  playSound(alert.sound);

  setTimeout(() => {
    card.classList.add("leave");
    setTimeout(() => card.remove(), 400);
  }, duration);

  // keep the stack from growing without bound
  while (stack.children.length > 5) stack.lastChild.remove();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function setStatus(online, text) {
  dot.className = "dot " + (online ? "online" : "offline");
  statusEl.textContent = text;
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------
async function resolveWsUrl() {
  const override = params.get("ws");
  if (override) return override;
  try {
    const res = await fetch("/config.json", { cache: "no-store" });
    if (res.ok) return (await res.json()).ws_url;
  } catch (_) { /* opened as a file, or server not up */ }
  return "ws://127.0.0.1:8765";
}

function connect(url) {
  setStatus(false, "connecting…");
  let ws;
  try {
    ws = new WebSocket(url);
  } catch (_) {
    return setTimeout(() => connect(url), 2000);
  }
  ws.onopen = () => { setStatus(true, "live"); ws.send("ping"); };
  ws.onmessage = (e) => {
    try { showAlert(JSON.parse(e.data)); } catch (_) {}
  };
  ws.onclose = () => { setStatus(false, "reconnecting…"); setTimeout(() => connect(url), 2000); };
  ws.onerror = () => ws.close();
}

// ---------------------------------------------------------------------------
// Demo mode — preview the look without a running server.
// ---------------------------------------------------------------------------
const DEMO_ALERTS = [
  { title: "GOAL!", subtitle: "You — 92.4 kph", icon: "🥅", color: "#2f8bff", animation: "pop", sound: "chime", duration_ms: 4000 },
  { title: "EPIC SAVE!", subtitle: "Highlight reel material", icon: "🛡️", color: "#a855f7", animation: "flash", sound: "coin", duration_ms: 4000 },
  { title: "DEMOLISHED", subtitle: "Sent Octane to the shadow realm", icon: "💥", color: "#ff8b32", animation: "pop", sound: "whoosh", duration_ms: 4000 },
  { title: "SUPERSONIC", subtitle: "Maximum velocity", icon: "⚡", color: "#fbbf24", animation: "slide", sound: "whoosh", duration_ms: 3500 },
  { title: "ASSIST", subtitle: "Set up Nitro", icon: "🤝", color: "#34d399", animation: "slide", sound: "ding", duration_ms: 3500 },
];

function runDemo() {
  setStatus(true, "demo mode");
  let i = 0;
  const fire = () => { showAlert(DEMO_ALERTS[i % DEMO_ALERTS.length]); i++; };
  fire();
  setInterval(fire, 2600);
}

// Resume audio on first interaction (browsers gate autoplay).
window.addEventListener("pointerdown", () => ac(), { once: true });
window.addEventListener("keydown", () => ac(), { once: true });

if (DEMO) {
  runDemo();
} else {
  resolveWsUrl().then(connect);
}
