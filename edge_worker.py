#!/usr/bin/env python3
import time
import requests
import socket
import logging

logging.basicConfig(level=logging.INFO, format="[EDGE] %(message)s")

SERVER_URL = "http://localhost:8090/api/v1/edge"
NODE_ID = f"worker-{socket.gethostname()}"
CAPABILITIES = ["python"] # this tiny node can only run python

def register():
    try:
        resp = requests.post(f"{SERVER_URL}/register", json={
            "node_id": NODE_ID,
            "capabilities": CAPABILITIES
        })
        if resp.status_code == 200:
            logging.info("Successfully registered with SARAS Edge Router.")
        else:
            logging.error(f"Failed to register: {resp.text}")
    except Exception as e:
        logging.error(f"Could not connect to router: {e}")

def run_python_task(code: str):
    logging.info("Executing Python task locally...")
    import sys
    from io import StringIO
    
    # Very insecure simple execution block just to prove the concept!
    old_stdout = sys.stdout
    redirected_output = StringIO()
    sys.stdout = redirected_output
    success = False
    try:
        exec(code)
        success = True
    except Exception as e:
        print(f"Error executing task: {e}")
    finally:
        sys.stdout = old_stdout
        
    result = redirected_output.getvalue()
    return success, result

def poll_and_execute():
    try:
        resp = requests.get(f"{SERVER_URL}/tasks/{NODE_ID}")
        if resp.status_code == 200:
            data = resp.json()
            task = data.get("task")
            if task:
                logging.info(f"Picked up task {task['task_id']}")
                meta = task.get("metadata", {})
                req_cap = meta.get("required_capability")
                payload = meta.get("payload")
                
                success = False
                result = "Unknown capability"
                
                if req_cap == "python":
                    success, result = run_python_task(payload)
                
                # Submit result
                requests.post(f"{SERVER_URL}/tasks/{task['task_id']}/complete", json={
                    "result": result,
                    "success": success
                })
                logging.info(f"Task {task['task_id']} complete. Result submitted.")
    except Exception as e:
        logging.error(f"Poll failed: {e}")

if __name__ == "__main__":
    logging.info(f"Starting SARAS Tiny Worker Node: {NODE_ID}")
    register()
    
    while True:
        poll_and_execute()
        time.sleep(3)
