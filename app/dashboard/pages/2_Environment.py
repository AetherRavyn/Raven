"""Environment Configuration page — read/edit .env variables."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SARAS - Environment", page_icon="⚙️", layout="wide")

st.title("Environment Configuration")
st.caption("Edit your .env file. Changes are saved instantly with a backup (.env.bak).")

from app.dashboard.utils import (
    ENV_CATEGORIES,
    ENV_FILE,
    SENSITIVE_KEYS,
    read_env_file,
    read_env_raw,
    update_env_value,
    write_env_raw,
)

# ---------------------------------------------------------------------------
# Mode selector
# ---------------------------------------------------------------------------
mode = st.radio(
    "Edit mode",
    ["Categorized View", "Raw Editor"],
    horizontal=True,
)

if mode == "Categorized View":
    env = read_env_file()

    st.info(
        f"Showing variables from `{ENV_FILE}`. "
        "Sensitive values are masked — click the eye icon to reveal."
    )

    # Track changes
    changes: dict[str, str] = {}

    for category, keys in ENV_CATEGORIES.items():
        with st.expander(f"**{category}**", expanded=False):
            for key in keys:
                current = env.get(key, "")
                is_sensitive = key in SENSITIVE_KEYS

                if is_sensitive:
                    new_val = st.text_input(
                        key,
                        value=current,
                        type="password",
                        key=f"env_{key}",
                        help=f"Current: {'(set)' if current else '(empty)'}",
                    )
                else:
                    new_val = st.text_input(
                        key,
                        value=current,
                        key=f"env_{key}",
                    )

                if new_val != current:
                    changes[key] = new_val

    if changes:
        st.warning(f"You have {len(changes)} unsaved change(s).")
        if st.button("Save Changes", type="primary"):
            for k, v in changes.items():
                update_env_value(k, v)
            st.success(
                f"Saved {len(changes)} change(s). A backup was created at `.env.bak`."
            )
            st.info(
                "Note: Changes to some variables require restarting SARAS to take effect."
            )
            st.rerun()
    else:
        st.success("No changes detected.")

else:
    # Raw editor
    raw = read_env_raw()

    st.warning(
        "Editing the raw .env file directly. Be careful with formatting. "
        "A backup (.env.bak) will be created on save."
    )

    edited = st.text_area(
        "Raw .env contents",
        value=raw,
        height=600,
        key="raw_env_editor",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Raw .env", type="primary"):
            write_env_raw(edited)
            st.success("Saved! Backup created at `.env.bak`.")
            st.info("Note: Restart SARAS for changes to take effect.")
    with col2:
        if st.button("Reset to .env.example"):
            from app.dashboard.utils import ENV_EXAMPLE

            if ENV_EXAMPLE.exists():
                example_raw = ENV_EXAMPLE.read_text(encoding="utf-8")
                write_env_raw(example_raw)
                st.success("Reset to .env.example contents.")
                st.rerun()
            else:
                st.error(".env.example not found.")
