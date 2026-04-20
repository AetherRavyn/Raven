import time
import requests
import subprocess
import logging
import csv
from io import StringIO

# Configure a nice logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("EdgeNode")


def parse_csv_string(csv_string):
    """Robustly parse a CSV string into a list of items."""
    if not csv_string:
        return []
    f = StringIO(csv_string)
    reader = csv.reader(f, skipinitialspace=True)
    try:
        items = next(reader)
        return [item.strip() for item in items if item.strip()]
    except StopIteration:
        return []


def run_edge_node(name, server, capabilities, location, sensors):
    logger.info(f"Starting edge node '{name}' connecting to {server}")

    cap_list = parse_csv_string(capabilities)
    sensor_list = parse_csv_string(sensors)

    logger.info(f"Capabilities: {cap_list}")
    logger.info(f"Sensors: {sensor_list}")

    register_payload = {
        "node_id": name,
        "capabilities": cap_list,
        "location": location,
        "sensors": sensor_list,
    }

    register_url = f"{server}/api/v1/edge/register"
    poll_url = f"{server}/api/v1/edge/tasks/{name}"

    # Initial registration backoff settings
    backoff = 2
    max_backoff = 60
    registered = False

    while not registered:
        try:
            logger.info("Attempting to register with server...")
            response = requests.post(register_url, json=register_payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Successfully registered edge node '{name}'.")
            registered = True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to register edge node: {e}")
            logger.info(f"Retrying registration in {backoff} seconds...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    logger.info("Entering task polling loop.")

    poll_backoff = 2
    max_poll_backoff = 30

    while True:
        try:
            response = requests.get(poll_url, timeout=10)

            # Reset poll backoff on successful connection
            poll_backoff = 2

            if response.status_code == 200:
                task = response.json()
                if task:
                    task_id = task.get("task_id")
                    metadata = task.get("metadata", {})
                    payload = metadata.get("payload", "")

                    if not task_id or not payload:
                        logger.warning(f"Received malformed task: {task}")
                        continue

                    logger.info(
                        f"Received task {task_id}. Executing payload:\n{payload}"
                    )

                    # Execute payload
                    process = subprocess.run(
                        payload, shell=True, capture_output=True, text=True
                    )

                    success = process.returncode == 0
                    result_output = (
                        process.stdout
                        if success
                        else (process.stderr or process.stdout)
                    )

                    logger.info(
                        f"Task {task_id} execution completed. Success: {success}"
                    )

                    # Send completion status
                    complete_url = f"{server}/api/v1/edge/tasks/{task_id}/complete"
                    complete_payload = {"success": success, "result": result_output}

                    # Retry loop for reporting completion
                    report_backoff = 2
                    while True:
                        try:
                            comp_resp = requests.post(
                                complete_url, json=complete_payload, timeout=10
                            )
                            comp_resp.raise_for_status()
                            logger.info(
                                f"Successfully reported completion for task {task_id}."
                            )
                            break
                        except requests.exceptions.RequestException as e:
                            logger.error(
                                f"Failed to report completion for task {task_id}: {e}"
                            )
                            logger.info(
                                f"Retrying reporting completion in {report_backoff} seconds..."
                            )
                            time.sleep(report_backoff)
                            report_backoff = min(report_backoff * 2, max_backoff)

            elif response.status_code == 404:
                # No tasks available
                time.sleep(5)
            else:
                logger.debug(
                    f"Polling returned unexpected status {response.status_code}"
                )
                time.sleep(5)

        except requests.exceptions.RequestException as e:
            logger.error(f"Connection error during polling: {e}")
            logger.info(f"Retrying poll in {poll_backoff} seconds...")
            time.sleep(poll_backoff)
            poll_backoff = min(poll_backoff * 2, max_poll_backoff)
