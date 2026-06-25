---
name: Email Triage
module_id: skill.bundled.email_triage
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "check email"
    confidence: 0.85
  - pattern: "email triage"
    confidence: 0.90
  - pattern: "unread"
    confidence: 0.70
  - pattern: "inbox"
    confidence: 0.65
capabilities: [email-reading, email-classification, priority-sorting]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Email Triage

Read, classify, and summarize unread emails, prioritizing urgent messages.

## When to Use
This skill activates when the user asks about their inbox or wants email triage. Requires Gmail API or SMTP IMAP configuration.

## Procedure

### Step 1: Connect & Fetch
1. Call `GmailTool` to fetch unread inbox messages (max 20)
2. For each email, extract: sender, subject, snippet, timestamp
3. Separate into categories: personal, work, newsletter, spam-like

### Step 2: Classify Priority
Classify each email into one of:
- **URGENT** — Time-sensitive (meeting reminders, deadline notices, replies needed today)
- **HIGH** — Requires action this week (project updates, client messages)
- **NORMAL** — Informational (reports, digests, team updates)
- **LOW** — Read-later (newsletters, promotions, notifications)

### Step 3: Summarize
For each priority level, provide a compact summary:
```
📬 Email Triage — [N] unread

🚨 URGENT ([count])
  • [sender]: [subject] ([time])

🔔 HIGH ([count])
  • [sender]: [subject]

📄 NORMAL ([count])
  • [sender]: [subject]

📰 LOW ([count])
  • [sender]: [subject]
```

### Step 4: Action Items
1. Suggest which emails need a reply
2. Offer to draft replies for urgent/high items
3. Ask if user wants to archive or mark as read the rest

## Example

**Output:**
```
📬 Email Triage — 12 unread

🚨 URGENT (2)
  • Alice Chen: "Deployment blocked — please review" (15m ago)
  • GitHub: "Pipeline failed: sprint-23" (8m ago)

🔔 HIGH (3)
  • Bob: "Q3 budget proposal draft" (1h ago)
  • Jira: "2 tickets assigned to you" (2h ago)
  • Design team: "Mockups for review" (3h ago)

📄 NORMAL (4)
  • Weekly CI report, Standup notes, LGTM bot, PR review request

📰 LOW (3)
  • Stack Overflow digest, Product newsletter, Company all-hands recording

Actions:
  1. Reply to Alice about deployment block?
  2. Check failed pipeline on GitHub?
  3. Archive 5 read-later items?
```

## Lessons Learned
- Never mark emails as read without user permission
- Use sender domain + subject keywords for priority heuristics
- Personal emails from known contacts get elevated priority
- Newsletters with same sender can be collapsed
