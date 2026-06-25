---
name: Health Coach
module_id: skill.bundled.health_coach
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "log.*sleep|slept"
    confidence: 0.85
  - pattern: "log.*exercise|workout"
    confidence: 0.85
  - pattern: "health.*summary|health.*stats"
    confidence: 0.80
capabilities: [health-tracking, trend-analysis, wellness-coaching]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Health Coach

Track and analyze sleep, exercise, nutrition, and mood with trend insights.

## When to Use
User logs a health metric ("slept 7 hours", "ran 5k", "had 2000 calories") or asks about their health data ("how's my sleep been?", "health summary").

## Procedure

### Step 1: Parse Health Data
1. Detect entry type from context (sleep/exercise/nutrition/mood/weight)
2. Extract numeric value and unit
3. Extract metadata (e.g., exercise type, meal items)

### Step 2: Log Entry
Use `health_tracker` with operation `log`:
- Sleep: value=hours, unit=hours, metadata={quality: good/fair/poor}
- Exercise: value=duration, unit=minutes, metadata={type, calories}
- Nutrition: value=calories, unit=kcal, metadata={meal, items}
- Mood: value=1-10, unit=score
- Weight: value=kg, unit=kg

### Step 3: Provide Insights
When user asks about trends:
1. Call `health_tracker` with operation `trends` or `stats`
2. Highlight week-over-week changes
3. Note concerning patterns (e.g., declining sleep, missed exercise)

### Step 4: Nudge
If patterns show health risk (poor sleep streak, no exercise in 5+ days), proactively suggest improvements.

## Example
**User:** "Slept 5 hours last night, feeling tired"
**Raven:** Logs sleep entry, checks recent sleep average, notes the drop below 7h threshold, suggests tips for better sleep hygiene.
