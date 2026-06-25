---
name: Morning Briefing
module_id: skill.morning_briefing
version: 1.0.0
category: skill
description: Comprehensive daily morning report
tags: [briefing, morning, weather, calendar, news, productivity]
enabled_by_default: true
---

# Morning Briefing

## When to Use
Triggered automatically at the user's configured morning time, or on-demand when
the user asks "what's happening today" or "morning briefing".

## Procedure

### Step 1: Gather Data
1. **Weather**: Get current conditions and forecast using `weather_tool`
2. **Calendar**: Check today's events using `google_calendar`
3. **Tasks**: Review pending todos using `todo_list`
4. **News**: Get top headlines using `rss_reader` or `web_ops`
5. **Portfolio**: Check market movers if configured using `finance_ops`

### Step 2: Compose Briefing
Format as a structured morning report:

```
☀️ Good morning, [Name]! Here's your briefing for [Date]:

🌤️ Weather: [conditions], [temp]°. [forecast note]

📅 Calendar:
- [time] — [event 1]
- [time] — [event 2]
- No meetings this afternoon

📋 Tasks (3 pending):
- [high priority task]
- [normal task]
- [normal task]

📰 Headlines:
- [headline 1]
- [headline 2]

💼 Markets: [brief summary if enabled]

Have a great day! 🚀
```

### Step 3: Deliver
- Voice channel: Speak the briefing aloud
- Chat channel: Send as formatted message
- Respect "do not disturb" settings
