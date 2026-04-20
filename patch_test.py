import re

with open("test_orchestrator_filetool.py", "r") as f:
    content = f.read()

target_method = """    async def test_unhandled_prompt_killo_failure_falls_back_to_minichat(self) -> None:"""

replacement = """    @patch("app.core.model_router.AutoModelRouter.get_available_models", return_value=[])
    async def test_unhandled_prompt_killo_failure_falls_back_to_minichat(self, mock_get_models) -> None:"""

if target_method in content:
    content = content.replace(target_method, replacement)
    
    # ensure mock is imported
    if "from unittest.mock import patch" not in content:
        content = "from unittest.mock import patch\n" + content
        
    with open("test_orchestrator_filetool.py", "w") as f:
        f.write(content)
    print("Patched test_orchestrator_filetool.py")
else:
    print("Target test not found.")
