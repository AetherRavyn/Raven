# app/provider/cli_proxy.py
"""CLI Proxy Provider — routes LLM requests through locally installed CLI tools.

Supports: claude, gemini, kilocode, opencode, gh copilot, qwen, jules.
Each CLI tool is invoked in non-interactive mode with the prompt piped via stdin
or passed as an argument, and ANSI escape codes are stripped from the output.

The provider uses the CLI tool's OWN API routes internally — SARAS just sends
the prompt as if the user typed it in the CLI, and captures the clean response.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from typing import Any, Dict, List

from app.provider.base import BaseLLMProvider
from app.settings.config import Config

import logging

logger = logging.getLogger(__name__)

# Regex to strip ANSI escape codes
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[[\d;]*m")
# Regex to strip box-drawing and spinner characters
_TUI_JUNK_RE = re.compile(r"[╭╮╰╯│─┌┐└┘├┤┬┴┼⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣿⡿⢿⡇⢸⣿⣷⣶⣾█░▓▒]+")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes, terminal control sequences, and TUI junk."""
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r", "")
    text = text.replace("\x00", "")
    text = _TUI_JUNK_RE.sub("", text)
    return text


def _extract_clean_response(raw: str) -> str:
    """Extract the actual model response from CLI tool output.
    
    CLI tools wrap their response in various TUI chrome (boxes, spinners,
    status bars, thinking indicators). This function strips all that and 
    returns only the meaningful content.
    """
    cleaned = _strip_ansi(raw)

    # Split into lines and filter out junk
    good_lines = []
    skip_patterns = [
        "Type a message",
        "/help for commands",
        "/mode to switch",
        "Thinking...",
        "Esc/Ctrl+X",
        "API Request",
        "Reasoning",
        "> Type a message or /command",
        "SARAS",
        "! for shell mode",
        "Kilo Code",
        "Auto/frontier",
        "Auto Frontier",
        "master",
        "| Code |",
        "| 0%",
        "Loading",
        "Connecting",
    ]

    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("{") and '"type"' in stripped:
            continue
        if len(stripped) < 3:
            continue
        if any(pat in stripped for pat in skip_patterns):
            continue
        alnum = sum(1 for c in stripped if c.isalnum() or c in ' .,;:!?-\'"()')
        if alnum < len(stripped) * 0.3:
            continue
        good_lines.append(stripped)

    result = "\n".join(good_lines).strip()

    if result.startswith("The user wants to") or result.startswith("The ..."):
        parts = result.split("\n\n", 1)
        if len(parts) > 1:
            result = parts[1].strip()

    return result


def _coerce_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_coerce_to_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("content", "text", "output", "message", "response"):
            text = _coerce_to_text(value.get(key))
            if text:
                return text
        parts = [_coerce_to_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


def _extract_json_response(raw: str) -> str:
    """Extract assistant text from JSON or line-delimited JSON CLI output."""
    cleaned = _strip_ansi(raw).strip()
    if not cleaned:
        return ""

    def _from_json(obj: Any) -> str:
        if isinstance(obj, dict):
            event_type = str(obj.get("type", "")).lower()
            part = obj.get("part")

            if isinstance(part, dict):
                part_type = str(part.get("type", "")).lower()
                if part_type in {
                    "step-start",
                    "step-finish",
                    "tool",
                    "tool_use",
                    "tool-result",
                    "tool_result",
                    "reasoning",
                    "thinking",
                    "status",
                }:
                    return ""
                if part_type == "text":
                    text = _coerce_to_text(part.get("text"))
                    if text:
                        return text
                text = _from_json(part)
                if text:
                    return text

            if event_type in {"status", "progress", "thinking", "log"}:
                return ""
            if event_type in {"step_start", "step_finish", "tool_use"}:
                return ""
            if event_type == "text":
                text = _coerce_to_text(obj.get("text"))
                if text:
                    return text
            if event_type in {"assistant", "message", "final", "output_text"}:
                text = _coerce_to_text(
                    obj.get("content") or obj.get("text") or obj.get("message")
                )
                if text:
                    return text
            if "messages" in obj:
                text = _from_json(obj.get("messages"))
                if text:
                    return text
            for key in (
                "content",
                "text",
                "output",
                "message",
                "response",
                "result",
                "data",
                "messages",
                "part",
            ):
                text = _from_json(obj.get(key))
                if text:
                    return text
            return ""
        if isinstance(obj, list):
            assistant_chunks: list[str] = []
            for item in obj:
                text = _from_json(item)
                if text:
                    assistant_chunks.append(text)
            return "\n".join(chunk for chunk in assistant_chunks if chunk).strip()
        return _coerce_to_text(obj)

    try:
        parsed = json.loads(cleaned)
        return _from_json(parsed)
    except Exception:
        pass

    chunks: list[str] = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line or not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        text = _from_json(parsed)
        if text:
            chunks.append(text)
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _is_garbage_response(text: str) -> bool:
    """Detect if a response is TUI garbage rather than actual content."""
    if not text or len(text.strip()) < 10:
        return True
    # If the clean text is very short compared to raw text, it's garbage
    alnum = sum(1 for c in text if c.isalnum())
    if alnum < 20:
        return True
    return False


class CLIProxyProvider(BaseLLMProvider):
    """Routes LLM requests through locally installed CLI coding tools.
    
    Each CLI tool uses its own API routes internally. SARAS just sends
    the prompt as a regular user would type it, making it look like
    the CLI itself is making the request (not SARAS/OpenClaw).
    """

    def __init__(
        self,
        tool_name: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self._tool_name = (tool_name or "").strip().lower() or None
        self._timeout = int(timeout or Config.CLI_PROXY_TIMEOUT)

    @property
    def name(self) -> str:
        return "cli_proxy"

    @staticmethod
    def _default_model_for_tool(tool: str) -> str:
        defaults = {
            "opencode": Config.OPENCODE_MODEL,
            "qwen": Config.QWEN_CLI_MODEL,
            "gemini": Config.GEMINI_CLI_MODEL,
            "kilocode": Config.KILOCODE_MODEL,
        }
        return defaults.get(tool, "")

    def _resolve_tool_and_model(self, model: str) -> tuple[str, str]:
        requested = (model or "").strip()
        if self._tool_name:
            tool = self._tool_name
            effective_model = requested or self._default_model_for_tool(tool)
            return tool, effective_model

        if requested.startswith("cli/"):
            tool = requested.removeprefix("cli/").strip()
            return tool, self._default_model_for_tool(tool)

        tool = requested.split("/", 1)[0].strip().lower()
        if tool in {"opencode", "qwen", "gemini", "kilocode"}:
            return tool, requested

        return requested.lower(), requested

    def _build_command(self, tool: str, prompt: str, model: str) -> tuple[list[str], bool]:
        if tool == "claude":
            return ["claude", "-p", prompt, "--no-input"], False
        if tool == "gh-copilot":
            return ["gh", "copilot", "suggest", "-t", "shell", prompt], False
        if tool == "qwen":
            cmd = ["qwen", prompt, "--output-format", "json"]
            if model:
                cmd.extend(["--model", model])
            return cmd, False
        if tool == "gemini":
            cmd = ["gemini", "-p", prompt, "--output-format", "json"]
            if model:
                cmd.extend(["--model", model])
            return cmd, False
        if tool == "kilocode":
            cmd = [
                "kilocode",
                "--auto",
                "--json",
                "--mode",
                "ask",
                "--timeout",
                str(self._timeout),
            ]
            if model:
                cmd.extend(["--model", model])
            cmd.append(prompt)
            return cmd, False
        if tool == "opencode":
            cmd = ["opencode", "run", prompt, "--format", "json"]
            if model:
                cmd.extend(["--model", model])
            return cmd, False
        if tool == "jules":
            return ["jules", "ask", prompt], False
        if tool == "gemini_cli":
            return ["gemini", "-p", prompt, "--output-format", "json"], False
        if tool == "qwen_cli":
            return ["qwen", prompt, "--output-format", "json"], False
        if tool == "opencode_cli":
            return ["opencode", "run", prompt, "--format", "json"], False
        if tool == "kilocode_cli":
            return [
                "kilocode",
                "--auto",
                "--json",
                "--mode",
                "ask",
                "--timeout",
                str(self._timeout),
                prompt,
            ], False
        else:
            return [tool, prompt], False

    async def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Route the request through a CLI tool.
        
        The model should be like "cli/claude", "cli/gemini", "cli/kilocode", etc.
        We extract the tool name and invoke it non-interactively.
        """
        tool, requested_model = self._resolve_tool_and_model(model)
        if not tool:
            return {"success": False, "error": f"Invalid CLI model name: '{model}'"}

        # Build a clean prompt — only use the last USER message, not the full
        # system prompt + tool schemas (which are HUGE and cause CLI tools to choke)
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break
        
        if not last_user_msg:
            # Fallback: combine all messages
            last_user_msg = "\n".join(
                msg.get("content", "") for msg in messages if msg.get("role") != "system"
            )

        openai_tools = kwargs.get("tools")
        tool_prompt_injection = ""
        if openai_tools:
            import json as _json
            tool_schema_str = _json.dumps(openai_tools)
            tool_prompt_injection = f"""
[SYSTEM INSTRUCTION] You have access to the following tools: {tool_schema_str}
If you need to use a tool, you MUST output ONLY the following raw JSON format and no other text:
{{"tool_calls": [{{"id": "call_123", "type": "function", "function": {{"name": "<tool name>", "arguments": "{{\\"arg_name\\": \\"arg_value\\"}}"}}}}]}}
[/SYSTEM INSTRUCTION]
"""

        prompt = (tool_prompt_injection + last_user_msg).strip()

        if not prompt:
            return {"success": False, "error": "Empty prompt"}

        # Check if the tool is installed
        cmd, uses_stdin = self._build_command(tool, prompt, requested_model)
        base_cmd = cmd[0]
        if not shutil.which(base_cmd):
            return {"success": False, "error": f"CLI tool '{base_cmd}' not installed."}

        # Environment: force non-interactive mode
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["CI"] = "true"
        env["NO_COLOR"] = "1"
        env["NONINTERACTIVE"] = "1"
        env["TERM"] = "dumb"  # Force dumb terminal — no TUI
        env["COLUMNS"] = "120"
        env["LINES"] = "50"

        logger.info("CLI proxy: invoking %s (tool=%s)", base_cmd, tool)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if uses_stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdin_data = prompt.encode("utf-8") if uses_stdin else None
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(stdin_data),
                    timeout=self._timeout,
                )
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise
            except asyncio.TimeoutError:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                logger.warning("CLI proxy: %s timed out after %ss", tool, self._timeout)
                return {
                    "success": False,
                    "error": f"CLI '{tool}' timed out after {self._timeout}s",
                }

            raw_output = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            raw_stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            clean_output = _extract_json_response(raw_output) or _extract_clean_response(
                raw_output
            )

            if _is_garbage_response(clean_output) and raw_stderr:
                clean_stderr = _extract_json_response(
                    raw_stderr
                ) or _extract_clean_response(raw_stderr)
                if not _is_garbage_response(clean_stderr):
                    clean_output = clean_stderr

            if process.returncode != 0:
                error_msg = _strip_ansi(raw_stderr or raw_output)[:500]
                return {
                    "success": False,
                    "error": f"CLI '{tool}' exited with code {process.returncode}: {error_msg}",
                }

            lower_clean = clean_output.lower()
            if "errorduringexecution" in lower_clean or ("\"iserror\":true" in lower_clean.replace(" ", "")):
                # Catch JSON-wrapped API errors that still returned code 0
                return {
                    "success": False,
                    "error": f"CLI '{tool}' API failure: {clean_output[:200]}",
                }

            if _is_garbage_response(clean_output):
                logger.warning("CLI proxy: %s returned garbage output", tool)
                return {
                    "success": False,
                    "error": f"CLI '{tool}' returned unusable TUI output. Tool may not support non-interactive mode.",
                }

            logger.info(
                "CLI proxy: %s returned %d chars of clean content",
                tool,
                len(clean_output),
            )
            
            # --- CLI Proxy Tool Overload parser ---
            parsed_tool_calls = None
            if "tool_calls" in clean_output:
                try:
                    import json
                    as_json = json.loads(clean_output)
                    if "tool_calls" in as_json:
                        parsed_tool_calls = as_json["tool_calls"]
                        clean_output = as_json.get("content", "")
                except Exception:
                    # Fallback to regex extraction if it tried to output markdown
                    import re
                    match = re.search(r'\{.*"tool_calls"\s*:.*\}', clean_output, re.DOTALL)
                    if match:
                        try:
                            import json
                            as_json = json.loads(match.group(0))
                            if "tool_calls" in as_json:
                                parsed_tool_calls = as_json["tool_calls"]
                                clean_output = ""
                        except Exception:
                            pass

            return {
                "success": True,
                "content": clean_output,
                "model_used": requested_model or model or tool,
                "provider": self.name,
                "raw": {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": clean_output,
                                "tool_calls": parsed_tool_calls,
                            }
                        }
                    ]
                },
            }

        except Exception as e:
            logger.error("CLI proxy: %s error: %s", tool, e)
            return {"success": False, "error": str(e)}
