import asyncio
import json
import random
import psutil
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from app.core.task_ledger import TaskLedger

router = APIRouter()

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SARAS Presence UI</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0f172a; color: #e2e8f0; font-family: monospace; }
        .pane { border: 1px solid #334155; padding: 1rem; border-radius: 0.5rem; background: #1e293b; }
        .pane h2 { font-size: 1.25rem; font-weight: bold; margin-bottom: 0.75rem; color: #38bdf8; }
    </style>
</head>
<body class="p-6">
    <header class="mb-8">
        <h1 class="text-3xl font-bold text-sky-400">SARAS Presence UI</h1>
        <p class="text-slate-400 text-sm">Real-time system state & telemetry</p>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="pane">
            <h2>🧠 Cognitive State</h2>
            <div id="cognitive-state" class="text-sm space-y-2">Waiting for data...</div>
        </div>
        
        <div class="pane">
            <h2>🖥️ System Hardware</h2>
            <div id="system-hardware" class="text-sm space-y-2">Waiting for data...</div>
        </div>

        <div class="pane">
            <h2>🌐 Edge Network</h2>
            <div id="edge-network" class="text-sm space-y-2">Waiting for data...</div>
        </div>

        <div class="pane">
            <h2>🤖 Multi-Model Swarm</h2>
            <div id="model-swarm" class="text-sm space-y-2">Waiting for data...</div>
        </div>

        <div class="pane">
            <h2>🐟 MiroFish Predictions</h2>
            <div id="mirofish" class="text-sm space-y-2">Waiting for data...</div>
        </div>

        <div class="pane">
            <h2>✅ Pending Approvals</h2>
            <div id="approvals" class="text-sm space-y-2">Waiting for data...</div>
        </div>
    </div>

    <script>
        const ws = new WebSocket(`ws://${location.host}/ws/ui`);
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'update') {
                const cog = data.cognitive || {};
                document.getElementById('cognitive-state').innerHTML = `
                    <p><span class="text-slate-400">Status:</span> ${cog.status || 'Idle'}</p>
                    <p><span class="text-slate-400">Active Task:</span> ${cog.active_task || 'None'}</p>
                    <p><span class="text-slate-400">Ledger Count:</span> ${cog.ledger_count || '0'}</p>
                `;

                const hw = data.hardware || {};
                document.getElementById('system-hardware').innerHTML = `
                    <p><span class="text-slate-400">CPU Usage:</span> ${hw.cpu || '0'}%</p>
                    <p><span class="text-slate-400">Memory Usage:</span> ${hw.memory || '0'}%</p>
                    <p><span class="text-slate-400">Disk Usage:</span> ${hw.disk || '0'}%</p>
                `;

                const swarm = data.swarm || {};
                document.getElementById('model-swarm').innerHTML = `
                    <p><span class="text-slate-400">Primary Router:</span> ${swarm.router || 'AutoModelRouter'}</p>
                    <p><span class="text-slate-400">Active Model:</span> ${swarm.active_model || 'None'}</p>
                    <p><span class="text-slate-400">Last Fallback:</span> ${swarm.last_fallback || 'None'}</p>
                `;

                const edge = data.edge || [];
                document.getElementById('edge-network').innerHTML = edge.length > 0 
                    ? edge.map(n => `<p><span class="text-green-400">●</span> ${n.id} (${n.status})</p>`).join('')
                    : '<p class="text-slate-500">No active edge nodes</p>';

                const miro = data.mirofish || {};
                document.getElementById('mirofish').innerHTML = `
                    <p><span class="text-slate-400">Forecast:</span> ${miro.forecast || 'N/A'}</p>
                    <p><span class="text-slate-400">Confidence:</span> ${miro.confidence || '0'}%</p>
                `;

                const approvals = data.approvals || [];
                document.getElementById('approvals').innerHTML = approvals.length > 0
                    ? approvals.map(a => `<div class="p-2 bg-slate-800 rounded mb-2"><span class="text-yellow-400">[${a.id}]</span> ${a.summary}</div>`).join('')
                    : '<p class="text-slate-500">No pending approvals</p>';
            }
        };

        ws.onclose = () => {
            console.log('WebSocket connection closed.');
        };
    </script>
</body>
</html>
"""


@router.get("/ui", response_class=HTMLResponse)
async def get_ui():
    return HTML_CONTENT


active_connections = []


@router.websocket("/ws/ui")
async def websocket_ui(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            from app.settings.config import Config

            ledger = TaskLedger(Config.MEMORY_ROOT)
            tasks = ledger.list_tasks()
            pending = [t for t in tasks if t.get("status") == "pending_approval"]

            # Simulated data for Presence UI mixed with real hardware telemetry
            payload = {
                "type": "update",
                "cognitive": {
                    "status": random.choice(
                        ["Idle", "Thinking", "Executing", "Learning"]
                    ),
                    "active_task": "System Monitoring"
                    if random.random() > 0.5
                    else "None",
                    "ledger_count": len(tasks),
                },
                "hardware": {
                    "cpu": psutil.cpu_percent(interval=None),
                    "memory": psutil.virtual_memory().percent,
                    "disk": psutil.disk_usage("/").percent,
                },
                "swarm": {
                    "router": "AutoModelRouter",
                    "active_model": random.choice(
                        [
                            "Claude 3.5 Sonnet",
                            "GPT-4o",
                            "DeepSeek-V3",
                            "Local vLLM",
                            "gh-copilot CLI",
                        ]
                    ),
                    "last_fallback": "None"
                    if random.random() > 0.1
                    else "LM Studio (Offline)",
                },
                "edge": [
                    {"id": "node-alpha", "status": "online"},
                    {"id": "node-beta", "status": random.choice(["online", "syncing"])},
                ],
                "mirofish": {
                    "forecast": random.choice(
                        ["Stable", "Anomalous Traffic", "High Load Expected"]
                    ),
                    "confidence": random.randint(70, 99),
                },
                "approvals": [
                    {
                        "id": t.get("task_id", "unknown"),
                        "summary": t.get("title", "Pending Task"),
                    }
                    for t in pending
                ],
            }

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        active_connections.remove(websocket)
