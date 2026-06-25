from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv() -> bool:
        return False


load_dotenv()


class Config:
    LLM_PROVIDER = (os.getenv("LLM_PROVIDER", "auto") or "auto").strip()
    LLM_MODEL = (os.getenv("LLM_MODEL", "") or "").strip()
    # Phase 6 — when True, the new app/core/planning/ planner leads.
    # The legacy app/core/planner.py shim still works for one release
    # so users can flip back via RAVEN_PLANNER_V2=false.
    RAVEN_PLANNER_V2 = os.getenv("RAVEN_PLANNER_V2", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    # SQLite path for the plan store.  Relative paths are resolved
    # against MEMORY_ROOT.  Empty string disables SQLite (in-memory
    # only — not recommended for production).
    PLAN_STORE_SQLITE = os.getenv("PLAN_STORE_SQLITE", "plan_store.sqlite").strip()
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
    TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
    TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1213902756633518181"))
    DISCORD_ENABLE_MESSAGE_CONTENT_INTENT = os.getenv(
        "DISCORD_ENABLE_MESSAGE_CONTENT_INTENT", "true"
    ).strip().lower() in {"1", "true", "yes", "y", "on"}
    VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or GEMINI_API_KEY
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY")
    HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
    BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENCODE_ZEN_API_KEY = os.getenv("OPENCODE_ZEN_API_KEY", "no-key-needed")
    OPENCODE_ZEN_BASE_URL = os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    OPENCODE_ZEN_MODEL = os.getenv("OPENCODE_ZEN_MODEL", "big-pickle")
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    XAI_GRPC_HOST = os.getenv("XAI_GRPC_HOST", "api.x.ai:443")
    XAI_VISION_MODEL = os.getenv("XAI_VISION_MODEL", "grok-2-vision-latest")
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
    API_KEY_SPEECHMATE = os.getenv("API_KEY_SPEECHMATE")
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # xoxb-...
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")  # xapp-... (Socket Mode)
    ADMIN_USER_IDS = [u.strip() for u in os.getenv("ADMIN_USER_IDS", "").split(",") if u.strip()]
    # Gmail OAuth
    GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "workspace/gmail_credentials.json")
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
    LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    LOCALAI_BASE_URL = os.getenv("LOCALAI_BASE_URL", "http://localhost:8080/v1")
    VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    # Home Assistant
    HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL", "http://homeassistant.local:8123")
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
    VOICE_TTS_VOICE: str = os.getenv("VOICE_TTS_VOICE", "")  # legacy BCP-47 name; deprecated in v33
    VOICE_WAKE_WORD_THRESHOLD: float = float(os.getenv("VOICE_WAKE_WORD_THRESHOLD", "0.5"))
    VOICE_MIC_DEVICE: int | None = (
        int(os.environ.get("VOICE_MIC_DEVICE", "0")) if os.environ.get("VOICE_MIC_DEVICE") else None
    )
    VOICE_REPLY_WITH_AUDIO: bool = os.getenv("VOICE_REPLY_WITH_AUDIO", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    # Per-user TTS voice customization: "user_id:voice_name,user_id2:voice_name2"
    VOICE_TTS_VOICES: str = os.getenv("VOICE_TTS_VOICES", "")
    # ---------------------------------------------------------
    # v33 voice stack — whisper.cpp STT + Piper-TTS personality
    # ---------------------------------------------------------
    # Whisper.cpp (replaces faster-whisper, v33)
    WHISPER_CPP_MODEL: str = os.getenv(
        "WHISPER_CPP_MODEL", "workspace/models/whisper/ggml-tiny.bin"
    )
    WHISPER_CPP_OFFLINE: bool = os.getenv("WHISPER_CPP_OFFLINE", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    WHISPER_CPP_LANGUAGE: str = os.getenv("WHISPER_CPP_LANGUAGE", "en")
    WHISPER_CPP_THREADS: int = int(os.getenv("WHISPER_CPP_THREADS", "2"))
    # Piper-TTS (replaces edge-tts, v33).  autherRaven is the
    # default personality voice shipped on disk.
    PIPER_VOICE_MODEL: str = os.getenv("PIPER_VOICE_MODEL", "app/voice/en_US-lessac-medium.onnx")
    PIPER_VOICE_CONFIG: str = os.getenv(
        "PIPER_VOICE_CONFIG", "app/voice/en_US-lessac-medium.onnx.json"
    )
    PIPER_VOICE_NAME: str = os.getenv("PIPER_VOICE_NAME", "autherRaven")
    # Browser voice WS endpoint (v33) — server-side gate.
    ENABLE_BROWSER_VOICE: bool = os.getenv("ENABLE_BROWSER_VOICE", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # ---------------------------------------------------------
    # MODULAR EXTENSION PLATFORM
    # ---------------------------------------------------------
    # When set to a non-empty path, main.py boots the Module_Platform
    # against the directory and auto-loads every module found there.
    # Empty (default) leaves the platform dormant — the registry
    # itself remains usable from tests and from explicit CLI calls
    # (``raven modules ...``), but no module is hot-loaded at
    # startup.  See ``docs/12-modular-platform-integration.md``.
    MODULES_ROOT: str = os.getenv("RAVEN_MODULES_ROOT", "")
    # Trust gating (Req 5.x): a module whose manifest declares
    # ``trust_level: community`` is refused auto-load at startup;
    # only ``workspace`` and ``system`` trust levels auto-load.
    # Set to ``false`` to require explicit approval for every
    # module (useful on multi-tenant / shared hosts).
    MODULES_AUTO_LOAD_COMMUNITY: bool = os.getenv(
        "RAVEN_MODULES_AUTO_LOAD_COMMUNITY", "false"
    ).lower() in {"1", "true", "yes", "on"}
    # Infrastructure
    # ---------------------------------------------------------
    # MEMORY & KNOWLEDGE STORE (HelixDB + SQLite only)
    # ---------------------------------------------------------
    MEMORY_ROOT: str = os.getenv("MEMORY_ROOT", "workspace/memory")
    VECTOR_DB_PATH: str = os.getenv("VECTOR_DB_PATH", f"{MEMORY_ROOT}/vector")
    GRAPH_DB_PATH: str = os.getenv("GRAPH_DB_PATH", f"{MEMORY_ROOT}/graph/raven.sqlite")
    STATE_DB_PATH: str = os.getenv("STATE_DB_PATH", f"{MEMORY_ROOT}/state/ledger.sqlite")
    # Memory backend selector: helix (default)
    MEMORY_BACKEND: str = os.getenv("MEMORY_BACKEND", "helix")
    # Knowledge graph backend selector: helix (default)
    KG_BACKEND: str = os.getenv("KG_BACKEND", "helix")
    # Embedding model used by every memory backend.
    MEMORY_EMBEDDING_MODEL: str = os.getenv("MEMORY_EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ---------------------------------------------------------
    # HYBRID ROUTING (System 1 vs System 2)
    # ---------------------------------------------------------
    LOCAL_LIGHT_MODEL: str = os.getenv("LOCAL_LIGHT_MODEL", "gemma:7b")  # Fast reflexes (System 1)
    CLOUD_HEAVY_MODEL: str = os.getenv("CLOUD_HEAVY_MODEL", "gpt-4o")  # Deep reasoning (System 2)

    # Privacy & Trust (Phase E) — gate every tool call on the
    # per-user consent ledger and run log lines through the
    # privacy redactor.
    PRIVACY_V2_ENABLED: bool = os.getenv("RAVEN_PRIVACY_V2", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Mirror consent + retention writes to HelixDB for durability.
    PRIVACY_HELIX_ENABLED: bool = os.getenv("RAVEN_PRIVACY_HELIX", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Trust & Explainability (Phase F1) — when true, the runtime
    # wraps the final LLM response with inline [1][2] markers and
    # a sources footer (only if at least one citation was gathered
    # during the turn).  Off by default to preserve channel
    # compatibility (some downstream renderers strip brackets).
    CITATIONS_IN_RESULTS: bool = os.getenv("RAVEN_CITATIONS_IN_RESULTS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # When true, the runtime also runs fact-checking on the final
    # response — claims without supporting evidence are flagged in
    # the audit log.  Pairs with CITATIONS_IN_RESULTS.
    FACT_CHECK_IN_RESULTS: bool = os.getenv("RAVEN_FACT_CHECK_IN_RESULTS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # When true, mutations executed by tools are auto-registered
    # with the RollbackManager so the user can undo them later.
    AUTO_ROLLBACK: bool = os.getenv("RAVEN_AUTO_ROLLBACK", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    TOOL_USER_PERMISSIONS = os.getenv("TOOL_USER_PERMISSIONS", "")
    TOOL_AGENT_PERMISSIONS = os.getenv("TOOL_AGENT_PERMISSIONS", "")
    # MQTT
    MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "")
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_TOPICS: list[str] = os.getenv("MQTT_TOPICS", "raven/#").split(",")
    # WhatsApp (Baileys bridge)
    WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "")
    WHATSAPP_WHAPI_TOKEN = os.getenv("WHATSAPP_WHAPI_TOKEN", "")
    WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
    # SIP / Phone (Twilio)
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
    # SIP / Phone (Plivo)
    PLIVO_AUTH_ID = os.getenv("PLIVO_AUTH_ID", "")
    PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN", "")
    PLIVO_PHONE_NUMBER = os.getenv("PLIVO_PHONE_NUMBER", "")
    # Direct SIP (self-hosted PBX / Asterisk)
    SIP_URI = os.getenv("SIP_URI", "")
    SIP_USER = os.getenv("SIP_USER", "")
    SIP_PASSWORD = os.getenv("SIP_PASSWORD", "")
    SIP_REALM = os.getenv("SIP_REALM", "")
    # Call webhook URL (public URL for Twilio/Plivo to reach back)
    CALL_WEBHOOK_URL = os.getenv("CALL_WEBHOOK_URL", "")
    # Call recording
    CALL_RECORDING_ENABLED: bool = os.getenv("CALL_RECORDING_ENABLED", "false").lower() in {
        "1", "true", "yes", "y", "on",
    }
    # Web dashboard
    WEB_DASHBOARD_ENABLED: bool = os.getenv("WEB_DASHBOARD_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    WEB_DASHBOARD_PORT: int = int(os.getenv("WEB_DASHBOARD_PORT", "8090"))
    WEB_DASHBOARD_HOST: str = os.getenv("WEB_DASHBOARD_HOST", "127.0.0.1")
    # Hermes-class dashboard (v31, 2026-06-21) — Jinja2 template
    # and static-asset directories.  Defaults live under app/web/
    # so a fresh checkout "just works" without env-var setup.
    DASHBOARD_TEMPLATES_DIR: str = os.getenv("RAVEN_DASHBOARD_TEMPLATES_DIR", "app/web/templates")
    DASHBOARD_STATIC_DIR: str = os.getenv("RAVEN_DASHBOARD_STATIC_DIR", "app/web/static")
    # Hermes dashboard binds to 127.0.0.1 by default (single-user).
    # Override with RAVEN_DASHBOARD_HOST=0.0.0.0 to expose on LAN.
    DASHBOARD_HOST: str = os.getenv("RAVEN_DASHBOARD_HOST", "127.0.0.1")
    DASHBOARD_PORT: int = int(os.getenv("RAVEN_DASHBOARD_PORT", "8765"))
    # Streamlit dashboard
    STREAMLIT_DASHBOARD_ENABLED: bool = os.getenv(
        "STREAMLIT_DASHBOARD_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    STREAMLIT_DASHBOARD_PORT: int = int(os.getenv("STREAMLIT_DASHBOARD_PORT", "8501"))
    STREAMLIT_DASHBOARD_HOST: str = os.getenv("STREAMLIT_DASHBOARD_HOST", "127.0.0.1")
    # Safety & Sandboxing
    ALLOW_HOST_SHELL_EXECUTION: bool = os.getenv("ALLOW_HOST_SHELL_EXECUTION", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    # Ollama / local LLM (Phase 6.3 — already present above; kept here for completeness)
