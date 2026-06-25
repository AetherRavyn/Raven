---
name: Weekly Review
module_id: skill.weekly_review
version: 1.0.0
category: skill
description: End-of-week retrospective with progress review and next-week planning
tags: [review, weekly, retrospective, productivity, planning]
enabled_by_default: true
---

# Weekly Review

## When to Use
Triggered every Friday afternoon (scheduled), or on-demand when user asks
for a "weekly review", "week summary", or "retrospective".

## Procedure

### Step 1: Gather Week Data
1. Review completed tasks from `todo_list`
2. Check interaction history and skill usage
3. Review calendar for meetings attended
4. Check git commits for development progress

### Step 2: Compile Review
```
## 📊 Weekly Review — Week of [Date]

### ✅ Completed This Week
- [Task/project 1]
- [Task/project 2]
- [Task/project 3]

### 🔄 In Progress
- [Ongoing task with progress %]

### ❌ Didn't Get To
- [Deferred task → moved to next week]

### 💡 Insights & Learnings
- [New skill learned]
- [Pattern observed]
- [Process improvement discovered]

### 📈 Stats
- Interactions: [count]
- Tools used: [count]
- Skills invoked: [count]
- Tasks completed: [count]

### 📋 Plan for Next Week
1. [Priority 1]
2. [Priority 2]
3. [Priority 3]

### 🎯 Goals Progress
- [Goal 1]: [progress %]
- [Goal 2]: [progress %]
```
