---
name: System Health Check
module_id: skill.bundled.system_health_check
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "system health"
    confidence: 0.90
  - pattern: "health check"
    confidence: 0.85
  - pattern: "server status"
    confidence: 0.80
  - pattern: "is everything.*running"
    confidence: 0.75
capabilities: [system-monitoring, process-check, disk-usage, service-status]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# System Health Check

Run comprehensive system diagnostics: CPU, memory, disk, network, and critical services.

## When to Use
This skill activates when the user asks about system health, server status, or performance. It runs both passive checks (reading stats) and active checks (pinging services, testing connectivity).

## Procedure

### Step 1: System Resources
1. Call `SystemStatsTool` for:
   - CPU: per-core usage %, load average (1m, 5m, 15m)
   - Memory: used/total/available RAM, swap usage
   - Disk: used/total per mount point, inode usage
   - Uptime: days since last boot
2. Flag any value exceeding warning threshold (CPU > 80%, disk > 85%, memory > 90%)

### Step 2: Process & Service Check
1. List top 5 processes by CPU and memory consumption
2. Check critical services: Docker, SSH, Nginx (if present), database
3. Report any stopped or unhealthy services

### Step 3: Network Connectivity
1. Call `NetworkTool.internet_test` to verify WAN connectivity
2. Check local network interfaces status (up/down)
3. Test DNS resolution (resolve google.com)
4. Measure latency to common endpoints

### Step 4: Docker Health (if applicable)
1. Call `DockerTool.list_containers` to check running containers
2. Report restart counts, uptime, and resource usage per container
3. Flag containers with health status "unhealthy" or "restarting"

### Step 5: Compose Report
```
🖥 System Health Report — [hostname]
⏱ Uptime: [X days, Y hours]

🔧 System Resources
  CPU: [X]% avg (⚠ if > 80)
  Memory: [used]/[total] GB ([X]%) (⚠ if > 90)
  Disk [/]: [used]/[total] GB ([X]%) (⚠ if > 85)

📊 Top Processes
  • [pid] [process] — [X]% CPU, [Y]% MEM

🐳 Docker (N containers)
  • [container] — [status] (up X days)

🌐 Network
  Internet: ✅ Connected / ❌ Disconnected
  Latency: [X]ms to 1.1.1.1
```

## Example

**Output:**
```
🖥 System Health Report — devbox
⏱ Uptime: 12 days, 4 hours

🔧 System Resources
  CPU: 23% avg ✅
  Memory: 6.2/16 GB (39%) ✅
  Disk [/]: 85/256 GB (33%) ✅
  Disk [/data]: 420/500 GB (84%) ⚠ approaching limit

📊 Top Processes
  • 2341 python — 12% CPU, 8% MEM
  • 1567 dockerd — 4% CPU, 3% MEM
  • 892 postgres — 2% CPU, 5% MEM

🐳 Docker (6 containers)
  • raven-web — running ✅
  • redis-cache — running ✅
  • postgres-db — running ✅

🌐 Network
  Internet: ✅ Connected
  Latency: 12ms to 1.1.1.1

Summary: System healthy. /data disk may need cleanup soon.
```

## Lessons Learned
- Always check disk inodes — full inodes crash services even with free space
- Swap usage > 10% indicates memory pressure
- Docker restart counts > 3 in 24h = likely issue
- Check /var/log for OOM killer messages when memory is high
