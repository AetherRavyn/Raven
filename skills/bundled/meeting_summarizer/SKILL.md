---
name: Meeting Summarizer
module_id: skill.bundled.meeting_summarizer
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "summarize.*meeting"
    confidence: 0.90
  - pattern: "meeting notes"
    confidence: 0.85
  - pattern: "transcript"
    confidence: 0.75
  - pattern: "summarize.*call"
    confidence: 0.80
capabilities: [transcription-analysis, meeting-summary, action-item-extraction, decision-logging]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Meeting Summarizer

Process meeting transcripts or notes into structured summaries with action items and decisions.

## When to Use
This skill activates when the user provides a meeting transcript, recording, or raw notes and asks for a summary. Works with text transcripts, voice note transcriptions, or meeting notes files.

## Procedure

### Step 1: Ingest Content
1. Accept input as: text transcript, audio file (transcribe via STT), or notes file
2. Identify the meeting metadata if present: date, attendees, duration, topic
3. Detect the meeting type: standup, planning, review, client call, 1:1

### Step 2: Extract Structure
Parse the content into sections:
- **Topic/Agenda** — What was meant to be discussed
- **Key Discussion Points** — What was actually discussed
- **Decisions Made** — What was agreed upon
- **Action Items** — Who needs to do what by when
- **Open Questions** — What remains unresolved

### Step 3: Generate Summary
Format as:
```
📝 Meeting Summary — [Meeting Title]
📅 [Date] | 👥 [Attendees] | ⏱ [Duration]

🎯 Topic
[1-2 sentence overview]

💬 Key Points
  • [point 1]
  • [point 2]
  • [point 3]

✅ Decisions
  • [decision 1]
  • [decision 2]

📋 Action Items
  • [@person]: [task] — due [date]
  • [@person]: [task] — due [date]

❓ Open Questions
  • [question 1]
  • [question 2]
```

### Step 4: Save & Share
1. Save summary to a meeting notes file
2. Offer to send summary to attendees via email or messaging
3. Add action items to task tracker

## Example

**Input:** Raw meeting transcript text

**Output:**
```
📝 Meeting Summary — Sprint Planning Week 26
📅 2026-06-22 | 👥 Alice, Bob, Charlie | ⏱ 45 min

🎯 Plan sprint 26 deliverables and assign story points

💬 Key Points
  • Auth module refactor estimated at 13 points
  • API rate limiting is a new requirement from security audit
  • Deployment pipeline needs updating for v2.1 schema changes
  • Team capacity: 47 points available (3 devs × 5 days)

✅ Decisions
  • Auth refactor is sprint top priority
  • Rate limiting to be handled as separate spike (2 pts)
  • Charlie owns the DB migration for v2.1

📋 Action Items
  • @Alice: Write auth refactor ADR — due Wed
  • @Bob: Research rate limiting libraries — due Thu
  • @Charlie: Draft DB migration plan — due Fri

❓ Open Questions
  • When does v2.1 need to ship?
  • Are we using Redis or in-memory for rate limiting?
```

## Lessons Learned
- Action items need explicit owners and dates — never leave them vague
- Decisions are more important than discussion details
- Keep summaries to 1 page max — executives scan
- If transcript is very long (>1h), ask user for key focus areas
