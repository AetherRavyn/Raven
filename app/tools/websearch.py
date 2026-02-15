from __future__ import annotations

import warnings
from typing import Any, Dict, List

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class WebSearchTool(BaseTool):
    def __init__(self, google_api_key: str | None = None, model: Any | None = None):
        api_key = google_api_key or Config.GEMINI_API_KEY
        self._sdk_mode = "injected"
        self._client = None
        self._types = None
        self.model = None

        if model is not None:
            self.model = model
            return

        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        # Preferred SDK: google-genai
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            self._client = genai.Client(api_key=api_key)
            self._types = types
            self._sdk_mode = "new"
            return
        except ImportError:
            pass

        # Legacy fallback for environments not yet migrated.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                import google.generativeai as genai  # type: ignore
        except ImportError as e:
            raise ImportError(
                "Install `google-genai` (preferred) or `google-generativeai` for WebSearchTool."
            ) from e

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self._sdk_mode = "legacy"

    def get_name(self) -> str:
        return "web_search"

    def get_description(self) -> str:
        return "Perform a web search and return concise answer with sources."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query to execute",
                    required=True,
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        query = kwargs.get("query")
        if not query:
            return self._error("Missing required parameter: 'query'")

        try:
            if self._sdk_mode == "new":
                grounding_tool = self._types.Tool(
                    google_search=self._types.GoogleSearch()
                )
                config = self._types.GenerateContentConfig(tools=[grounding_tool])
                response = self._client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=query,
                    config=config,
                )
            else:
                # injected and legacy both use model.generate_content signature
                response = self.model.generate_content(
                    contents=query, tools="google_search_retrieval"
                )

            candidate = (getattr(response, "candidates", None) or [None])[0]
            original_text = getattr(response, "text", None)
            if not original_text and candidate:
                parts = getattr(getattr(candidate, "content", None), "parts", []) or []
                if parts:
                    original_text = getattr(parts[0], "text", None)

            if not original_text:
                return {
                    "llmContent": f"No search results found for: '{query}'",
                    "returnDisplay": {"error": "No results"},
                }

            grounding_metadata = getattr(candidate, "grounding_metadata", None)
            if not grounding_metadata:
                return {
                    "llmContent": original_text,
                    "returnDisplay": {"results": original_text},
                }

            final_text, source_list = self._process_grounding(
                original_text, grounding_metadata
            )
            return {
                "llmContent": final_text,
                "returnDisplay": {"summary": final_text, "sources": source_list},
            }
        except Exception as e:
            return self._error(f"Search failed: {str(e)}")

    def _process_grounding(
        self, text: str, metadata: Any
    ) -> tuple[str, List[Dict[str, Any]]]:
        chunks = getattr(metadata, "grounding_chunks", None) or []
        supports = getattr(metadata, "grounding_supports", None) or []

        if not chunks:
            return text, []

        formatted_sources: list[str] = []
        source_display_list: list[Dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            web = getattr(chunk, "web", None)
            title = getattr(web, "title", None) or "Untitled"
            uri = getattr(web, "uri", None) or "No URI"
            formatted_sources.append(f"[{i + 1}] {title} ({uri})")
            source_display_list.append({"index": i + 1, "title": title, "uri": uri})

        if not supports:
            final_text = text + "\n\nSources:\n" + "\n".join(formatted_sources)
            return final_text, source_display_list

        text_bytes = text.encode("utf-8")
        insertions: list[Dict[str, Any]] = []

        for support in supports:
            indices = getattr(support, "grounding_chunk_indices", None) or []
            segment = getattr(support, "segment", None)
            if indices and segment:
                marker = "".join([f"[{i + 1}]" for i in indices])
                end_index = int(getattr(segment, "end_index", len(text_bytes)))
                insertions.append({"pos": end_index, "marker": marker.encode("utf-8")})

        insertions.sort(key=lambda x: x["pos"], reverse=True)
        final_byte_array = bytearray(text_bytes)
        for ins in insertions:
            pos = min(ins["pos"], len(final_byte_array))
            final_byte_array[pos:pos] = ins["marker"]

        final_text = final_byte_array.decode("utf-8", errors="replace")
        final_text += "\n\nSources:\n" + "\n".join(formatted_sources)
        return final_text, source_display_list

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"llmContent": f"Error: {msg}", "returnDisplay": {"error": msg}}
