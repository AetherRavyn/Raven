import subprocess
import time
import os
import signal
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestLauncher")

def main():
    logger.info("Starting background SARAS services for testing...")
    
    envs = os.environ.copy()
    envs["PYTHONPATH"] = "/home/swadhin/SARAS"
    
    # Start microservices in background
    procs = []
    
    services = [
        "monitoring/src/risk_analysis.py",
        "monitoring/src/alert.py",
        "monitoring/src/storage.py"
    ]
    
    for svc in services:
        logger.info(f"Launching {svc}...")
        p = subprocess.Popen(["uv", "run", svc], env=envs)
        procs.append(p)
        
    logger.info("Waiting for services to connect to MessageBus...")
    time.sleep(3)
    
    try:
        logger.info("Executing mock event script: test_phase4.py")
        result = subprocess.run(["uv", "run", "monitoring/test_phase4.py"], env=envs, capture_output=True, text=True)
        print("--- Test Output ---")
        print(result.stdout)
        print("--- Test Errors (if any) ---")
        print(result.stderr)
        
        logger.info("Waiting 4 seconds to allow async services to finish processing...")
        time.sleep(4)
        logger.info("Test finished.")
        
    finally:
        logger.info("Cleaning up background processes...")
        for p in procs:
            p.terminate()
            
        logger.info("All processes terminated. Check Redis or Console logs if applicable.")

if __name__ == "__main__":
    main()
