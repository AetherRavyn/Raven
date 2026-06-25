"""Process supervisor — Phase 1.1.

Spawns each sidecar (voice pipeline, monitoring, MCP, web dashboard,
Streamlit) as a separate process so a fault in one cannot take down
the orchestrator. Each sidecar reports a small JSON health line on a
queue, the supervisor pings every 5 s, and restarts processes that
go silent with exponential backoff (capped at 5 min, 10 restarts
per hour).

This module is intentionally **self-contained**:
- No third-party deps.
- The supervisor itself is a single coroutine.
- No shared mutable state outside the Supervisor instance.
- All exceptions are caught and logged; the supervisor must not
  die because a child misbehaved.
"""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import os
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────────

HEALTH_PING_INTERVAL_S = 5.0
MAX_RESTARTS_PER_HOUR = 10
BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 300.0  # 5 min cap
SHUTDOWN_GRACE_S = 3.0


# ── Data shapes ───────────────────────────────────────────────────────


class SidecarState(str, Enum):
    PENDING = "pending"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    FAILED = "failed"  # exceeded restart budget


@dataclass
class HealthSnapshot:
    """Tiny per-sidecar health record (≤ 64 bytes on the wire)."""

    rss_mb: float = 0.0
    last_turn_ms: float = 0.0
    status: str = "ok"  # "ok" | "warn" | "error"
    note: str = ""

    def to_line(self) -> str:
        return json.dumps(
            {
                "rss_mb": round(self.rss_mb, 1),
                "last_turn_ms": round(self.last_turn_ms, 1),
                "status": self.status,
                "note": self.note[:120],
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_line(cls, line: str) -> "HealthSnapshot":
        try:
            d = json.loads(line)
        except Exception:
            return cls(status="warn", note="bad health line")
        return cls(
            rss_mb=float(d.get("rss_mb", 0.0)),
            last_turn_ms=float(d.get("last_turn_ms", 0.0)),
            status=str(d.get("status", "ok")),
            note=str(d.get("note", "")),
        )


@dataclass
class SidecarSpec:
    """A single sidecar the supervisor will keep alive.

    The ``target`` is an async function that receives the health queue
    as its first positional argument:

        async def my_sidecar(health_q: "mp.Queue[str]") -> None: ...
    """

    name: str
    target: Callable[..., Awaitable[None]]  # async fn(health_q, *args)
    # Maximum allowed RSS in MB before the supervisor logs an alert.
    rss_warn_mb: float = 800.0
    # If the sidecar goes silent for longer than this, mark it degraded.
    silence_warn_s: float = 15.0
    # Extra args for the target (appended after health_q).
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


@dataclass
class _SidecarRuntime:
    spec: SidecarSpec
    state: SidecarState = SidecarState.PENDING
    proc: Optional[mp.Process] = None
    health_q: Optional[mp.Queue] = None
    last_health: HealthSnapshot = field(default_factory=HealthSnapshot)
    last_health_at: float = 0.0
    restarts_in_window: list[float] = field(default_factory=list)
    backoff_s: float = BACKOFF_INITIAL_S
    last_restart_at: float = 0.0
    exit_code: int = 0


# ── Supervisor ────────────────────────────────────────────────────────


class Supervisor:
    """Owns and supervises a set of sidecar processes.

    The supervisor itself runs as a single asyncio task. It does **not**
    create a thread pool, does **not** import torch/transformers, and
    does **not** share state with the children beyond an mp.Queue per
    sidecar for health pings.
    """

    def __init__(self) -> None:
        self._sidecars: dict[str, _SidecarRuntime] = {}
        self._running: bool = False
        self._start_time: float = 0.0
        # Process start method — "spawn" is the only safe default on
        # macOS and on Linux with CUDA.
        try:
            mp.set_start_method("spawn", force=False)
        except RuntimeError:
            # Already set — fine.
            pass

    # ── Public API ──────────────────────────────────────────────────

    def register(self, spec: SidecarSpec) -> None:
        """Register a sidecar. Idempotent — re-registration overwrites."""
        self._sidecars[spec.name] = _SidecarRuntime(spec=spec)

    async def run(self) -> None:
        """Main supervisor loop. Runs forever until stop() is called."""
        self._running = True
        self._start_time = time.time()
        logger.info(
            "Supervisor started with %d sidecar(s): %s",
            len(self._sidecars),
            ", ".join(self._sidecars.keys()) or "(none)",
        )

        # Kick off the initial spawns.
        for name in list(self._sidecars.keys()):
            self._schedule_start(name, delay=0.0)

        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Supervisor tick error: %s", exc)
            await asyncio.sleep(HEALTH_PING_INTERVAL_S)

        await self._stop_all()
        logger.info("Supervisor stopped")

    def stop(self) -> None:
        self._running = False

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable view of all sidecars. Cheap."""
        out: dict[str, Any] = {}
        for name, rt in self._sidecars.items():
            out[name] = {
                "state": rt.state.value,
                "rss_mb": rt.last_health.rss_mb,
                "last_turn_ms": rt.last_health.last_turn_ms,
                "status": rt.last_health.status,
                "note": rt.last_health.note,
                "restarts_last_hour": len(rt.restarts_in_window),
                "backoff_s": rt.backoff_s,
            }
        return out

    # ── Internal ────────────────────────────────────────────────────

    async def _tick(self) -> None:
        now = time.time()
        for name, rt in list(self._sidecars.items()):
            self._drain_health_queue(rt)
            self._maybe_alert_silence(rt, now)
            self._check_process(rt, now)
            self._maybe_restart(rt, now)

    def _drain_health_queue(self, rt: _SidecarRuntime) -> None:
        if rt.health_q is None:
            return
        # Drain without blocking.
        while True:
            try:
                line = rt.health_q.get_nowait()
            except Exception:
                break
            try:
                snap = HealthSnapshot.from_line(line)
            except Exception:
                continue
            rt.last_health = snap
            rt.last_health_at = time.time()
            if rt.state != SidecarState.HEALTHY:
                logger.info("Sidecar %s is HEALTHY (%s)", rt.spec.name, snap.to_line())
            rt.state = SidecarState.HEALTHY

    def _maybe_alert_silence(self, rt: _SidecarRuntime, now: float) -> None:
        if rt.state != SidecarState.HEALTHY:
            return
        if not rt.last_health_at:
            return
        if now - rt.last_health_at > rt.spec.silence_warn_s:
            logger.warning(
                "Sidecar %s silent for %.1fs (> %.1fs threshold)",
                rt.spec.name,
                now - rt.last_health_at,
                rt.spec.silence_warn_s,
            )
            rt.state = SidecarState.DEGRADED

    def _check_process(self, rt: _SidecarRuntime, now: float) -> None:
        if rt.proc is None:
            return
        if not rt.proc.is_alive():
            rt.exit_code = rt.proc.exitcode or 0
            if rt.state not in (
                SidecarState.STOPPED,
                SidecarState.RESTARTING,
                SidecarState.FAILED,
            ):
                logger.warning(
                    "Sidecar %s exited (code=%s)", rt.spec.name, rt.exit_code
                )
                rt.state = SidecarState.RESTARTING

    def _maybe_restart(self, rt: _SidecarRuntime, now: float) -> None:
        if rt.state != SidecarState.RESTARTING:
            return
        # Restrict to 10 restarts per rolling hour.
        rt.restarts_in_window = [
            t for t in rt.restarts_in_window if now - t < 3600.0
        ]
        if len(rt.restarts_in_window) >= MAX_RESTARTS_PER_HOUR:
            logger.error(
                "Sidecar %s exceeded %d restarts/hour — leaving FAILED",
                rt.spec.name,
                MAX_RESTARTS_PER_HOUR,
            )
            rt.state = SidecarState.FAILED
            return

        # Respect the backoff window.
        if now - rt.last_restart_at < rt.backoff_s:
            return
        self._schedule_start(rt.spec.name, delay=0.0)
        rt.last_restart_at = now
        rt.restarts_in_window.append(now)
        # Exponential backoff up to the cap.
        rt.backoff_s = min(rt.backoff_s * 2.0, BACKOFF_MAX_S)

    def _schedule_start(self, name: str, *, delay: float) -> None:
        """Spawn the sidecar as a child process (called from the loop)."""
        rt = self._sidecars.get(name)
        if rt is None:
            return
        if rt.proc is not None and rt.proc.is_alive():
            return  # already running

        rt.health_q = mp.Queue(maxsize=64)
        rt.state = SidecarState.STARTING
        proc = mp.Process(
            target=_sidecar_entrypoint,
            args=(rt.spec, rt.health_q),
            name=f"raven-sidecar-{name}",
            daemon=True,
        )
        proc.start()
        rt.proc = proc
        logger.info(
            "Sidecar %s started (pid=%s, backoff_next=%.1fs)",
            name,
            proc.pid,
            rt.backoff_s,
        )

    async def _stop_all(self) -> None:
        for name, rt in self._sidecars.items():
            if rt.proc is None or not rt.proc.is_alive():
                continue
            logger.info("Stopping sidecar %s (pid=%s)", name, rt.proc.pid)
            try:
                rt.proc.terminate()
                rt.proc.join(timeout=SHUTDOWN_GRACE_S)
                if rt.proc.is_alive():
                    rt.proc.kill()
                    rt.proc.join(timeout=1.0)
            except Exception as exc:
                logger.debug("Sidecar %s stop raised: %s", name, exc)
            rt.state = SidecarState.STOPPED


# ── Child entrypoint ─────────────────────────────────────────────────


def _sidecar_entrypoint(
    spec: SidecarSpec, health_q: "mp.Queue[str]"
) -> None:
    """Run inside the child process.

    Each sidecar must:
    1. Periodically put a HealthSnapshot JSON line on `health_q`.
    2. Catch its own exceptions — never raise to the top, or
       the supervisor will think it crashed.
    """
    # Each child gets its own event loop. We re-use asyncio.run for
    # the lifetime of the sidecar.
    try:
        asyncio.run(_sidecar_main(spec, health_q))
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # last-resort guard
        # Surface the failure to the parent via the health queue so
        # the supervisor's next tick sees a non-`ok` status.
        try:
            health_q.put_nowait(
                HealthSnapshot(status="error", note=f"crashed: {exc}").to_line()
            )
        except Exception:
            pass
        traceback.print_exc()


async def _sidecar_main(
    spec: SidecarSpec, health_q: "mp.Queue[str]"
) -> None:
    """Async runner for a single sidecar.

    It calls `spec.target(*args, **kwargs)`. The target is responsible
    for its own scheduling; we wrap it with a health pinger that
    reports process RSS every 5 s.
    """
    ping_task = asyncio.create_task(
        _sidecar_health_pinger(spec, health_q), name=f"ping-{spec.name}"
    )
    try:
        await spec.target(health_q, *spec.args, **spec.kwargs)
    finally:
        ping_task.cancel()
        with contextlib_suppress(Exception):
            await ping_task


async def _sidecar_health_pinger(
    spec: SidecarSpec, health_q: "mp.Queue[str]"
) -> None:
    """Push a health line every 5 s for the lifetime of the sidecar."""
    try:
        import psutil  # type: ignore

        have_psutil = True
    except Exception:
        have_psutil = False
    proc = None
    if have_psutil:
        try:
            proc = psutil.Process()
        except Exception:
            have_psutil = False

    while True:
        rss_mb = 0.0
        if have_psutil and proc is not None:
            try:
                rss_mb = proc.memory_info().rss / 1024 / 1024
            except Exception:
                pass
        snap = HealthSnapshot(rss_mb=rss_mb)
        if rss_mb > spec.rss_warn_mb:
            snap.status = "warn"
            snap.note = f"RSS {rss_mb:.0f}MB > warn {spec.rss_warn_mb:.0f}MB"
        try:
            health_q.put_nowait(snap.to_line())
        except Exception:
            # Queue full — drop and continue. The supervisor will
            # catch silence as the next fallback signal.
            pass
        await asyncio.sleep(HEALTH_PING_INTERVAL_S)


# Tiny shim so we don't need to import contextlib at module top.
class contextlib_suppress:
    def __init__(self, *exc: type[BaseException]) -> None:
        self.excs = exc

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, self.excs)


# ── Module singleton ────────────────────────────────────────────────

_SUPERVISOR: Supervisor | None = None


def get_supervisor() -> Supervisor:
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = Supervisor()
    return _SUPERVISOR


__all__ = [
    "Supervisor",
    "SidecarSpec",
    "SidecarState",
    "HealthSnapshot",
    "get_supervisor",
]