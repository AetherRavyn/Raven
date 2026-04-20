import re

with open("app/core/orchestrator.py", "r") as f:
    content = f.read()

target = """        try:
            resilient_func = getattr(provider, "chat_completion_resilient", None)
            if callable(resilient_func):
                _func: Any = resilient_func
                result = await _func(
                    messages=messages,
                    preferred_models=[self._agent_runtime.model_name],
                    free_only_guard=True,
                )
            else:
                result = await provider.chat_completion(
                    model=self._agent_runtime.model_name,
                    messages=messages,
                )
        except Exception as exc:
            result = {"success": False, "error": str(exc)}"""

replacement = """        try:
            resilient_func = getattr(provider, "chat_completion_resilient", None)
            if callable(resilient_func):
                _func: Any = resilient_func
                result = await _func(
                    messages=messages,
                    preferred_models=[self._agent_runtime.model_name],
                    free_only_guard=True,
                )
            else:
                result = await provider.chat_completion(
                    model=self._agent_runtime.model_name,
                    messages=messages,
                )
        except Exception as exc:
            result = {"success": False, "error": str(exc)}

        if not result.get("success"):
            # Resilient fallback across all configured providers
            from app.core.model_router import AutoModelRouter
            from app.provider.factory import create_provider
            
            fallbacks = AutoModelRouter.get_available_models("agent")
            for f_prov_name, f_model_name in fallbacks:
                try:
                    f_prov = create_provider(f_prov_name)
                    f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
                    if f_res.get("success"):
                        result = f_res
                        provider_name = f_prov_name
                        break
                except Exception:
                    continue"""

if target in content:
    content = content.replace(target, replacement)
    with open("app/core/orchestrator.py", "w") as f:
        f.write(content)
    print("Replaced orchestrator fallback block")
else:
    print("Could not find orchestrator fallback target")
