---
name: Code Explain
module_id: skill.bundled.code_explain
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "explain.*code"
    confidence: 0.90
  - pattern: "what does this code do"
    confidence: 0.90
  - pattern: "how does.*work"
    confidence: 0.80
  - pattern: "understand.*function"
    confidence: 0.75
capabilities: [code-analysis, code-explanation, algorithm-understanding]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Code Explain

Analyze and explain source code in plain language, from single functions to entire modules.

## When to Use
This skill activates when the user pastes code or references a file and asks for an explanation. It reads the code, analyzes its structure, and produces a clear explanation suitable for the user's skill level.

## Procedure

### Step 1: Read & Scope
1. If file path given: read the file with `FileTool`
2. If code pasted directly: use the provided text
3. Determine scope: single function, class, module, or multi-file
4. Detect language and paradigm (OOP, functional, procedural)

### Step 2: Analyze Structure
For the given code:
1. **Purpose** — What does this code accomplish? (1 sentence)
2. **Input/Output** — What goes in, what comes out?
3. **Flow** — Step-by-step walkthrough of the logic
4. **Key Patterns** — Notable algorithms, design patterns, idioms
5. **Dependencies** — External libraries, APIs, or services used

### Step 3: Compose Explanation
Tailor the depth to what the user needs:
- **High-level** (1 paragraph) — For quick understanding
- **Detailed** (walkthrough) — For deep comprehension
- **Line-by-line** — For debugging or learning

### Step 4: Additional Insights
1. Identify potential bugs or edge cases not handled
2. Suggest optimizations if any are obvious
3. Note any non-idiomatic patterns for the language
4. Offer to generate docstrings or comments

## Example

**Input:** Explain this Python function:
```python
def rate_limiter(max_requests: int, window_seconds: int):
    requests = []
    def wrapper(fn):
        def inner(*args, **kwargs):
            now = time.time()
            requests[:] = [r for r in requests if now - r < window_seconds]
            if len(requests) >= max_requests:
                raise RateLimitError("Too many requests")
            requests.append(now)
            return fn(*args, **kwargs)
        return inner
    return wrapper
```

**Output:**
```
🔍 Code Explanation — rate_limiter (decorator factory)

Purpose: Creates a rate-limiting decorator that allows max N calls per time window.

Flow:
  1. `rate_limiter(max_requests, window_seconds)` — Configures the limit
  2. Maintains a list of timestamps across calls (closure over `requests`)
  3. On each call, filters out expired timestamps (outside the window)
  4. If count ≥ max: raises RateLimitError
  5. Otherwise: records timestamp, calls the original function

Pattern: Decorator + closure pattern. Uses list mutation (`requests[:]`) 
         instead of reassignment to persist across wrapper calls.

⚠ Note: This is not thread-safe (use a lock or Redis for production).
✅ Suggestion: Consider using collections.deque for O(1) popleft.
```

## Lessons Learned
- Tailor complexity to how the user asked — "wtf does this do" = simple
- For beginners, explain concepts (decorator, closure) along with the code
- For experts, skip the basics and focus on edge cases and perf
- Always mention thread safety if the code isn't
- Point out non-obvious side effects (mutating inputs, global state)
