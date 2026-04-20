#!/bin/bash
echo "🚀 Starting SARAS OS Ecosystem..."

# Cleanup any leftover processes
pkill -f "main.py daemon" || true
pkill -f "main.py edge-node" || true

echo "🧠 1. Starting Core Daemon (API, Autonomy, WebSockets)..."
uv run python3 main.py daemon > daemon.log 2>&1 &
DAEMON_PID=$!

echo "⏳ Waiting for Daemon to initialize (5 seconds)..."
sleep 5

echo "🌐 2. Starting Local Edge Node (PicoCompute Worker)..."
# Starts a background edge node connected to localhost
uv run python3 main.py edge-node > edge.log 2>&1 &
EDGE_PID=$!

echo ""
echo "======================================================="
echo "✅ SARAS OS is fully live and running in the background!"
echo "======================================================="
echo "🌍 1. WEB UI: Open http://localhost:8090/ui in your browser"
echo "💬 2. CHAT:   Run 'uv run python3 main.py chat' in your terminal"
echo "⚙️  3. DEMO:   Run 'uv run python3 demo_enterprise.py' to see Docker & Edge in action"
echo "📜 4. LOGS:   Run 'tail -f daemon.log' to see system logs"
echo ""
echo "🛑 To shut everything down later, run: pkill -f main.py"
echo "======================================================="

# Keep script running to easily kill processes on Ctrl+C
trap "echo 'Shutting down SARAS...'; kill $DAEMON_PID $EDGE_PID 2>/dev/null || true; exit" INT TERM
wait
