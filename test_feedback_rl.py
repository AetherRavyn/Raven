from __future__ import annotations

from app.core.feedback import FeedbackStore
from app.core.model_router import ModelRouter


def test_feedback_store_records_and_scores(tmp_path) -> None:
    store = FeedbackStore(str(tmp_path))
    store.add_feedback("u1", "route", "local", 1.0, reason="good")
    store.add_feedback("u1", "route", "local", -1.0, reason="bad")
    assert store.score("route", "local", "u1") == 0.0
    summary = store.summary("u1")
    assert summary["count"] == 2


def test_model_router_records_feedback(tmp_path) -> None:
    router = ModelRouter(default_provider=object(), default_model="m")
    router.feedback = FeedbackStore(str(tmp_path))
    router.record_feedback("local", 1.0, reason="good")
    assert router.feedback.score("route", "local") == 1.0
