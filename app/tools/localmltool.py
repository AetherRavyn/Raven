"""Local ML Tool — Run local models via llama.cpp, interact with HuggingFace Hub.

Provides agents with access to on-device ML inference and model management.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class LocalMLTool(BaseTool):
    """Run local ML models: llama.cpp inference, HuggingFace Hub, vLLM serve."""

    group = "development"

    def get_name(self) -> str:
        return "local_ml"

    def get_description(self) -> str:
        return (
            "Run local machine learning models: "
            "llama.cpp inference, HuggingFace Hub operations, "
            "vLLM server management. Use 'chat' for interactive "
            "LLM prompts via llama.cpp, 'hf_download' to pull "
            "models from HuggingFace, 'hf_search' to find models, "
            "or 'vllm' to manage vLLM server."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "Operation: chat, hf_download, hf_search, vllm_status, list_models"
                    ),
                    required=True,
                    enum=[
                        "chat",
                        "hf_download",
                        "hf_search",
                        "vllm_status",
                        "list_models",
                    ],
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Prompt text (required for chat)",
                    required=False,
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    description="Model path or HuggingFace repo ID",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (required for hf_search)",
                    required=False,
                ),
                ToolParameter(
                    name="max_tokens",
                    type="integer",
                    description="Max tokens for generation (default 512)",
                    required=False,
                ),
                ToolParameter(
                    name="temperature",
                    type="number",
                    description="Temperature for generation (default 0.7)",
                    required=False,
                ),
                ToolParameter(
                    name="top_k",
                    type="integer",
                    description="Top-k sampling (default 40)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "")

        if action == "chat":
            return await self._chat(kwargs)
        elif action == "hf_download":
            return await self._hf_download(kwargs)
        elif action == "hf_search":
            return await self._hf_search(kwargs)
        elif action == "vllm_status":
            return await self._vllm_status()
        elif action == "list_models":
            return await self._list_models()
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    async def _chat(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        prompt = kwargs.get("prompt", "").strip()
        if not prompt:
            return {"success": False, "error": "prompt is required for chat"}

        model = kwargs.get("model", "").strip()
        if not model:
            return {"success": False, "error": "model path is required for chat"}

        max_tokens = int(kwargs.get("max_tokens", 512))
        temperature = float(kwargs.get("temperature", 0.7))
        top_k = int(kwargs.get("top_k", 40))

        model_path = Path(model)
        if not model_path.exists():
            return {"success": False, "error": f"Model not found: {model}"}

        # Check for llama.cpp CLI
        import shutil

        llama_bin = shutil.which("llama-cli") or shutil.which("llama.cpp") or shutil.which("main")
        if not llama_bin:
            return {
                "success": False,
                "error": (
                    "llama.cpp not found in PATH. "
                    "Install from https://github.com/ggerganov/llama.cpp "
                    "or set up a vLLM server instead."
                ),
            }

        try:
            result = subprocess.run(
                [
                    llama_bin,
                    "-m",
                    str(model_path),
                    "-p",
                    prompt,
                    "-n",
                    str(max_tokens),
                    "--temp",
                    str(temperature),
                    "--top-k",
                    str(top_k),
                    "--no-display-prompt",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout.strip()
            if result.stderr:
                output += f"\n{result.stderr.strip()}"
            return {
                "success": result.returncode == 0,
                "output": output[:10000],
                "return_code": result.returncode,
                "model": str(model_path),
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Inference timed out after 120s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _hf_download(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        repo_id = kwargs.get("model", "").strip()
        if not repo_id:
            return {"success": False, "error": "model (repo ID) is required for hf_download"}

        try:
            from huggingface_hub import hf_hub_download, snapshot_download, list_repo_files
        except ImportError:
            return {
                "success": False,
                "error": "huggingface_hub not installed. Run: pip install huggingface_hub",
            }

        import os

        hf_token = os.getenv("HUGGINGFACE_TOKEN", os.getenv("HF_TOKEN"))
        cache_dir = os.getenv("HF_CACHE_DIR", str(Path.home() / ".cache" / "huggingface" / "hub"))

        try:
            files = list_repo_files(repo_id, token=hf_token)
            gguf_files = [f for f in files if f.endswith(".gguf")]
            if gguf_files:
                target = gguf_files[0]
                local_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=target,
                    token=hf_token,
                    cache_dir=cache_dir,
                )
                return {
                    "success": True,
                    "file": target,
                    "local_path": str(local_path),
                    "model_type": "gguf",
                    "available_files": len(gguf_files),
                }

            local_path = snapshot_download(
                repo_id=repo_id,
                token=hf_token,
                cache_dir=cache_dir,
                ignore_patterns=["*.safetensors", "*.bin"],
            )
            return {
                "success": True,
                "local_path": str(local_path),
                "model_type": "directory",
                "total_files": len(files),
            }
        except Exception as e:
            return {"success": False, "error": f"HuggingFace download failed: {e}"}

    async def _hf_search(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        query = kwargs.get("query", "").strip()
        if not query:
            return {"success": False, "error": "query is required for hf_search"}

        try:
            from huggingface_hub import HfApi
        except ImportError:
            return {
                "success": False,
                "error": "huggingface_hub not installed. Run: pip install huggingface_hub",
            }

        try:
            api = HfApi()
            models = api.list_models(search=query, sort="downloads", direction=-1, limit=20)
            results = [
                {
                    "model_id": m.modelId,
                    "pipeline_tag": m.pipeline_tag or "unknown",
                    "downloads": getattr(m, "downloads", 0),
                    "likes": getattr(m, "likes", 0),
                }
                for m in models
            ]
            return {
                "success": True,
                "query": query,
                "results": results,
                "total": len(results),
            }
        except Exception as e:
            return {"success": False, "error": f"Search failed: {e}"}

    async def _vllm_status(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "vllm.entrypoints"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                pids = result.stdout.strip().split()
                return {
                    "success": True,
                    "running": True,
                    "pids": pids,
                    "process_count": len(pids),
                }
            return {"success": True, "running": False, "pids": [], "process_count": 0}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _list_models(self) -> dict[str, Any]:
        model_dirs = [
            Path.cwd() / "models",
            Path.home() / ".cache" / "llama.cpp",
            Path.home() / ".cache" / "huggingface" / "hub",
        ]
        found: list[dict[str, Any]] = []
        for d in model_dirs:
            if d.exists():
                for f in d.rglob("*.gguf"):
                    found.append(
                        {
                            "path": str(f),
                            "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                            "source": str(d),
                        }
                    )
                for f in d.iterdir():
                    if f.is_dir() and not f.name.startswith("."):
                        found.append(
                            {
                                "path": str(f),
                                "size_mb": (
                                    round(
                                        sum(p.stat().st_size for p in f.rglob("*") if p.is_file())
                                        / (1024 * 1024),
                                        1,
                                    )
                                    if any(p.is_file() for p in f.rglob("*"))
                                    else 0
                                ),
                                "type": "directory",
                            }
                        )
        return {
            "success": True,
            "models": sorted(found, key=lambda x: x.get("size_mb", 0), reverse=True)[:50],
            "total_found": len(found),
            "search_paths": [str(d) for d in model_dirs],
        }
