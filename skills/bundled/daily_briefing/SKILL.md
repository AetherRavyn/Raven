---
name: Daily Briefing
module_id: skill.bundled.daily_briefing
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "daily briefing"
    confidence: 0.90
  - pattern: "good morning"
    confidence: 0.60
  - pattern: "what.*today"
    confidence: 0.70
  - pattern: "brief me"
    confidence: 0.75
capabilities: [briefing, calendar-summary, weather-check, task-review]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Daily Briefing

Deliver a consolidated morning briefing with calendar, weather, tasks, and news.

## When to Use
This skill runs on a scheduled cron or when the user says "good morning" or "daily briefing". It gathers context from multiple sources and presents a structured morning report.

## Procedure

### Step 1: Gather Calendar Events
1. Call `GoogleCalendarTool` with operation `list_events` for today
2. Extract event names, times, locations, and attendees
3. Note any events starting within the next hour as "upcoming"

### Step 2: Check Weather
1. Call `WeatherTool` with the user's default location
2. Get current conditions, high/low temperature, and precipitation chance
3. Note any weather alerts or extreme conditions

### Step 3: Review Tasks & Reminders
1. Call `TaskInboxStore` or `TodoListTool` to get pending tasks
2. Identify any overdue or due-today tasks
3. Check `ReminderTool` for time-sensitive items

### Step 4: News Headlines (Optional)
1. If configured, call `NewsTool` or `WebSearch` for top 3 headlines
2. Focus on topics relevant to the user's interests

### Step 5: Compose Briefing
Format as:
```
☀️ Good morning — [day of week], [date]

📅 Calendar ([N] events)
  • [time] — [event name] ([location/attendees])

🌤 Weather
  • [condition], [temp]°C, high [high]°C / low [low]°C

📋 Tasks ([N] pending)
  • [priority] — [task name] ([due])

📰 In Brief
  • [headline 1]
```

## Example

**Output:**
```
☀️ Good morning — Monday, June 22

📅 Calendar (3 events)
  • 10:00 AM — Sprint Planning (Engineering)
  • 2:00 PM — Client Call w/ Acme Corp
  • 4:30 PM — Gym

🌤 Weather
  • Partly cloudy, 22°C, high 26°C / low 18°C

📋 Tasks (5 pending)
  • HIGH — Deploy v2.1 to staging (due today)
  • MED — Review PR #342
  • LOW — Update README

📰 In Brief
  • AI chip stocks rally on new export rules
  • Python 3.13 release candidate announced
```

## Lessons Learned
- Keep it concise — the user scans, not reads
- Calendar events are highest value, put them first
- Skip news if user seems rushed (< 3 word query)
- Cache weather data for 30 min to avoid API spam
