import os
import platform
import random
import re
import socket
import sys
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from app.provider.factory import create_provider
from app.settings.config import Config


class System1Router:
    def __init__(self, cache_ttl_seconds: int = 45):
        self.user_memory = defaultdict(dict)
        self.user_message_times = defaultdict(lambda: deque(maxlen=10))
        self.cache: dict[str, tuple[float, str, bool]] = {}
        self.cache_ttl_seconds = cache_ttl_seconds
        self.token_uses = defaultdict(int)
        self.blocked_words = [".env", "rm -rf /"]
        self.unmatched_queries = defaultdict(list)
        self.learned_responses = {}
        self.intents = [
            {
                "name": "greeting",
                "priority": 2,
                "patterns": [r"\bhi+\b", r"\bhello\b", r"\bhey+\b", r"\byo\b"],
                "response": ["Hey there! 👋", "Hello! 😊"],
            },
            {
                "name": "how_are_you",
                "priority": 3,
                "patterns": [r"how are you", r"how r u"],
                "response": ["I'm doing great! 😄", "All good here!"],
            },
            {
                "name": "time",
                "priority": 4,
                "patterns": [r"what time", r"current time"],
                "dynamic": True,
            },
            {
                "name": "identity",
                "priority": 5,
                "patterns": [r"who are you", r"what are you"],
                "response": ["I'm your AI assistant 🤖"],
            },
            {
                "name": "learning_summary",
                "priority": 5,
                "patterns": [
                    r"what have you learned",
                    r"what did you learn",
                    r"show me what you know",
                ],
                "dynamic": True,
            },
        ]
        self._provider = None
        self._provider_health_checked = False
        self._provider_is_healthy = False

    async def _get_provider(self):
        if not self._provider_health_checked:
            try:
                from app.provider.manager import ProviderManager

                pm = ProviderManager()
                pm_provider, pm_model = pm.select_model()
                if pm_provider != "opencode_zen" or pm_model != "big-pickle":
                    self._provider = create_provider(pm_provider)
                    self._provider_is_healthy = True
                else:
                    self._provider = create_provider("ollama", model=Config.LOCAL_LIGHT_MODEL)
                    if hasattr(self._provider, "health"):
                        self._provider_is_healthy = await self._provider.health()
                    else:
                        self._provider_is_healthy = True
            except Exception:
                self._provider = None
                self._provider_is_healthy = False
            self._provider_health_checked = True
        return self._provider if self._provider_is_healthy else None

    async def route_message(self, user_id, text) -> tuple[str, bool]:
        """Routes the incoming message and returns a response."""
        original_text = text
        text_clean = text.lower().strip()

        # Check for blocked words
        if any(word in text_clean for word in self.blocked_words):
            return "I can't talk about that. 🙊", False

        # Update user memory/history
        self.user_message_times[user_id].append(time.time())

        cached = self._cache_get(text_clean)
        if cached is not None:
            response, escalate_to_prompt = cached
            return f"{response}\n[cache:hit]", escalate_to_prompt

        builtin_response = self._run_builtin_tool(text_clean)
        if builtin_response is not None:
            self._cache_set(text_clean, builtin_response, False)
            return builtin_response, False

        # Try fast intent regex
        intent = self._match_intent(text_clean)
        if intent:
            if intent.get("dynamic"):
                response = self._get_dynamic_response(intent["name"])
            else:
                response = random.choice(intent["response"])
            self._cache_set(text_clean, response, False)
            return response, False

        # Fallback: store unmatched query and check for learned responses
        self.unmatched_queries[user_id].append(original_text)

        if text_clean in self.learned_responses:
            response = self.learned_responses[text_clean]
            self._cache_set(text_clean, response, False)
            return response, False

        # Semantic routing using Local Light Model
        provider = await self._get_provider()
        if provider:
            system_prompt = (
                "You are a System 1 router. Determine if the user's query is simple and conversational "
                "(like a greeting, small talk, or simple question) or if it requires deep reasoning, tools, or search. "
                "If it's simple, answer it briefly. If it requires System 2 (deep reasoning), reply EXACTLY with 'ESCALATE'."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": original_text},
            ]
            try:
                resp = await provider.chat_completion(messages=messages)
                if resp.get("success"):
                    # Depending on provider, the content might be in different places
                    # Handle raw OpenAI-style response from OllamaProvider
                    raw = resp.get("raw", {})
                    choices = raw.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "").strip()
                    else:
                        content = resp.get("content", "").strip()

                    if content and "ESCALATE" not in content:
                        self._cache_set(text_clean, content, False)
                        return content, False
            except Exception:
                pass

        return f"RAVEN is analyzing your problem: {original_text}", True

    def _cache_get(self, key: str) -> tuple[str, bool] | None:
        cached = self.cache.get(key)
        if not cached:
            return None
        ts, response, escalate = cached
        if time.time() - ts > self.cache_ttl_seconds:
            self.cache.pop(key, None)
            return None
        return response, escalate

    def _cache_set(self, key: str, response: str, escalate_to_prompt: bool) -> None:
        self.cache[key] = (time.time(), response, escalate_to_prompt)

    def _run_builtin_tool(self, text: str) -> str | None:
        if text in {"/tools", "/help-tools", "tools"}:
            return (
                "Available built-in tools:\n"
                "/time - current time and date\n"
                "/os - operating system details\n"
                "/server - server health snapshot\n"
                "/internet - internet connectivity and speed probe"
            )
        if text.startswith("/time") or "what time" in text or "current time" in text:
            return self._tool_time()
        if text.startswith("/os") or "os status" in text or "system info" in text:
            return self._tool_os_status()
        if text.startswith("/server") or "server status" in text or "server health" in text:
            return self._tool_server_status()
        if (
            text.startswith("/internet")
            or "internet speed" in text
            or "network status" in text
            or "internet status" in text
        ):
            return self._tool_internet_status()
        return None

    def _tool_time(self) -> str:
        now = datetime.now()
        return (
            "Time tool response:\n"
            f"local_date: {now.strftime('%Y-%m-%d')}\n"
            f"local_time: {now.strftime('%H:%M:%S')}"
        )

    def _tool_os_status(self) -> str:
        return (
            "OS status tool response:\n"
            f"system: {platform.system()}\n"
            f"release: {platform.release()}\n"
            f"version: {platform.version()}\n"
            f"python: {sys.version.split()[0]}\n"
            f"hostname: {socket.gethostname()}"
        )

    def _tool_server_status(self) -> str:
        load_text = "unavailable"
        if hasattr(os, "getloadavg"):
            load1, load5, load15 = os.getloadavg()
            load_text = f"{load1:.2f}, {load5:.2f}, {load15:.2f}"

        disk = os.statvfs(str(Path.cwd()))
        total_bytes = disk.f_frsize * disk.f_blocks
        free_bytes = disk.f_frsize * disk.f_bfree
        used_bytes = total_bytes - free_bytes
        disk_pct = (used_bytes / total_bytes * 100) if total_bytes else 0.0

        mem_line = "unavailable"
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                meminfo = fh.read()
            total_kb = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1))
            avail_kb = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1))
            used_kb = total_kb - avail_kb
            mem_line = (
                f"used_mb: {used_kb // 1024}, total_mb: {total_kb // 1024}, "
                f"usage_pct: {used_kb / total_kb * 100:.1f}"
            )
        except Exception:
            pass

        uptime_text = "unavailable"
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as fh:
                uptime_seconds = float(fh.read().split()[0])
            uptime_text = f"{int(uptime_seconds)}s"
        except Exception:
            pass

        return (
            "Server status tool response:\n"
            f"load_avg_1_5_15: {load_text}\n"
            f"disk_used_pct: {disk_pct:.1f}\n"
            f"memory: {mem_line}\n"
            f"uptime: {uptime_text}"
        )

    def _tool_internet_status(self) -> str:
        connect_latency_ms = "unavailable"
        try:
            start = time.perf_counter()
            with socket.create_connection(("1.1.1.1", 53), timeout=2):
                pass
            connect_latency_ms = f"{(time.perf_counter() - start) * 1000:.1f}"
        except OSError:
            pass

        download_speed_mbps = "unavailable"
        try:
            start = time.perf_counter()
            with urllib.request.urlopen("https://www.google.com/generate_204", timeout=4) as resp:
                data = resp.read()
            elapsed = max(time.perf_counter() - start, 1e-6)
            download_speed_mbps = f"{(len(data) * 8) / elapsed / 1_000_000:.3f}"
        except Exception:
            pass

        return (
            "Internet status tool response:\n"
            f"tcp_connect_latency_ms: {connect_latency_ms}\n"
            f"download_speed_mbps_est: {download_speed_mbps}"
        )

    def _match_intent(self, text):
        """Matches the text against defined intents, sorted by priority."""
        matched_intents = []
        for intent in self.intents:
            for pattern in intent["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    matched_intents.append(intent)
                    break

        if not matched_intents:
            return None

        # Return intent with highest priority (lowest number)
        return min(matched_intents, key=lambda x: x["priority"])

    def _get_dynamic_response(self, intent_name):
        """Generates a dynamic response based on the intent."""
        if intent_name == "time":
            now = datetime.now().strftime("%I:%M %p")
            return f"The current time is {now}. ⏰"
        if intent_name == "learning_summary":
            return (
                "Let me check what I've learned and get back to you. "
                "(Learning summary queries are handled in deeper reasoning.)"
            )
        return "I'm not sure how to handle that dynamic request yet."

    def teach_response(self, pattern, response):
        """Teach the engine a new pattern-response pair."""
        self.learned_responses[pattern.lower().strip()] = response
        return f"Learned: '{pattern}' -> '{response}'"

    def get_unmatched_queries(self, user_id=None):
        """Retrieve unmatched queries for analysis."""
        if user_id:
            return self.unmatched_queries.get(user_id, [])
        return dict(self.unmatched_queries)
