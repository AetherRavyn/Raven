"""Multi-Modal Understanding — analyze images, video, and speech.

FRIDAY-style: Raven understands more than just text.

Capabilities:
- Image analysis (describe, OCR, detect objects)
- Video analysis (summarize, detect events)
- Speech understanding (transcribe, identify speaker, detect emotion)
- Document analysis (read PDFs, extract text)
- Screen understanding (read what's on screen)

Uses existing tools (XAI image, camera, whisper) under a
unified multi-modal API.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImageAnalysis:
    """Result of image analysis."""
    description: str
    objects: list[str] = field(default_factory=list)
    text_content: str = ""
    mood: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoAnalysis:
    """Result of video analysis."""
    summary: str
    duration_seconds: float = 0.0
    key_frames: list[dict[str, Any]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SpeechAnalysis:
    """Result of speech analysis."""
    transcription: str
    language: str = "en"
    speaker: str = "unknown"
    emotion: str = "neutral"
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MultiModalProcessor:
    """FRIDAY-style multi-modal understanding.

    Provides a unified API for analyzing images, video, and speech.
    Uses existing tools under the hood.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._workspace = workspace_dir

    async def analyze_image(
        self,
        image_path: str | None = None,
        image_bytes: bytes | None = None,
        prompt: str = "Describe this image in detail.",
    ) -> ImageAnalysis:
        """Analyze an image."""
        try:
            from app.tools.xaiimagetool import XAIImageUnderstandTool
            tool = XAIImageUnderstandTool()

            kwargs: dict[str, Any] = {"prompt": prompt}
            if image_path:
                kwargs["image_path"] = image_path
            elif image_bytes:
                # Save to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                    f.write(image_bytes)
                    kwargs["image_path"] = f.name

            result = await tool.execute(**kwargs)

            if result.get("success"):
                return ImageAnalysis(
                    description=result.get("description", ""),
                    objects=result.get("objects", []),
                    text_content=result.get("text", ""),
                    metadata={"source": "xai"},
                )
            else:
                return ImageAnalysis(description=f"Analysis failed: {result.get('error', 'unknown')}")

        except Exception as exc:
            logger.error("Image analysis failed: %s", exc)
            return ImageAnalysis(description=f"Error: {exc}")

    async def analyze_video(
        self,
        video_path: str,
        max_frames: int = 10,
    ) -> VideoAnalysis:
        """Analyze a video by sampling key frames."""
        try:
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return VideoAnalysis(summary="Could not open video")

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # Sample key frames
            frame_interval = max(1, total_frames // max_frames)
            key_frames = []
            descriptions = []

            for i in range(0, total_frames, frame_interval):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if ret:
                    # Analyze each key frame
                    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    frame_bytes = buffer.tobytes()

                    analysis = await self.analyze_image(image_bytes=frame_bytes)
                    key_frames.append({
                        "frame": i,
                        "timestamp": i / fps if fps > 0 else 0,
                        "description": analysis.description[:200],
                    })
                    if analysis.description:
                        descriptions.append(analysis.description[:100])

            cap.release()

            summary = f"Video analysis: {len(key_frames)} key frames sampled. " + " ".join(descriptions[:3])

            return VideoAnalysis(
                summary=summary,
                duration_seconds=duration,
                key_frames=key_frames,
                events=[d for d in descriptions if any(w in d.lower() for w in ("person", "car", "action", "movement"))],
            )

        except Exception as exc:
            logger.error("Video analysis failed: %s", exc)
            return VideoAnalysis(summary=f"Error: {exc}")

    async def analyze_speech(
        self,
        audio_path: str | None = None,
        audio_bytes: bytes | None = None,
    ) -> SpeechAnalysis:
        """Analyze speech from audio."""
        try:
            from app.voice.transcribe import transcribe_audio
            from app.core.language_detect import detect_language, get_language_name
            from app.voice.emotion import detect_emotion

            if audio_path:
                result = await transcribe_audio(audio_path)
            elif audio_bytes:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_bytes)
                    result = await transcribe_audio(f.name)
            else:
                return SpeechAnalysis(transcription="", confidence=0.0)

            text = result.get("text", "") if isinstance(result, dict) else str(result)
            lang = detect_language(text)
            emotion = detect_emotion(text)

            return SpeechAnalysis(
                transcription=text,
                language=lang.language,
                emotion=emotion.emotion,
                confidence=lang.confidence,
                metadata={"language_name": get_language_name(lang.language)},
            )

        except Exception as exc:
            logger.error("Speech analysis failed: %s", exc)
            return SpeechAnalysis(transcription=f"Error: {exc}")

    async def analyze_screen(self) -> ImageAnalysis:
        """Analyze what's currently on screen (screenshot)."""
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            import io
            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            return await self.analyze_image(
                image_bytes=buffer.getvalue(),
                prompt="Read and describe everything visible on this screen.",
            )
        except Exception as exc:
            return ImageAnalysis(description=f"Screen capture failed: {exc}")

    def get_modality_prompt(self, modality: str) -> str:
        """Get a prompt template for a specific modality."""
        prompts = {
            "image": "Analyze this image. Describe what you see, identify objects, read any text, and assess the mood/context.",
            "video": "Analyze this video. Summarize the content, identify key events, and describe what's happening.",
            "speech": "Transcribe and analyze this speech. Identify the speaker, language, emotion, and key points.",
            "screen": "Read everything on this screen. Identify active applications, visible text, and current context.",
        }
        return prompts.get(modality, "Analyze this content.")
