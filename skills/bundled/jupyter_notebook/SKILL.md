---
name: Jupyter Notebook
module_id: skill.bundled.jupyter_notebook
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "run.*notebook|execute.*ipynb|jupyter"
    confidence: 0.90
  - pattern: "read.*notebook|open.*ipynb"
    confidence: 0.85
  - pattern: "create.*notebook|new.*ipynb"
    confidence: 0.80
capabilities: [jupyter, notebook, python, data-analysis]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Jupyter Notebook

Read, create, edit, and execute Jupyter notebooks (.ipynb) using the jupyter tool.

## When to Use
Use when the user shares a .ipynb file, asks you to run notebook code, create a new notebook, or modify cells in an existing notebook.

## Procedure

### Read a Notebook
1. Call `jupyter` with `action=read` and `filepath=<path>`
2. The response contains all cells with their types, sources, and outputs
3. Present a summary: number of code/markdown cells, any errors in outputs

### Create a Notebook
1. Call `jupyter` with `action=create`, `filepath=<path>`, and `source=<initial cell content>`
2. Optionally set `cell_type` to "code" or "markdown"

### Execute a Notebook
1. Call `jupyter` with `action=run`, `filepath=<path>`, and `timeout=<seconds>`
2. All cells execute in order via a fresh kernel
3. Review outputs for errors and present them to the user

### Edit Cells
- Use `edit_cell` to replace a cell's source by index
- Use `add_cell` to append a new cell at the end

## Example
```
User: Run my notebook and show me the results
Agent: I'll execute notebook.ipynb now.
       [jupyter: action=run, filepath=notebook.ipynb, timeout=120]
       The notebook completed. Cell 3 has a matplotlib chart output.
       Cell 5 has an error: "ModuleNotFoundError: No module named pandas"
```

## Dependencies
- Python: nbformat, jupyter-client
- System: Jupyter kernel (ipykernel)
