from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    from deepgram import (
        AsyncDeepgramClient,
        DeepgramClient,
        LiveOptions,
        PrerecordedOptions,
    )
    from deepgram.core.events import EventType
except ImportError as exc:
    raise ImportError(
        "deepgram-sdk is required.  Install with: pip install deepgram-sdk"
    ) from exc


class DeepgramTool(BaseTool):
    """
    Agent tool for Deepgram speech-to-text.

    Operations
    ----------
    transcribe_file      – Transcribe a local audio/video file.
    transcribe_url       – Transcribe audio from a public URL.
    transcribe_live      – Real-time streaming transcription (sync WebSocket).
    transcribe_sagemaker – Real-time streaming via an AWS SageMaker endpoint
                           (requires ``deepgram-sagemaker``, Python 3.12+).
    """

    # ── BaseTool interface ────────────────────────────────────────────────────

    def get_name(self) -> str:
        return "deepgram"

    def get_description(self) -> str:
        return (
            "Deepgram speech-to-text tool: transcribe local audio files, "
            "remote audio URLs, real-time microphone streams, or live audio "
            "via AWS SageMaker endpoints.  Supports diarization, smart "
            "formatting, punctuation, and custom model selection."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    required=True,
                    description="Operation to perform.",
                    enum=[
                        "transcribe_file",
                        "transcribe_url",
                        "transcribe_live",
                        "transcribe_sagemaker",
                    ],
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    required=False,
                    description=(
                        "Absolute or relative path to a local audio/video file. "
                        "Required for 'transcribe_file'."
                    ),
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    required=False,
                    description=(
                        "Publicly accessible HTTPS URL of the audio resource. "
                        "Required for 'transcribe_url'."
                    ),
                ),
                ToolParameter(
                    name="audio_chunks",
                    type="array",
                    required=False,
                    description=(
                        "List of base64-encoded audio byte chunks to stream. "
                        "Required for 'transcribe_live' and 'transcribe_sagemaker'."
                    ),
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    required=False,
                    description="Deepgram model name (default: 'nova-3').",
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    required=False,
                    description="BCP-47 language code (default: 'en').",
                ),
                ToolParameter(
                    name="punctuate",
                    type="boolean",
                    required=False,
                    description="Add punctuation to the transcript (default: true).",
                ),
                ToolParameter(
                    name="smart_format",
                    type="boolean",
                    required=False,
                    description=(
                        "Apply smart formatting for numbers, dates, etc. "
                        "(default: true)."
                    ),
                ),
                ToolParameter(
                    name="diarize",
                    type="boolean",
                    required=False,
                    description="Enable speaker diarization (default: false).",
                ),
                ToolParameter(
                    name="encoding",
                    type="string",
                    required=False,
                    description=(
                        "PCM encoding of live audio chunks "
                        "(default: 'linear16').  Used by streaming operations."
                    ),
                ),
                ToolParameter(
                    name="sample_rate",
                    type="integer",
                    required=False,
                    description="Sample rate in Hz (default: 16000).",
                ),
                ToolParameter(
                    name="channels",
                    type="integer",
                    required=False,
                    description="Number of audio channels (default: 1).",
                ),
                ToolParameter(
                    name="interim_results",
                    type="boolean",
                    required=False,
                    description=(
                        "Emit partial transcripts during streaming (default: true)."
                    ),
                ),
                ToolParameter(
                    name="sagemaker_endpoint",
                    type="string",
                    required=False,
                    description=(
                        "AWS SageMaker endpoint name.  Falls back to the "
                        "DEEPGRAM_SAGEMAKER_ENDPOINT environment variable."
                    ),
                ),
                ToolParameter(
                    name="sagemaker_region",
                    type="string",
                    required=False,
                    description=(
                        "AWS region of the SageMaker endpoint (default: 'us-east-1')."
                    ),
                ),
                ToolParameter(
                    name="timeout",
                    type="number",
                    required=False,
                    description=(
                        "HTTP timeout in seconds for prerecorded requests "
                        "(default: 30)."
                    ),
                ),
                ToolParameter(
                    name="max_retries",
                    type="integer",
                    required=False,
                    description=(
                        "Retry attempts for failed requests (408/429/5xx) (default: 3)."
                    ),
                ),
            ],
        )

    # ── Main dispatcher ───────────────────────────────────────────────────────

    async def execute(
        self,
        operation: str,
        file_path: str | None = None,
        url: str | None = None,
        audio_chunks: list[str] | None = None,
        model: str = "nova-3",
        language: str = "en",
        punctuate: bool = True,
        smart_format: bool = True,
        diarize: bool = False,
        encoding: str = "linear16",
        sample_rate: int = 16_000,
        channels: int = 1,
        interim_results: bool = True,
        sagemaker_endpoint: str | None = None,
        sagemaker_region: str = "us-east-1",
        timeout: float = 30.0,
        max_retries: int = 3,
        **_: Any,
    ) -> Dict[str, Any]:

        try:
            if operation == "transcribe_file":
                return self._transcribe_file(
                    file_path=file_path,
                    model=model,
                    language=language,
                    punctuate=punctuate,
                    smart_format=smart_format,
                    diarize=diarize,
                    timeout=timeout,
                    max_retries=max_retries,
                )

            elif operation == "transcribe_url":
                return self._transcribe_url(
                    url=url,
                    model=model,
                    language=language,
                    punctuate=punctuate,
                    smart_format=smart_format,
                    diarize=diarize,
                    timeout=timeout,
                    max_retries=max_retries,
                )

            elif operation == "transcribe_live":
                return self._transcribe_live(
                    audio_chunks=audio_chunks,
                    model=model,
                    language=language,
                    encoding=encoding,
                    sample_rate=sample_rate,
                    channels=channels,
                    interim_results=interim_results,
                )

            elif operation == "transcribe_sagemaker":
                return await self._transcribe_sagemaker(
                    audio_chunks=audio_chunks,
                    model=model,
                    language=language,
                    encoding=encoding,
                    sample_rate=sample_rate,
                    channels=channels,
                    interim_results=interim_results,
                    endpoint_name=sagemaker_endpoint,
                    region=sagemaker_region,
                )

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── Operation implementations ─────────────────────────────────────────────

    def _transcribe_file(
        self,
        file_path: str | None,
        model: str,
        language: str,
        punctuate: bool,
        smart_format: bool,
        diarize: bool,
        timeout: float,
        max_retries: int,
    ) -> Dict[str, Any]:
        if not file_path:
            return {"success": False, "error": "file_path required"}

        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        client = self._make_client(timeout=timeout)
        options = PrerecordedOptions(
            model=model,
            language=language,
            punctuate=punctuate,
            smart_format=smart_format,
            diarize=diarize,
        )

        with open(path, "rb") as f:
            audio_data = {"buffer": f.read()}

        response = client.listen.v1.media.transcribe_file(
            request=audio_data,
            options=options,
            request_options={
                "timeout_in_seconds": timeout,
                "max_retries": max_retries,
            },
        )

        return {
            "success": True,
            "operation": "transcribe_file",
            "file": str(path),
            **self._parse_prerecorded(response),
        }

    def _transcribe_url(
        self,
        url: str | None,
        model: str,
        language: str,
        punctuate: bool,
        smart_format: bool,
        diarize: bool,
        timeout: float,
        max_retries: int,
    ) -> Dict[str, Any]:
        if not url:
            return {"success": False, "error": "url required"}

        client = self._make_client(timeout=timeout)
        options = PrerecordedOptions(
            model=model,
            language=language,
            punctuate=punctuate,
            smart_format=smart_format,
            diarize=diarize,
        )

        response = client.listen.v1.media.transcribe_url(
            request={"url": url},
            options=options,
            request_options={
                "timeout_in_seconds": timeout,
                "max_retries": max_retries,
            },
        )

        return {
            "success": True,
            "operation": "transcribe_url",
            "url": url,
            **self._parse_prerecorded(response),
        }

    def _transcribe_live(
        self,
        audio_chunks: list[str] | None,
        model: str,
        language: str,
        encoding: str,
        sample_rate: int,
        channels: int,
        interim_results: bool,
    ) -> Dict[str, Any]:
        import base64

        if not audio_chunks:
            return {"success": False, "error": "audio_chunks required"}

        client = self._make_client()
        options = LiveOptions(
            model=model,
            language=language,
            encoding=encoding,
            sample_rate=sample_rate,
            channels=channels,
            interim_results=interim_results,
            smart_format=True,
        )

        segments: list[dict] = []

        def _on_message(self_conn, result, **kwargs):
            try:
                alt = result.channel.alternatives[0]
                if alt.transcript and result.is_final:
                    segments.append(
                        {"transcript": alt.transcript, "confidence": alt.confidence}
                    )
            except (AttributeError, IndexError):
                pass

        with client.listen.v1.connect(options=options) as conn:
            conn.on(EventType.TRANSCRIPT_RECEIVED, _on_message)
            conn.start_listening()

            for chunk_b64 in audio_chunks:
                conn.send(base64.b64decode(chunk_b64))

            conn.finish()

        return {
            "success": True,
            "operation": "transcribe_live",
            "transcript": " ".join(s["transcript"] for s in segments),
            "segments": segments,
            "segment_count": len(segments),
        }

    async def _transcribe_sagemaker(
        self,
        audio_chunks: list[str] | None,
        model: str,
        language: str,
        encoding: str,
        sample_rate: int,
        channels: int,
        interim_results: bool,
        endpoint_name: str | None,
        region: str,
    ) -> Dict[str, Any]:
        import base64

        if not audio_chunks:
            return {"success": False, "error": "audio_chunks required"}

        resolved_endpoint = endpoint_name or os.environ.get(
            "DEEPGRAM_SAGEMAKER_ENDPOINT", ""
        )
        if not resolved_endpoint:
            return {
                "success": False,
                "error": (
                    "SageMaker endpoint name required.  "
                    "Pass sagemaker_endpoint= or set DEEPGRAM_SAGEMAKER_ENDPOINT."
                ),
            }

        try:
            from deepgram_sagemaker import SageMakerTransportFactory
        except ImportError:
            return {
                "success": False,
                "error": (
                    "deepgram-sagemaker not installed.  "
                    "Run: pip install deepgram-sagemaker  (Python 3.12+)"
                ),
            }

        factory = SageMakerTransportFactory(
            endpoint_name=resolved_endpoint,
            region=region,
        )
        async_client = AsyncDeepgramClient(
            api_key="unused",  # SageMaker uses AWS credentials, not Deepgram keys
            transport_factory=factory,
        )

        options = LiveOptions(
            model=model,
            language=language,
            encoding=encoding,
            sample_rate=sample_rate,
            channels=channels,
            interim_results=interim_results,
            smart_format=True,
        )

        segments: list[dict] = []

        def _on_message(self_conn, result, **kwargs):
            try:
                alt = result.channel.alternatives[0]
                if alt.transcript and result.is_final:
                    segments.append(
                        {"transcript": alt.transcript, "confidence": alt.confidence}
                    )
            except (AttributeError, IndexError):
                pass

        async with async_client.listen.v1.connect(options=options) as conn:
            conn.on(EventType.TRANSCRIPT_RECEIVED, _on_message)
            await conn.start_listening()

            for chunk_b64 in audio_chunks:
                await conn.send(base64.b64decode(chunk_b64))

            await conn.finish()

        return {
            "success": True,
            "operation": "transcribe_sagemaker",
            "endpoint": resolved_endpoint,
            "transcript": " ".join(s["transcript"] for s in segments),
            "segments": segments,
            "segment_count": len(segments),
        }

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _make_client(timeout: float = 30.0) -> DeepgramClient:
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY environment variable is not set.")
        return DeepgramClient(api_key=api_key, timeout=timeout)

    @staticmethod
    def _parse_prerecorded(response) -> Dict[str, Any]:
        try:
            alt = response.results.channels[0].alternatives[0]
            words = [
                w.to_dict() if hasattr(w, "to_dict") else {} for w in (alt.words or [])
            ]
            return {
                "transcript": alt.transcript,
                "confidence": alt.confidence,
                "words": words,
            }
        except (AttributeError, IndexError, KeyError) as exc:
            logger.warning("Could not parse Deepgram response: %s", exc)
            return {"transcript": "", "confidence": 0.0, "words": []}
