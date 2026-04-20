with open("app/core/runtime.py", "r") as f:
    content = f.read()

target = """                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages
                    )"""

replacement = """                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages
                    )

                if not res.get("success"):
                    from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                    from app.provider.factory import create_provider  # noqa: PLC0415
                    
                    for f_prov_name, f_model_name in AutoModelRouter.get_available_models("agent"):
                        try:
                            f_prov = create_provider(f_prov_name)
                            f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
                            if f_res.get("success"):
                                res = f_res
                                break
                        except Exception:
                            continue"""

if target in content:
    content = content.replace(target, replacement)
    with open("app/core/runtime.py", "w") as f:
        f.write(content)
    print("Replaced")
else:
    print("Target not found")
