"""Tool → DataClass mapping for runtime consent checks (Day 20).

Maps each registered tool name to the :class:`DataClass` whose
consent must be ``ALLOW`` (or ``AUTO_PURGE``) for the tool to
execute.  Unknown tools default to ``PROFILE`` (lowest-risk) so
the runtime is never accidentally fail-open.

The mapping is intentionally conservative — when in doubt, the
runtime requires explicit consent.
"""

from __future__ import annotations

from app.core.privacy.consent import DataClass

# Tool name → DataClass
TOOL_DATA_CLASS: dict[str, DataClass] = {
    # Filesystem
    "file_read": DataClass.FILES,
    "file_write": DataClass.FILES,
    "file_list": DataClass.FILES,
    "file_delete": DataClass.FILES,
    "file_operations": DataClass.FILES,
    "fs_read": DataClass.FILES,
    "fs_write": DataClass.FILES,
    "read_file": DataClass.FILES,
    "write_file": DataClass.FILES,
    # Shell (highest risk)
    "shell": DataClass.FILES,
    "bash": DataClass.FILES,
    "exec": DataClass.FILES,
    # Calendar
    "calendar_read": DataClass.CALENDAR,
    "calendar_write": DataClass.CALENDAR,
    "calendar_event": DataClass.CALENDAR,
    "add_calendar_event": DataClass.CALENDAR,
    "get_calendar": DataClass.CALENDAR,
    # Email
    "email_send": DataClass.EMAIL,
    "email_read": DataClass.EMAIL,
    "gmail_send": DataClass.EMAIL,
    "gmail_read": DataClass.EMAIL,
    "gmail": DataClass.EMAIL,
    # Contacts
    "contacts_read": DataClass.CONTACTS,
    "contacts_write": DataClass.CONTACTS,
    "contact_lookup": DataClass.CONTACTS,
    # Location
    "location": DataClass.LOCATION,
    "geolocate": DataClass.LOCATION,
    "weather": DataClass.LOCATION,
    # Conversation
    "memory_search": DataClass.CONVERSATION,
    "memory_store": DataClass.CONVERSATION,
    "memory_recall": DataClass.CONVERSATION,
    "remember": DataClass.CONVERSATION,
    # Health
    "health_read": DataClass.HEALTH,
    "fitbit": DataClass.HEALTH,
    "heart_rate": DataClass.HEALTH,
    # Financial
    "finance_read": DataClass.FINANCIAL,
    "stock_price": DataClass.FINANCIAL,
    "budget_read": DataClass.FINANCIAL,
    "budget_write": DataClass.FINANCIAL,
    # Credentials
    "vault_read": DataClass.CREDENTIALS,
    "vault_write": DataClass.CREDENTIALS,
    "secret_read": DataClass.CREDENTIALS,
    "secret_write": DataClass.CREDENTIALS,
    # Analytics
    "analytics": DataClass.ANALYTICS,
    "metrics": DataClass.ANALYTICS,
    # Profile
    "profile_read": DataClass.PROFILE,
    "profile_write": DataClass.PROFILE,
}

DEFAULT_DATA_CLASS = DataClass.PROFILE


def data_class_for(tool_name: str) -> DataClass:
    """Return the :class:`DataClass` that owns ``tool_name``."""
    if not tool_name:
        return DEFAULT_DATA_CLASS
    key = tool_name.strip().lower()
    if key in TOOL_DATA_CLASS:
        return TOOL_DATA_CLASS[key]
    # Allow short suffix matches — e.g. ``gmail_send_message`` → EMAIL.
    for prefix, dc in TOOL_DATA_CLASS.items():
        if key.startswith(f"{prefix}_") or key.endswith(f"_{prefix}"):
            return dc
    return DEFAULT_DATA_CLASS


__all__ = ["TOOL_DATA_CLASS", "DEFAULT_DATA_CLASS", "data_class_for"]
