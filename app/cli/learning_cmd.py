"""CLI commands for the learning system."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def cmd_learning(args):
    """Learning system operations."""
    action = args.action

    if action == "stats":
        _run_learning_stats(args)
    elif action == "search":
        _run_learning_search(args)
    elif action == "events":
        _run_learning_events(args)
    elif action == "export":
        _run_learning_export(args)
    elif action == "import":
        _run_learning_import(args)
    else:
        print(f"Unknown learning action: {action}")


def _get_store():
    from app.core.learning_db import get_learning_store

    return get_learning_store()


def _run_learning_stats(args):
    store = _get_store()
    stats = store.get_stats()
    print("\n  Learning Store Stats\n")
    print(f"  {'Total learnings:':<30} {stats['total']}")
    print(f"  {'Avg confidence:':<30} {stats['avg_confidence']:.3f}")
    print()
    if stats["by_type"]:
        print(f"  {'Type':<25} Count")
        print(f"  {'-' * 35}")
        for type_, count in sorted(stats["by_type"].items()):
            print(f"  {type_:<25} {count}")
    else:
        print("  No learnings recorded yet.")
    print()


def _run_learning_search(args):
    query = " ".join(args.query) if args.query else ""
    if not query:
        print("Usage: raven learning search <query>")
        return
    store = _get_store()
    results = store.search(
        query,
        type_=args.type,
        limit=args.limit,
        min_confidence=args.min_confidence,
    )
    if not results:
        print(f"  No results for '{query}'.")
        return
    print(f"\n  Search results for '{query}' ({len(results)})\n")
    for r in results:
        tag = r["type"].replace("_", " ").title()
        conf = r["confidence"]
        topic = r["topic"] or "(no topic)"
        content = r["content"][:120]
        print(f"  [{tag}] (conf={conf:.2f}) [{topic}]")
        print(f"    {content}")
        print()


def _run_learning_events(args):
    from app.core.learning_events import get_events

    events = get_events(limit=args.limit, kind=args.kind)
    if not events:
        print("  No events.")
        return
    print(f"\n  Recent Events ({len(events)})\n")
    for e in events:
        ts = e["timestamp"][:19]  # ISO format, strip subseconds
        print(f"  {ts}  [{e['kind']:<15}] {e['title']}")
        if e["detail"]:
            print(f"    {e['detail']}")
    print()


def _run_learning_export(args):
    store = _get_store()
    all_rows = store.get_recent(limit=99999)
    output = {
        "version": "export_v1",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "learnings": all_rows,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2, default=str))
        print(f"  Exported {len(all_rows)} learnings to {args.output}")
    else:
        print(json.dumps(output, indent=2, default=str))


def _run_learning_import(args):
    store = _get_store()
    if args.input:
        data = json.loads(Path(args.input).read_text())
    else:
        data = json.loads(sys.stdin.read())
    learnings = data.get("learnings", [])
    # Pre-fetch existing content for cheap dedup (avoid FTS5 column syntax issues)
    existing = {(r["type"], r["content"]) for r in store.get_recent(limit=99999)}
    count = 0
    for item in learnings:
        key = (item.get("type", "unknown"), item.get("content", ""))
        if key in existing:
            continue
        store.add(
            type_=item.get("type", "unknown"),
            content=item.get("content", ""),
            topic=item.get("topic", ""),
            confidence=item.get("confidence", 0.5),
            metadata=json.loads(item["metadata"])
            if isinstance(item.get("metadata"), str)
            else item.get("metadata", {}),
            source=item.get("source", "import"),
        )
        count += 1
    print(f"  Imported {count} learnings ({len(learnings) - count} duplicates skipped).")
