# Contributing to Raven

> **Last updated**: 2026-06-30

First off, thank you for considering contributing to Raven. This is a community-driven project, and every contribution — whether code, documentation, bug reports, or feature ideas — is valued.

---

## Code of Conduct

This project adheres to the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct.html) code of conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

**Key principles:**
- Be respectful and inclusive
- Assume good faith
- Focus on what is best for the community
- Show empathy towards other community members

---

## Setting Up a Development Environment

### Prerequisites

- Python 3.12+ (3.12 or 3.13 recommended)
- uv >=0.4.0
- Git >=2.30
- System dependencies (see `docs/installation.md`)

### Clone and Install

```bash
git clone https://github.com/AetherRavyn/Raven.git
cd Raven
uv venv
source .venv/bin/activate
uv sync
```

This installs all dependencies including dev extras (ruff, pyright, pytest).

### Install Pre-Commit Hooks

```bash
uv pip install pre-commit
pre-commit install
```

Pre-commit runs `ruff` and `pyright` on every commit. Configuration is in:
- `.pre-commit-config.yaml` — hook definitions
- `pyproject.toml` — tool settings (ruff, pytest)

### Verify Setup

```bash
python -c "import app; print('OK')"
raven doctor
```

---

## Code Style

### Formatter

We use **ruff format** with these settings (from `pyproject.toml`):

| Setting | Value |
|---------|-------|
| Line length | 100 |
| Target version | py312 |
| Quote style | double |
| Indent style | space |
| Line ending | lf |

```bash
# Format all files
ruff format .

# Check without fixing
ruff format --check .
```

### Linter

We use **ruff check** with rules `E`, `F`, `W` (pycodestyle + pyflakes):

```bash
# Lint all files
ruff check .

# Lint with auto-fix
ruff check --fix .
```

There are per-file exceptions for legacy modules (`app/core/runtime.py`, `app/core/security.py`). New code should have zero lint violations.

### Type Checker

We use **pyright** in strict mode:

```bash
pyright
```

All new code must pass pyright without errors. Use type hints throughout — no `Any` unless unavoidable. Configuration in `pyrightconfig.json`.

### Modern Python Conventions

- **Always use type hints** — every function signature must have typed parameters and return values
- **Use dataclasses** for data containers
- **Async/await** for all I/O operations (asyncio, never threading for I/O)
- **Pathlib** over `os.path`
- **f-strings** over `%` or `.format()`
- **`from __future__ import annotations`** at the top of every module
- **`TYPE_CHECKING`** guard for type-only imports to avoid circular dependencies

### Logging

```python
import logging
logger = logging.getLogger(__name__)
logger.info("message")
```

Never use `print()` for logging. Use the `structlog` or standard library `logging` module.

### Imports

Ordered as: **standard library → third-party → local**. Ruff handles this automatically.

```python
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

from app.core.models import IncomingRequest
```

---

## Testing Expectations

### Test Framework

We use **pytest** with `pytest-asyncio`:

| Package | Purpose |
|---------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| pytest-cov | Coverage reporting |
| pytest-timeout | Test timeout enforcement |

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_orchestrator.py

# Run tests matching a pattern
pytest -k "memory"

# Run with verbose output
pytest -v
```

### Test Configuration

Defined in `pyproject.toml`:

- Test paths: `tests/` (root-level `test_*.py` files are ad-hoc probes, not part of the suite)
- `asyncio_mode = "auto"` — async tests work without explicit decorators
- Strict markers enforced
- Short traceback format

### Writing Tests

**Naming convention:**
- File: `test_<module_name>.py`
- Function: `test_<function_name>`
- Class: `Test<ClassName>`

**Async test pattern:**

```python
import pytest
from app.core.my_module import MyClass

@pytest.mark.asyncio
async def test_my_function():
    obj = MyClass()
    result = await obj.my_async_method()
    assert result == expected_value
```

**Test structure:**

```python
# Arrange
fixture = await setup_fixture()
expected = {"key": "value"}

# Act
result = await function_under_test(fixture)

# Assert
assert result == expected
```

### Mocking External Services

Use `unittest.mock` or `pytest-mock` for external API calls. Never make real network requests in tests.

```python
async def test_web_search(mocker):
    mock_client = mocker.AsyncMock()
    mock_client.get.return_value.status_code = 200
    result = await web_search_function(client=mock_client)
    assert "results" in result
```

### Coverage

Aim for >=80% coverage on new code. Run `pytest --cov=app --cov-report=term-missing` to see uncovered lines.

---

## Pull Request Process

### Before You Start

1. Search existing issues and PRs to avoid duplication
2. Open a discussion or issue for significant changes first
3. For bug fixes, include steps to reproduce

### Development Workflow

```bash
# 1. Create a branch
git checkout -b feat/my-feature

# 2. Make changes
# ... code ...

# 3. Run checks
ruff check .
ruff format --check .
pyright
pytest

# 4. Commit
git add <files>
git commit -m "feat(scope): concise description"

# 5. Push
git push -u origin feat/my-feature
```

### Commit Convention

Follow the [Conventional Commits](https://www.conventionalcommits.org/) spec:

```
<type>(<scope>): <description>
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

**Scopes:** `core`, `tools`, `agents`, `voice`, `channels`, `skills`, `cli`, `gateway`

**Examples:**
```
feat(tools): add web scraping tool
fix(voice): resolve race condition in STT pipeline
docs(cli): update command examples
chore(deps): upgrade ruff to 0.9.0
```

### PR Checklist

Before submitting, ensure:

- [ ] Code compiles and runs (`raven doctor` passes)
- [ ] All lint checks pass (`ruff check .`)
- [ ] Formatting is correct (`ruff format --check .`)
- [ ] Type checking passes (`pyright`)
- [ ] Tests pass (`pytest`)
- [ ] New code has tests (>=80% coverage)
- [ ] Documentation updated if behavior changed
- [ ] No secrets or credentials committed
- [ ] Commit messages follow the convention

### Review Process

1. At least one maintainer review required
2. All CI checks must pass
3. Address review comments with additional commits
4. Squash commits before merge if requested

---

## Documentation Standards

### Doc Location

| Type | Location |
|------|----------|
| User docs | `docs/*.md` |
| API reference | `docs/reference-api.md` |
| CLI reference | `docs/reference-cli.md` |
| Architecture | `docs/developer-*.md` |
| Feature guides | `docs/features-*.md` |
| Integration guides | `docs/integrations.md` |
| Installation | `docs/installation.md` |
| Deployment | `docs/deployment.md` |
| Tutorials | `docs/guides-*.md` |
| Inline code docs | In `__init__.py` or docstrings |

### Doc Quality

Documentation at the "Hermes" level should be:

- **Complete** — covers all options, examples, error conditions
- **Correct** — verified against actual behavior
- **Current** — reflects the latest version
- **Clear** — written for the target audience
- **Concise** — no filler, every sentence adds value

### mkdocs Integration

The doc site is built with mkdocs (config in `mkdocs.yml`). When adding a new doc:

1. Create the `.md` file in `docs/`
2. Add it to `mkdocs.yml` under the appropriate nav section
3. Add a link from the relevant index or overview page

---

## Project Structure

```
app/                — Main application package
├── agents/         — Agent definitions (15 agents)
├── api/            — FastAPI server + endpoints
├── cli/            — CLI commands (main, dashboard, doctor, etc.)
├── core/           — Core cognitive engine, memory, learning, tools
├── dashboard/      — Streamlit admin dashboard
├── gateway/        — Platform gateway daemon
├── mcp/            — MCP server management
├── providers/      — LLM provider implementations
├── routines/       — Background routine definitions
├── runtime/        — Agent runtime, outbox
├── settings/       — Configuration (Config class)
├── tools/          — 98+ tool implementations
├── voice/          — STT/TTS pipeline
├── web/            — Web dashboard (Hermes UI)
├── discord/        — Discord connector
├── telegram/       — Telegram connector
├── whatsapp/       — WhatsApp connector
├── signal/         — Signal connector
├── slack/          — Slack connector
├── matrix/         — Matrix connector
├── irc/            — IRC connector
├── imessage/       — iMessage connector
├── wechat/         — WeChat connector
├── line/           — LINE connector

web/                — Static frontend files
docs/               — Documentation (mkdocs)
tests/              — Test suite
```

---

## Getting Help

- Open an issue on GitHub
- Ask in the project's Discord/Telegram channels
- Review existing docs in `docs/`
- Run `raven doctor` for system diagnostics

---

## Recognition

Contributors are listed in the release notes and the project README. Significant contributions may result in maintainer invitations.
