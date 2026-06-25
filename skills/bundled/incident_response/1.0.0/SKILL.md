---
name: Incident Response
module_id: skill.incident_response
version: 1.0.0
category: skill
description: Real-time incident handling with diagnosis, containment, and post-mortem
tags: [incident, response, security, monitoring, emergency]
enabled_by_default: true
---

# Incident Response

## When to Use
Activate immediately when:
- Monitoring alerts fire
- User reports "system down", "service crashed", etc.
- Sentinel Bridge detects anomalies
- Health checks fail

## Procedure

### Step 1: Triage (< 2 minutes)
1. Identify affected service/system
2. Determine severity (P1-P4)
3. Check if it's a known issue pattern

### Step 2: Diagnose (< 5 minutes)
1. Check system stats (CPU, memory, disk, network)
2. Review recent logs for errors
3. Check Docker container status
4. Verify network connectivity
5. Check recent deployments or config changes

### Step 3: Contain
1. If spreading: isolate affected service
2. If traffic-related: enable rate limiting
3. If security: block suspicious IPs/users
4. Redirect traffic to healthy instances

### Step 4: Fix
1. Apply the appropriate fix based on diagnosis
2. Restart services if needed
3. Rollback recent changes if they caused the issue
4. Verify fix resolves the problem

### Step 5: Post-Mortem
```
## Incident Report — [Date] [Time]

**Severity**: P[1-4]
**Duration**: [start] to [end] ([minutes] minutes)
**Impact**: [what was affected]

### Timeline
- [time] — Issue detected
- [time] — Diagnosis began
- [time] — Root cause identified
- [time] — Fix applied
- [time] — Service restored

### Root Cause
[Detailed explanation]

### Resolution
[What was done to fix it]

### Prevention
1. [Action item to prevent recurrence]
```
