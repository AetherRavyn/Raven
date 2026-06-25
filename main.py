import asyncio
import logging
import logging.handlers
import signal
from pathlib import Path

from app.core import BotSignal, MessageOrchestrator, get_botsignal
from app.core.executor import DaemonExecutor
from app.core.proactive_bootstrap import register_proactive_routines
from app.discord import DiscordBot
from app.settings.config import Config
from app.slack import SlackBot
from app.telegram import bind_runtime, create_bot
from app.core.scheduler import get_scheduler
from app.core.proactive import schedule_follow_up

logger = logging.getLogger(__name__)
_SHUTDOWN_GRACE_SECONDS = 8.0


def _setup_logging() -> None:
    """Configure rotating file handler + console handler."""
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    log_file = workspace / "raven.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(console)

    # Rotating file handler: 10 MB per file, keep 5 backups = max 50 MB
    rotating = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    rotating.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(rotating)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)


async def _run_telegram(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    app = create_bot()
    bind_runtime(app, orchestrator, botsignal)

    if app.updater is None:
        raise RuntimeError("Telegram updater is unavailable; cannot run polling mode")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await stop_event.wait()
    finally:
        try:
            await asyncio.wait_for(app.updater.stop(), timeout=3.0)
        except Exception:
            logger.debug("Telegram updater stop timed out or failed", exc_info=True)
        try:
            await asyncio.wait_for(app.stop(), timeout=3.0)
        except Exception:
            logger.debug("Telegram app stop timed out or failed", exc_info=True)
        try:
            await asyncio.wait_for(app.shutdown(), timeout=3.0)
        except Exception:
            logger.debug("Telegram app shutdown timed out or failed", exc_info=True)


async def _run_discord(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    enable_message_content = Config.DISCORD_ENABLE_MESSAGE_CONTENT_INTENT
    logger.info(
        "Discord message content intent is %s",
        "enabled" if enable_message_content else "disabled",
    )
    bot = DiscordBot(
        Config.DISCORD_BOT_TOKEN,
        Config.DISCORD_CHANNEL_ID,
        orchestrator,
        enable_message_content=enable_message_content,
    )
    bot.register_output_sender(botsignal)

    bot_task = asyncio.create_task(bot.start_bot(), name="discord-bot")
    stop_task = asyncio.create_task(stop_event.wait(), name="discord-stop")

    done, pending = await asyncio.wait(
        {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    try:
        if bot_task in done:
            await bot_task
        else:
            if not bot.is_closed():
                await bot.close()
            await bot_task
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)  # type: ignore


async def _run_slack(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    bot_token = Config.SLACK_BOT_TOKEN
    app_token = Config.SLACK_APP_TOKEN
    if not bot_token or not app_token:
        logger.warning(
            "Slack tokens not set (SLACK_BOT_TOKEN / SLACK_APP_TOKEN) — Slack connector skipped"
        )
        await stop_event.wait()
        return

    bot = SlackBot(bot_token, app_token, orchestrator)
    bot.register_output_sender(botsignal)

    bot_task = asyncio.create_task(bot.start_bot(), name="slack-bot")
    stop_task = asyncio.create_task(stop_event.wait(), name="slack-stop")

    done, pending = await asyncio.wait(
        {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    try:
        if bot_task in done:
            await bot_task
        else:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)  # type: ignore
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)  # type: ignore


async def _run_web(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    """Run the web dashboard (FastAPI) until stop_event is set.

    Silently skips when WEB_DASHBOARD_ENABLED is false (default).
    """
    if not Config.WEB_DASHBOARD_ENABLED:
        logger.debug("Web dashboard disabled (WEB_DASHBOARD_ENABLED=false)")
        await stop_event.wait()
        return

    from app.web.server import WebDashboard  # noqa: PLC0415

    dashboard = WebDashboard(orchestrator)
    dashboard.register_output_sender(botsignal)

    server_task = asyncio.create_task(
        dashboard.start(host=Config.WEB_DASHBOARD_HOST, port=Config.WEB_DASHBOARD_PORT),
        name="web-dashboard-inner",
    )
    stop_task = asyncio.create_task(stop_event.wait(), name="web-stop")

    done, pending = await asyncio.wait(
        {server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)  # type: ignore
    logger.info("Web dashboard shut down.")


async def _run_whatsapp(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    """Run the WhatsApp ↔ Baileys bridge receiver until stop_event is set.

    Silently skips when WHATSAPP_BRIDGE_URL is not configured.
    """
    if not Config.WHATSAPP_BRIDGE_URL:
        logger.debug("WHATSAPP_BRIDGE_URL not set — WhatsApp connector skipped")
        await stop_event.wait()
        return

    from app.whatsapp.whatsappapp import WhatsAppBot  # noqa: PLC0415

    bot = WhatsAppBot(Config.WHATSAPP_BRIDGE_URL, orchestrator)
    bot.register_output_sender(botsignal)

    bot_task = asyncio.create_task(bot.start_bot(), name="whatsapp-bot")
    stop_task = asyncio.create_task(stop_event.wait(), name="whatsapp-stop")

    done, pending = await asyncio.wait(
        {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)  # type: ignore
    logger.info("WhatsApp connector shut down.")


async def _run_streamlit(stop_event: asyncio.Event) -> None:
    """Run the Streamlit admin dashboard as a subprocess.

    Streamlit is its own web server; we spawn it as a child process and
    wait for the stop_event to terminate it.  Silently skips when
    STREAMLIT_DASHBOARD_ENABLED is false (default).
    """
    if not Config.STREAMLIT_DASHBOARD_ENABLED:
        logger.debug("Streamlit dashboard disabled (STREAMLIT_DASHBOARD_ENABLED=false)")
        await stop_event.wait()
        return

    import sys
    import subprocess as _sp

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app/dashboard/dashboard.py",
        "--server.port",
        str(Config.STREAMLIT_DASHBOARD_PORT),
        "--server.address",
        Config.STREAMLIT_DASHBOARD_HOST,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]

    logger.info(
        "Starting Streamlit dashboard on %s:%s",
        Config.STREAMLIT_DASHBOARD_HOST,
        Config.STREAMLIT_DASHBOARD_PORT,
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        await stop_event.wait()
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("Streamlit dashboard shut down.")


async def _run_webhook(stop_event: asyncio.Event) -> None:
    from app.sensors.webhook_server import run_webhook_server

    webhook_task = asyncio.create_task(run_webhook_server())
    await stop_event.wait()
    webhook_task.cancel()
    await asyncio.gather(webhook_task, return_exceptions=True)  # type: ignore


async def _run_mqtt(stop_event: asyncio.Event) -> None:
    """Run the MQTT sensor listener until the stop event is set.

    Silently skips when MQTT_BROKER_URL is not configured.
    """
    broker = Config.MQTT_BROKER_URL
    if not broker:
        logger.debug("MQTT_BROKER_URL not set — MQTT listener skipped")
        await stop_event.wait()
        return

    from app.sensors.mqtt_listener import run_mqtt_listener  # noqa: PLC0415

    mqtt_task = asyncio.create_task(
        run_mqtt_listener(
            broker_url=broker,
            topics=Config.MQTT_TOPICS,
            username=Config.MQTT_USERNAME,
            password=Config.MQTT_PASSWORD,
        ),
        name="mqtt-listener-inner",
    )
    await stop_event.wait()
    mqtt_task.cancel()
    await asyncio.gather(mqtt_task, return_exceptions=True)  # type: ignore
    logger.info("MQTT listener shut down.")


async def _run_voice_pipeline(
    stop_event: asyncio.Event, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    """Start the local wake-word → STT → LLM → TTS voice pipeline.

    Silently skips when ENABLE_LOCAL_VOICE is false (default).
    """
    from app.settings.config import Config  # noqa: PLC0415

    if not Config.ENABLE_LOCAL_VOICE:
        logger.debug("Local voice pipeline disabled (ENABLE_LOCAL_VOICE=false)")
        await stop_event.wait()
        return

    from app.voice.pipeline import VoicePipeline  # noqa: PLC0415

    pipeline = VoicePipeline(orchestrator, botsignal)
    pipeline_task = asyncio.create_task(pipeline.start(), name="voice-pipeline-inner")
    stop_waiter = asyncio.create_task(stop_event.wait(), name="voice-stop")

    done, pending = await asyncio.wait(
        {pipeline_task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
    )
    pipeline.stop()
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)  # type: ignore
    logger.info("Voice pipeline shut down.")


async def _main_async() -> None:
    _setup_logging()

    from app.settings.validate import validate_config

    validate_config()

    stop_event = asyncio.Event()
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(DaemonExecutor(thread_name_prefix="raven"))

    def _request_shutdown() -> None:
        if not stop_event.is_set():
            logger.info("Shutdown signal received")
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Signal handlers are not supported in some environments.
            pass

    # Start persistent scheduler (APScheduler + SQLite)
    scheduler = get_scheduler()
    scheduler.set_botsignal(botsignal)
    await scheduler.start()

    register_proactive_routines(scheduler)

    # ── A2A Module Protocol ────────────────────────────────────────
    # Register A2A-compliant modules for inter-module communication
    try:
        from raven_protocol import get_registry
        from raven_iot.a2a_server import create_iot_server
        from app.voice.a2a_server import create_voice_server
        from app.core.context_a2a_server import create_context_server
        from app.core.memory_a2a_server import create_memory_server
        from app.core.agent_a2a_server import create_agent_server
        from app.core.scheduling_a2a_server import create_scheduling_server
        from app.core.api_gateway_a2a_server import create_api_gateway_server

        registry = get_registry()
        iot_server = create_iot_server()
        iot_server.start()
        voice_server = create_voice_server()
        voice_server.start()
        context_server = create_context_server()
        context_server.start()
        memory_server = create_memory_server()
        memory_server.start()
        agent_server = create_agent_server()
        agent_server.start()
        scheduling_server = create_scheduling_server()
        scheduling_server.start()
        api_server = create_api_gateway_server()
        api_server.start()

        logger.info("A2A modules registered: %s",
                    [c.name for c in registry.list_modules()])
    except Exception as exc:
        logger.warning("A2A module registration failed: %s", exc)

    # Keep a callable available for other startup code and future follow-up hooks.
    _ = schedule_follow_up

    telegram_task = asyncio.create_task(
        _run_telegram(stop_event, orchestrator, botsignal), name="telegram-bot"
    )
    discord_task = asyncio.create_task(
        _run_discord(stop_event, orchestrator, botsignal), name="discord-runner"
    )
    slack_task = asyncio.create_task(
        _run_slack(stop_event, orchestrator, botsignal), name="slack-runner"
    )
    webhook_task = asyncio.create_task(_run_webhook(stop_event), name="webhook-server")
    voice_task = asyncio.create_task(
        _run_voice_pipeline(stop_event, orchestrator, botsignal), name="voice-pipeline"
    )
    mqtt_task = asyncio.create_task(_run_mqtt(stop_event), name="mqtt-listener")
    whatsapp_task = asyncio.create_task(
        _run_whatsapp(stop_event, orchestrator, botsignal), name="whatsapp-runner"
    )
    web_task = asyncio.create_task(
        _run_web(stop_event, orchestrator, botsignal), name="web-dashboard"
    )
    streamlit_task = asyncio.create_task(
        _run_streamlit(stop_event), name="streamlit-dashboard"
    )

    # ── Ambient Intelligence Loop ──────────────────────────────────────
    # Always-on background heartbeat: self-improvement, workflow ticks,
    # sentinel digest, dashboard heartbeats
    from app.core.ambient_loop import get_ambient_loop
    ambient = get_ambient_loop()
    ambient._orchestrator = orchestrator
    ambient._botsignal = botsignal
    ambient_task = asyncio.create_task(ambient.run(), name="ambient-loop")
    stop_waiter = asyncio.create_task(stop_event.wait(), name="shutdown-waiter")

    service_tasks = {
        telegram_task,
        discord_task,
        slack_task,
        webhook_task,
        voice_task,
        mqtt_task,
        whatsapp_task,
        web_task,
        streamlit_task,
        ambient_task,
    }

    try:
        done, pending = await asyncio.wait(
            service_tasks | {stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_waiter in done:
            logger.info("Graceful shutdown started")
        else:
            for task in done:
                if task is stop_waiter:
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error("Task %s failed: %s", task.get_name(), exc)
                    break
        stop_event.set()
        ambient.stop()

        to_wait = [task for task in service_tasks if not task.done()]
        if to_wait:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*to_wait, return_exceptions=True),
                    timeout=_SHUTDOWN_GRACE_SECONDS,
                )
            except asyncio.TimeoutError:
                stuck = [task for task in to_wait if not task.done()]
                logger.warning(
                    "Forcing shutdown; %d task(s) still running: %s",
                    len(stuck),
                    ", ".join(task.get_name() for task in stuck),
                )
                for task in stuck:
                    task.cancel()
                await asyncio.gather(*stuck, return_exceptions=True)

        for task in done:
            if task is stop_waiter:
                continue
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        stop_waiter.cancel()
        await asyncio.gather(stop_waiter, return_exceptions=True)
        await scheduler.shutdown()

    logger.info("All bot tasks stopped.")


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
