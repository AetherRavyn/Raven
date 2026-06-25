"""RAVEN nightly eval prompt set.

A curated set of 30 prompts that exercise the planner, cost router,
verifier, replanner, and the various side-effect boundaries.  Each
prompt is a small record with:

  * ``id``           — stable identifier
  * ``prompt``       — the user-facing input
  * ``expect``       — the expected output type:
                        "exact" | "substring" | "regex" | "json"
  * ``needle``       — the substring / regex / expected value
  * ``budget_tok``   — max output tokens the planner may spend
  * ``tier``         — preferred cost tier for the routing decision
                        ("nano" | "small" | "medium" | "large" | "any")
  * ``category``     — for grouping in the eval report
                        ("plan" | "tool" | "summary" | "extract" | "verify")

The set is small and deterministic so the nightly eval finishes in
well under a minute.  Each prompt is also a useful unit test — see
``tests/test_phase8_eval.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ExpectKind(str, Enum):
    EXACT = "exact"
    SUBSTRING = "substring"
    REGEX = "regex"
    JSON = "json"


class Tier(str, Enum):
    NANO = "nano"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    ANY = "any"


@dataclass(slots=True)
class EvalPrompt:
    id: str
    prompt: str
    expect: ExpectKind
    needle: str
    budget_tok: int = 200
    tier: Tier = Tier.SMALL
    category: str = "general"
    # For JSON expectations, an optional shape hint (list of keys).
    json_keys: list[str] = field(default_factory=list)
    # Optional: the prompt expects a specific tool to be called.
    tool_required: str = ""
    # Optional: a free-form note shown in the report.
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "expect": self.expect.value,
            "needle": self.needle,
            "budget_tok": self.budget_tok,
            "tier": self.tier.value,
            "category": self.category,
            "json_keys": list(self.json_keys),
            "tool_required": self.tool_required,
            "note": self.note,
        }


# The 30-prompt set.  Five per category, all deterministic.
# The "expected answer" is what the eval grades against — a small
# stub function returns the right answer so the regression gate can
# exercise the routing / budget / verifier logic without an LLM.
PROMPTS: list[EvalPrompt] = [
    # ── plan (5) ────────────────────────────────────────────────
    EvalPrompt(
        id="plan-01",
        prompt="Research the topic of vertical farming and summarize findings.",
        expect=ExpectKind.SUBSTRING,
        needle="vertical farming",
        budget_tok=300,
        tier=Tier.MEDIUM,
        category="plan",
        note="Multi-step plan: search + summarize.",
    ),
    EvalPrompt(
        id="plan-02",
        prompt="Send an email to alice@example.com with the weekly report.",
        expect=ExpectKind.SUBSTRING,
        needle="send_email",
        budget_tok=150,
        tier=Tier.SMALL,
        category="plan",
        tool_required="send_email",
    ),
    EvalPrompt(
        id="plan-03",
        prompt="Check the weather in Tokyo and write a short briefing.",
        expect=ExpectKind.SUBSTRING,
        needle="tokyo",
        budget_tok=200,
        tier=Tier.SMALL,
        category="plan",
        tool_required="weather",
    ),
    EvalPrompt(
        id="plan-04",
        prompt="Search for the latest RAVEN release notes.",
        expect=ExpectKind.SUBSTRING,
        needle="release",
        budget_tok=200,
        tier=Tier.SMALL,
        category="plan",
        tool_required="web_search",
    ),
    EvalPrompt(
        id="plan-05",
        prompt="List my calendar events for tomorrow.",
        expect=ExpectKind.SUBSTRING,
        needle="calendar",
        budget_tok=150,
        tier=Tier.SMALL,
        category="plan",
        tool_required="calendar",
    ),
    # ── tool (5) ────────────────────────────────────────────────
    EvalPrompt(
        id="tool-01",
        prompt="What is 2 + 2?",
        expect=ExpectKind.EXACT,
        needle="4",
        budget_tok=20,
        tier=Tier.NANO,
        category="tool",
        note="Trivial math; nano tier is correct.",
    ),
    EvalPrompt(
        id="tool-02",
        prompt="Reverse the string 'hello world'.",
        expect=ExpectKind.EXACT,
        needle="dlrow olleh",
        budget_tok=30,
        tier=Tier.NANO,
        category="tool",
    ),
    EvalPrompt(
        id="tool-03",
        prompt="Count the words in 'the quick brown fox jumps over the lazy dog'.",
        expect=ExpectKind.EXACT,
        needle="9",
        budget_tok=30,
        tier=Tier.NANO,
        category="tool",
    ),
    EvalPrompt(
        id="tool-04",
        prompt="Convert 100 USD to EUR at today's rate.",
        expect=ExpectKind.REGEX,
        needle=r"^\d+(\.\d+)?\s*(eur|EUR)",
        budget_tok=50,
        tier=Tier.SMALL,
        category="tool",
    ),
    EvalPrompt(
        id="tool-05",
        prompt="What's the SHA-256 of the string 'raven'?",
        expect=ExpectKind.REGEX,
        needle=r"^[a-f0-9]{64}$",
        budget_tok=20,
        tier=Tier.NANO,
        category="tool",
    ),
    # ── summary (5) ─────────────────────────────────────────────
    EvalPrompt(
        id="sum-01",
        prompt="Summarize the previous 5 messages in 1 sentence.",
        expect=ExpectKind.SUBSTRING,
        needle="summary",
        budget_tok=100,
        tier=Tier.SMALL,
        category="summary",
    ),
    EvalPrompt(
        id="sum-02",
        prompt="Give me a TL;DR of the RAVEN architecture in 30 words.",
        expect=ExpectKind.SUBSTRING,
        needle="raven",
        budget_tok=80,
        tier=Tier.SMALL,
        category="summary",
    ),
    EvalPrompt(
        id="sum-03",
        prompt="Summarize this error: 'ConnectionRefused on port 8080'.",
        expect=ExpectKind.SUBSTRING,
        needle="8080",
        budget_tok=60,
        tier=Tier.NANO,
        category="summary",
    ),
    EvalPrompt(
        id="sum-04",
        prompt="Condense this changelog: 'feat: add replan, fix: planner bug'.",
        expect=ExpectKind.SUBSTRING,
        needle="replan",
        budget_tok=60,
        tier=Tier.NANO,
        category="summary",
    ),
    EvalPrompt(
        id="sum-05",
        prompt="One-line summary of: 'Morning briefing generated at 8 AM'.",
        expect=ExpectKind.SUBSTRING,
        needle="morning",
        budget_tok=40,
        tier=Tier.NANO,
        category="summary",
    ),
    # ── extract (5) ─────────────────────────────────────────────
    EvalPrompt(
        id="ext-01",
        prompt="Extract the email address from 'contact: bob@raven.ai'.",
        expect=ExpectKind.EXACT,
        needle="bob@raven.ai",
        budget_tok=30,
        tier=Tier.NANO,
        category="extract",
    ),
    EvalPrompt(
        id="ext-02",
        prompt="Extract all numbers from 'I have 3 cats and 2 dogs'.",
        expect=ExpectKind.REGEX,
        needle=r"^[,\s]*\d+[,\s]*\d+[,\s]*$|^\d+$",
        budget_tok=30,
        tier=Tier.NANO,
        category="extract",
    ),
    EvalPrompt(
        id="ext-03",
        prompt="Return a JSON object with keys 'name' and 'age' for Alice, 30.",
        expect=ExpectKind.JSON,
        needle="",
        budget_tok=60,
        tier=Tier.SMALL,
        category="extract",
        json_keys=["name", "age"],
    ),
    EvalPrompt(
        id="ext-04",
        prompt="Parse the date from 'Meeting on 2026-07-15 at 14:00'.",
        expect=ExpectKind.EXACT,
        needle="2026-07-15",
        budget_tok=30,
        tier=Tier.NANO,
        category="extract",
    ),
    EvalPrompt(
        id="ext-05",
        prompt="Extract the city from 'User is in San Francisco, CA'.",
        expect=ExpectKind.EXACT,
        needle="San Francisco",
        budget_tok=30,
        tier=Tier.NANO,
        category="extract",
    ),
    # ── verify (5) ──────────────────────────────────────────────
    EvalPrompt(
        id="ver-01",
        prompt="Verify: 'The capital of France is Paris'.",
        expect=ExpectKind.SUBSTRING,
        needle="true",
        budget_tok=50,
        tier=Tier.NANO,
        category="verify",
        note="Verifier should accept a true claim.",
    ),
    EvalPrompt(
        id="ver-02",
        prompt="Verify: 'The capital of France is London'.",
        expect=ExpectKind.SUBSTRING,
        needle="false",
        budget_tok=50,
        tier=Tier.SMALL,
        category="verify",
        note="Verifier must reject a false claim (LLM-as-judge path).",
    ),
    EvalPrompt(
        id="ver-03",
        prompt="Verify the JSON: '{\"a\": 1, \"b\": 2}' is well-formed.",
        expect=ExpectKind.SUBSTRING,
        needle="true",
        budget_tok=30,
        tier=Tier.NANO,
        category="verify",
    ),
    EvalPrompt(
        id="ver-04",
        prompt="Verify the URL 'https://raven.ai/health' is well-formed.",
        expect=ExpectKind.SUBSTRING,
        needle="true",
        budget_tok=30,
        tier=Tier.NANO,
        category="verify",
    ),
    EvalPrompt(
        id="ver-05",
        prompt="Verify the regex '.+' matches 'abc'.",
        expect=ExpectKind.SUBSTRING,
        needle="true",
        budget_tok=30,
        tier=Tier.NANO,
        category="verify",
    ),
    # ── general (5) ─────────────────────────────────────────────
    EvalPrompt(
        id="gen-01",
        prompt="Greet the user in a friendly way.",
        expect=ExpectKind.SUBSTRING,
        needle="hello",
        budget_tok=40,
        tier=Tier.NANO,
        category="general",
    ),
    EvalPrompt(
        id="gen-02",
        prompt="Define the word 'orchestrator'.",
        expect=ExpectKind.SUBSTRING,
        needle="orchestrator",
        budget_tok=60,
        tier=Tier.SMALL,
        category="general",
    ),
    EvalPrompt(
        id="gen-03",
        prompt="Translate 'good morning' to French.",
        expect=ExpectKind.EXACT,
        needle="bonjour",
        budget_tok=20,
        tier=Tier.NANO,
        category="general",
    ),
    EvalPrompt(
        id="gen-04",
        prompt="List three primary colors.",
        expect=ExpectKind.REGEX,
        needle=r"red.*blue.*yellow|red.*yellow.*blue|blue.*red.*yellow|blue.*yellow.*red|yellow.*red.*blue|yellow.*blue.*red",
        budget_tok=40,
        tier=Tier.NANO,
        category="general",
    ),
    EvalPrompt(
        id="gen-05",
        prompt="Return the current ISO-8601 date.",
        expect=ExpectKind.REGEX,
        needle=r"^\d{4}-\d{2}-\d{2}$",
        budget_tok=20,
        tier=Tier.NANO,
        category="general",
    ),
]


def all_prompts() -> list[EvalPrompt]:
    return list(PROMPTS)


def by_category(cat: str) -> list[EvalPrompt]:
    return [p for p in PROMPTS if p.category == cat]


def get_prompt(prompt_id: str) -> Optional[EvalPrompt]:
    for p in PROMPTS:
        if p.id == prompt_id:
            return p
    return None


__all__ = [
    "ExpectKind",
    "Tier",
    "EvalPrompt",
    "PROMPTS",
    "all_prompts",
    "by_category",
    "get_prompt",
]