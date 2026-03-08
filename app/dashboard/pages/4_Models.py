"""LLM Models configuration page — provider/model per agent, API keys, connectivity."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SARAS - Models", page_icon="🧠", layout="wide")

st.title("LLM Model Configuration")
st.caption(
    "View and manage AI provider settings, API keys, and per-agent model assignments."
)

from app.dashboard.utils import (
    SENSITIVE_KEYS,
    check_port_open,
    get_agent_instances,
    read_env_file,
    update_env_value,
)

# ---------------------------------------------------------------------------
# Provider overview
# ---------------------------------------------------------------------------
st.subheader("AI Providers")

env = read_env_file()

PROVIDERS = {
    "Kilo (killo)": {
        "key_var": "KILLO_API_KEY",
        "base_url_var": "KILLO_BASE_URL",
        "default_url": "https://api.kilo.ai/api/gateway",
        "description": "Multi-model gateway — routes to 100+ models. Primary provider for all agents.",
    },
    "xAI (Grok)": {
        "key_var": "XAI_API_KEY",
        "base_url_var": None,
        "default_url": "api.x.ai:443",
        "description": "xAI Grok models for vision and advanced reasoning.",
    },
    "Google (Gemini)": {
        "key_var": "GEMINI_API_KEY",
        "base_url_var": None,
        "default_url": "generativelanguage.googleapis.com",
        "description": "Google Gemini models — used by web search and fetch tools.",
    },
    "OpenAI": {
        "key_var": "OPENAI_API_KEY",
        "base_url_var": None,
        "default_url": "api.openai.com",
        "description": "OpenAI GPT models — optional provider.",
    },
    "Anthropic": {
        "key_var": "ANTHROPIC_API_KEY",
        "base_url_var": None,
        "default_url": "api.anthropic.com",
        "description": "Anthropic Claude models — optional provider.",
    },
    "Ollama (Local)": {
        "key_var": None,
        "base_url_var": "OLLAMA_BASE_URL",
        "default_url": "http://localhost:11434",
        "description": "Local LLM via Ollama — fallback provider when cloud APIs fail.",
    },
}

for provider_name, pinfo in PROVIDERS.items():
    with st.expander(f"**{provider_name}**", expanded=False):
        st.markdown(pinfo["description"])

        # API Key
        if pinfo["key_var"]:
            current_key = env.get(pinfo["key_var"], "")
            has_key = bool(current_key and current_key not in ("", "your_key_here"))
            st.markdown(
                f"**API Key** (`{pinfo['key_var']}`): {'🟢 Set' if has_key else '🔴 Not set'}"
            )

            new_key = st.text_input(
                f"Set {pinfo['key_var']}",
                value=current_key,
                type="password",
                key=f"model_{pinfo['key_var']}",
            )
            if new_key != current_key:
                if st.button(
                    f"Save {pinfo['key_var']}", key=f"save_model_{pinfo['key_var']}"
                ):
                    update_env_value(pinfo["key_var"], new_key)
                    st.success(f"Saved {pinfo['key_var']}. Restart SARAS to apply.")
                    st.rerun()

        # Base URL
        if pinfo["base_url_var"]:
            current_url = env.get(pinfo["base_url_var"], pinfo["default_url"])
            new_url = st.text_input(
                f"Base URL (`{pinfo['base_url_var']}`)",
                value=current_url,
                key=f"model_url_{pinfo['base_url_var']}",
            )
            if new_url != current_url:
                if st.button(f"Save URL", key=f"save_url_{pinfo['base_url_var']}"):
                    update_env_value(pinfo["base_url_var"], new_url)
                    st.success(f"Saved {pinfo['base_url_var']}.")
                    st.rerun()

        # Connectivity test for Ollama
        if provider_name == "Ollama (Local)":
            ollama_url = env.get("OLLAMA_BASE_URL", "http://localhost:11434")
            # Parse host/port
            try:
                from urllib.parse import urlparse

                parsed = urlparse(ollama_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 11434
                reachable = check_port_open(host, port)
                if reachable:
                    st.success(f"Ollama is reachable at `{host}:{port}`")
                else:
                    st.warning(f"Ollama is NOT reachable at `{host}:{port}`")
            except Exception:
                st.warning("Could not parse Ollama URL")

            model = env.get("OLLAMA_MODEL", "mistral")
            st.markdown(f"**Default model**: `{model}`")
            new_model = st.text_input(
                "Ollama model", value=model, key="ollama_model_input"
            )
            if new_model != model:
                if st.button("Save Ollama model", key="save_ollama_model"):
                    update_env_value("OLLAMA_MODEL", new_model)
                    st.success("Saved.")
                    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Per-agent model assignments
# ---------------------------------------------------------------------------
st.subheader("Per-Agent Model Assignments")
st.info(
    "Each agent has a `provider_name` and `model_name` property defined in code. "
    "To change these, edit the agent's Python file. Below is a read-only overview."
)

agents = get_agent_instances()
if agents:
    agent_models = []
    for name, inst in sorted(agents.items()):
        agent_models.append(
            {
                "Agent": name,
                "Provider": getattr(inst, "provider_name", "killo"),
                "Model": getattr(inst, "model_name", "unknown"),
                "Perfectness": getattr(inst, "perfectness", 0.5),
            }
        )
    st.dataframe(agent_models, use_container_width=True, hide_index=True)

    # Distribution chart
    st.markdown("**Model Distribution:**")
    model_counts: dict[str, int] = {}
    for am in agent_models:
        model = am["Model"]
        model_counts[model] = model_counts.get(model, 0) + 1
    for model, count in sorted(model_counts.items(), key=lambda x: -x[1]):
        bar_len = count * 4
        st.markdown(f"`{model}`: {'█' * bar_len} ({count} agents)")
else:
    st.warning("No agents loaded.")

st.divider()

# ---------------------------------------------------------------------------
# Model failover settings
# ---------------------------------------------------------------------------
st.subheader("Model Failover")
st.markdown(
    """
The SARAS runtime uses a **resilient provider loop** (`chat_completion_resilient`):

1. Tries the agent's preferred model via Kilo gateway
2. If the primary model fails, tries free alternatives from the same provider
3. If all cloud providers fail, falls back to **Ollama** (local LLM)

This chain is configured in `app/core/runtime.py` and `app/providers/ollama/client.py`.
"""
)

ollama_reachable = check_port_open("localhost", 11434)
if ollama_reachable:
    st.success("Ollama fallback: AVAILABLE")
else:
    st.warning(
        "Ollama fallback: NOT AVAILABLE — "
        "Install Ollama (https://ollama.ai) and run `ollama serve` for local LLM fallback."
    )
