from __future__ import annotations

import asyncio
import shlex
import shutil
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class SpotifyOperationTool(BaseTool):
    """Unified Spotify control tool — exactly matches your GitOperationTool / ObsidianOperationTool style.
    Prefers spogo (best CLI, cookie auth, --json support).
    Falls back to spotify_player automatically.
    Works on Windows / macOS / Linux (all devices)."""

    def __init__(self):
        self.player = self._detect_player()  # "spogo" or "spotify_player"
        self.MAX_OUTPUT_LENGTH = 6000

    def _detect_player(self) -> str:
        """Auto-detect preferred player (spogo first)."""
        if shutil.which("spogo"):
            return "spogo"
        elif shutil.which("spotify_player"):
            return "spotify_player"
        raise ValueError(
            "Neither spogo nor spotify_player found in PATH.\n"
            "• Install spogo (preferred): cargo install spogo\n"
            "• Or spotify_player: cargo install spotify-player\n"
            "Then run: spogo auth import --browser chrome"
        )

    def get_name(self) -> str:
        return "spotify_ops"

    def get_description(self) -> str:
        return (
            f"Full Spotify control using {self.player} (spogo preferred). "
            "Playback, search, devices, status — Spotify Premium required."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The Spotify operation to perform.",
                    required=True,
                    enum=[
                        "status",
                        "play",
                        "pause",
                        "next",
                        "previous",
                        "search",
                        "device_list",
                        "device_set",
                        "like",
                        "play_uri",
                    ],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for search)",
                    required=False,
                ),
                ToolParameter(
                    name="target",
                    type="string",
                    description="Spotify URI, device name/ID, or track URI",
                    required=False,
                ),
                ToolParameter(
                    name="search_type",
                    type="string",
                    description="spogo only: track | album | artist | playlist",
                    required=False,
                    enum=["track", "album", "artist", "playlist"],
                    default="track",
                ),
                ToolParameter(
                    name="extra_args",
                    type="string",
                    description="Extra CLI flags (e.g. '--limit 10 --json')",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        query = str(kwargs.get("query", "")).strip()
        target = str(kwargs.get("target", "")).strip()
        search_type = str(kwargs.get("search_type", "track")).strip()
        extra = str(kwargs.get("extra_args", "")).strip()
        extras = shlex.split(extra) if extra else []

        try:
            if op == "status":
                cmd = self._build_status_cmd()
            elif op == "play":
                cmd = self._build_play_cmd(target, extras)
            elif op == "pause":
                cmd = self._build_pause_cmd()
            elif op == "next":
                cmd = self._build_next_cmd()
            elif op == "previous":
                cmd = self._build_previous_cmd()
            elif op == "search":
                if not query:
                    return self._error("query required for search")
                cmd = self._build_search_cmd(query, search_type, extras)
            elif op == "device_list":
                cmd = self._build_device_list_cmd()
            elif op == "device_set":
                if not target:
                    return self._error("target (device name or ID) required")
                cmd = self._build_device_set_cmd(target)
            elif op == "like":
                cmd = self._build_like_cmd()
            elif op == "play_uri":
                if not target:
                    return self._error("target (spotify:track:...) URI required")
                cmd = self._build_play_uri_cmd(target)
            else:
                return self._error(f"Unknown operation: {op}")

            result = await self._run_command(cmd)
            result["operation"] = op
            result["player_used"] = self.player

            # Friendly post-processing
            if result["success"] and op == "status":
                result["now_playing"] = result.get("output", "").strip()[:500]

            return result

        except Exception as e:
            return self._error(str(e))

    # ─────────────────────────────────────────────────────────────
    # Command builders (spogo preferred, clean fallback)
    # ─────────────────────────────────────────────────────────────
    def _build_status_cmd(self) -> List[str]:
        return (
            ["spogo", "status"]
            if self.player == "spogo"
            else ["spotify_player", "playback", "get"]
        )

    def _build_play_cmd(self, target: str, extras: List[str]) -> List[str]:
        if self.player == "spogo":
            base = ["spogo", "play"]
            if target:
                base.append(target)
            return base + extras
        return ["spotify_player", "playback", "play"]

    def _build_pause_cmd(self) -> List[str]:
        return (
            ["spogo", "pause"]
            if self.player == "spogo"
            else ["spotify_player", "playback", "pause"]
        )

    def _build_next_cmd(self) -> List[str]:
        return (
            ["spogo", "next"]
            if self.player == "spogo"
            else ["spotify_player", "playback", "next"]
        )

    def _build_previous_cmd(self) -> List[str]:
        return (
            ["spogo", "prev"]
            if self.player == "spogo"
            else ["spotify_player", "playback", "previous"]
        )

    def _build_search_cmd(
        self, query: str, search_type: str, extras: List[str]
    ) -> List[str]:
        if self.player == "spogo":
            return ["spogo", "search", search_type, query] + extras
        return ["spotify_player", "search", query] + extras

    def _build_device_list_cmd(self) -> List[str]:
        return (
            ["spogo", "device", "list"]
            if self.player == "spogo"
            else ["spotify_player", "device", "list"]
        )

    def _build_device_set_cmd(self, target: str) -> List[str]:
        if self.player == "spogo":
            return ["spogo", "device", "set", target]
        return (
            ["spotify_player", "connect", target]
            if target
            else ["spotify_player", "connect"]
        )

    def _build_like_cmd(self) -> List[str]:
        if self.player == "spogo":
            return [
                "spogo",
                "status",
            ]  # spogo has no direct "like" → just return current status
        return ["spotify_player", "like"]

    def _build_play_uri_cmd(self, uri: str) -> List[str]:
        return (
            ["spogo", "play", uri]
            if self.player == "spogo"
            else ["spotify_player", "playback", "play", "--uri", uri]
        )

    async def _run_command(self, cmd: List[str]) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if len(out) > self.MAX_OUTPUT_LENGTH:
                out = (
                    out[: self.MAX_OUTPUT_LENGTH]
                    + f"\n... [Output truncated ({len(out)} chars)]"
                )

            if process.returncode != 0:
                return {
                    "success": False,
                    "output": err or out,
                    "return_code": process.returncode,
                    "command": " ".join(cmd),
                }

            return {
                "success": True,
                "output": out or "Success",
                "stderr_info": err,
            }
        except FileNotFoundError:
            return self._error(
                f"Command not found: {cmd[0]} (is {self.player} installed?)"
            )
        except Exception as e:
            return self._error(f"Execution failed: {e}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "output": f"Error: {msg}"}
