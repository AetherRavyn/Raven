import subprocess
import time
import os
import signal
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RAVEN_Launcher")

# Keep track of background processes
procs = []

def signal_handler(sig, frame):
    logger.info("Interrupt received, shutting down all RAVEN services...")
    for p in procs:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    logger.info("Initializing RAVEN Local Edge Server...")
    
    envs = os.environ.copy()
    envs["PYTHONPATH"] = "/home/swadhin/RAVEN"
    
    # Define all the isolated microservices required for the full pipeline
    services = [
        ("Scheduler", "monitoring/src/scheduler.py"),
        ("P2P Node", "monitoring/src/p2p.py"),
        ("Anomaly", "monitoring/src/anomaly.py"),
        ("Risk AI", "monitoring/src/risk_analysis.py"),
        ("Storage", "monitoring/src/storage.py"),
        ("Alerts", "monitoring/src/alert.py"),
        ("FastAPI", "monitoring/main.py"),
        ("LLM Uplink", "monitoring/src/llm.py"),
    ]
    
    for name, script_path in services:
        if not os.path.exists(script_path):
            logger.warning(f"Script {script_path} not found. Skipping {name}.")
            continue
            
        logger.info(f"Launching {name} -> {script_path}")
        # Run using uv to ensure virtual environment dependencies if applicable
        p = subprocess.Popen(["uv", "run", script_path], env=envs)
        procs.append(p)
        # Give a slight stagger so Bus listeners initialize gracefully
        time.sleep(1.5)
        
    logger.info("==============================================")
    logger.info("RAVEN is now fully running.")
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
