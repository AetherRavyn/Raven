from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

LSP_SERVERS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "python_alt": ["pylsp"],
    "javascript": ["typescript-language-server", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "rust": ["rust-analyzer"],
    "c": ["clangd"],
    "cpp": ["clangd"],
    "go": ["gopls"],
}

FILE_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".go": "go",
}


def detect_language(file_path: str) -> str | None:
    import os

    ext = os.path.splitext(file_path)[1].lower()
    return FILE_LANGUAGE_MAP.get(ext)


@dataclass
class Diagnostic:
    severity: int
    message: str
    file_path: str
    line: int
    column: int
    end_line: int
    end_column: int
    source: str = ""
    code: str = ""


SEVERITY_MAP = {1: "error", 2: "warning", 3: "info", 4: "hint"}


class LSPClient:
    def __init__(self, language: str, server_command: list[str]) -> None:
        self.language = language
        self.server_command = server_command
        self._process: asyncio.subprocess.Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._request_id = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._diagnostics: dict[str, list[Diagnostic]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._initialized = False
        self._shutdown = False

    async def start(self) -> bool:
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error(
                "LSP server not found for %s: %s",
                self.language,
                self.server_command[0],
            )
            return False
        except Exception as e:
            logger.error("Failed to start LSP server for %s: %s", self.language, e)
            return False

        self._writer = self._process.stdin
        self._reader = self._process.stdout
        if self._writer is None or self._reader is None:
            logger.error("LSP process streams not available for %s", self.language)
            return False

        self._reader_task = asyncio.create_task(self._read_loop())

        result = await self._send_request(
            "initialize",
            {
                "processId": None,
                "capabilities": {
                    "textDocument": {
                        "diagnostics": True,
                        "codeAction": True,
                    },
                },
            },
        )
        if result is None:
            logger.error("LSP initialization failed for %s", self.language)
            await self.stop()
            return False

        await self._send_notification("initialized", {})
        self._initialized = True
        logger.info("LSP client initialized for %s", self.language)
        return True

    async def open_file(self, file_path: str, language_id: str) -> None:
        if not self._initialized:
            logger.warning("Cannot open file: LSP client not initialized for %s", self.language)
            return
        uri = self._path_to_uri(file_path)
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": "",
                },
            },
        )
        logger.debug("Opened file in LSP: %s", file_path)

    async def update_file(self, file_path: str, text: str, version: int) -> None:
        if not self._initialized:
            return
        uri = self._path_to_uri(file_path)
        await self._send_notification(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": uri,
                    "version": version,
                },
                "contentChanges": [
                    {"text": text},
                ],
            },
        )

    async def close_file(self, file_path: str) -> None:
        if not self._initialized:
            return
        uri = self._path_to_uri(file_path)
        await self._send_notification(
            "textDocument/didClose",
            {
                "textDocument": {"uri": uri},
            },
        )
        self._diagnostics.pop(file_path, None)

    async def get_diagnostics(self, file_path: str | None = None) -> list[Diagnostic]:
        if file_path:
            return list(self._diagnostics.get(file_path, []))
        result: list[Diagnostic] = []
        for diags in self._diagnostics.values():
            result.extend(diags)
        return result

    async def get_code_actions(self, file_path: str, line: int, column: int) -> list[dict]:
        if not self._initialized:
            return []
        uri = self._path_to_uri(file_path)
        result = await self._send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": uri},
                "range": {
                    "start": {"line": line, "character": column},
                    "end": {"line": line, "character": column + 1},
                },
                "context": {
                    "diagnostics": [
                        d
                        for d in self._diagnostics.get(file_path, [])
                        if d.line <= line <= d.end_line
                    ],
                },
            },
        )
        if result is None:
            return []
        return result if isinstance(result, list) else []

    async def execute_code_action(self, action: dict) -> bool:
        if not self._initialized:
            return False
        command = action.get("command")
        if command:
            result = await self._send_request(
                "workspace/executeCommand",
                {
                    "command": command,
                    "arguments": action.get("arguments", []),
                },
            )
            return result is not None
        edit = action.get("edit")
        if edit:
            for changes in edit.get("changes", {}).values():
                for _ in changes:
                    pass
            return True
        return False

    async def stop(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        if self._initialized:
            await self._send_request("shutdown", {})
            await self._send_notification("exit", {})
        self._initialized = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.warning("Error stopping LSP process: %s", e)
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._writer = None
        self._reader = None
        self._process = None
        logger.info("LSP client stopped for %s", self.language)

    async def _send_request(self, method: str, params: dict) -> dict | None:
        if self._shutdown:
            return None
        self._request_id += 1
        request_id = str(self._request_id)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write_message(payload)
            result = await asyncio.wait_for(future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            logger.warning("LSP request timed out: %s (id=%s)", method, request_id)
            self._pending.pop(request_id, None)
            return None
        except Exception as e:
            logger.warning("LSP request error %s: %s", method, e)
            self._pending.pop(request_id, None)
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        if self._shutdown:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            await self._write_message(payload)
        except Exception as e:
            logger.warning("LSP notification error %s: %s", method, e)

    async def _write_message(self, payload: dict) -> None:
        if self._writer is None:
            raise RuntimeError("LSP writer not available")
        body = json.dumps(payload)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        self._writer.write(header.encode("utf-8"))
        self._writer.write(body.encode("utf-8"))
        await self._writer.drain()

    async def _read_loop(self) -> None:
        if self._reader is None:
            return
        try:
            while not self._shutdown:
                message = await self._read_message()
                if message is None:
                    break
                self._dispatch_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("LSP read loop error: %s", e)

    async def _read_message(self) -> dict | None:
        if self._reader is None:
            return None
        try:
            content_length = 0
            while True:
                line = await asyncio.wait_for(self._reader.readline(), timeout=30.0)
                if not line:
                    return None
                header_line = line.decode("utf-8").strip()
                if not header_line:
                    break
                if header_line.lower().startswith("content-length:"):
                    content_length = int(header_line.split(":")[1].strip())
            if content_length <= 0:
                return None
            body = await asyncio.wait_for(self._reader.readexactly(content_length), timeout=30.0)
            return json.loads(body.decode("utf-8"))
        except asyncio.TimeoutError:
            return None
        except asyncio.IncompleteReadError:
            return None
        except json.JSONDecodeError:
            return None

    def _dispatch_message(self, message: dict) -> None:
        if "id" in message and message.get("id") in self._pending:
            request_id = str(message["id"])
            future = self._pending.pop(request_id, None)
            if future is not None and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"].get("message", "LSP error")))
                else:
                    result = message.get("result")
                    if result is not None:
                        future.set_result(result)
                    else:
                        future.set_result({})
        elif "method" in message:
            method = message["method"]
            params = message.get("params", {})
            if method == "textDocument/publishDiagnostics":
                self._handle_publish_diagnostics(params)

    def _handle_publish_diagnostics(self, params: dict) -> None:
        uri = params.get("uri", "")
        file_path = self._uri_to_path(uri)
        diags = params.get("diagnostics", [])
        parsed: list[Diagnostic] = []
        for d in diags:
            range_data = d.get("range", {})
            start = range_data.get("start", {})
            end = range_data.get("end", {})
            parsed.append(
                Diagnostic(
                    severity=d.get("severity", 0),
                    message=d.get("message", ""),
                    file_path=file_path,
                    line=start.get("line", 0),
                    column=start.get("character", 0),
                    end_line=end.get("line", 0),
                    end_column=end.get("character", 0),
                    source=d.get("source", ""),
                    code=str(d.get("code", "")),
                )
            )
        self._diagnostics[file_path] = parsed
        logger.debug("Received %d diagnostics for %s", len(parsed), file_path)

    @staticmethod
    def _path_to_uri(file_path: str) -> str:
        import urllib.parse

        return "file://" + urllib.parse.quote(file_path, safe="/:@")

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        import urllib.parse

        parsed = urllib.parse.urlparse(uri)
        return urllib.parse.unquote(parsed.path)


class LSPClientManager:
    _instances: dict[str, LSPClient] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_client(cls, language: str) -> LSPClient | None:
        async with cls._lock:
            if language in cls._instances:
                return cls._instances[language]
            server_command = LSP_SERVERS.get(language)
            if not server_command:
                logger.warning("No LSP server configured for language: %s", language)
                return None
            client = LSPClient(language, server_command)
            started = await client.start()
            if not started:
                return None
            cls._instances[language] = client
            return client

    @classmethod
    async def shutdown_all(cls) -> None:
        async with cls._lock:
            for language, client in list(cls._instances.items()):
                try:
                    await client.stop()
                except Exception as e:
                    logger.warning("Error shutting down LSP client %s: %s", language, e)
            cls._instances.clear()
