import asyncio
import logging
from typing import Dict, Any

from app.tools.docker_exec_tool import DockerExecTool
from app.tools.edgetool import EdgeDeviceTool
from app.core.skill_registry import SkillRegistry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("EnterpriseWorkflow")


class EnterpriseOrchestrator:
    """
    Context-Aware Workflow Orchestrator that analyzes a situation
    and routes it to the appropriate JARVIS/FRIDAY enterprise workflow.
    """

    def __init__(self):
        self.docker_tool = DockerExecTool()
        self.edge_tool = EdgeDeviceTool()
        # Mocking a lightweight registry just to load text for the demo
        self.registry = SkillRegistry()

    def analyze_context(self, prompt: str) -> str:
        """Analyze the situation/context to determine the required workflow."""
        prompt_lower = prompt.lower()
        if any(
            w in prompt_lower for w in ["security", "audit", "secret", "vulnerability"]
        ):
            return "zerotrust"
        elif any(
            w in prompt_lower for w in ["sensor", "edge", "data", "process", "network"]
        ):
            return "picocompute"
        elif any(w in prompt_lower for w in ["code", "bug", "test", "fix", "develop"]):
            return "omnicoder"
        return "unknown"

    async def execute_zerotrust(self, context: str):
        logger.info("🛡️ Initiating ZeroTrust Security Auditor...")

        scanner_code = """
import os
import sys

with open('config.env', 'w') as f:
    f.write('PORT=8080\\nAPI_KEY=sk_test_123456\\nDEBUG=true')

print("Scanning for exposed secrets...")
found_secrets = False
with open('config.env', 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if 'API_KEY' in line or 'PASSWORD' in line:
            print(f"CRITICAL: Secret found on line {i+1}: {line.strip()}")
            found_secrets = True

if found_secrets:
    sys.exit(1)
"""

        # 2. Run the scanner in an isolated Docker container
        logger.info("Containerizing scanner payload in Docker...")
        res = await self.docker_tool.execute(
            command='python -c "{}"'.format(scanner_code.replace('"', '\\"')),
            image="python:3.11-slim",
            timeout=10,
        )

        # 3. Analyze the result
        if res.get("status_code") != 0:
            logger.error("🚨 ZeroTrust Scan Failed: Vulnerabilities detected!")
            logger.info("Invoking 'code_reviewer' skill to analyze findings...")
            # Ideally we'd invoke the LLM here. For demo, we just log the output.
            logger.warning(f"Scan Output:\n{res.get('output')}")
            logger.info("Patch drafted and Edge Nodes alerted.")
        else:
            logger.info("✅ ZeroTrust Scan Passed: No vulnerabilities found.")

    async def execute_picocompute(self, context: str):
        logger.info("📡 Initiating PicoCompute Edge Data Processing...")

        # 1. Query Edge Devices
        logger.info("Querying Edge Device Network via EdgeDeviceTool...")
        devices_res = await self.edge_tool.execute(operation="list_devices")
        logger.info(f"Edge Status: {devices_res}")

        # 2. Mock Data aggregation script
        logger.info(
            "Aggregating telemetry from distributed nodes into Docker Compute Engine..."
        )
        data_script = """
import json

edge_data = [
    {'node': 'alpha', 'temp': 45.2, 'cpu': 80},
    {'node': 'beta', 'temp': 38.1, 'cpu': 45},
    {'node': 'gamma', 'temp': 42.0, 'cpu': 60}
]

avg_temp = sum(d['temp'] for d in edge_data) / len(edge_data)
avg_cpu = sum(d['cpu'] for d in edge_data) / len(edge_data)

result = {"status": "success", "network_avg_temp": round(avg_temp, 2), "network_avg_cpu": round(avg_cpu, 2)}
print(json.dumps(result))
"""
        # 3. Run processing
        res = await self.docker_tool.execute(
            command='python -c "{}"'.format(data_script.replace('"', '\\"')),
            image="python:3.11-slim",
            timeout=10,
        )
        logger.info(f"📊 PicoCompute Result: {res.get('output', '').strip()}")

    async def execute_omnicoder(self, context: str):
        logger.info("👨‍💻 Initiating OmniCoder Self-Correcting Loop...")

        bad_code = """
def add(a, b):
    return a - b  # Deliberate bug

assert add(2, 3) == 5, "Test failed: 2 + 3 should be 5"
print("All tests passed!")
"""

        logger.info("Running initial code iteration in Docker sandbox...")
        res = await self.docker_tool.execute(
            command='python -c "{}"'.format(bad_code.replace('"', '\\"')),
            image="python:3.11-slim",
            timeout=10,
        )

        # 2. Check if tests failed and SELF-CORRECT
        if res.get("status_code") != 0:
            logger.error(f"Test Suite Failed! Output:\n{res.get('output')}")
            logger.info("ReAct Loop triggered. Model self-correcting the bug...")

            # 3. Corrected code
            good_code = """
def add(a, b):
    return a + b  # Bug fixed

assert add(2, 3) == 5, "Test failed: 2 + 3 should be 5"
print("All tests passed!")
"""
            logger.info("Running patched code iteration in Docker sandbox...")
            res2 = await self.docker_tool.execute(
                command='python -c "{}"'.format(good_code.replace('"', '\\"')),
                image="python:3.11-slim",
                timeout=10,
            )
            if res2.get("status_code") == 0:
                logger.info("✅ OmniCoder Successfully Self-Corrected! Tests passed.")
                logger.info(f"Final Output: {str(res2.get('output', '')).strip()}")

    async def run(self, prompt: str):
        logger.info(f"--- Processing Request: '{prompt}' ---")
        workflow_type = self.analyze_context(prompt)

        if workflow_type == "zerotrust":
            await self.execute_zerotrust(prompt)
        elif workflow_type == "picocompute":
            await self.execute_picocompute(prompt)
        elif workflow_type == "omnicoder":
            await self.execute_omnicoder(prompt)
        else:
            logger.warning(
                "Could not determine context. Defaulting to standard chat response."
            )


async def main():
    orchestrator = EnterpriseOrchestrator()

    # Simulate dynamically changing contexts
    prompts = [
        "Please write a python function to add two numbers and ensure the tests pass.",
        "Can you audit the config files for exposed API keys?",
        "Fetch the latest sensor temperatures from the edge network and process the average.",
    ]

    for p in prompts:
        await orchestrator.run(p)
        print("\\n" + "=" * 50 + "\\n")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
