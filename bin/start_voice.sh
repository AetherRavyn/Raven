#!/usr/bin/env bash
# SARAS Embodied Voice + Live Logging Dashboard

# Force the local voice pipeline ON
export ENABLE_LOCAL_VOICE=1

# Ensure workspace exists
mkdir -p workspace

# Start the main backend (which includes the VoicePipeline now)
# Log everything cleanly to workspace/saras.log
echo "Starting SARAS Backend..."
uv run python main.py > workspace/saras.log 2>&1 &
BACKEND_PID=$!

# Give it a second to boot up
sleep 1

# Launch the live visual dashboard
echo "Launching SARAS Live Dashboard..."
uv run python log_panel.py --file workspace/saras.log

# When the dashboard is closed (user hits 'q'), kill the backend
echo "Shutting down SARAS Backend..."
kill $BACKEND_PID
