import asyncio
import logging
import logging.handlers
import signal
from pathlib import Path

from app.core import BotSignal, MessageOrchestrator, get_botsignal
from app.discord import DiscordBot
from app.settings.config import Config
from app.slack import SlackBot
from app.telegram import bind_runtime, create_bot
from app.core.scheduler import get_scheduler

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure rotating file handler + console handler."""
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    log_file = workspace / "saras.log"

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
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


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
        await asyncio.gather(*pending, return_exceptions=True)


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
            await asyncio.gather(bot_task, return_exceptions=True)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


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
    await asyncio.gather(*pending, return_exceptions=True)
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
    await asyncio.gather(*pending, return_exceptions=True)
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
    await asyncio.gather(webhook_task, return_exceptions=True)


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
    await asyncio.gather(mqtt_task, return_exceptions=True)
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
    await asyncio.gather(*pending, return_exceptions=True)
    logger.info("Voice pipeline shut down.")


async def _main_async() -> None:
    _setup_logging()

    from app.settings.validate import validate_config

    validate_config()

    stop_event = asyncio.Event()
    botsignal = get_botsignal()
    orchestrator = MessageOrchestrator(botsignal)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Signal handlers are not supported in some environments.
            pass

    # Start persistent scheduler (APScheduler + SQLite)
    scheduler = get_scheduler()
    scheduler.set_botsignal(botsignal)
    await scheduler.start()

    # Register morning briefing routine (if configured)
    if Config.MORNING_BRIEFING_USERS:
        from app.routines.morning_briefing import register_morning_briefing

        for entry in Config.MORNING_BRIEFING_USERS.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                plat, uid, cid = parts
                register_morning_briefing(
                    scheduler,
                    uid,
                    plat,
                    cid,
                    cron_hour=Config.MORNING_BRIEFING_HOUR,
                    cron_minute=Config.MORNING_BRIEFING_MINUTE,
                )

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

    try:
        done, pending = await asyncio.wait(
            {
                telegram_task,
                discord_task,
                slack_task,
                webhook_task,
                voice_task,
                mqtt_task,
                whatsapp_task,
                web_task,
                streamlit_task,
            },
            return_when=asyncio.FIRST_EXCEPTION,
        )

        stop_event.set()
        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        await scheduler.shutdown()

    logger.info("All bot tasks stopped.")


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
