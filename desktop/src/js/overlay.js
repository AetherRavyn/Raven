/* ═══════════════════════════════════════════════════════
   AetherRavyn — Overlay HUD Controller
   Polls backend for goals, memory, and system stats
   ═══════════════════════════════════════════════════════ */

const BACKEND = 'http://localhost:8090';
const POLL_INTERVAL = 10000;

const els = {
  status: document.getElementById('hud-status'),
  goal: document.getElementById('hud-goal'),
  progress: document.getElementById('hud-progress'),
  memory: document.getElementById('hud-memory'),
  response: document.getElementById('hud-response'),
  cpu: document.getElementById('hud-cpu'),
  ram: document.getElementById('hud-ram'),
  tools: document.getElementById('hud-tools'),
};

// ── Status Polling ─────────────────────────────────────
async function pollStatus() {
  try {
    const res = await fetch(`${BACKEND}/api/system/status`);
    const data = await res.json();
    if (data.status === 'online') {
      els.status.style.color = '#3fb950';
      els.cpu.textContent = `CPU ${data.system.cpu_percent}%`;
      els.ram.textContent = `RAM ${data.system.memory.used_gb}G`;
      els.tools.textContent = `${data.tools.count} tools`;
    }
  } catch {
    els.status.style.color = '#f85149';
  }
}

// ── Goals Polling ──────────────────────────────────────
async function pollGoals() {
  try {
    const res = await fetch(`${BACKEND}/api/goals`);
    const data = await res.json();
    if (data.goals && data.goals.length > 0) {
      const active = data.goals.find(g => g.status === 'Active') || data.goals[0];
      els.goal.querySelector('.hud-goal-title').textContent = active.title;
      // Estimate progress from subtasks if available
      const progress = active.progress || 0;
      els.progress.style.width = `${progress}%`;
    }
  } catch { /* silent */ }
}

// ── Working Memory Polling ─────────────────────────────
async function pollMemory() {
  try {
    const res = await fetch(`${BACKEND}/api/working-memory`);
    const data = await res.json();
    if (data.items && data.items.length > 0) {
      els.memory.innerHTML = data.items
        .slice(0, 5)
        .map(item => `<li class="hud-memory-item">${escapeHtml(item.content || item)}</li>`)
        .join('');
    }
  } catch { /* silent — endpoint may not exist yet */ }
}

// ── Event Stream ───────────────────────────────────────
function connectEvents() {
  try {
    const ws = new WebSocket(`ws://localhost:8090/ws/events`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.event === 'message' && data.text) {
        els.response.textContent = data.text;
      } else if (data.event === 'goal_created') {
        pollGoals();
      }
    };
    ws.onclose = () => setTimeout(connectEvents, 5000);
  } catch { setTimeout(connectEvents, 5000); }
}

// ── Utils ──────────────────────────────────────────────
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ── Init ───────────────────────────────────────────────
pollStatus();
pollGoals();
pollMemory();
connectEvents();
setInterval(pollStatus, POLL_INTERVAL);
setInterval(pollGoals, POLL_INTERVAL * 3);
setInterval(pollMemory, POLL_INTERVAL * 2);
