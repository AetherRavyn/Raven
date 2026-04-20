import asyncio
import os
from app.tools.docker_exec_tool import DockerExecTool


async def test_docker_tool():
    print("Testing DockerExecTool...")
    tool = DockerExecTool()

    # Simple Python code execution
    python_code = "print('Hello from ephemeral Docker container!')"
    command = f'python -c "{python_code}"'

    try:
        res = await tool.execute(command=command, image="python:3.11-slim", timeout=10)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Failed to run docker tool (maybe docker daemon is not running?): {e}")


if __name__ == "__main__":
    asyncio.run(test_docker_tool())
