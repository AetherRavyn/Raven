import subprocess
import time
import os
import signal
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("SARAS_Launcher")

# Keep track of background processes
procs = []

def signal_handler(sig, frame):
    logger.info("Interrupt received, shutting down all SARAS services...")
    for p in procs:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    logger.info("Initializing SARAS Local Edge Server...")
    
    envs = os.environ.copy()
    # Ensure the parent directory is in PYTHONPATH so python can resolve our module paths
    envs["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # Define all the isolated microservices required for the full pipeline
    # Paths are relative to the monitoring directory
    services = [
        ("Scheduler", "src/scheduler.py"),
        ("P2P Node", "src/p2p.py"),
        ("Anomaly", "src/anomaly.py"),
        ("Risk AI", "src/risk_analysis.py"),
        ("Storage", "src/storage.py"),
        ("Alerts", "src/alert.py"),
        ("FastAPI", "main.py"),
        ("LLM Uplink", "src/llm.py"),
    ]
    
    for name, script_path in services:
        if not os.path.exists(script_path):
            logger.warning(f"Script {script_path} not found. Skipping {name}.")
            continue
            
        logger.info(f"Launching {name} -> {script_path}")
        # Run using python (or uv run python if preferred, but assuming standard venv/python context)
        p = subprocess.Popen([sys.executable, script_path], env=envs)
        procs.append(p)
        # Give a slight stagger so Redis/Bus listeners initialize gracefully
        time.sleep(1.5)
        
    logger.info("==============================================")
    logger.info("SARAS is now fully running.")
    logger.info("Dashboard available at: http://localhost:8000")
    logger.info("MCP Server available via stdio.")
    logger.info("Press Ctrl+C to stop all services.")
    logger.info("==============================================")
    
    # Block and keep alive
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
