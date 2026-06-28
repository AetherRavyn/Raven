"""Benchmark harness for Raven's learning pipeline.

Measures:
- Correction detection accuracy (precision/recall)
- Retrieval relevance (FTS5 top-k quality)
- Consolidation effectiveness
- Skill crystallization yield
"""

from __future__ import annotations

import json
import re as _re
import time
from pathlib import Path
from typing import Any

from app.core.consolidation import ConsolidationEngine
from app.core.learning_db import LearningStore
from app.core.skill_crystallizer import SkillCrystallizer


def _simulate_corrections(store: LearningStore) -> None:
    corrections = [
        (
            "fact",
            "climate",
            "The Earth's average temperature has risen 1.2°C since pre-industrial times.",
            0.9,
        ),
        ("fact", "history", "World War II ended in 1945.", 0.95),
        ("fact", "tech", "Python was created by Guido van Rossum.", 0.85),
        ("fact", "science", "Water boils at 100°C at sea level.", 0.8),
        ("fact", "math", "The square root of 144 is 12.", 0.9),
        ("preference", "coding", "User prefers spaces over tabs for indentation.", 0.7),
        ("preference", "coding", "User prefers Python type hints for all new code.", 0.75),
        ("preference", "communication", "User prefers concise bullet-point responses.", 0.65),
        (
            "pattern",
            "success",
            "Multi-tool tasks succeed more often when tools are called sequentially.",
            0.6,
        ),
        ("pattern", "success", "Web searches benefit from rephrasing the query twice.", 0.55),
        ("insight", "user", "User often asks about climate data in the context of policy.", 0.5),
        ("insight", "user", "User is a software engineer working on AI/ML projects.", 0.7),
    ]
    for type_, topic, content, confidence in corrections:
        store.add(type_=type_, topic=topic, content=content, confidence=confidence)


def _heuristic_is_correction(text: str) -> bool:
    patterns: list[str] = [
        r"\b(?:actually|correction|wrong|incorrect|mistake|error|no[,:]|that.?s not|hold on|wait)\b",
        r"\byou (?:said|told |claimed|stated|wrote).*\b(?:wrong|incorrect|not right|mistaken)\b",
        r"\bi (?:meant|think|prefer|like|use)\b",
        r"\b(?:correct|update|fix|revise)\s+(?:that|it|my|the)\b",
    ]
    lower = text.lower()
    return any(_re.search(pat, lower) for pat in patterns)


def benchmark_correction_detection() -> dict[str, Any]:
    test_cases = [
        ("correction", "Actually, the temperature has risen 1.2°C, not 0.8."),
        ("correction", "That's wrong, WW2 ended in 1945."),
        ("correction", "Correction: Python 1.0 was released in 1994."),
        ("normal", "What's the weather like today?"),
        ("normal", "Can you help me write a Python function?"),
        ("correction", "I actually prefer tabs over spaces."),
    ]
    tp = fp = tn = fn = 0
    for label, text in test_cases:
        is_correction = label == "correction"
        result = _heuristic_is_correction(text)
        if result and is_correction:
            tp += 1
        elif result and not is_correction:
            fp += 1
        elif not result and not is_correction:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "detection": {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }
    }


def benchmark_retrieval() -> dict[str, Any]:
    store = LearningStore(db_path=":memory:")
    _simulate_corrections(store)
    queries = [
        ("climate change temperature", "climate"),
        ("python programming", "tech"),
        ("world war ii", "history"),
        ("coding style preferences", "coding"),
        ("weather forecast", None),
    ]
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    for query, expected_topic in queries:
        results_list = store.search(query, limit=5)
        if not results_list:
            precision_scores.append(0.0)
            recall_scores.append(0.0)
            continue
        relevant = sum(
            1 for r in results_list if expected_topic is None or r["topic"] == expected_topic
        )
        precision_scores.append(relevant / len(results_list))
        recall_scores.append(relevant / max(len(results_list), 1))
    return {
        "retrieval": {
            "avg_precision": round(sum(precision_scores) / max(len(precision_scores), 1), 3),
            "avg_recall": round(sum(recall_scores) / max(len(recall_scores), 1), 3),
        }
    }


def benchmark_consolidation() -> dict[str, Any]:
    store = LearningStore(db_path=":memory:")
    _simulate_corrections(store)
    pre_count = store.get_stats()["total"]
    store.add(
        type_="fact",
        topic="climate",
        content="The Earth's average temperature has risen 1.2°C since pre-industrial times.",
        confidence=0.9,
    )
    engine = ConsolidationEngine(store=store)
    output = engine.consolidate_all()
    post_count = store.get_stats()["total"]
    return {
        "consolidation": {
            "pre_count": pre_count,
            "post_count": post_count,
            "dedup_removed": output.get("merges", 0),
            "contradictions_found": len(output.get("contradictions", [])),
            "archived": output.get("deletions", 0),
            "promoted_to_skills": len(output.get("promotions", [])),
        }
    }


def benchmark_skill_crystallization() -> dict[str, Any]:
    crystal = SkillCrystallizer()
    created = crystal.crystallize_all()
    return {
        "crystallization": {
            "skills_created": len(created) if isinstance(created, list) else created
        }
    }


def run_all() -> dict[str, Any]:
    print("=" * 60)
    print("  Raven Learning Pipeline — Benchmark Suite")
    print("=" * 60)
    print()
    all_results: dict[str, Any] = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    print("[1/4] Correction Detection Benchmark...")
    t0 = time.time()
    all_results.update(benchmark_correction_detection())
    print(f"      → {all_results['detection']['f1']:.1%} F1  (took {time.time() - t0:.2f}s)\n")

    print("[2/4] FTS5 Retrieval Benchmark...")
    t0 = time.time()
    all_results.update(benchmark_retrieval())
    print(
        f"      → {all_results['retrieval']['avg_precision']:.1%} avg precision  (took {time.time() - t0:.2f}s)\n"
    )

    print("[3/4] Consolidation Benchmark...")
    t0 = time.time()
    all_results.update(benchmark_consolidation())
    c = all_results["consolidation"]
    print(
        f"      → {c['dedup_removed']} deduped, {c['contradictions_found']} contradictions, {c['promoted_to_skills']} promoted  (took {time.time() - t0:.2f}s)\n"
    )

    print("[4/4] Skill Crystallization Benchmark...")
    t0 = time.time()
    all_results.update(benchmark_skill_crystallization())
    print(
        f"      → {all_results['crystallization']['skills_created']} skills created  (took {time.time() - t0:.2f}s)\n"
    )

    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Detection F1:          {all_results['detection']['f1']:.1%}")
    print(f"  Avg Retrieval Prec:    {all_results['retrieval']['avg_precision']:.1%}")
    print(
        f"  Consolidation Run:     {all_results['consolidation']['pre_count']}→{all_results['consolidation']['post_count']} items"
    )
    print(f"  Skills Created:        {all_results['crystallization']['skills_created']}")
    print("=" * 60)
    return all_results


if __name__ == "__main__":
    results = run_all()
    out_path = Path("workspace/benchmark_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {out_path}")
