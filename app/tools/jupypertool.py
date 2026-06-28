"""Jupyter Notebook Tool — Read, create, edit, and execute .ipynb files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.tools import deps_error, tool_error

logger = logging.getLogger(__name__)

# Lazy imports — module loads without nbformat; error returned at call time if missing
_HAS_DEPS: bool = False
try:
    import nbformat as _nbformat
    from jupyter_client.manager import KernelManager as _KernelManager
    from nbformat.v4 import new_code_cell as _new_code_cell
    from nbformat.v4 import new_markdown_cell as _new_markdown_cell
    from nbformat.v4 import new_notebook as _new_notebook

    _HAS_DEPS = True
except ImportError:
    pass


class JupyterTool(BaseTool):
    """Read, create, edit, and execute Jupyter notebook (.ipynb) files."""

    group = "development"

    def get_name(self) -> str:
        return "jupyter"

    def get_description(self) -> str:
        return (
            "Manages Jupyter notebook (.ipynb) files. "
            "Actions: 'read' (parse and return cells), "
            "'create' (create a new notebook with one cell), "
            "'run' (execute all cells and capture outputs), "
            "'edit_cell' (replace a cell's source by index), "
            "'add_cell' (append a cell to an existing notebook)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: read, create, run, edit_cell, add_cell",
                    required=True,
                    enum=["read", "create", "run", "edit_cell", "add_cell"],
                ),
                ToolParameter(
                    name="filepath",
                    type="string",
                    description="Path to the .ipynb file",
                    required=True,
                ),
                ToolParameter(
                    name="cell_type",
                    type="string",
                    description="Type of cell: 'code' or 'markdown' (default 'code')",
                    required=False,
                ),
                ToolParameter(
                    name="source",
                    type="string",
                    description="Cell source content (for create, edit_cell, add_cell)",
                    required=False,
                ),
                ToolParameter(
                    name="cell_index",
                    type="integer",
                    description="Cell index (for edit_cell)",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Execution timeout in seconds (default 60, for run)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        global _HAS_DEPS
        if not _HAS_DEPS:
            return deps_error("nbformat/jupyter-client", pip_install="nbformat jupyter-client")

        action = kwargs.get("action")
        filepath = kwargs.get("filepath", "").strip()
        cell_type = kwargs.get("cell_type", "code")
        source = kwargs.get("source", "")
        cell_index = kwargs.get("cell_index")
        timeout = int(kwargs.get("timeout", 60))

        if not filepath:
            return tool_error("filepath is required")

        try:
            if action == "read":
                return await self._read_notebook(filepath)
            elif action == "create":
                return await self._create_notebook(filepath, source, cell_type)
            elif action == "run":
                return await self._run_notebook(filepath, timeout)
            elif action == "edit_cell":
                return await self._edit_cell(filepath, cell_index, source, cell_type)
            elif action == "add_cell":
                return await self._add_cell(filepath, source, cell_type)
            else:
                return tool_error(f"Unknown action: {action}")
        except Exception as e:
            logger.exception("JupyterTool failed")
            return tool_error(str(e))

    async def _read_notebook(self, filepath: str) -> dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        def _read() -> dict[str, Any]:
            with open(path) as f:
                nb = _nbformat.read(f, as_version=4)
            cells = []
            for idx, cell in enumerate(nb.cells):
                cells.append(
                    {
                        "cell_index": idx,
                        "cell_type": cell.cell_type,
                        "source": cell.source,
                        "outputs": (
                            [
                                {k: v for k, v in output.items() if k != "metadata"}
                                for output in cell.outputs
                            ]
                            if hasattr(cell, "outputs")
                            else []
                        ),
                    }
                )
            return {
                "success": True,
                "nbformat": nb.nbformat,
                "nbformat_minor": nb.nbformat_minor,
                "cells": cells,
                "cell_count": len(cells),
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read)

    async def _create_notebook(self, filepath: str, source: str, cell_type: str) -> dict[str, Any]:
        def _create() -> dict[str, Any]:
            nb = _new_notebook()
            if cell_type == "markdown":
                cell = _new_markdown_cell(source=source)
            else:
                cell = _new_code_cell(source=source)
            nb.cells.append(cell)
            with open(filepath, "w") as f:
                _nbformat.write(nb, f)
            return {"success": True, "filepath": filepath, "cell_count": 1}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _create)

    async def _run_notebook(self, filepath: str, timeout: int) -> dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        def _run() -> dict[str, Any]:
            with open(path) as f:
                nb = _nbformat.read(f, as_version=4)

            km = _KernelManager(kernel_name="python3")
            km.start_kernel()
            kc = km.client()
            kc.wait_for_ready()

            executed_cells: list[dict[str, Any]] = []
            try:
                for cell_idx, cell in enumerate(nb.cells):
                    cell_info: dict[str, Any] = {
                        "cell_index": cell_idx,
                        "cell_type": cell.cell_type,
                        "source": cell.source,
                        "outputs": [],
                        "execution_error": None,
                    }
                    if cell.cell_type == "code":
                        try:
                            msg_id = kc.execute(cell.source)
                            while True:
                                msg = kc.get_iopub_msg(timeout=timeout)
                                if msg.get("parent_header", {}).get("msg_id") != msg_id:
                                    continue
                                content = msg["content"]
                                msg_type = msg["msg_type"]
                                if msg_type == "stream":
                                    cell_info["outputs"].append(
                                        {
                                            "output_type": "stream",
                                            "name": content.get("name", "stdout"),
                                            "text": content.get("text", ""),
                                        }
                                    )
                                elif msg_type == "execute_result":
                                    data = content.get("data", {})
                                    cell_info["outputs"].append(
                                        {
                                            "output_type": "execute_result",
                                            "text": data.get("text/plain", ""),
                                        }
                                    )
                                elif msg_type == "error":
                                    cell_info["outputs"].append(
                                        {
                                            "output_type": "error",
                                            "ename": content.get("ename", ""),
                                            "evalue": content.get("evalue", ""),
                                            "traceback": content.get("traceback", []),
                                        }
                                    )
                                elif (
                                    msg_type == "status"
                                    and content.get("execution_state") == "idle"
                                ):
                                    break
                        except Exception as exc:
                            cell_info["execution_error"] = str(exc)
                    executed_cells.append(cell_info)
            finally:
                km.shutdown_kernel()

            return {"success": True, "executed_cells": executed_cells}

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _run)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _edit_cell(
        self, filepath: str, cell_index: int | None, source: str, cell_type: str
    ) -> dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}
        if cell_index is None:
            return {"success": False, "error": "cell_index is required for edit_cell"}

        def _edit() -> dict[str, Any]:
            with open(path) as f:
                nb = _nbformat.read(f, as_version=4)
            if cell_index < 0 or cell_index >= len(nb.cells):
                return {
                    "success": False,
                    "error": (f"cell_index {cell_index} out of range (0-{len(nb.cells) - 1})"),
                }
            # Replace the cell with a new one of the requested type
            if cell_type == "markdown":
                nb.cells[cell_index] = _new_markdown_cell(source=source)
            else:
                nb.cells[cell_index] = _new_code_cell(source=source)
            with open(path, "w") as f:
                _nbformat.write(nb, f)
            return {
                "success": True,
                "filepath": filepath,
                "cell_index": cell_index,
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _edit)

    async def _add_cell(self, filepath: str, source: str, cell_type: str) -> dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        def _add() -> dict[str, Any]:
            with open(path) as f:
                nb = _nbformat.read(f, as_version=4)
            if cell_type == "markdown":
                new_cell = _new_markdown_cell(source=source)
            else:
                new_cell = _new_code_cell(source=source)
            nb.cells.append(new_cell)
            new_index = len(nb.cells) - 1
            with open(path, "w") as f:
                _nbformat.write(nb, f)
            return {
                "success": True,
                "filepath": filepath,
                "cell_index": new_index,
                "cell_count": len(nb.cells),
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _add)
