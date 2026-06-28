from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.settings.config import Config


class XAIGrpcClient:
    """Minimal xAI gRPC Chat client.

    Notes:
    - Expects generated protobuf modules for xAI Chat API to be available.
    - Uses `Authorization: Bearer <XAI_API_KEY>` metadata per request.
    """

    def __init__(
        self,
        api_key: str | None = None,
        host: str | None = None,
        timeout_seconds: float = 60.0,
        *,
        proto: Any | None = None,
        stub: Any | None = None,
        channel: Any | None = None,
    ) -> None:
        self.api_key = api_key or Config.XAI_API_KEY
        self.host = host or Config.XAI_GRPC_HOST
        self.timeout_seconds = timeout_seconds

        if not self.api_key:
            raise ValueError("XAI_API_KEY is not configured")

        self._proto = proto
        self._stub = stub
        self._channel = channel

        if self._proto is None or self._stub is None:
            self._init_grpc_default()

    def _init_grpc_default(self) -> None:
        try:
            import grpc  # type: ignore
        except ImportError as e:
            raise ImportError("grpcio is required for XAIGrpcClient. Install `grpcio`.") from e

        # Try common generated module locations.
        chat_pb2 = None
        chat_pb2_grpc = None
        import_errors: list[str] = []

        for mod_pair in (
            ("xai.api.v1.chat_pb2", "xai.api.v1.chat_pb2_grpc"),
            ("chat_pb2", "chat_pb2_grpc"),
        ):
            try:
                chat_pb2 = __import__(mod_pair[0], fromlist=["*"])
                chat_pb2_grpc = __import__(mod_pair[1], fromlist=["*"])
                break
            except Exception as e:  # pragma: no cover - best effort import path
                import_errors.append(f"{mod_pair[0]} / {mod_pair[1]}: {e}")

        if chat_pb2 is None or chat_pb2_grpc is None:
            raise ImportError(
                "Could not import xAI generated gRPC stubs. "
                "Expected modules like `xai.api.v1.chat_pb2` and `chat_pb2_grpc`. "
                f"Errors: {'; '.join(import_errors)}"
            )

        creds = grpc.ssl_channel_credentials()
        self._channel = grpc.secure_channel(self.host, creds)
        self._proto = chat_pb2
        self._stub = chat_pb2_grpc.ChatStub(self._channel)

    def _metadata(self) -> list[tuple[str, str]]:
        return [("authorization", f"Bearer {self.api_key}")]

    def _role_value(self, role: str) -> int:
        role_lower = role.lower().strip()
        mapping = {
            "user": getattr(self._proto, "ROLE_USER"),
            "assistant": getattr(self._proto, "ROLE_ASSISTANT"),
            "system": getattr(self._proto, "ROLE_SYSTEM"),
            "tool": getattr(self._proto, "ROLE_TOOL"),
            "developer": getattr(self._proto, "ROLE_DEVELOPER"),
        }
        return mapping.get(role_lower, getattr(self._proto, "ROLE_USER"))

    def _build_messages(self, messages: List[Dict[str, Any]]) -> list[Any]:
        out = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts = self._build_content_parts(content)
            msg = self._proto.Message(role=self._role_value(role), content=parts)
            out.append(msg)
        return out

    def _detail_value(self, detail: str | None) -> int:
        detail_name = (detail or "auto").strip().lower()
        mapping = {
            "auto": getattr(self._proto, "DETAIL_AUTO", 1),
            "low": getattr(self._proto, "DETAIL_LOW", 2),
            "high": getattr(self._proto, "DETAIL_HIGH", 3),
        }
        return mapping.get(detail_name, getattr(self._proto, "DETAIL_AUTO", 1))

    def _build_content_parts(self, raw_content: Any) -> list[Any]:
        if raw_content is None:
            return [self._proto.Content(text="")]

        if isinstance(raw_content, str):
            return [self._proto.Content(text=raw_content)]

        if not isinstance(raw_content, list):
            return [self._proto.Content(text=str(raw_content))]

        out: list[Any] = []
        for part in raw_content:
            if isinstance(part, str):
                out.append(self._proto.Content(text=part))
                continue

            if not isinstance(part, dict):
                out.append(self._proto.Content(text=str(part)))
                continue

            part_type = str(part.get("type", "text")).strip().lower()
            if part_type == "image_url":
                image_url = part.get("image_url") or part.get("url") or part.get("image") or ""
                detail = self._detail_value(part.get("detail"))
                out.append(
                    self._proto.Content(
                        image_url=self._proto.ImageUrlContent(
                            image_url=str(image_url),
                            detail=detail,
                        )
                    )
                )
                continue

            text = part.get("text") or part.get("content") or ""
            out.append(self._proto.Content(text=str(text)))

        return out or [self._proto.Content(text="")]

    def _build_request(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Any:
        req = self._proto.GetCompletionsRequest(
            model=model, messages=self._build_messages(messages)
        )
        if max_tokens is not None:
            req.max_tokens = int(max_tokens)
        if temperature is not None:
            req.temperature = float(temperature)
        if top_p is not None:
            req.top_p = float(top_p)
        if user:
            req.user = user
        return req

    @staticmethod
    def _extract_output_content(response: Any) -> str:
        outputs = getattr(response, "outputs", None) or []
        texts: list[str] = []
        for out in outputs:
            msg = getattr(out, "message", None)
            if msg is not None:
                text = getattr(msg, "content", "")
                if text:
                    texts.append(text)
        return "\n".join(texts).strip()

    def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        request = self._build_request(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            user=user,
        )
        response = self._stub.GetCompletion(
            request, metadata=self._metadata(), timeout=self.timeout_seconds
        )
        return {
            "success": True,
            "content": self._extract_output_content(response),
            "raw": response,
        }

    def chat_completion_stream(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Iterable[Dict[str, Any]]:
        request = self._build_request(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            user=user,
        )
        stream = self._stub.GetCompletionChunk(
            request, metadata=self._metadata(), timeout=self.timeout_seconds
        )
        for chunk in stream:
            outputs = getattr(chunk, "outputs", None) or []
            delta_texts: list[str] = []
            for out in outputs:
                delta = getattr(out, "delta", None)
                if delta is not None:
                    text = getattr(delta, "content", "")
                    if text:
                        delta_texts.append(text)
            yield {"success": True, "delta": "".join(delta_texts), "raw": chunk}

    def chat_completion_with_image(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
        image_detail: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": image_url,
                        "detail": image_detail,
                    },
                ],
            }
        ]
        return self.chat_completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            user=user,
        )
