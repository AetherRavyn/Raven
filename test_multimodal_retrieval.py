from __future__ import annotations

from unittest import mock

import pytest

from app.core.models import IncomingRequest, ReplyTarget
from app.core.multimodal_retrieval import MultimodalRetriever


class _GraphToolStub:
    async def execute(self, **kwargs):
        if kwargs.get("operation") == "query_entity":
            return {"success": True, "connections": ["[User] --(OWNS)--> [Laptop]"]}
        return {"success": False}


@pytest.mark.asyncio
async def test_multimodal_retriever_collects_graph_hits(monkeypatch):
    retriever = MultimodalRetriever(graph_tool=_GraphToolStub())
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="Tell me about User Laptop",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
    )
    bundle = await retriever.collect(request)
    assert bundle.event_payloads
    assert bundle.graph_hits


@pytest.mark.asyncio
async def test_multimodal_retriever_handles_no_image_hits(monkeypatch):
    retriever = MultimodalRetriever(graph_tool=_GraphToolStub())
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="plain text only",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
    )
    bundle = await retriever.collect(request)
    assert bundle.notes == ["No additional multimodal evidence found."]
