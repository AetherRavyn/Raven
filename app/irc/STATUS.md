# IRC Connector — STUB

**Status:** Not implemented (stub).
**Last verified:** 2026-06-18

This directory exists to make the package layout importable, but the
connector itself is **not implemented**. Do not list IRC in any user-
facing "supported channels" list until this STATUS is removed.

To implement:
1. Add `irc` or `pydle` to `pyproject.toml`.
2. Add `app/irc/ircapp.py` with an `IrcBot` class exposing
   `start_bot()` and `stop_bot()`.
3. Wire it into `main.py` following the Discord pattern.
4. Add a `config.validate()` rule that requires `IRC_SERVER`,
   `IRC_NICK`, `IRC_CHANNELS` when enabled.
5. Remove this STATUS.md.

The audit script `scripts/audit_channel_truths.py` will fail CI until
this is either implemented or its STATUS.md is updated to reflect the
truth.
