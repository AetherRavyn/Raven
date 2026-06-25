---
name: Project Setup
module_id: skill.bundled.project_setup
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "set up.*project"
    confidence: 0.90
  - pattern: "new project"
    confidence: 0.85
  - pattern: "scaffold"
    confidence: 0.80
  - pattern: "initialize.*repo"
    confidence: 0.75
capabilities: [project-scaffolding, git-init, dependency-setup, readme-creation]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Project Setup

Scaffold a new project with Git, dependency management, and standard project structure.

## When to Use
This skill activates when the user wants to set up a new software project. It handles the boilerplate so the user can start coding immediately.

## Procedure

### Step 1: Choose Stack
1. Ask the user for: project name, language/framework, package manager
2. If not specified, infer from context or default to Python + uv

### Step 2: Create Directory Structure
Create standard project layout:
```
project-name/
├── src/                    # Source code
│   └── project_name/
│       └── __init__.py
├── tests/                  # Test files
│   └── __init__.py
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── .gitignore
├── README.md
└── [config files]          # pyproject.toml, package.json, etc.
```

### Step 3: Initialize Version Control
1. Run `git init` in the project directory
2. Create a `.gitignore` appropriate for the stack
3. Make initial commit with message `chore: initial scaffold`

### Step 4: Configure Dependencies
1. Create language-appropriate config file (pyproject.toml, package.json, Cargo.toml)
2. Add common dev dependencies (linter, formatter, test runner)
3. Run install command

### Step 5: Create README
Write a minimal README.md with:
```
# Project Name

Brief description of what this project does.

## Prerequisites

- Python 3.12+ / Node 20+ / etc
- Package manager (uv, pip, npm, etc)

## Setup

```bash
git clone <url>
cd project-name
[install command]
```

## Usage

Brief example of how to use the project.

## License

MIT
```

## Example

**Input:** `set up a Python CLI project called "logwatcher"`

**Output:**
```
✅ Created logwatcher/
✅ Created src/logwatcher/__init__.py
✅ Created tests/
✅ Initialized git repository
✅ Wrote .gitignore (Python)
✅ Created pyproject.toml with typer + rich deps
✅ Installed dependencies via uv
✅ Wrote README.md
✅ Initial commit: chore: initial scaffold

Ready to code! Next steps:
  cd logwatcher
  Add your CLI entry point in src/logwatcher/main.py
```

## Lessons Learned
- Python projects should use `src/` layout to avoid import confusion
- Always add a `.gitignore` — forgetting it commits venv/node_modules
- uv is significantly faster than pip for dependency resolution
- First commit should be just the scaffold (no generated content)
