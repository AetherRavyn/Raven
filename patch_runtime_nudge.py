import re

with open("app/core/runtime.py", "r") as f:
    content = f.read()

old_nudge_block = """            try:
                if hasattr(self.provider, "chat_completion_resilient"):
                    res = await self.provider.chat_completion_resilient(
                        messages=messages,
                        preferred_models=[self.model_name],
                        free_only_guard=True,
                    )
                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages
                    )
                if res.get("success"):
                    raw_msg = (
                        res.get("raw", {}).get("choices", [{}])[0].get("message", {})
                    )
                    content = raw_msg.get("content") or "I have completed the task."
                else:
                    content = "I wasn't able to fully answer — please try rephrasing your question."
            except Exception:
                content = "I wasn't able to fully answer — please try rephrasing your question." """

new_nudge_block = """            try:
                if hasattr(self.provider, "chat_completion_resilient"):
                    res = await self.provider.chat_completion_resilient(
                        messages=messages,
                        preferred_models=[self.model_name],
                        free_only_guard=True,
                    )
                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages
                    )
                
                if not res.get("success"):
                    from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                    from app.provider.factory import create_provider  # noqa: PLC0415
                    
                    fallbacks = AutoModelRouter.get_available_models("agent")
                    for f_prov_name, f_model_name in fallbacks:
                        try:
                            f_prov = create_provider(f_prov_name)
                            f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
                            if f_res.get("success"):
                                res = f_res
                                break
                        except Exception:
                            continue

                if res.get("success"):
                    raw_msg = (
                        res.get("raw", {}).get("choices", [{}])[0].get("message", {})
                    )
                    content = raw_msg.get("content") or "I have completed the task."
                else:
                    content = "I wasn't able to fully answer — please try rephrasing your question."
            except Exception:
                content = "I wasn't able to fully answer — please try rephrasing your question." """

if old_nudge_block in content:
    content = content.replace(old_nudge_block, new_nudge_block)
    with open("app/core/runtime.py", "w") as f:
        f.write(content)
    print("Replaced nudge fallback block")
else:
    print("Could not find old nudge fallback block.")
