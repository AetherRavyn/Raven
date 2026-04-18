from __future__ import annotations

from app.core.models import IncomingRequest, ReplyTarget
from app.core.multimodal import MultimodalContextBuilder
from app.core.multimodal_retrieval import MultimodalRetriever


def test_image_attachments_remain_lightweight_hints() -> None:
    builder = MultimodalContextBuilder()
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="check this",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
        image_urls=["https://example.com/a.png"],
    )
    ctx = builder.from_request(request)
    rendered = ctx.render()
    assert "image attachment(s) available in monitoring only" in rendered


def test_retriever_stays_db_only_for_media() -> None:
    retriever = MultimodalRetriever(graph_tool=None)
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="show me the camera event",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
        image_urls=["https://example.com/a.png"],
    )
    # No semantic or video retrieval should run; notes explain the DB-only boundary.
    import asyncio

    bundle = asyncio.run(retriever.collect(request))
    assert bundle.notes
    assert any("DB-only" in note or "monitoring" in note for note in bundle.notes)
