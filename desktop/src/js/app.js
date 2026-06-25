/* ═══════════════════════════════════════════════════════
   AetherRavyn Desktop — Main Application
   ═══════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────
const state = {
  ws: null,
  wsEvents: null,
  connected: false,
  messages: [],
  typing: false,
  agentMode: false,
  webSearch: false,
  backendUrl: 'http://localhost:8090',
  wsUrl: 'ws://localhost:8090',
  userId: 'desktop_user',
};

// ── DOM References ─────────────────────────────────────
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const els = {
  msgInput: $('#message-input'),
  sendBtn: $('#btn-send'),
  chatMessages: $('#chat-messages'),
  welcomeScreen: $('#welcome-screen'),
  statusDot: $('#status-dot'),
  statusText: $('#status-text'),
  statusUptime: $('#status-uptime'),
  statusCpu: $('#status-cpu'),
  statusMem: $('#status-mem'),
  statusTools: $('#status-tools'),
  modelName: $('#model-name'),
  toasts: $('#toast-container'),
  sessionList: $('#session-list'),
};

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTitlebar();
  setupInput();
  setupRailNav();
  setupWelcomeCards();
  connectWebSocket();
  connectEventStream();
  pollStatus();
  setInterval(pollStatus, 15000);

  // Wire new dashboard features
  $('#btn-create-goal')?.addEventListener('click', createGoal);
  $('#btn-clear-canvas')?.addEventListener('click', clearCanvas);
  $('#btn-trigger-capture')?.addEventListener('click', triggerScreenCapture);
  $('#btn-save-settings')?.addEventListener('click', saveSettings);

  // Tool search filter
  $('#tool-search')?.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    const filtered = allTools.filter(t => t.toLowerCase().includes(term));
    renderToolsList(filtered);
  });

  // Memory search trigger on enter
  $('#memory-search-input')?.addEventListener('keyup', (e) => {
    if (e.key === 'Enter') loadMemory();
  });
});

// ── Titlebar Controls ──────────────────────────────────
function setupTitlebar() {
  const { appWindow } = window.__TAURI__?.window || {};
  $('#btn-minimize')?.addEventListener('click', () => {
    if (appWindow) appWindow.minimize();
  });
  $('#btn-maximize')?.addEventListener('click', async () => {
    if (!appWindow) return;
    const maximized = await appWindow.isMaximized();
    maximized ? appWindow.unmaximize() : appWindow.maximize();
  });
  $('#btn-close')?.addEventListener('click', () => {
    if (appWindow) appWindow.close();
  });
}

// ── Rail Navigation ────────────────────────────────────
function setupRailNav() {
  $$('.rail-btn[data-panel]').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.rail-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const panel = btn.dataset.panel;
      $('#titlebar-title').textContent = btn.title || 'Chat';

      // Hide all panels
      $$('.panel-view').forEach(p => p.classList.add('hidden'));
      // Show the selected panel
      $(`#panel-${panel}`)?.classList.remove('hidden');

      // Only chat panel shows sidebar
      if (panel === 'chat') {
        $('#sidebar').classList.remove('collapsed');
      } else {
        $('#sidebar').classList.add('collapsed');
      }

      // Load data for active panel
      if (panel === 'goals') loadGoals();
      else if (panel === 'agents') loadAgents();
      else if (panel === 'tools') loadTools();
      else if (panel === 'memory') loadMemory();
      else if (panel === 'canvas') loadCanvas();
      else if (panel === 'screen') loadScreen();
      else if (panel === 'settings') loadSettings();
    });
  });
}

// ── Input Handling ─────────────────────────────────────
function setupInput() {
  const input = els.msgInput;
  const sendBtn = els.sendBtn;

  // Auto-resize textarea
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 150) + 'px';
    sendBtn.disabled = !input.value.trim();
  });

  // Send on Enter (Shift+Enter for newline)
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (input.value.trim()) sendMessage();
    }
  });

  sendBtn.addEventListener('click', () => {
    if (input.value.trim()) sendMessage();
  });

  // Agent mode toggle
  $('#btn-agent-mode')?.addEventListener('click', function() {
    state.agentMode = !state.agentMode;
    this.classList.toggle('active', state.agentMode);
  });

  // Web search toggle
  $('#btn-web-search')?.addEventListener('click', function() {
    state.webSearch = !state.webSearch;
    this.classList.toggle('active', state.webSearch);
  });
}

// ── Welcome Cards ──────────────────────────────────────
function setupWelcomeCards() {
  $$('.welcome-card').forEach(card => {
    card.addEventListener('click', () => {
      const prompt = card.dataset.prompt;
      if (prompt) {
        els.msgInput.value = prompt;
        els.sendBtn.disabled = false;
        sendMessage();
      }
    });
  });
}

// ── WebSocket Connection ───────────────────────────────
function connectWebSocket() {
  try {
    state.ws = new WebSocket(`${state.wsUrl}/chat/${state.userId}`);

    state.ws.onopen = () => {
      state.connected = true;
      updateStatus(true);
      showToast('Connected to AetherRavyn', 'success');
    };

    state.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      handleWSMessage(data);
    };

    state.ws.onclose = () => {
      state.connected = false;
      updateStatus(false);
      setTimeout(connectWebSocket, 3000);
    };

    state.ws.onerror = () => {
      state.connected = false;
      updateStatus(false);
    };
  } catch {
    updateStatus(false);
    setTimeout(connectWebSocket, 5000);
  }
}

function connectEventStream() {
  try {
    state.wsEvents = new WebSocket(`${state.wsUrl}/ws/events`);
    state.wsEvents.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.event === 'goal_created') {
        showToast(`Goal created: ${data.title}`, 'info');
      }
    };
    state.wsEvents.onclose = () => setTimeout(connectEventStream, 5000);
  } catch { /* retry silently */ }
}

function handleWSMessage(data) {
  if (data.type === 'thinking') {
    showTypingIndicator();
  } else if (data.type === 'chunk') {
    hideTypingIndicator();
    appendOrUpdateAIMessage(data.text);
  } else if (data.type === 'done') {
    hideTypingIndicator();
    finalizeAIMessage();
  } else if (data.type === 'error') {
    hideTypingIndicator();
    appendSystemMessage(`Error: ${data.message}`, 'error');
  }
}

// ── Send Message ───────────────────────────────────────
function sendMessage() {
  const text = els.msgInput.value.trim();
  if (!text) return;

  // Switch from welcome to chat
  els.welcomeScreen.classList.add('hidden');
  els.chatMessages.classList.remove('hidden');

  // Add user message
  appendUserMessage(text);

  // Send via WebSocket
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ text }));
  } else {
    // Fallback to REST
    sendREST(text);
  }

  // Clear input
  els.msgInput.value = '';
  els.msgInput.style.height = 'auto';
  els.sendBtn.disabled = true;
}

async function sendREST(text) {
  showTypingIndicator();
  try {
    const res = await fetch(`${state.backendUrl}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: state.userId, text, platform: 'desktop' }),
    });
    const data = await res.json();
    hideTypingIndicator();
    if (data.reply) appendAIMessage(data.reply);
  } catch (err) {
    hideTypingIndicator();
    appendSystemMessage('Failed to reach backend. Is ravyn daemon running?', 'error');
  }
}

// ── Message Rendering ──────────────────────────────────
function appendUserMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-user';
  div.innerHTML = `
    <div class="msg-avatar">U</div>
    <div class="msg-body">${escapeHtml(text)}</div>
  `;
  els.chatMessages.appendChild(div);
  scrollToBottom();
}

function appendAIMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg msg-ai';
  div.innerHTML = `
    <div class="msg-avatar">🦅</div>
    <div class="msg-body">${renderMarkdown(text)}</div>
  `;
  els.chatMessages.appendChild(div);
  scrollToBottom();
}

let currentAIMsg = null;
let currentAIText = '';

function appendOrUpdateAIMessage(text) {
  currentAIText = text;
  if (!currentAIMsg) {
    currentAIMsg = document.createElement('div');
    currentAIMsg.className = 'msg msg-ai';
    currentAIMsg.innerHTML = `
      <div class="msg-avatar">🦅</div>
      <div class="msg-body"></div>
    `;
    els.chatMessages.appendChild(currentAIMsg);
  }
  currentAIMsg.querySelector('.msg-body').innerHTML = renderMarkdown(currentAIText);
  scrollToBottom();
}

function finalizeAIMessage() {
  if (currentAIMsg) {
    currentAIMsg.querySelector('.msg-body').innerHTML = renderMarkdown(currentAIText);
  }
  currentAIMsg = null;
  currentAIText = '';
}

function appendSystemMessage(text, type = 'info') {
  const div = document.createElement('div');
  div.className = 'msg msg-ai';
  div.innerHTML = `
    <div class="msg-avatar" style="background:${type === 'error' ? 'rgba(248,81,73,0.15)' : 'rgba(88,166,255,0.15)'}; color:${type === 'error' ? 'var(--error)' : 'var(--info)'}">!</div>
    <div class="msg-body" style="border-color:${type === 'error' ? 'var(--error)' : 'var(--info)'}">${escapeHtml(text)}</div>
  `;
  els.chatMessages.appendChild(div);
  scrollToBottom();
}

// ── Typing Indicator ───────────────────────────────────
function showTypingIndicator() {
  if (state.typing) return;
  state.typing = true;
  const div = document.createElement('div');
  div.className = 'msg msg-ai';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <div class="msg-avatar">🦅</div>
    <div class="typing-indicator">
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    </div>
  `;
  els.chatMessages.appendChild(div);
  scrollToBottom();
}

function hideTypingIndicator() {
  state.typing = false;
  const el = $('#typing-indicator');
  if (el) el.remove();
}

// ── Status Polling ─────────────────────────────────────
async function pollStatus() {
  try {
    const res = await fetch(`${state.backendUrl}/api/system/status`);
    const data = await res.json();
    if (data.status === 'online') {
      updateStatus(true);
      els.statusUptime.textContent = `⏱ ${data.uptime_human}`;
      els.statusCpu.textContent = `CPU ${data.system.cpu_percent}%`;
      els.statusMem.textContent = `RAM ${data.system.memory.used_gb}/${data.system.memory.total_gb}G`;
      els.statusTools.textContent = `${data.tools.count} tools`;
    }
  } catch {
    // Backend not reachable — don't flip status if WS is alive
    if (!state.connected) updateStatus(false);
  }
}

function updateStatus(online) {
  els.statusDot.className = `status-dot ${online ? 'online' : 'offline'}`;
  els.statusText.textContent = online ? 'Connected' : 'Disconnected';
}

// ── Utils ──────────────────────────────────────────────
function scrollToBottom() {
  const el = els.chatMessages;
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderMarkdown(text) {
  if (!text) return '';
  return text
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    // Headers
    .replace(/^### (.*$)/gm, '<h3>$1</h3>')
    .replace(/^## (.*$)/gm, '<h2>$1</h2>')
    .replace(/^# (.*$)/gm, '<h1>$1</h1>')
    // Lists
    .replace(/^\- (.*$)/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    // Blockquotes
    .replace(/^> (.*$)/gm, '<blockquote>$1</blockquote>')
    // Line breaks
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>');
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.style.borderLeftColor = type === 'error' ? 'var(--error)' :
                                 type === 'success' ? 'var(--success)' :
                                 'var(--info)';
  toast.textContent = message;
  els.toasts.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(30px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── Dashboard Loader Functions ─────────────────────────

// 1. GOALS PANEL
async function loadGoals() {
  try {
    const res = await fetch(`${state.backendUrl}/api/goals`);
    const data = await res.json();
    const count = data.count || 0;
    $('#goals-total-count').textContent = count;
    $('#goals-active-badge').textContent = count;

    const list = $('#goals-list-container');
    if (data.goals && data.goals.length > 0) {
      list.innerHTML = data.goals.map(g => {
        const st = (g.status || 'Active').toLowerCase();
        const tc = st === 'active' ? 'tag-green' : st === 'blocked' ? 'tag-red' : 'tag-blue';
        const steps = g.plan?.steps || [];
        const done = steps.filter(s => s.status === 'Completed').length;
        const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;
        return `
          <div class="li" style="flex-wrap: wrap;">
            <div class="li-body" style="width: 100%;">
              <div class="li-title">${escapeHtml(g.title || g.description || 'Untitled')}</div>
              <div class="li-sub" style="display: flex; gap: 6px; margin-top: 4px;">
                <span class="tag ${tc}">${escapeHtml(g.status || 'Active')}</span>
                ${steps.length ? `<span class="tag tag-blue">${done}/${steps.length} Steps</span>` : ''}
              </div>
            </div>
            ${steps.length ? `
              <div class="progress" style="width: 100%;">
                <div class="progress-fill" style="width: ${pct}%; background: ${st === 'blocked' ? 'var(--error)' : 'var(--success)'};"></div>
              </div>
            ` : ''}
          </div>
        `;
      }).join('');
    } else {
      list.innerHTML = '<div class="card-empty">No active goals found</div>';
    }
  } catch (err) {
    $('#goals-list-container').innerHTML = '<div class="card-empty">Failed to load goals from backend</div>';
  }
}

async function createGoal() {
  const title = $('#goal-input-title').value.trim();
  const desc = $('#goal-input-desc').value.trim();
  if (!title || !desc) {
    showToast('Please provide both a title and description', 'error');
    return;
  }

  $('#btn-create-goal').disabled = true;
  $('#btn-create-goal').textContent = 'Decomposing Goal...';

  try {
    const res = await fetch(`${state.backendUrl}/api/goals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description: desc }),
    });
    const data = await res.json();
    if (data.success || data.goal_id) {
      showToast('Goal initialized successfully!', 'success');
      $('#goal-input-title').value = '';
      $('#goal-input-desc').value = '';
      loadGoals();
    } else {
      showToast('Failed to initialize goal: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    showToast('Network error initializing goal', 'error');
  } finally {
    $('#btn-create-goal').disabled = false;
    $('#btn-create-goal').textContent = 'Initialize Autonomous Goal';
  }
}

// 2. AGENTS PANEL
async function loadAgents() {
  try {
    const res = await fetch(`${state.backendUrl}/api/agents`);
    const data = await res.json();
    $('#agents-count-badge').textContent = data.count || 0;

    const list = $('#agents-list-container');
    if (data.agents && data.agents.length > 0) {
      const icons = ['🧠','🔬','💰','🛡️','👨‍💻','📊','🌐','🎯','📈','🔍','🤝','📝','🎨','⚡'];
      list.innerHTML = data.agents.map((a, i) => `
        <div class="li">
          <div class="li-icon" style="background: var(--accent-soft); color: var(--accent);">${icons[i % icons.length]}</div>
          <div class="li-body">
            <div class="li-title">${escapeHtml(a.name)}</div>
            <div class="li-sub">${escapeHtml(a.soul || 'No description available')}</div>
          </div>
          <span class="tag tag-green">active</span>
        </div>
      `).join('');
    } else {
      list.innerHTML = '<div class="card-empty">No agents registered</div>';
    }
  } catch (err) {
    $('#agents-list-container').innerHTML = '<div class="card-empty">Failed to load agent swarm details</div>';
  }
}

// 3. TOOLS PANEL
let allTools = [];
async function loadTools() {
  try {
    const res = await fetch(`${state.backendUrl}/api/system/status`);
    const data = await res.json();
    allTools = data.tools?.names || [];
    $('#tools-count-badge').textContent = allTools.length;
    renderToolsList(allTools);
  } catch (err) {
    $('#tools-list-container').innerHTML = '<div class="card-empty">Failed to load system tools</div>';
  }
}

function renderToolsList(tools) {
  const list = $('#tools-list-container');
  if (tools.length > 0) {
    list.innerHTML = tools.map(t => `
      <div class="li">
        <div class="li-icon" style="background: var(--accent-soft); color: var(--accent);">🔧</div>
        <div class="li-body">
          <div class="li-title">${escapeHtml(t)}</div>
          <div class="li-sub">Tool registered in AgentRuntime</div>
        </div>
        <span class="tag tag-blue">active</span>
      </div>
    `).join('');
  } else {
    list.innerHTML = '<div class="card-empty">No tools match filter</div>';
  }
}

// 4. MEMORY PANEL
async function loadMemory() {
  const query = $('#memory-search-input').value.trim();
  const list = $('#memory-list-container');
  if (!query) {
    list.innerHTML = '<div class="card-empty">Type a query above to search semantic memories</div>';
    $('#memory-count-badge').textContent = '0';
    return;
  }

  try {
    const res = await fetch(`${state.backendUrl}/api/memory/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    const results = data.results || [];
    $('#memory-count-badge').textContent = results.length;

    if (results.length > 0) {
      list.innerHTML = results.map(r => `
        <div class="li">
          <div class="li-icon" style="background: rgba(167,139,250,0.15); color: #a78bfa;">🧠</div>
          <div class="li-body">
            <div class="li-title" style="white-space: normal;">${escapeHtml(r.text || r.content || r)}</div>
            ${r.metadata ? `<div class="li-sub">Score: ${r.score || 'N/A'} · Source: ${r.metadata.source || 'memory'}</div>` : ''}
          </div>
        </div>
      `).join('');
    } else {
      list.innerHTML = '<div class="card-empty">No matching memories found</div>';
    }
  } catch (err) {
    list.innerHTML = '<div class="card-empty">Failed to query memory store</div>';
  }
}

// 5. CANVAS PANEL
async function loadCanvas() {
  try {
    const res = await fetch(`${state.backendUrl}/api/canvas/state?canvas_id=main`);
    const data = await res.json();
    const container = $('#canvas-render-container');
    const components = data.components || [];

    if (components.length > 0) {
      container.innerHTML = components.map(c => `
        <div style="background:var(--bg-secondary); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; margin-bottom:12px;">
          <div style="font-weight:600; color:var(--accent); font-size:12px; margin-bottom:6px;">[Component ID: ${escapeHtml(c.id)}] Type: ${escapeHtml(c.type)}</div>
          <div style="font-size:13px; color:var(--fg);">${c.content ? escapeHtml(JSON.stringify(c.content)) : escapeHtml(c.data || '')}</div>
        </div>
      `).join('');
    } else {
      container.innerHTML = '<div class="card-empty">No visual components rendered yet</div>';
    }
  } catch (err) {
    $('#canvas-render-container').innerHTML = '<div class="card-empty">Failed to load canvas state</div>';
  }
}

async function clearCanvas() {
  try {
    await fetch(`${state.backendUrl}/api/canvas/clear?canvas_id=main`, { method: 'POST' });
    showToast('Live Canvas cleared', 'info');
    loadCanvas();
  } catch (err) {
    showToast('Failed to clear canvas', 'error');
  }
}

// 6. SCREEN AWARENESS PANEL
async function loadScreen() {
  // Screen panel initially idle
}

async function triggerScreenCapture() {
  const statusEl = $('#screen-capture-status');
  const ocrEl = $('#screen-ocr-text');

  statusEl.textContent = 'Triggering Desktop Screenshot capture...';
  ocrEl.innerHTML = '<div class="card-empty">Waiting for OCR analysis...</div>';

  try {
    let captured = false;
    if (window.__TAURI__?.core?.invoke) {
      const res = await window.__TAURI__.core.invoke('capture_screen');
      captured = res.includes('captured');
    } else if (window.__TAURI__?.invoke) {
      const res = await window.__TAURI__.invoke('capture_screen');
      captured = res.includes('captured');
    } else {
      statusEl.textContent = 'No Tauri host context found. Simulating backend capture.';
      captured = true;
    }

    if (captured) {
      statusEl.textContent = 'Captured. Fetching backend screen awareness analysis...';
      const res = await fetch(`${state.backendUrl}/api/screen/awareness`);
      const data = await res.json();
      
      if (data.success) {
        statusEl.textContent = `Captured successfully at ${new Date().toLocaleTimeString()}`;
        ocrEl.textContent = data.text || 'No text recognized on screen.';
      } else {
        statusEl.textContent = 'Capture succeeded, but backend analysis failed.';
        ocrEl.textContent = `Backend error: ${data.error || 'Unknown error'}`;
      }
    } else {
      statusEl.textContent = 'Screenshot capture command failed.';
    }
  } catch (err) {
    statusEl.textContent = 'Capture failed. Make sure desktop dependencies (scrot, tesseract) exist.';
    ocrEl.textContent = `Error details: ${err.message || err}`;
  }
}

// 7. SETTINGS PANEL
async function loadSettings() {
  try {
    const res = await fetch(`${state.backendUrl}/api/settings/env`);
    const data = await res.json();
    if (data.success && data.settings) {
      const s = data.settings;
      $('#settings-sel-provider').value = s.LLM_PROVIDER || 'nvidia';
      $('#settings-input-model').value = s.LLM_MODEL || '';
      $('#settings-key-gemini').value = s.GEMINI_API_KEY || '';
      $('#settings-key-openai').value = s.OPENAI_API_KEY || '';
      $('#settings-key-groq').value = s.GROQ_API_KEY || '';
      $('#settings-key-xai').value = s.XAI_API_KEY || '';
      $('#settings-tg-token').value = s.TELEGRAM_BOT_TOKEN || '';
      $('#settings-dc-token').value = s.DISCORD_BOT_TOKEN || '';

      $('#settings-check-pairing').checked = s.DM_PAIRING_ENABLED === 'true' || s.DM_PAIRING_ENABLED === true;
      $('#settings-check-shell').checked = s.ALLOW_HOST_SHELL_EXECUTION === 'true' || s.ALLOW_HOST_SHELL_EXECUTION === true;

      $('#settings-check-voice').checked = s.ENABLE_LOCAL_VOICE === 'true' || s.ENABLE_LOCAL_VOICE === true;
      $('#settings-voice-stt').value = s.VOICE_STT_MODEL || 'tiny';
      $('#settings-voice-tts').value = s.VOICE_TTS_VOICE || 'en-US-AriaNeural';
    }

    const skRes = await fetch(`${state.backendUrl}/api/skills/list`);
    const skData = await skRes.json();
    $('#settings-skills-badge').textContent = skData.count || 0;
    const skillsContainer = $('#settings-skills-container');
    if (skData.skills && skData.skills.length > 0) {
      skillsContainer.innerHTML = skData.skills.map(sk => `
        <div class="li">
          <div class="li-icon" style="background: var(--amber-dim); color: var(--warning);">⚒️</div>
          <div class="li-body">
            <div class="li-title">${escapeHtml(sk.name)}</div>
            <div class="li-sub">${escapeHtml((sk.description || '').slice(0, 50))}...</div>
          </div>
          <span class="tag ${sk.enabled_by_default ? 'tag-green' : 'tag-red'}">${sk.enabled_by_default ? 'Active' : 'Inactive'}</span>
        </div>
      `).join('');
    } else {
      skillsContainer.innerHTML = '<div class="card-empty">No skills active.</div>';
    }

    const statusRes = await fetch(`${state.backendUrl}/api/system/status`);
    const statusData = await statusRes.json();
    const channelsContainer = $('#settings-channels-container');
    const platforms = statusData.platforms || [];
    if (platforms.length > 0) {
      channelsContainer.innerHTML = platforms.map(p => `
        <div class="li">
          <div class="li-icon" style="background: var(--emerald-dim); color: var(--success);">✅</div>
          <div class="li-body">
            <div class="li-title">${escapeHtml(p)}</div>
            <div class="li-sub">Connected & Active</div>
          </div>
        </div>
      `).join('');
    } else {
      channelsContainer.innerHTML = '<div class="card-empty">No platforms active.</div>';
    }

    // Load pending pairing requests
    try {
      await loadPendingPairings();
    } catch (e) {}

  } catch (err) {
    showToast('Failed to load configuration settings from backend', 'error');
  }
}

async function saveSettings() {
  const updates = {
    LLM_PROVIDER: $('#settings-sel-provider').value,
    LLM_MODEL: $('#settings-input-model').value.trim(),
    GEMINI_API_KEY: $('#settings-key-gemini').value.trim(),
    OPENAI_API_KEY: $('#settings-key-openai').value.trim(),
    GROQ_API_KEY: $('#settings-key-groq').value.trim(),
    XAI_API_KEY: $('#settings-key-xai').value.trim(),
    TELEGRAM_BOT_TOKEN: $('#settings-tg-token').value.trim(),
    DISCORD_BOT_TOKEN: $('#settings-dc-token').value.trim(),
    DM_PAIRING_ENABLED: $('#settings-check-pairing').checked,
    ALLOW_HOST_SHELL_EXECUTION: $('#settings-check-shell').checked,
    ENABLE_LOCAL_VOICE: $('#settings-check-voice').checked,
    VOICE_STT_MODEL: $('#settings-voice-stt').value.trim(),
    VOICE_TTS_VOICE: $('#settings-voice-tts').value.trim(),
  };

  try {
    const res = await fetch(`${state.backendUrl}/api/settings/env`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: updates }),
    });
    const data = await res.json();
    if (data.success) {
      showToast('Settings saved and written to .env successfully!', 'success');
      loadSettings();
    } else {
      showToast('Failed to save settings: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    showToast('Network error saving settings', 'error');
  }
}

async function loadPendingPairings() {
  try {
    const res = await fetch(`${state.backendUrl}/api/settings/pairing/pending`);
    const data = await res.json();
    const container = $('#settings-pairing-requests-container');
    if (data.success && data.pending) {
      if (data.pending.length === 0) {
        container.innerHTML = '<div class="card-empty">No pending pairing requests.</div>';
      } else {
        container.innerHTML = data.pending.map(p => `
          <div class="li" style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding:8px 0; gap:12px;">
            <div class="li-body" style="flex:1;">
              <div class="li-title" style="font-weight:600;">Code: <span style="color:var(--accent); font-family:monospace; font-size:16px;">${p.code}</span></div>
              <div class="li-sub" style="font-size:11px; color:var(--text-3); margin-top:2px;">User: ${escapeHtml(p.user_id)} · Platform: ${escapeHtml(p.platform)}</div>
            </div>
            <button class="settings-btn" onclick="window.approvePairingCode('${p.code}')" style="padding:4px 8px; font-size:11px; margin-top:0; width:auto;">Approve</button>
          </div>
        `).join('');
      }
    }
  } catch (err) {
    console.error('Error loading pending pairings:', err);
  }
}

async function approvePairingCode(code) {
  try {
    const res = await fetch(`${state.backendUrl}/api/settings/pairing/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code }),
    });
    const data = await res.json();
    if (data.success) {
      showToast('Pairing request approved successfully!', 'success');
      loadPendingPairings();
    } else {
      showToast('Failed to approve pairing: ' + (data.error || 'Unknown'), 'error');
    }
  } catch (err) {
    showToast('Network error approving pairing request', 'error');
  }
}

window.approvePairingCode = approvePairingCode;
