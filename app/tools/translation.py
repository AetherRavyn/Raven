"""Translation Tool — multi-language translation via multiple providers.

Supports:
- Google Translate (free, no API key)
- DeepL (API key required)
- LibreTranslate (self-hosted)

Auto-detects source language.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

# Language codes
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
    "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
    "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "sv": "Swedish",
}


class TranslationTool(BaseTool):
    """Multi-language translation via Google Translate (free) or DeepL."""

    def get_name(self) -> str:
        return "translate"

    def get_description(self) -> str:
        return "Translate text between languages. Auto-detects source language. Supports 100+ languages."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(name="text", type="string", required=True,
                             description="Text to translate"),
                ToolParameter(name="target_lang", type="string", required=True,
                             description="Target language code (e.g. 'es', 'fr', 'de')"),
                ToolParameter(name="source_lang", type="string", required=False,
                             description="Source language code (auto-detected if omitted)"),
                ToolParameter(name="provider", type="string", required=False,
                             description="Translation provider: google (default), deepl",
                             enum=["google", "deepl"]),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        text = kwargs.get("text", "")
        target_lang = kwargs.get("target_lang", "en")
        source_lang = kwargs.get("source_lang", "")
        provider = kwargs.get("provider", "google")

        if not text:
            return {"success": False, "error": "text is required"}

        try:
            if provider == "deepl":
                return await self._translate_deepl(text, target_lang, source_lang)
            else:
                return await self._translate_google(text, target_lang, source_lang)
        except Exception as e:
            logger.exception("TranslationTool error")
            return {"success": False, "error": str(e)}

    async def _translate_google(self, text: str, target_lang: str, source_lang: str) -> Dict[str, Any]:
        """Translate using Google Translate (free, no API key)."""
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": source_lang or "auto",
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            translated = "".join(part[0] for part in data[0] if part[0])
            detected_lang = data[2] if len(data) > 2 else "auto"
            return {
                "success": True,
                "translated": translated,
                "source_lang": detected_lang,
                "target_lang": target_lang,
                "provider": "google",
            }

    async def _translate_deepl(self, text: str, target_lang: str, source_lang: str) -> Dict[str, Any]:
        """Translate using DeepL API (requires API key)."""
        from app.settings.config import Config
        api_key = getattr(Config, "DEEPL_API_KEY", "")
        if not api_key:
            return {"success": False, "error": "DEEPL_API_KEY not configured"}

        url = "https://api-free.deepl.com/v2/translate"
        data = {
            "auth_key": api_key,
            "text": text,
            "target_lang": target_lang.upper(),
        }
        if source_lang:
            data["source_lang"] = source_lang.upper()

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            result = resp.json()
            translation = result["translations"][0]
            return {
                "success": True,
                "translated": translation["text"],
                "source_lang": translation.get("detected_source_language", source_lang),
                "target_lang": target_lang,
                "provider": "deepl",
            }
