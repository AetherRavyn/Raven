# RAVEN nightly-eval timer — install + operations

This document covers the operational side of the nightly-eval cron
that ships with RAVEN. The **code** side (`scripts/nightly_eval.py`,
`scripts/regression_gate.py`, `scripts/rotate_eval_reports.py`) is
already covered by `tests/test_phase8_eval_drift.py` and the new
`tests/test_rotate_eval_reports.py`. This file is the install +
verification guide for an operator.

## What runs, in what order

The timer triggers a single systemd `oneshot` service
(`raven-nightly-eval.service`) which runs four Python scripts in
sequence:

| Step | Script | Purpose |
|---|---|---|
| 1 | `scripts/nightly_eval.py --runner stub` | Run the 30-prompt eval set; write a fresh `nightly_report.json` |
| 2 | `scripts/regression_gate.py` | Compare the new report against the frozen `baseline.json`; write a markdown verdict for the dashboard |
| 3 | `scripts/eval_to_prom.py` | Convert the report + baseline + verdict into a Prometheus textfile payload (consumed by the textfile collector) |
| 4 | `scripts/rotate_eval_reports.py` | Prune archive reports older than the retention window |

Each step's exit code is captured in the systemd journal. A
non-zero exit on step 1 propagates (the timer sees the failure
and records it in the journal). Steps 2–4 are best-effort
(`|| true`) — a regression-fail, a Prometheus-emit error, or a
prune error must not block the timer's next run.

## Install (systemd, root)

```bash
# 1. Drop the unit + timer into the system location
install -m 0644 monitoring/nightly-eval.service /etc/systemd/system/
install -m 0644 monitoring/nightly-eval.timer   /etc/systemd/system/

# 2. Reload systemd so it sees the new units
systemctl daemon-reload

# 3. Enable + start the timer (the service is a oneshot, so it's
#    triggered by the timer, not started directly)
systemctl enable --now raven-nightly-eval.timer
```

The service runs as user `raven` group `raven` from
`/home/raven/RAVEN`. If your checkout lives elsewhere, edit
`WorkingDirectory` and the `Environment=` lines in
`monitoring/nightly-eval.service` before installing.

## Verify it's armed

```bash
# When does it next fire?
systemctl list-timers raven-nightly-eval.timer

# Show the unit's status (no active sessions is normal — it's a
# oneshot that runs briefly and exits)
systemctl status raven-nightly-eval.service

# Force an out-of-band run (useful after install to confirm wiring)
systemctl start raven-nightly-eval.service
journalctl -u raven-nightly-eval.service -n 50 --no-pager
```

## What gets written

| Path | Producer | Contents |
|---|---|---|
| `/home/raven/RAVEN/workspace/eval/nightly_report.json` | Step 1 | The fresh eval report (overwritten each run) |
| `/home/raven/RAVEN/workspace/eval/regression.md` | Step 2 | Markdown verdict (PASS / FAIL badge + deltas) |
| `/home/raven/RAVEN/workspace/eval/eval_metrics.prom` | Step 3 | Prometheus textfile payload (consumed by the Prometheus textfile collector; see `monitoring/prometheus.yml`) |
| `/home/raven/RAVEN/workspace/eval/baseline.json` | (frozen) | The baseline the gate compares against. Update manually when a release ships |
| `/home/raven/RAVEN/workspace/eval/archive/` | (recommended layout for step 4) | Per-day buckets, each containing one or more reports. Step 4 prunes any bucket whose newest report is older than `NIGHTLY_RETENTION_DAYS` |

## Setting up the archive layout

The retention script supports two layouts: **flat** (a single
directory of `*.json` files) and **archived** (per-day subdirs).
The systemd unit points at `workspace/eval/archive/` so the
recommended workflow is:

```bash
mkdir -p workspace/eval/archive
# After the first nightly run lands a fresh nightly_report.json,
# move it into a date bucket:
mv workspace/eval/nightly_report.json workspace/eval/archive/$(date -u +%F)/
```

The freshest report always lives at the top-level
`workspace/eval/nightly_report.json` (the timer's
`NIGHTLY_OUTPUT` env var). Move it into `archive/YYYY-MM-DD/`
once the gate has finished running.

## Smoke-test (no systemd)

To run the same four steps by hand (e.g. from a laptop while
debugging):

```bash
.venv/bin/python scripts/nightly_eval.py \
    --output workspace/eval/nightly_report.json \
    --runner stub

.venv/bin/python scripts/regression_gate.py \
    --baseline workspace/eval/baseline.json \
    --current  workspace/eval/nightly_report.json \
    --markdown-output workspace/eval/regression.md

.venv/bin/python scripts/eval_to_prom.py \
    --report workspace/eval/nightly_report.json \
    --baseline workspace/eval/baseline.json \
    --regression-md workspace/eval/regression.md \
    --archive workspace/eval/archive \
    --output workspace/eval/eval_metrics.prom

.venv/bin/python scripts/rotate_eval_reports.py \
    --dir workspace/eval/archive \
    --keep-days 14 \
    --verbose
```

## Customising

| Knob | Where | Default | Why |
|---|---|---|---|
| `--keep-days` | `rotate_eval_reports.py` CLI / `NIGHTLY_RETENTION_DAYS` env | 14 | Longer windows are useful for trend analysis; shorter windows save disk on flash storage |
| `--runner` | `nightly_eval.py` CLI / systemd `ExecStart` | `stub` | `stub` is offline + deterministic; `orchestrator` is a placeholder that also calls stub today |
| `OnCalendar` | `nightly-eval.timer` | `03:15` daily | After midnight (so yesterday's data is finalised), before 04:00 (so the morning briefing can include the verdict) |
| `Persistent` | `nightly-eval.timer` | `true` | Catches missed runs after a sleep/suspend; without this, an asleep laptop skips a night's eval entirely |
| `MemoryMax` / `CPUQuota` | `nightly-eval.service` | 512M / 80% | The eval is small; these are generous but bounded |

## Uninstall

```bash
systemctl disable --now raven-nightly-eval.timer
rm /etc/systemd/system/raven-nightly-eval.{service,timer}
systemctl daemon-reload
```

The eval reports under `workspace/eval/` are left in place —
delete them by hand if you want to clear the history.

## Why a systemd timer and not a cron entry?

systemd timers give us four properties cron doesn't, all of which
matter for a self-hosted personal assistant:

  * **Journal integration** — every run logs to the systemd
    journal with the `SyslogIdentifier=raven-nightly-eval` tag;
    `journalctl -u raven-nightly-eval.service` shows the history.
  * **`Persistent=true` catches missed runs** — cron skips if the
    host was asleep; the timer catches up on next boot.
  * **Hardened service unit** — `NoNewPrivileges`,
    `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`
    give us a sandbox for free that a `crontab` entry doesn't.
  * **Three-step `ExecStartPost` chain** — the eval, the gate,
    and the rotation all share one timer and one log stream. A
    cron file would need three separate entries with their own
    ordering and failure handling.

A vanilla `crontab` entry remains a viable fallback if the host
runs a non-systemd init. The script `scripts/nightly_eval.cron`
captures the equivalent crontab line for that case (kept here as
a comment so it's easy to copy out):

```cron
# Nightly eval at 03:15 every day.  Run the three scripts in
# sequence; ignore non-zero exits from steps 2 + 3 so the next
# night's run still fires.
15 3 * * * cd /home/raven/RAVEN && .venv/bin/python scripts/nightly_eval.py --runner stub >/dev/null 2>&1 && .venv/bin/python scripts/regression_gate.py --baseline workspace/eval/baseline.json --current workspace/eval/nightly_report.json || true
```