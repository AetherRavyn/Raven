"""Shared pytest fixtures for the RAVEN test suite.

The single most important fixture here is :func:`isolated_outbox`,
which makes the durable :class:`app.runtime.outbox.Outbox` write to
a per-session temp file and resets the process-wide singleton
between tests.  Without this, every test that goes through
:class:`app.core.botsignal.BotSignal` would inherit the host's
``~/.raven/runtime/outbox.jsonl`` (which has live "sent" entries
from real prior runs) and the outbox's idempotency dedup would
silently swallow the test's first send.

The second autouse fixture, :func:`fake_helix_in_process`,
swaps every ``HelixClient`` constructed during the test with
:class:`tests_harness.fake_helix.FakeHelixClient`.  This
removes the Docker-gateway requirement from the live Helix
integration tests; they now run in CI without a sidecar.

The v31 cycle (Hermes-class dashboard, 2026-06-21) adds:

- :func:`dashboard_test_env` — autouse, sets ``HF_HUB_OFFLINE=1``
  so the page-render tests don't trigger a HuggingFace model
  download via the lazy sentence-transformers load in the
  memory store; also resets the InProcBus subscriber set between
  tests.
- :func:`isolated_singleton` — autouse, snapshots every class
  attribute on :class:`app.settings.config.Config` and restores
  them on teardown.  Without this, a test that mutates
  ``Config.LLM_MODEL = "..."`` would leak into the next test.
- :func:`dashboard_client` — session-scoped, builds a
  ``WebDashboard._app`` once and wraps it in a
  ``fastapi.testclient.TestClient`` so the v31 tests don't pay
  the construction cost per test.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_outbox(tmp_path: Path) -> Generator[None, None, None]:
    """Point the process-wide Outbox at a per-test temp file.

    Two pieces of state are reset:

    1. ``RAVEN_OUTBOX_PATH`` is set to ``tmp_path/outbox.jsonl`` for
       the duration of the test.  The next ``get_outbox()`` call
       will read this env var and create the singleton at that path.
    2. The cached singleton itself is dropped via
       :func:`app.runtime.outbox.reset_outbox_for_tests` so a
       previously-created outbox (from a sibling test, or from an
       earlier collection) does not leak in.

    After the test, the env var is restored and the singleton is
    dropped again so the next test starts clean.
    """
    from app.runtime.outbox import reset_outbox_for_tests

    sentinel = tmp_path / "outbox.jsonl"
    saved = os.environ.get("RAVEN_OUTBOX_PATH")
    os.environ["RAVEN_OUTBOX_PATH"] = str(sentinel)
    reset_outbox_for_tests()
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("RAVEN_OUTBOX_PATH", None)
        else:
            os.environ["RAVEN_OUTBOX_PATH"] = saved
        reset_outbox_for_tests()


@pytest.fixture(autouse=True)
def fake_helix_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Replace :class:`app.db.helix.HelixClient` with the in-process fake.

    The fake is a subclass of ``HelixClient`` so ``isinstance``
    checks in production code remain true.  It records every
    envelope and maintains an in-memory node store so the live
    ``count_nodes`` / ``AddN`` / ``AddE`` round-trip in tests
    works without a running gateway.

    The patch only applies to ``HelixClient.__init__`` — any
    client constructed before this fixture ran (rare; happens
    only if a sibling test module imported at collection time
    constructed one) keeps its real implementation.
    """
    from tests_harness.fake_helix import install_fake

    install_fake(monkeypatch)
    yield


@pytest.fixture(autouse=True)
def isolated_event_outbox(tmp_path: Path) -> Generator[None, None, None]:
    """Point the process-wide :class:`app.runtime.event_outbox.EventOutbox`
    at a per-test temp file.

    Mirrors :func:`isolated_outbox` for the BotSignal outbox.  Without
    this, every test that constructs an ``EventBridge`` with
    ``durable=True`` would inherit the host's
    ``~/.raven/runtime/event_outbox.jsonl`` and either
    (a) write to a real on-disk file the operator cares about, or
    (b) inherit stale ``sent`` entries that the outbox's idempotency
    dedup would silently swallow.

    Two pieces of state are reset:

    1. ``RAVEN_EVENT_OUTBOX_PATH`` is set to
       ``tmp_path/event_outbox.jsonl`` for the duration of the test.
       The next ``get_event_outbox()`` call will read this env var
       and create the singleton at that path.
    2. The cached singleton itself is dropped via
       :func:`app.runtime.event_outbox.reset_event_outbox_for_tests`
       so a previously-created outbox (from a sibling test, or
       from an earlier collection) does not leak in.

    After the test, the env var is restored and the singleton is
    dropped again so the next test starts clean.
    """
    from app.runtime.event_outbox import reset_event_outbox_for_tests

    sentinel = tmp_path / "event_outbox.jsonl"
    saved = os.environ.get("RAVEN_EVENT_OUTBOX_PATH")
    os.environ["RAVEN_EVENT_OUTBOX_PATH"] = str(sentinel)
    reset_event_outbox_for_tests()
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("RAVEN_EVENT_OUTBOX_PATH", None)
        else:
            os.environ["RAVEN_EVENT_OUTBOX_PATH"] = saved
        reset_event_outbox_for_tests()


# ──────────────────────────────────────────────────────────────────────
# Hermes-class dashboard fixtures (v31, 2026-06-21)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def dashboard_test_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Autouse env-reset for every dashboard test.

    Three pieces of state are reset on every test:

    1. ``HF_HUB_OFFLINE=1`` is set so the lazy sentence-transformers
       load inside the memory store (used by the SESSIONS page) does
       not reach the network.  Without this, page renders would try
       to download ``all-MiniLM-L6-v2`` from HuggingFace and either
       hang in a sandboxed CI or pollute test output with a 200-line
       progress bar.
    2. The ``InProcBus`` singleton's subscriber set is snapshotted
       and cleared between tests so a test that subscribes does not
       leak handlers into the next test's /ws/events broadcaster.
    3. The dashboard's WEB_DASHBOARD_ENABLED is forced to True so the
       WebDashboard singleton (if one exists) is available — the
       v31 tests build their own app per session, so this is a
       defensive guard for future tests.
    """
    from app.core.inproc_bus import get_inproc_bus

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("WEB_DASHBOARD_ENABLED", "true")
    bus = get_inproc_bus()
    saved_subs: dict[str, list] = {}
    for topic in list(bus._handlers.keys()):  # noqa: SLF001 - test reset
        saved_subs[topic] = list(bus._handlers[topic])  # noqa: SLF001
        bus._handlers[topic] = []  # noqa: SLF001
    try:
        yield
    finally:
        # Restore subscribers exactly (don't drop topics that
        # appeared during the test — just empty them).
        for topic, handlers in saved_subs.items():
            bus._handlers[topic] = handlers  # noqa: SLF001
        for topic in list(bus._handlers.keys()):  # noqa: SLF001
            if topic not in saved_subs:
                bus._handlers[topic] = []  # noqa: SLF001


# ──────────────────────────────────────────────────────────────────────
# Voice-stack fixtures (v33, 2026-06-21)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_voice_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Stub the v33 voice engines so tests do not download 75 MB
    of whisper.cpp model or load the Piper onnx kernel.

    Two monkeypatches are installed:

    1. ``app.voice.transcribe._get_whisper_cpp_model`` is
       replaced with a function that returns a ``MagicMock``
       whose ``.transcribe(audio_path)`` returns a list with a
       single ``Segment(text="hello world")`` mock.  This lets
       the integration tests assert the wiring end-to-end
       without actually transcribing anything.
    2. ``app.voice.piper.PiperTTS._ensure_loaded`` is replaced
       with a function that returns a ``MagicMock`` voice
       whose ``.synthesize(text, file)`` writes a 100-byte
       silent WAV.  Again, real audio is not produced.

    The ``WHISPER_CPP_OFFLINE=1`` env var is also set so a
    *real* loader call (e.g. from a test that exercises the
    fallback path) raises ``FileNotFoundError`` fast instead
    of trying to download.
    """
    from unittest.mock import MagicMock

    monkeypatch.setenv("WHISPER_CPP_OFFLINE", "1")

    # --- 1. whisper.cpp stub -----------------------------------------
    from app.voice import transcribe as _transcribe_mod

    class _StubSegment:
        def __init__(self, text: str) -> None:
            self.text = text
            self.t0 = 0.0
            self.t1 = 1.0

    class _StubWhisperModel:
        def transcribe(self, audio_path: str) -> list[_StubSegment]:
            return [_StubSegment("hello world")]

        @property
        def config(self) -> MagicMock:
            cfg = MagicMock()
            cfg.sample_rate = 22050
            return cfg

    def _fake_get_whisper_cpp_model() -> _StubWhisperModel:
        # Match the real loader's behaviour: cache the model so
        # multiple calls return the same instance.  State lives
        # on the function itself so the fixture stays hermetic.
        if _fake_get_whisper_cpp_model._cached is None:
            _fake_get_whisper_cpp_model._cached = _StubWhisperModel()
        return _fake_get_whisper_cpp_model._cached

    _fake_get_whisper_cpp_model._cached = None

    monkeypatch.setattr(
        _transcribe_mod,
        "_get_whisper_cpp_model",
        _fake_get_whisper_cpp_model,
    )
    _transcribe_mod.reset_whisper_cpp_for_tests()

    # --- 2. Piper stub -----------------------------------------------
    from app.voice import piper as _piper_mod

    class _StubAudioChunk:
        """Mimics the piper AudioChunk namedtuple / dataclass:
        has an ``audio`` attribute that is a numpy int16 array."""

        def __init__(self, audio):
            self.audio = audio

    class _StubPiperVoice:
        @property
        def config(self) -> MagicMock:
            cfg = MagicMock()
            cfg.sample_rate = 22050
            return cfg

        def synthesize(self, text: str):
            """Yield one AudioChunk with 100 frames of silence.

            piper-tts >= 1.3 returns ``Iterable[AudioChunk]`` where
            each chunk's ``.audio`` is a numpy int16 array.  The
            stub mirrors this API exactly so :mod:`app.voice.piper`
            can iterate + concatenate + write a real WAV header."""
            import numpy as _np

            yield _StubAudioChunk(_np.zeros(100, dtype=_np.int16))

    _stub_voice = _StubPiperVoice()

    def _fake_ensure_loaded(self: Any) -> _StubPiperVoice:  # type: ignore[override]
        return _stub_voice

    monkeypatch.setattr(_piper_mod.PiperTTS, "_ensure_loaded", _fake_ensure_loaded)
    _piper_mod.PiperTTS.reset_cache_for_tests()

    # --- 3. Sink registry reset --------------------------------------
    from app.voice.sink_registry import reset_sink_registry_for_tests

    reset_sink_registry_for_tests()

    try:
        yield
    finally:
        # Reset between tests so the singleton stays clean.
        _transcribe_mod.reset_whisper_cpp_for_tests()
        _piper_mod.PiperTTS.reset_cache_for_tests()
        reset_sink_registry_for_tests()


@pytest.fixture(autouse=True)
def isolated_singleton() -> Generator[None, None, None]:
    """Snapshot every class attribute on ``Config`` and restore on teardown.

    The dashboard tests mutate ``Config.LLM_MODEL`` (MODELS page) and
    ``Config.DASHBOARD_TEMPLATES_DIR`` (render-page tests).  Without
    this fixture, a test that sets ``Config.LLM_MODEL = "foo"`` would
    leak into the next test's snapshot of ``Config.LLM_MODEL``.
    """
    from app.settings.config import Config

    saved = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(Config, k, v)


@pytest.fixture(scope="session")
def dashboard_client() -> Generator["fastapi.testclient.TestClient", None, None]:
    """Session-scoped ``TestClient`` over the unified dashboard app.

    Uses ``app.api.server:app`` which serves all Hermes dashboard
    pages, OpenAI-compatible API, ACP, and WebSocket endpoints from
    a single FastAPI app (same app that ``raven run`` serves).
    """
    from fastapi.testclient import TestClient

    from app.api.server import app as dashboard_app

    client = TestClient(dashboard_app)
    yield client
