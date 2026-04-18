from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv() -> bool:
        return False


load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1213902756633518181"))
    DISCORD_ENABLE_MESSAGE_CONTENT_INTENT = os.getenv(
        "DISCORD_ENABLE_MESSAGE_CONTENT_INTENT", "true"
    ).strip().lower() in {"1", "true", "yes", "y", "on"}
    VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or GEMINI_API_KEY
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    KILLO_API_KEY = os.getenv("KILLO_API_KEY") or os.getenv("KILO_API_KEY")
    KILLO_BASE_URL = os.getenv("KILLO_BASE_URL", "https://api.kilo.ai/api/gateway")
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    XAI_GRPC_HOST = os.getenv("XAI_GRPC_HOST", "api.x.ai:443")
    XAI_VISION_MODEL = os.getenv("XAI_VISION_MODEL", "grok-2-vision-latest")
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
    API_KEY_SPEECHMATE = os.getenv("API_KEY_SPEECHMATE")
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # xoxb-...
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")  # xapp-... (Socket Mode)
    ADMIN_USER_IDS = [
        u.strip() for u in os.getenv("ADMIN_USER_IDS", "").split(",") if u.strip()
    ]
    # Gmail OAuth
    GMAIL_CREDENTIALS_PATH = os.getenv(
        "GMAIL_CREDENTIALS_PATH", "workspace/gmail_credentials.json"
    )
    # Obsidian
    OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
    # Spotify
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    # SMTP (outgoing email)
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    # Weather
    OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
    DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "London")
    # Morning briefing
    MORNING_BRIEFING_USERS = os.getenv(
        "MORNING_BRIEFING_USERS", ""
    )  # "platform:user_id:chat_id,..."
    MORNING_BRIEFING_HOUR = int(os.getenv("MORNING_BRIEFING_HOUR", "8"))
    MORNING_BRIEFING_MINUTE = int(os.getenv("MORNING_BRIEFING_MINUTE", "0"))
    # Ollama (local LLM fallback)
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
    # Home Assistant
    HOME_ASSISTANT_URL = os.getenv(
        "HOME_ASSISTANT_URL", "http://homeassistant.local:8123"
    )
    HOME_ASSISTANT_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN")
    # Google Calendar OAuth
    GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv(
        "GOOGLE_CALENDAR_CREDENTIALS_PATH", "workspace/google_calendar_credentials.json"
    )
    GOOGLE_CALENDAR_TOKEN_PATH = os.getenv(
        "GOOGLE_CALENDAR_TOKEN_PATH", "workspace/calendar_token.json"
    )
    # Notion
    NOTION_API_KEY = os.getenv("NOTION_API_KEY")
    # Wolfram Alpha
    WOLFRAM_ALPHA_APP_ID = os.getenv("WOLFRAM_ALPHA_APP_ID")
    # SearXNG (self-hosted private search)
    SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")
    # Voice pipeline
    ENABLE_LOCAL_VOICE: bool = os.getenv("ENABLE_LOCAL_VOICE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    VOICE_STT_MODEL: str = os.getenv("VOICE_STT_MODEL", "tiny")  # tiny/base/small
    VOICE_TTS_VOICE: str = os.getenv("VOICE_TTS_VOICE", "en-US-AriaNeural")
    VOICE_WAKE_WORD_THRESHOLD: float = float(
        os.getenv("VOICE_WAKE_WORD_THRESHOLD", "0.5")
    )
    VOICE_REPLY_WITH_AUDIO: bool = os.getenv(
        "VOICE_REPLY_WITH_AUDIO", "false"
    ).lower() in {"1", "true", "yes"}
    # Infrastructure
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "chroma")  # "chroma" | "pgvector"
    TOOL_USER_PERMISSIONS = os.getenv("TOOL_USER_PERMISSIONS", "")
    TOOL_AGENT_PERMISSIONS = os.getenv("TOOL_AGENT_PERMISSIONS", "")
    # MQTT
    MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "")
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_TOPICS: list[str] = os.getenv("MQTT_TOPICS", "saras/#").split(",")
    # WhatsApp (Baileys bridge)
    WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "")
    # Web dashboard
    WEB_DASHBOARD_ENABLED: bool = os.getenv(
        "WEB_DASHBOARD_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    WEB_DASHBOARD_PORT: int = int(os.getenv("WEB_DASHBOARD_PORT", "8090"))
    WEB_DASHBOARD_HOST: str = os.getenv("WEB_DASHBOARD_HOST", "0.0.0.0")
    # Streamlit admin dashboard
    STREAMLIT_DASHBOARD_ENABLED: bool = os.getenv(
        "STREAMLIT_DASHBOARD_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    STREAMLIT_DASHBOARD_PORT: int = int(os.getenv("STREAMLIT_DASHBOARD_PORT", "8501"))
    STREAMLIT_DASHBOARD_HOST: str = os.getenv("STREAMLIT_DASHBOARD_HOST", "0.0.0.0")
    # Ollama / local LLM (Phase 6.3 — already present above; kept here for completeness)
