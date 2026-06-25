from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AuthType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    FREE = "free"
    LOCAL = "local"
    CLI = "cli"
    BRIDGE = "bridge"


class ProviderTier(str, Enum):
    FREE = "free"
    CHEAP = "cheap"
    SUBSCRIPTION = "subscription"
    PREMIUM = "premium"
    LARGE = "large"
    LOCAL = "local"


@dataclass
class ModelInfo:
    id: str
    name: str
    context: int = 8192
    tier: ProviderTier = ProviderTier.FREE
    quality: float = 0.5


@dataclass
class ProviderInfo:
    id: str
    name: str
    auth_type: AuthType
    tier: ProviderTier
    base_url: str = ""
    env_var: str = ""
    config_attr: str = ""
    models: list[ModelInfo] = field(default_factory=list)
    group: str = "cloud"
    description: str = ""
    website: str = ""
    default_model: str = ""


PROVIDER_REGISTRY: list[ProviderInfo] = [
    # ── Subscription / OAuth Providers ──────────────────────────
    ProviderInfo(
        id="anthropic",
        name="Anthropic (Claude)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="https://api.anthropic.com/v1",
        env_var="ANTHROPIC_API_KEY",
        config_attr="ANTHROPIC_API_KEY",
        group="subscription",
        website="https://anthropic.com",
        description="Claude Opus, Sonnet, Haiku — best-in-class reasoning",
        default_model="claude-sonnet-4-20250514",
        models=[
            ModelInfo(
                "claude-sonnet-4-20250514",
                "Claude Sonnet 4",
                200000,
                ProviderTier.SUBSCRIPTION,
                0.93,
            ),
            ModelInfo(
                "claude-opus-4-20250514", "Claude Opus 4", 200000, ProviderTier.SUBSCRIPTION, 0.95
            ),
            ModelInfo(
                "claude-3-5-sonnet-20241022",
                "Claude 3.5 Sonnet",
                200000,
                ProviderTier.SUBSCRIPTION,
                0.90,
            ),
            ModelInfo(
                "claude-3-5-haiku-20241022", "Claude 3.5 Haiku", 200000, ProviderTier.CHEAP, 0.78
            ),
        ],
    ),
    ProviderInfo(
        id="openai",
        name="OpenAI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="https://api.openai.com/v1",
        env_var="OPENAI_API_KEY",
        config_attr="OPENAI_API_KEY",
        group="subscription",
        website="https://openai.com",
        description="GPT-4o, GPT-4.1, o3 — broad capabilities",
        default_model="gpt-4o",
        models=[
            ModelInfo("gpt-4o", "GPT-4o", 128000, ProviderTier.SUBSCRIPTION, 0.88),
            ModelInfo("gpt-4.1", "GPT-4.1", 1000000, ProviderTier.LARGE, 0.92),
            ModelInfo("gpt-4o-mini", "GPT-4o Mini", 128000, ProviderTier.CHEAP, 0.72),
            ModelInfo("o3", "o3 (Reasoning)", 200000, ProviderTier.PREMIUM, 0.95),
        ],
    ),
    ProviderInfo(
        id="google",
        name="Google Gemini",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="GOOGLE_API_KEY",
        config_attr="GOOGLE_API_KEY",
        group="subscription",
        website="https://ai.google.dev",
        description="Gemini 1.5 Pro/Flash, 2.0 Flash — 1M context, strong vision",
        default_model="gemini-1.5-pro",
        models=[
            ModelInfo("gemini-1.5-pro", "Gemini 1.5 Pro", 1000000, ProviderTier.SUBSCRIPTION, 0.88),
            ModelInfo("gemini-1.5-flash", "Gemini 1.5 Flash", 1000000, ProviderTier.CHEAP, 0.72),
            ModelInfo("gemini-2.0-flash", "Gemini 2.0 Flash", 1000000, ProviderTier.CHEAP, 0.78),
        ],
    ),
    ProviderInfo(
        id="xai",
        name="xAI (Grok)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="https://api.x.ai/v1",
        env_var="XAI_API_KEY",
        config_attr="XAI_API_KEY",
        group="subscription",
        website="https://x.ai",
        description="Grok-2, Grok-2 Vision — real-time knowledge",
        default_model="grok-2",
        models=[
            ModelInfo("grok-2", "Grok-2", 131072, ProviderTier.SUBSCRIPTION, 0.85),
            ModelInfo("grok-2-vision", "Grok-2 Vision", 131072, ProviderTier.SUBSCRIPTION, 0.85),
        ],
    ),
    # ── Free Providers ──────────────────────────────────────────
    ProviderInfo(
        id="opencode_zen",
        name="OpenCode Zen (Free)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.FREE,
        base_url="https://opencode.ai/zen/v1",
        env_var="OPENCODE_ZEN_API_KEY",
        config_attr="OPENCODE_ZEN_API_KEY",
        group="free",
        website="https://opencode.ai",
        description="Free models via OpenCode Zen gateway — no key needed",
        default_model="big-pickle",
        models=[
            ModelInfo("big-pickle", "Big Pickle (Free)", 200000, ProviderTier.FREE, 0.72),
            ModelInfo(
                "deepseek-v4-flash-free",
                "DeepSeek V4 Flash (Free)",
                128000,
                ProviderTier.FREE,
                0.78,
            ),
            ModelInfo("mimo-v2.5-free", "MiMo V2.5 (Free)", 128000, ProviderTier.FREE, 0.70),
            ModelInfo("qwen3.6-plus-free", "Qwen 3.6 Plus (Free)", 128000, ProviderTier.FREE, 0.75),
            ModelInfo(
                "nemotron-3-super-free",
                "Nemotron 3 Super (Free)",
                1000000,
                ProviderTier.FREE,
                0.80,
            ),
        ],
    ),
    # ── Aggregators / Multi-Provider ────────────────────────────
    ProviderInfo(
        id="openrouter",
        name="OpenRouter",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://openrouter.ai/api/v1",
        env_var="OPENROUTER_API_KEY",
        config_attr="OPENROUTER_API_KEY",
        group="aggregator",
        website="https://openrouter.ai",
        description="200+ models via single key — auto-fallback, routing",
        default_model="anthropic/claude-3.5-sonnet",
        models=[
            ModelInfo(
                "anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", 200000, ProviderTier.CHEAP, 0.90
            ),
            ModelInfo(
                "meta-llama/llama-3.1-70b-instruct",
                "Llama 3.1 70B",
                128000,
                ProviderTier.CHEAP,
                0.82,
            ),
            ModelInfo(
                "qwen/qwen-2.5-coder-32b-instruct",
                "Qwen 2.5 Coder 32B",
                32768,
                ProviderTier.CHEAP,
                0.86,
            ),
            ModelInfo("mistralai/mistral-large", "Mistral Large", 128000, ProviderTier.CHEAP, 0.84),
        ],
    ),
    ProviderInfo(
        id="nvidia",
        name="NVIDIA NIM",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://integrate.api.nvidia.com/v1",
        env_var="NVIDIA_NIM_API_KEY",
        config_attr="NVIDIA_NIM_API_KEY",
        group="aggregator",
        website="https://build.nvidia.com",
        description="Llama, Nemotron, Mixtral — free tier available",
        default_model="meta/llama3-70b-instruct",
        models=[
            ModelInfo("meta/llama3-70b-instruct", "Llama 3 70B", 128000, ProviderTier.CHEAP, 0.82),
            ModelInfo(
                "mistralai/mixtral-8x22b-instruct", "Mixtral 8x22B", 65536, ProviderTier.CHEAP, 0.80
            ),
        ],
    ),
    ProviderInfo(
        id="huggingface",
        name="HuggingFace Inference",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api-inference.huggingface.co/v1",
        env_var="HUGGINGFACE_API_KEY",
        config_attr="HUGGINGFACE_API_KEY",
        group="aggregator",
        website="https://huggingface.co",
        description="Any model on HF Hub via unified API",
        default_model="meta-llama/Meta-Llama-3-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3-70B-Instruct",
                "Llama 3 70B",
                8192,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    ProviderInfo(
        id="bytez",
        name="Bytez",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.bytez.com/v1",
        env_var="BYTEZ_API_KEY",
        config_attr="BYTEZ_API_KEY",
        group="aggregator",
        website="https://bytez.com",
        description="Multi-model gateway",
        default_model="meta-llama/Meta-Llama-3-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3-70B-Instruct",
                "Llama 3 70B",
                8192,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    # ── Cloud API Providers ─────────────────────────────────────
    ProviderInfo(
        id="groq",
        name="Groq",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.FREE,
        base_url="https://api.groq.com/openai/v1",
        env_var="GROQ_API_KEY",
        config_attr="GROQ_API_KEY",
        group="cloud",
        website="https://groq.com",
        description="Fast inference — Llama 3.1, Mixtral, Gemma — free tier",
        default_model="llama-3.1-70b-versatile",
        models=[
            ModelInfo("llama-3.1-70b-versatile", "Llama 3.1 70B", 131072, ProviderTier.FREE, 0.82),
            ModelInfo("llama-3.1-8b-instant", "Llama 3.1 8B", 131072, ProviderTier.FREE, 0.72),
            ModelInfo("mixtral-8x7b-32768", "Mixtral 8x7B", 32768, ProviderTier.FREE, 0.76),
        ],
    ),
    ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.deepseek.com/v1",
        env_var="DEEPSEEK_API_KEY",
        config_attr="",
        group="cloud",
        website="https://deepseek.com",
        description="DeepSeek-V3, DeepSeek-R1 — extremely cheap, strong coding",
        default_model="deepseek-chat",
        models=[
            ModelInfo("deepseek-chat", "DeepSeek V3", 65536, ProviderTier.CHEAP, 0.86),
            ModelInfo("deepseek-reasoner", "DeepSeek R1", 65536, ProviderTier.CHEAP, 0.88),
        ],
    ),
    ProviderInfo(
        id="mistral",
        name="Mistral AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.mistral.ai/v1",
        env_var="MISTRAL_API_KEY",
        config_attr="",
        group="cloud",
        website="https://mistral.ai",
        description="Mistral Large, Small, Codestral — strong European LLMs",
        default_model="mistral-large-latest",
        models=[
            ModelInfo("mistral-large-latest", "Mistral Large", 128000, ProviderTier.CHEAP, 0.84),
            ModelInfo("codestral-latest", "Codestral", 256000, ProviderTier.CHEAP, 0.82),
            ModelInfo("mistral-small-latest", "Mistral Small", 32768, ProviderTier.CHEAP, 0.76),
        ],
    ),
    ProviderInfo(
        id="cohere",
        name="Cohere",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.cohere.ai/v1",
        env_var="COHERE_API_KEY",
        config_attr="",
        group="cloud",
        website="https://cohere.com",
        description="Command R+, Command R — enterprise-grade RAG",
        default_model="command-r-plus",
        models=[
            ModelInfo("command-r-plus", "Command R+", 128000, ProviderTier.CHEAP, 0.82),
            ModelInfo("command-r", "Command R", 128000, ProviderTier.CHEAP, 0.76),
        ],
    ),
    ProviderInfo(
        id="perplexity",
        name="Perplexity AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.perplexity.ai",
        env_var="PERPLEXITY_API_KEY",
        config_attr="",
        group="cloud",
        website="https://perplexity.ai",
        description="Online LLMs with web search grounding",
        default_model="sonar-pro",
        models=[
            ModelInfo("sonar-pro", "Sonar Pro", 200000, ProviderTier.CHEAP, 0.84),
            ModelInfo("sonar", "Sonar", 200000, ProviderTier.CHEAP, 0.78),
        ],
    ),
    ProviderInfo(
        id="together",
        name="Together AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.together.xyz/v1",
        env_var="TOGETHER_API_KEY",
        config_attr="",
        group="cloud",
        website="https://together.ai",
        description="200+ open models — Llama, Qwen, DeepSeek, Mixtral",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                "Llama 3.1 70B",
                131072,
                ProviderTier.CHEAP,
                0.82,
            ),
            ModelInfo(
                "Qwen/Qwen2.5-Coder-32B-Instruct",
                "Qwen 2.5 Coder 32B",
                32768,
                ProviderTier.CHEAP,
                0.86,
            ),
        ],
    ),
    ProviderInfo(
        id="fireworks",
        name="Fireworks AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.fireworks.ai/inference/v1",
        env_var="FIREWORKS_API_KEY",
        config_attr="",
        group="cloud",
        website="https://fireworks.ai",
        description="Fast, cheap — Llama 3, Qwen, DeepSeek, Mixtral",
        default_model="accounts/fireworks/models/llama-v3p1-70b-instruct",
        models=[
            ModelInfo(
                "accounts/fireworks/models/llama-v3p1-70b-instruct",
                "Llama 3.1 70B",
                131072,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    ProviderInfo(
        id="cerebras",
        name="Cerebras",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.cerebras.ai/v1",
        env_var="CEREBRAS_API_KEY",
        config_attr="",
        group="cloud",
        website="https://cerebras.ai",
        description="Fastest inference — Llama 3.1 8B, 70B — wafer-scale",
        default_model="llama3.1-70b",
        models=[
            ModelInfo("llama3.1-70b", "Llama 3.1 70B", 8192, ProviderTier.CHEAP, 0.82),
            ModelInfo("llama3.1-8b", "Llama 3.1 8B", 8192, ProviderTier.CHEAP, 0.72),
        ],
    ),
    # ── Local Providers ─────────────────────────────────────────
    ProviderInfo(
        id="ollama",
        name="Ollama (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://localhost:11434",
        env_var="OLLAMA_BASE_URL",
        config_attr="OLLAMA_BASE_URL",
        group="local",
        website="https://ollama.ai",
        description="Run models locally — Llama, Qwen, Mistral, Gemma",
        default_model="llama3.2:3b",
        models=[
            ModelInfo("llama3.2:3b", "Llama 3.2 3B", 8192, ProviderTier.LOCAL, 0.55),
            ModelInfo("llama3.2:1b", "Llama 3.2 1B", 8192, ProviderTier.LOCAL, 0.40),
            ModelInfo("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B", 32768, ProviderTier.LOCAL, 0.78),
            ModelInfo("llama3.1:8b", "Llama 3.1 8B", 128000, ProviderTier.LOCAL, 0.65),
            ModelInfo("qwen2.5:14b", "Qwen 2.5 14B", 128000, ProviderTier.LOCAL, 0.70),
        ],
    ),
    ProviderInfo(
        id="lm_studio",
        name="LM Studio (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://localhost:1234/v1",
        env_var="LM_STUDIO_BASE_URL",
        config_attr="LM_STUDIO_BASE_URL",
        group="local",
        website="https://lmstudio.ai",
        description="Local model server — OpenAI-compatible API",
        default_model="local-model",
        models=[
            ModelInfo("local-model", "Local Model", 8192, ProviderTier.LOCAL, 0.50),
        ],
    ),
    ProviderInfo(
        id="localai",
        name="LocalAI (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://localhost:8080/v1",
        env_var="LOCALAI_BASE_URL",
        config_attr="LOCALAI_BASE_URL",
        group="local",
        website="https://localai.io",
        description="Self-hosted OpenAI-compatible API",
        default_model="local-model",
        models=[
            ModelInfo("local-model", "Local Model", 8192, ProviderTier.LOCAL, 0.50),
        ],
    ),
    ProviderInfo(
        id="vllm",
        name="vLLM (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://localhost:8000/v1",
        env_var="VLLM_BASE_URL",
        config_attr="VLLM_BASE_URL",
        group="local",
        website="https://vllm.ai",
        description="High-throughput local inference server",
        default_model="local-model",
        models=[
            ModelInfo("local-model", "Local Model", 8192, ProviderTier.LOCAL, 0.50),
        ],
    ),
    # ── 9Router — Smart AI Router ────────────────────────────────
    ProviderInfo(
        id="9router",
        name="9Router (Smart Router)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="http://localhost:20128/v1",
        env_var="NINEROUTER_API_KEY",
        config_attr="NINEROUTER_API_KEY",
        group="router",
        website="https://9router.com",
        description="40+ providers, auto-fallback, RTK token savings (-20-40%), format translation",
        default_model="kr/claude-sonnet-4.5",
        models=[
            ModelInfo(
                "kr/claude-sonnet-4.5",
                "Claude Sonnet 4.5 (Kiro Free)",
                200000,
                ProviderTier.FREE,
                0.88,
            ),
            ModelInfo("kr/glm-5", "GLM-5 (Kiro Free)", 128000, ProviderTier.FREE, 0.75),
            ModelInfo(
                "kr/deepseek-3.2", "DeepSeek 3.2 (Kiro Free)", 128000, ProviderTier.FREE, 0.80
            ),
            ModelInfo("oc/autonomous", "OpenCode Free", 128000, ProviderTier.FREE, 0.70),
            ModelInfo("glm/glm-5.1", "GLM-5.1", 128000, ProviderTier.CHEAP, 0.82),
            ModelInfo("minimax/MiniMax-M2.7", "MiniMax M2.7", 128000, ProviderTier.CHEAP, 0.78),
            ModelInfo(
                "cc/claude-opus-4-7",
                "Claude Opus 4.7 (Claude Code)",
                200000,
                ProviderTier.SUBSCRIPTION,
                0.95,
            ),
            ModelInfo(
                "cc/claude-sonnet-4-6",
                "Claude Sonnet 4.6 (Claude Code)",
                200000,
                ProviderTier.SUBSCRIPTION,
                0.93,
            ),
            ModelInfo("cx/gpt-5.5", "GPT-5.5 (Codex)", 128000, ProviderTier.SUBSCRIPTION, 0.92),
        ],
    ),
    # ── OpenCode Providers (from opencode.ai/docs/providers/) ──────
    ProviderInfo(
        id="moonshot",
        name="Moonshot AI (Kimi)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.moonshot.cn/v1",
        env_var="MOONSHOT_API_KEY",
        config_attr="MOONSHOT_API_KEY",
        group="cloud",
        website="https://moonshot.ai",
        description="Kimi K2 — 128K context, strong reasoning",
        default_model="moonshot-v1-8k",
        models=[
            ModelInfo("moonshot-v1-8k", "Moonshot V1 8K", 8192, ProviderTier.CHEAP, 0.78),
            ModelInfo("moonshot-v1-32k", "Moonshot V1 32K", 32768, ProviderTier.CHEAP, 0.80),
            ModelInfo("moonshot-v1-128k", "Moonshot V1 128K", 128000, ProviderTier.CHEAP, 0.82),
        ],
    ),
    ProviderInfo(
        id="minimax",
        name="MiniMax",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.minimax.chat/v1",
        env_var="MINIMAX_API_KEY",
        config_attr="MINIMAX_API_KEY",
        group="cloud",
        website="https://minimax.chat",
        description="MiniMax M2.1 — ultra-cheap, strong multilingual",
        default_model="MiniMax-Text-01",
        models=[
            ModelInfo("MiniMax-Text-01", "MiniMax M2.1", 4096000, ProviderTier.CHEAP, 0.78),
        ],
    ),
    ProviderInfo(
        id="zhipu",
        name="Zhipu AI (GLM)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        env_var="ZHIPU_API_KEY",
        config_attr="ZHIPU_API_KEY",
        group="cloud",
        website="https://zhipuai.cn",
        description="GLM-4, GLM-4-Plus — Chinese AI leader",
        default_model="glm-4",
        models=[
            ModelInfo("glm-4", "GLM-4", 128000, ProviderTier.CHEAP, 0.80),
            ModelInfo("glm-4-plus", "GLM-4 Plus", 128000, ProviderTier.CHEAP, 0.84),
        ],
    ),
    ProviderInfo(
        id="volcengine",
        name="Volcengine (Doubao)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        env_var="VOLCENGINE_API_KEY",
        config_attr="VOLCENGINE_API_KEY",
        group="cloud",
        website="https://volcengine.com",
        description="Doubao Pro — ByteDance's flagship LLM",
        default_model="doubao-pro-32k",
        models=[
            ModelInfo("doubao-pro-32k", "Doubao Pro 32K", 32768, ProviderTier.CHEAP, 0.78),
            ModelInfo("doubao-lite-32k", "Doubao Lite 32K", 32768, ProviderTier.CHEAP, 0.68),
        ],
    ),
    ProviderInfo(
        id="baidu",
        name="Baidu (ERNIE)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop",
        env_var="BAIDU_API_KEY",
        config_attr="BAIDU_API_KEY",
        group="cloud",
        website="https://cloud.baidu.com",
        description="ERNIE 4.0, ERNIE Speed — Baidu's LLM family",
        default_model="ernie-4.0-8k",
        models=[
            ModelInfo("ernie-4.0-8k", "ERNIE 4.0", 8192, ProviderTier.CHEAP, 0.80),
            ModelInfo("ernie-speed-128k", "ERNIE Speed 128K", 128000, ProviderTier.CHEAP, 0.72),
        ],
    ),
    ProviderInfo(
        id="alibaba",
        name="Alibaba (Qwen)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        env_var="DASHSCOPE_API_KEY",
        config_attr="DASHSCOPE_API_KEY",
        group="cloud",
        website="https://dashscope.aliyun.com",
        description="Qwen2.5, Qwen-Max — Alibaba's LLM family",
        default_model="qwen-max",
        models=[
            ModelInfo("qwen-max", "Qwen-Max", 32768, ProviderTier.CHEAP, 0.84),
            ModelInfo("qwen-plus", "Qwen-Plus", 131072, ProviderTier.CHEAP, 0.80),
            ModelInfo("qwen-turbo", "Qwen-Turbo", 131072, ProviderTier.CHEAP, 0.72),
        ],
    ),
    ProviderInfo(
        id="siliconflow",
        name="SiliconFlow",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.FREE,
        base_url="https://api.siliconflow.cn/v1",
        env_var="SILICONFLOW_API_KEY",
        config_attr="SILICONFLOW_API_KEY",
        group="cloud",
        website="https://siliconflow.cn",
        description="Free tier for open models — Llama, Qwen, DeepSeek",
        default_model="Qwen/Qwen2.5-72B-Instruct",
        models=[
            ModelInfo("Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B", 131072, ProviderTier.FREE, 0.82),
            ModelInfo("deepseek-ai/DeepSeek-R1", "DeepSeek R1", 65536, ProviderTier.FREE, 0.86),
        ],
    ),
    ProviderInfo(
        id="nebius",
        name="Nebius",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.studio.nebius.com/v1",
        env_var="NEBIUS_API_KEY",
        config_attr="NEBIUS_API_KEY",
        group="cloud",
        website="https://nebius.com",
        description="Qwen 3, Llama 3 — cheap open model hosting",
        default_model="Qwen/Qwen3-235B-A22B",
        models=[
            ModelInfo("Qwen/Qwen3-235B-A22B", "Qwen3 235B", 131072, ProviderTier.CHEAP, 0.86),
            ModelInfo(
                "meta-llama/Llama-4-Scout-17B-16E-Instruct",
                "Llama 4 Scout",
                131072,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    ProviderInfo(
        id="chutes",
        name="Chutes AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.FREE,
        base_url="https://api.chutes.ai/v1",
        env_var="CHUTES_API_KEY",
        config_attr="CHUTES_API_KEY",
        group="cloud",
        website="https://chutes.ai",
        description="Free tier for open models",
        default_model="chutesai/Llama-3.3-70B-Instruct",
        models=[
            ModelInfo(
                "chutesai/Llama-3.3-70B-Instruct", "Llama 3.3 70B", 128000, ProviderTier.FREE, 0.80
            ),
        ],
    ),
    ProviderInfo(
        id="hyperbolic",
        name="Hyperbolic",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.hyperbolic.xyz/v1",
        env_var="HYPERBOLIC_API_KEY",
        config_attr="HYPERBOLIC_API_KEY",
        group="cloud",
        website="https://hyperbolic.xyz",
        description="Open model hosting — Llama, Qwen, DeepSeek",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "Llama 3.1 70B",
                128000,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    ProviderInfo(
        id="deepinfra",
        name="Deep Infra",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.deepinfra.com/v1/openai",
        env_var="DEEPINFRA_API_KEY",
        config_attr="DEEPINFRA_API_KEY",
        group="cloud",
        website="https://deepinfra.com",
        description="Cheap open model hosting — Llama, Mistral, Qwen",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "Llama 3.1 70B",
                128000,
                ProviderTier.CHEAP,
                0.82,
            ),
            ModelInfo(
                "mistralai/Mistral-Small-24B-Instruct-2501",
                "Mistral Small 24B",
                32768,
                ProviderTier.CHEAP,
                0.78,
            ),
        ],
    ),
    ProviderInfo(
        id="venice",
        name="Venice AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.venice.ai/api/v1",
        env_var="VENICE_API_KEY",
        config_attr="VENICE_API_KEY",
        group="cloud",
        website="https://venice.ai",
        description="Private AI — no logging, open models",
        default_model="venice-uncensored",
        models=[
            ModelInfo("venice-uncensored", "Venice Uncensored", 128000, ProviderTier.CHEAP, 0.72),
        ],
    ),
    ProviderInfo(
        id="scaleway",
        name="Scaleway",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.scaleway.ai/v1",
        env_var="SCALEWAY_API_KEY",
        config_attr="SCALEWAY_API_KEY",
        group="cloud",
        website="https://scaleway.com",
        description="Llama, Mistral — European hosting",
        default_model="meta/llama-3.3-70B-Instruct",
        models=[
            ModelInfo(
                "meta/llama-3.3-70B-Instruct", "Llama 3.3 70B", 128000, ProviderTier.CHEAP, 0.80
            ),
        ],
    ),
    ProviderInfo(
        id="ovhcloud",
        name="OVHcloud AI Endpoints",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://endpoints.ai.cloud.ovh.com/v1",
        env_var="OVHCLOUD_API_KEY",
        config_attr="OVHCLOUD_API_KEY",
        group="cloud",
        website="https://ovhcloud.com",
        description="Llama, Mistral — European data residency",
        default_model="meta/llama-3.3-70b-instruct",
        models=[
            ModelInfo(
                "meta/llama-3.3-70b-instruct", "Llama 3.3 70B", 128000, ProviderTier.CHEAP, 0.80
            ),
        ],
    ),
    ProviderInfo(
        id="stackit",
        name="STACKIT",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.stackit.ai/v1",
        env_var="STACKIT_API_KEY",
        config_attr="STACKIT_API_KEY",
        group="cloud",
        website="https://stackit.de",
        description="German cloud AI — Llama, Mistral",
        default_model="meta-llama/Llama-3.3-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Llama-3.3-70B-Instruct",
                "Llama 3.3 70B",
                128000,
                ProviderTier.CHEAP,
                0.80,
            ),
        ],
    ),
    ProviderInfo(
        id="digitalocean",
        name="DigitalOcean",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.digitalocean.com/v2/genai",
        env_var="DIGITALOCEAN_ACCESS_TOKEN",
        config_attr="DIGITALOCEAN_ACCESS_TOKEN",
        group="cloud",
        website="https://digitalocean.com",
        description="Inference Engine — GPT-OSS, Llama, Qwen, DeepSeek",
        default_model="llama-3.3-70b-instruct",
        models=[
            ModelInfo("llama-3.3-70b-instruct", "Llama 3.3 70B", 128000, ProviderTier.CHEAP, 0.80),
        ],
    ),
    ProviderInfo(
        id="baseten",
        name="Baseten",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.baseten.co/v1",
        env_var="BASETEN_API_KEY",
        config_attr="BASETEN_API_KEY",
        group="cloud",
        website="https://baseten.co",
        description="Truss model hosting — Llama, Mistral",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "Llama 3.1 70B",
                128000,
                ProviderTier.CHEAP,
                0.82,
            ),
        ],
    ),
    ProviderInfo(
        id="cortecs",
        name="Cortecs",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.cortecs.ai/v1",
        env_var="CORTECS_API_KEY",
        config_attr="CORTECS_API_KEY",
        group="cloud",
        website="https://cortecs.ai",
        description="Kimi K2 — fast inference",
        default_model="kimi-k2",
        models=[
            ModelInfo("kimi-k2", "Kimi K2", 128000, ProviderTier.CHEAP, 0.80),
        ],
    ),
    ProviderInfo(
        id="io_net",
        name="IO.NET",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.io.net/v1",
        env_var="IO_NET_API_KEY",
        config_attr="IO_NET_API_KEY",
        group="cloud",
        website="https://io.net",
        description="Decentralized GPU network — Llama, Mistral",
        default_model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        models=[
            ModelInfo(
                "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "Llama 3.1 70B",
                128000,
                ProviderTier.CHEAP,
                0.80,
            ),
        ],
    ),
    ProviderInfo(
        id="302ai",
        name="302.AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.302.ai/v1",
        env_var="THREE_HUNDRED_TWO_AI_API_KEY",
        config_attr="THREE_HUNDRED_TWO_AI_API_KEY",
        group="cloud",
        website="https://302.ai",
        description="Multi-model gateway — Llama, Qwen, DeepSeek",
        default_model="deepseek-chat",
        models=[
            ModelInfo("deepseek-chat", "DeepSeek V3", 65536, ProviderTier.CHEAP, 0.86),
        ],
    ),
    ProviderInfo(
        id="frogbot",
        name="FrogBot",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.frogbot.ai/v1",
        env_var="FROGBOT_API_KEY",
        config_attr="FROGBOT_API_KEY",
        group="cloud",
        website="https://frogbot.ai",
        description="AI agent platform",
        default_model="frogbot-default",
        models=[
            ModelInfo("frogbot-default", "FrogBot Default", 128000, ProviderTier.CHEAP, 0.70),
        ],
    ),
    # ── OAuth / Subscription Providers ──────────────────────────
    ProviderInfo(
        id="github_copilot",
        name="GitHub Copilot",
        auth_type=AuthType.OAUTH,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="GITHUB_TOKEN",
        config_attr="GITHUB_TOKEN",
        group="subscription",
        website="https://github.com/features/copilot",
        description="GPT-4o, Claude via GitHub Copilot subscription",
        default_model="gpt-4o",
        models=[
            ModelInfo("gpt-4o", "GPT-4o", 128000, ProviderTier.SUBSCRIPTION, 0.88),
            ModelInfo(
                "claude-3.5-sonnet", "Claude 3.5 Sonnet", 200000, ProviderTier.SUBSCRIPTION, 0.90
            ),
        ],
    ),
    ProviderInfo(
        id="gitlab_duo",
        name="GitLab Duo",
        auth_type=AuthType.OAUTH,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="GITLAB_TOKEN",
        config_attr="GITLAB_TOKEN",
        group="subscription",
        website="https://gitlab.com",
        description="Claude via GitLab Duo Agent Platform",
        default_model="duo-chat-haiku-4-5",
        models=[
            ModelInfo(
                "duo-chat-haiku-4-5", "Claude Haiku 4.5", 200000, ProviderTier.SUBSCRIPTION, 0.78
            ),
            ModelInfo(
                "duo-chat-sonnet-4-5", "Claude Sonnet 4.5", 200000, ProviderTier.SUBSCRIPTION, 0.88
            ),
            ModelInfo(
                "duo-chat-opus-4-5", "Claude Opus 4.5", 200000, ProviderTier.SUBSCRIPTION, 0.95
            ),
        ],
    ),
    ProviderInfo(
        id="google_vertex",
        name="Google Vertex AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="GOOGLE_APPLICATION_CREDENTIALS",
        config_attr="GOOGLE_APPLICATION_CREDENTIALS",
        group="subscription",
        website="https://cloud.google.com/vertex-ai",
        description="Gemini via Google Cloud — $300 free credits",
        default_model="gemini-2.5-pro-preview-05-06",
        models=[
            ModelInfo(
                "gemini-2.5-pro-preview-05-06",
                "Gemini 2.5 Pro",
                1000000,
                ProviderTier.SUBSCRIPTION,
                0.92,
            ),
            ModelInfo(
                "gemini-2.5-flash-preview-05-20",
                "Gemini 2.5 Flash",
                1000000,
                ProviderTier.CHEAP,
                0.80,
            ),
        ],
    ),
    ProviderInfo(
        id="azure_openai",
        name="Azure OpenAI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="AZURE_RESOURCE_NAME",
        config_attr="AZURE_RESOURCE_NAME",
        group="subscription",
        website="https://azure.microsoft.com",
        description="GPT-4o, GPT-4.1 via Azure — enterprise compliance",
        default_model="gpt-4o",
        models=[
            ModelInfo("gpt-4o", "GPT-4o", 128000, ProviderTier.SUBSCRIPTION, 0.88),
        ],
    ),
    ProviderInfo(
        id="amazon_bedrock",
        name="Amazon Bedrock",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="AWS_ACCESS_KEY_ID",
        config_attr="AWS_ACCESS_KEY_ID",
        group="subscription",
        website="https://aws.amazon.com/bedrock",
        description="Claude, Llama, Mistral via AWS — enterprise compliance",
        default_model="anthropic.claude-3-5-sonnet-20241022-v1:0",
        models=[
            ModelInfo(
                "anthropic.claude-3-5-sonnet-20241022-v1:0",
                "Claude 3.5 Sonnet",
                200000,
                ProviderTier.SUBSCRIPTION,
                0.90,
            ),
            ModelInfo(
                "meta.llama3-70b-instruct-v1:0",
                "Llama 3 70B",
                128000,
                ProviderTier.SUBSCRIPTION,
                0.82,
            ),
        ],
    ),
    # ── Gateway / Proxy Providers ────────────────────────────────
    ProviderInfo(
        id="cloudflare_gateway",
        name="Cloudflare AI Gateway",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="",
        env_var="CLOUDFLARE_ACCOUNT_ID",
        config_attr="CLOUDFLARE_ACCOUNT_ID",
        group="gateway",
        website="https://developers.cloudflare.com/ai-gateway",
        description="Unified proxy for OpenAI, Anthropic, Workers AI",
        default_model="openai/gpt-4o",
        models=[
            ModelInfo("openai/gpt-4o", "GPT-4o", 128000, ProviderTier.CHEAP, 0.88),
        ],
    ),
    ProviderInfo(
        id="cloudflare_workers",
        name="Cloudflare Workers AI",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.FREE,
        base_url="",
        env_var="CLOUDFLARE_ACCOUNT_ID",
        config_attr="CLOUDFLARE_ACCOUNT_ID",
        group="gateway",
        website="https://developers.cloudflare.com/workers-ai",
        description="Free tier — Llama, Mistral on Cloudflare's network",
        default_model="@cf/meta/llama-3.3-70b-instruct-fp8",
        models=[
            ModelInfo(
                "@cf/meta/llama-3.3-70b-instruct-fp8",
                "Llama 3.3 70B",
                8192,
                ProviderTier.FREE,
                0.78,
            ),
        ],
    ),
    ProviderInfo(
        id="helicone",
        name="Helicone",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://ai-gateway.helicone.ai",
        env_var="HELICONE_API_KEY",
        config_attr="HELICONE_API_KEY",
        group="gateway",
        website="https://helicone.ai",
        description="LLM observability + proxy — cache, rate limit, analytics",
        default_model="openai/gpt-4o",
        models=[
            ModelInfo("openai/gpt-4o", "GPT-4o", 128000, ProviderTier.CHEAP, 0.88),
        ],
    ),
    ProviderInfo(
        id="llm_gateway",
        name="LLM Gateway",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.llmgateway.io/v1",
        env_var="LLMGATEWAY_API_KEY",
        config_attr="LLMGATEWAY_API_KEY",
        group="gateway",
        website="https://llmgateway.io",
        description="Multi-provider gateway — GLM, GPT, Gemini, Claude",
        default_model="glm-4.7",
        models=[
            ModelInfo("glm-4.7", "GLM 4.7", 128000, ProviderTier.CHEAP, 0.80),
        ],
    ),
    ProviderInfo(
        id="vercel_gateway",
        name="Vercel AI Gateway",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="",
        env_var="VERCEL_AI_GATEWAY_API_KEY",
        config_attr="VERCEL_AI_GATEWAY_API_KEY",
        group="gateway",
        website="https://vercel.com",
        description="Vercel's AI gateway — proxy for OpenAI, Anthropic",
        default_model="openai/gpt-4o",
        models=[
            ModelInfo("openai/gpt-4o", "GPT-4o", 128000, ProviderTier.CHEAP, 0.88),
        ],
    ),
    ProviderInfo(
        id="llamacpp",
        name="llama.cpp (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://localhost:8080/v1",
        env_var="LLAMACPP_BASE_URL",
        config_attr="LLAMACPP_BASE_URL",
        group="local",
        website="https://github.com/ggml-org/llama.cpp",
        description="Local llama-server — run any GGUF model",
        default_model="local-model",
        models=[
            ModelInfo("local-model", "Local Model", 8192, ProviderTier.LOCAL, 0.50),
        ],
    ),
    ProviderInfo(
        id="ollama_cloud",
        name="Ollama Cloud",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.ollama.com/v1",
        env_var="OLLAMA_CLOUD_API_KEY",
        config_attr="OLLAMA_CLOUD_API_KEY",
        group="cloud",
        website="https://ollama.com",
        description="Ollama hosted models — cloud inference",
        default_model="llama3.3-70b",
        models=[
            ModelInfo("llama3.3-70b", "Llama 3.3 70B", 128000, ProviderTier.CHEAP, 0.80),
        ],
    ),
    ProviderInfo(
        id="sap_ai_core",
        name="SAP AI Core",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="AICORE_SERVICE_KEY",
        config_attr="AICORE_SERVICE_KEY",
        group="enterprise",
        website="https://sap.com",
        description="Enterprise AI — Claude, GPT, Gemini via SAP BTP",
        default_model="gpt-4o",
        models=[
            ModelInfo("gpt-4o", "GPT-4o", 128000, ProviderTier.SUBSCRIPTION, 0.88),
        ],
    ),
    ProviderInfo(
        id="snowflake",
        name="Snowflake Cortex",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.SUBSCRIPTION,
        base_url="",
        env_var="SNOWFLAKE_ACCOUNT",
        config_attr="SNOWFLAKE_ACCOUNT",
        group="enterprise",
        website="https://snowflake.com",
        description="Enterprise AI via Snowflake — Llama, Mistral",
        default_model="llama3.1-70b",
        models=[
            ModelInfo("llama3.1-70b", "Llama 3.1 70B", 128000, ProviderTier.SUBSCRIPTION, 0.82),
        ],
    ),
    ProviderInfo(
        id="z_ai",
        name="Z.AI (Zhipu)",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        env_var="Z_AI_API_KEY",
        config_attr="Z_AI_API_KEY",
        group="cloud",
        website="https://z.ai",
        description="GLM-4 — Zhipu's international API",
        default_model="glm-4",
        models=[
            ModelInfo("glm-4", "GLM-4", 128000, ProviderTier.CHEAP, 0.80),
        ],
    ),
    ProviderInfo(
        id="zenmux",
        name="ZenMux",
        auth_type=AuthType.API_KEY,
        tier=ProviderTier.CHEAP,
        base_url="https://api.zenmux.ai/v1",
        env_var="ZENMUX_API_KEY",
        config_attr="ZENMUX_API_KEY",
        group="cloud",
        website="https://zenmux.ai",
        description="Multi-provider mux — aggregate multiple API keys",
        default_model="openai/gpt-4o",
        models=[
            ModelInfo("openai/gpt-4o", "GPT-4o", 128000, ProviderTier.CHEAP, 0.88),
        ],
    ),
    ProviderInfo(
        id="atomic_chat",
        name="Atomic Chat (Local)",
        auth_type=AuthType.LOCAL,
        tier=ProviderTier.LOCAL,
        base_url="http://127.0.0.1:1337/v1",
        env_var="ATOMIC_CHAT_URL",
        config_attr="ATOMIC_CHAT_URL",
        group="local",
        website="https://atomic.chat",
        description="Local LLM server — run any model locally",
        default_model="local-model",
        models=[
            ModelInfo("local-model", "Local Model", 8192, ProviderTier.LOCAL, 0.50),
        ],
    ),
]

PROVIDER_MAP: dict[str, ProviderInfo] = {p.id: p for p in PROVIDER_REGISTRY}


def get_provider(provider_id: str) -> ProviderInfo | None:
    return PROVIDER_MAP.get(provider_id)


def get_providers_by_tier(tier: ProviderTier) -> list[ProviderInfo]:
    return [p for p in PROVIDER_REGISTRY if p.tier == tier]


def get_providers_by_group(group: str) -> list[ProviderInfo]:
    return [p for p in PROVIDER_REGISTRY if p.group == group]


def get_enabled_providers() -> list[ProviderInfo]:
    import os
    from app.settings.config import Config

    enabled: list[ProviderInfo] = []
    for p in PROVIDER_REGISTRY:
        if p.auth_type == AuthType.LOCAL:
            enabled.append(p)
        elif p.id == "opencode_zen":
            enabled.append(p)
        elif p.auth_type in {AuthType.FREE, AuthType.OAUTH, AuthType.BRIDGE}:
            enabled.append(p)
        elif p.env_var:
            env_val = os.environ.get(p.env_var) or getattr(Config, p.env_var, None)
            if env_val:
                enabled.append(p)
    return enabled
