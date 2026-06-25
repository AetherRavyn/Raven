---
name: Research Synthesis
module_id: skill.research_synthesis
version: 1.0.0
category: skill
description: Deep multi-source research with structured report output
tags: [research, synthesis, analysis, report]
enabled_by_default: true
---

# Research Synthesis

## When to Use
Activate when the user asks for in-depth research, competitive analysis,
literature review, or any task requiring multi-source information gathering.

## Procedure

### Step 1: Define Research Scope
1. Identify the core question or topic
2. Determine relevant sub-questions
3. Identify required sources (web, academic, news, code repos)

### Step 2: Multi-Source Search
1. **Web search** via `web_ops` — broad coverage (3-5 queries)
2. **Deep reading** via `web_fetch_ops` — read top 3-5 results fully
3. **GitHub** — if technical topic, search repos and issues
4. **News** — check recent developments if time-sensitive

### Step 3: Analysis
1. Cross-reference findings across sources
2. Identify consensus and disagreements
3. Note data quality and source reliability
4. Flag gaps in available information

### Step 4: Synthesize Report
```
# Research Report: [Topic]

## Executive Summary
[2-3 sentence overview of findings]

## Key Findings
1. [Finding with source citation]
2. [Finding with source citation]
3. [Finding with source citation]

## Detailed Analysis
### [Subtopic 1]
[Analysis with citations]

### [Subtopic 2]
[Analysis with citations]

## Sources
1. [URL] — [brief description]
2. [URL] — [brief description]

## Gaps & Limitations
- [What couldn't be determined]

## Recommendations
1. [Actionable recommendation]
```
