import re

with open("app/core/runtime.py", "r") as f:
    content = f.read()

# We need to replace the `Try Ollama as resilient local fallback before giving up` block with a generic multi-model fallback.
old_block = """                if not res.get("success"):
                    # Try Ollama as resilient local fallback before giving up
                    try:
                        from app.providers.ollama.client import OllamaProvider  # noqa: PLC0415
                        from app.settings.config import Config  # noqa: PLC0415

                        if Config.OLLAMA_BASE_URL:
                            _ollama = OllamaProvider(
                                Config.OLLAMA_BASE_URL, Config.OLLAMA_MODEL
                            )
                            if await _ollama.health():
                                logger.warning(
                                    "AGENT_RUNTIME  ollama_fallback  session=%s",
                                    session_id,
                                )
                                res = await _ollama.chat_completion(
                                    messages=messages, **kwargs
                                )
                    except Exception as _ollama_exc:
                        logger.debug("Ollama fallback failed: %s", _ollama_exc)"""

new_block = """                if not res.get("success"):
                    # Try resilient fallback across all configured providers [CLI, API, Local, etc]
                    logger.warning("AGENT_RUNTIME  primary_provider_failed  session=%s provider=%s", session_id, provider_name)
                    try:
                        from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                        from app.provider.factory import create_provider  # noqa: PLC0415
                        
                        fallbacks = AutoModelRouter.get_available_models("agent")
                        for f_prov_name, f_model_name in fallbacks:
                            if f_prov_name == provider_name and f_model_name == self.model_name:
                                continue # Skip the one that just failed
                            
                            try:
                                logger.info("AGENT_RUNTIME  trying_fallback  session=%s  fallback_provider=%s", session_id, f_prov_name)
                                f_prov = create_provider(f_prov_name)
                                f_res = await f_prov.chat_completion(model=f_model_name, messages=messages, **kwargs)
                                if f_res.get("success"):
                                    logger.info("AGENT_RUNTIME  fallback_success  session=%s  fallback_provider=%s", session_id, f_prov_name)
                                    res = f_res
                                    # Update current provider for remainder of session/turn
                                    self.provider = f_prov
                                    self.model_name = f_model_name
                                    break
                            except Exception as _f_exc:
                                logger.debug("Fallback %s failed: %s", f_prov_name, _f_exc)
                    except Exception as _routing_exc:
                        logger.debug("Fallback routing failed: %s", _routing_exc)"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open("app/core/runtime.py", "w") as f:
        f.write(content)
    print("Replaced fallback block")
else:
    print("Could not find old fallback block. Here's a snippet near it:")
    print(content[content.find("if not res.get(\"success\"):"):content.find("if not res.get(\"success\"):")+1000])

