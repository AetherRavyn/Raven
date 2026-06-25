// ═══════════════════════════════════════════════════
// RAVEN Dashboard — Client-side Application Logic
// ═══════════════════════════════════════════════════

// ─── Page Navigation ─────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('.nav-btn').forEach((b, i) => {
    const pages = ['live', 'cameras', 'esps', 'analytics', 'identities'];
    b.classList.toggle('active', pages[i] === name);
  });
  if (name === 'cameras') refreshCameras();
  if (name === 'esps') refreshEsps();
}

function switchSidebar(name) {
  document.querySelectorAll('.sidebar-tab').forEach((t, i) => {
    t.classList.toggle('active', ['events', 'visitors'][i] === name);
  });
  document.querySelectorAll('.sidebar-content').forEach(c => c.classList.remove('active'));
  document.getElementById('sb-' + name).classList.add('active');
  if (name === 'visitors') loadVisitors();
}

// ─── Clock ───────────────────────────────────────
setInterval(() => {
  document.getElementById('clock').textContent = new Date().toLocaleString();
}, 1000);

// ═══════════════════════════════════════════════════
// CAMERA GRID
// ═══════════════════════════════════════════════════
let currentGrid = 1;

function setGrid(n, el) {
  currentGrid = n;
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
  buildCamGrid();
}

async function buildCamGrid() {
  const r = await fetch('/api/cameras');
  const data = await r.json();
  const grid = document.getElementById('cam-grid');
  grid.className = 'cam-grid grid-' + currentGrid;
  grid.innerHTML = '';

  const cams = data.cameras.slice(0, currentGrid);
  if (cams.length === 0) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#128247;</div><div>No cameras configured</div><div style="font-size:.75rem">Go to <b>Cameras</b> page to add your first camera stream</div></div>';
    return;
  }
  cams.forEach(c => {
    const tile = document.createElement('div');
    tile.className = 'cam-tile';
    tile.innerHTML = '<img src="/video/' + c.id + '" alt="' + c.id + '"><div class="cam-label">' + c.id + ' &mdash; ' + (c.location || 'unknown') + '</div>';
    tile.onclick = () => { currentGrid = 1; buildSingleCamGrid(c.id); };
    grid.appendChild(tile);
  });
}

function buildSingleCamGrid(camId) {
  const grid = document.getElementById('cam-grid');
  grid.className = 'cam-grid grid-1';
  grid.innerHTML = '<div class="cam-tile"><img src="/video/' + camId + '" alt="' + camId + '"><div class="cam-label">' + camId + '</div></div>';
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.view-btn')[0].classList.add('active');
}

// Initial camera grid load + auto-refresh every 5s
setTimeout(buildCamGrid, 500);
setInterval(buildCamGrid, 5000);

// ═══════════════════════════════════════════════════
// CAMERA MANAGEMENT
// ═══════════════════════════════════════════════════
async function refreshCameras() {
  const r = await fetch('/api/cameras');
  const data = await r.json();
  const list = document.getElementById('camera-list');
  list.innerHTML = '';
  data.cameras.forEach(c => {
    const row = document.createElement('div');
    row.className = 'item-row';
    row.innerHTML = `
      <span class="name">${c.id}</span>
      <span class="detail">${c.url} &bull; ${c.location}</span>
      <span class="tag tag-green">LIVE</span>
      <button class="btn btn-danger btn-sm" onclick="removeCamera('${c.id}')">Remove</button>`;
    list.appendChild(row);
  });
  if (data.cameras.length === 0) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:.8rem;">No cameras registered</div>';
  }
}

async function addCamera() {
  const id = document.getElementById('add-cam-id').value.trim();
  const url = document.getElementById('add-cam-url').value.trim();
  const loc = document.getElementById('add-cam-loc').value.trim() || 'unknown';
  if (!id || !url) return;
  const fd = new FormData();
  fd.append('cam_id', id);
  fd.append('url', url);
  fd.append('location', loc);
  const r = await fetch('/api/cameras', { method: 'POST', body: fd });
  const d = await r.json();
  document.getElementById('cam-msg').textContent = d.status;
  document.getElementById('add-cam-id').value = '';
  document.getElementById('add-cam-url').value = '';
  document.getElementById('add-cam-loc').value = '';
  refreshCameras();
  buildCamGrid();
}

async function removeCamera(id) {
  await fetch('/api/cameras/' + id, { method: 'DELETE' });
  refreshCameras();
  buildCamGrid();
}

// ═══════════════════════════════════════════════════
// ESP MANAGEMENT
// ═══════════════════════════════════════════════════
async function refreshEsps() {
  const r = await fetch('/api/esps');
  const data = await r.json();
  const list = document.getElementById('esp-list');
  list.innerHTML = '';
  data.esps.forEach(e => {
    const row = document.createElement('div');
    row.className = 'item-row';
    row.innerHTML = `
      <span class="name">${e.id}</span>
      <span class="detail">${e.type} &bull; ${e.ip} &bull; ${e.location}</span>
      <span class="tag tag-green">ONLINE</span>
      <button class="btn btn-danger btn-sm" onclick="removeEsp('${e.id}')">Remove</button>`;
    list.appendChild(row);
  });
  if (data.esps.length === 0) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:.8rem;">No ESP devices registered</div>';
  }
}

async function addEsp() {
  const id = document.getElementById('add-esp-id').value.trim();
  const type = document.getElementById('add-esp-type').value;
  const ip = document.getElementById('add-esp-ip').value.trim();
  const loc = document.getElementById('add-esp-loc').value.trim() || 'unknown';
  if (!id) return;
  const fd = new FormData();
  fd.append('esp_id', id);
  fd.append('esp_type', type);
  fd.append('ip', ip);
  fd.append('location', loc);
  const r = await fetch('/api/esps', { method: 'POST', body: fd });
  const d = await r.json();
  document.getElementById('esp-msg').textContent = d.status;
  document.getElementById('add-esp-id').value = '';
  document.getElementById('add-esp-ip').value = '';
  document.getElementById('add-esp-loc').value = '';
  refreshEsps();
}

async function removeEsp(id) {
  await fetch('/api/esps/' + id, { method: 'DELETE' });
  refreshEsps();
}

// ═══════════════════════════════════════════════════
// SSE LIVE EVENTS
// ═══════════════════════════════════════════════════
const evContainer = document.getElementById('sb-events');
const evSrc = new EventSource('/events/live');
evSrc.onopen = () => document.getElementById('status').textContent = 'Live';
evSrc.onerror = () => document.getElementById('status').textContent = 'Reconnecting…';
evSrc.onmessage = e => {
  const ev = JSON.parse(e.data);
  const div = document.createElement('div');

  if (ev.type === 'anomaly') {
    // Anomaly event — red styling
    const riskClass = ev.risk === 'CRITICAL' ? 'critical' : ev.risk === 'HIGH' ? 'high' : 'warning';
    div.className = 'card ev-card anomaly ' + riskClass;
    div.innerHTML = '<div class="ev-label">🚨 ' + ev.label + '</div><div class="ev-meta">' + (ev.description || '') + ' &bull; ' + (ev.camera || '') + ' &bull; ' + ev.ts.replace('T', ' ').slice(0, 19) + '</div>';
  } else {
    // Identity event — green/orange
    div.className = 'card ev-card ' + (ev.known ? 'known' : 'unknown');
    div.innerHTML = '<div class="ev-label">' + ev.label + '</div><div class="ev-meta">dist: ' + ev.score + ' &bull; ' + (ev.camera || '') + ' &bull; ' + ev.ts.replace('T', ' ').slice(0, 19) + '</div>';
  }

  evContainer.prepend(div);
  while (evContainer.children.length > 80) evContainer.removeChild(evContainer.lastChild);
};

// ═══════════════════════════════════════════════════
// VISITORS
// ═══════════════════════════════════════════════════
async function loadVisitors() {
  const r = await fetch('/api/visitors');
  const data = await r.json();
  const list = document.getElementById('visitor-list');
  list.innerHTML = '';
  data.known.forEach(v => {
    const d = document.createElement('div');
    d.className = 'item-row';
    d.innerHTML = '<span class="name">&#9733; ' + v.id + '</span><span class="tag tag-green">known</span>';
    list.appendChild(d);
  });
  data.unknown.forEach(v => {
    const d = document.createElement('div');
    d.className = 'item-row';
    d.innerHTML = '<span class="name">' + v.label + '</span><span class="tag tag-orange">x' + v.visit_count + '</span>';
    list.appendChild(d);
  });
  if (list.children.length === 0) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:.8rem;">No visitors yet</div>';
  }
}

// ═══════════════════════════════════════════════════
// VISION ANALYTICS
// ═══════════════════════════════════════════════════
let activeVTool = null;

async function toggleVision(tool) {
  const enabling = activeVTool !== tool;
  activeVTool = enabling ? tool : null;
  document.querySelectorAll('.v-btn').forEach(b => b.classList.remove('active'));
  if (enabling) document.getElementById('vb-' + tool).classList.add('active');
  const fd = new FormData();
  fd.append('tool_name', tool);
  fd.append('enabled', enabling ? 'true' : 'false');
  try {
    const r = await fetch('/api/analytics/configure', { method: 'POST', body: fd });
    const d = await r.json();
    document.getElementById('v-status').textContent = d.status;
  } catch (e) {
    document.getElementById('v-status').textContent = 'Error configuring.';
  }
}

// ═══════════════════════════════════════════════════
// SEMANTIC SEARCH
// ═══════════════════════════════════════════════════
async function semanticSearch() {
  const f = document.getElementById('sem-file').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  fd.append('top_k', 5);
  const r = await fetch('/api/search/semantic', { method: 'POST', body: fd });
  const d = await r.json();
  if (d.results && d.results.length > 0) {
    let out = '';
    d.results.forEach(res => {
      out += 'Event: ' + res.event_id + '\nSim: ' + (res.similarity || 0).toFixed(3) + ' | ' + (res.description || '') + '\n\n';
    });
    document.getElementById('sem-result').textContent = out;
  } else {
    document.getElementById('sem-result').textContent = 'No matches found.';
  }
}

// ═══════════════════════════════════════════════════
// IDENTITY TOOLS
// ═══════════════════════════════════════════════════
async function identifyFace() {
  const f = document.getElementById('id-file').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  const r = await fetch('/api/identify', { method: 'POST', body: fd });
  const d = await r.json();
  document.getElementById('id-result').textContent = d.label + '  (dist: ' + d.score + ')';
}

async function registerFace() {
  const name = document.getElementById('reg-name').value.trim();
  const f = document.getElementById('reg-file').files[0];
  if (!name || !f) return;
  const fd = new FormData();
  fd.append('name', name);
  fd.append('file', f);
  const r = await fetch('/api/identity', { method: 'POST', body: fd });
  const d = await r.json();
  document.getElementById('reg-result').textContent = d.result;
}

async function promoteUnknown() {
  const uid = document.getElementById('promo-uid').value.trim();
  const name = document.getElementById('promo-name').value.trim();
  if (!uid || !name) return;
  const fd = new FormData();
  fd.append('name', name);
  const r = await fetch('/api/promote/' + uid, { method: 'POST', body: fd });
  const d = await r.json();
  document.getElementById('promo-result').textContent = d.result;
}
