import re

with open("app/core/model_router.py", "r") as f:
    content = f.read()

new_method = """
    @classmethod
    def get_available_models(cls, role: str = "general") -> list[tuple[str, str]]:
        import shutil
        from app.settings.config import Config
        
        available = []

        # 0. Check fast local services
        if cls._check_local_endpoint(f"{Config.VLLM_BASE_URL}/models"):
            available.append(("vllm", "local-model"))
        if cls._check_local_endpoint(f"{Config.LM_STUDIO_BASE_URL}/models"):
            available.append(("lm_studio", "local-model"))
        if cls._check_local_endpoint(f"{Config.LOCALAI_BASE_URL}/models"):
            available.append(("localai", "local-model"))
        if cls._check_local_endpoint(f"{Config.OLLAMA_BASE_URL}/api/tags"):
            available.append(("ollama", Config.OLLAMA_MODEL))

        # 1. High-tier APIs
        if getattr(Config, "ANTHROPIC_API_KEY", None):
            available.append(("anthropic", "claude-3-5-sonnet-20241022"))
        if getattr(Config, "OPENAI_API_KEY", None):
            available.append(("openai", "gpt-4o"))
        if getattr(Config, "GOOGLE_API_KEY", None) or getattr(Config, "GEMINI_API_KEY", None):
            available.append(("google", "gemini-1.5-pro"))

        # 2. Aggregator APIs
        if getattr(Config, "OPENROUTER_API_KEY", None):
            available.append(("openrouter", "anthropic/claude-3.5-sonnet"))
        if getattr(Config, "NVIDIA_NIM_API_KEY", None):
            available.append(("nvidia", "meta/llama3-70b-instruct"))
        if getattr(Config, "HUGGINGFACE_API_KEY", None):
            available.append(("huggingface", "meta-llama/Meta-Llama-3-70B-Instruct"))
        if getattr(Config, "BYTEZ_API_KEY", None):
            available.append(("bytez", "meta-llama/Meta-Llama-3-70B-Instruct"))

        # 3. Local CLI Proxies
        cli_tools = [
            ("gh", "cli/gh-copilot"),
            ("opencode", "cli/opencode"),
            ("kilocode", "cli/kilocode"),
            ("jules", "cli/jules"),
            ("claude", "cli/claude"),
            ("qwen", "cli/qwen"),
            ("gemini", "cli/gemini"),
        ]

        for tool_cmd, model_name in cli_tools:
            if shutil.which(tool_cmd):
                available.append(("cli_proxy", model_name))

        # 4. Free fallback
        available.append(("killo", "qwen/qwen3-coder:free"))
        
        return available
"""

if "def get_available_models" not in content:
    content += new_method
    with open("app/core/model_router.py", "w") as f:
        f.write(content)
    print("Added get_available_models")
else:
    print("get_available_models already exists")
