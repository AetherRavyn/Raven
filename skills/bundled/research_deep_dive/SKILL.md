---
name: Research Deep Dive
module_id: skill.bundled.research_deep_dive
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "deep dive.*topic"
    confidence: 0.90
  - pattern: "research.*thorough"
    confidence: 0.85
  - pattern: "comprehensive.*analysis"
    confidence: 0.80
  - pattern: "investigate"
    confidence: 0.75
capabilities: [deep-research, multi-source-synthesis, report-generation, competitive-analysis]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Research Deep Dive

Conduct thorough multi-source research on a topic and produce a structured report.

## When to Use
This skill activates when the user asks for deep research on a topic — not just a quick search but a comprehensive analysis across multiple sources, perspectives, and formats.

## Procedure

### Step 1: Define Scope
1. Confirm the exact research question with the user
2. Define subtopics to cover (3-5 key aspects)
3. Set depth: quick overview (5 min) vs full deep dive (30+ min)
4. Note any specific sources or formats the user prefers

### Step 2: Multi-Source Gathering
Use multiple search strategies in parallel:
1. **Web search** — `WebSearch` for broad coverage (5+ queries)
2. **News** — `NewsTool` for recent developments (last 30 days)
3. **Academic/specialized** — `WolframTool` for data, `SearXNG` for tech
4. **Social/community** — `RedditTool`, `HackerNewsTool` for discussion
5. **Deep content** — `WebFetch` on top 5-10 results for detailed content

### Step 3: Analyze & Synthesize
1. Identify key themes, claims, and data points
2. Cross-reference information across sources
3. Note contradictions or areas of uncertainty
4. Extract supporting evidence (quotes, data, citations)
5. Detect emerging patterns or consensus views

### Step 4: Compose Report
Format as a structured markdown report:
```
# [Topic] — Research Report
📅 [Date] | 🔍 [N] sources consulted

## Executive Summary
[3-5 bullet key findings]

## Key Findings
### [Subtopic 1]
- Finding with supporting evidence [source]
- Data point or statistic [source]

### [Subtopic 2]
...

## Analysis
[Your synthesis — patterns, implications, conflicts]

## Sources
1. [Title] — [URL] — [key takeaway]
2. [Title] — [URL] — [key takeaway]
```

### Step 5: Deliver
1. Present the report to the user
2. Highlight the most important finding
3. Offer to go deeper on any subtopic
4. Save the report to workspace if desired

## Example

**Input:** `deep dive: Rust vs Go for cloud services in 2026`

**Output:** *(abridged)*
```
# Rust vs Go for Cloud Services — Research Report
📅 2026-06-22 | 🔍 12 sources consulted

## Executive Summary
- Go dominates cloud infrastructure tooling (Docker, K8s, Terraform)
- Rust gaining fast in latency-critical and safety-critical paths
- Both are production-viable; choice depends on team and perf needs

## Key Findings
### Performance
- Rust: ~2-5x faster for compute-heavy workloads [benchmark link]
- Go: faster compile times, simpler deployment [source]

### Ecosystem
- Go: mature cloud SDKs (AWS, GCP, Azure), 1.5M+ packages
- Rust: growing fast, 200K+ crates, WASM-first design

### Team Productivity
- Go: shallow learning curve, "boring" = predictable
- Rust: steep curve, but catches many bugs at compile time

## Analysis
For a new cloud service, Go is the pragmatic choice unless you need
maximum performance or memory safety guarantees. Rust excels for
network proxies, auth systems, and database engines.

## Sources
1. "2026 Cloud Language Survey" — [url] — Go #1, Rust #3
2. "Rust in Production at Cloudflare" — [url] — 60% less CPU usage
...
```

## Lessons Learned
- 5 web searches with different phrasings > 1 deep search
- Cross-reference before trusting any single source
- Separate facts from opinions in the report
- Include publication dates — stale info is worse than no info
- Always ask user if they want more depth on specific findings
