"""app/core/render.py — Platform-specific rich-text renderers.

Converts LLM-produced standard Markdown to each platform's native format:

  • Telegram  → HTML  (parse_mode="HTML")
               Supports <b>, <i>, <u>, <s>, <code>, <pre>, <a href="...">
               All & < > outside tags must be HTML-escaped.

  • Discord   → Discord-flavoured Markdown
               Almost identical to standard Markdown — **bold**, *italic*,
               `inline code`, ```lang\\nblock```, ~~strike~~, > quote.
               Very little conversion needed since LLMs already produce
               standard Markdown.

  • Slack     → mrkdwn
               *bold*, _italic_, ~strike~, `inline`, ```block```.
               Headings become *bold*.  HTML entities &amp; &lt; &gt;
               must be used for literal &, <, >.

All converters are tolerant: on any exception they return the original
plain text so the message is never lost.
"""

from __future__ import annotations

import re


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _extract_code_blocks(
    text: str,
) -> tuple[str, list[str]]:
    """Replace fenced + inline code with numbered placeholders.

    Returns (text_with_placeholders, list_of_original_code_strings).
    Callers process the placeholder text, then restore code afterwards.
    """
    saved: list[str] = []

    def _fence(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"\x00BLK{len(saved) - 1}\x00"

    def _inline(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"\x00BLK{len(saved) - 1}\x00"

    # Fenced code blocks first (greedy on content, non-greedy on fence)
    text = re.sub(r"```[\w]*\n?[\s\S]*?```", _fence, text)
    # Inline code
    text = re.sub(r"`[^`\n]+`", _inline, text)
    return text, saved


def _restore_code_blocks(text: str, saved: list[str]) -> str:
    for i, original in enumerate(saved):
        text = text.replace(f"\x00BLK{i}\x00", original)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM HTML
# ─────────────────────────────────────────────────────────────────────────────

_TG_LIMIT = 4096  # Telegram sendMessage hard limit


def _html_escape(s: str) -> str:
    """Escape &, <, > for Telegram HTML; do NOT double-escape."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_fence_to_html(m: re.Match) -> str:
    lang = (m.group(1) or "").strip()
    code = _html_escape(m.group(2))
    if lang:
        return f'<pre><code class="language-{lang}">{code}</code></pre>'
    return f"<pre>{code}</pre>"


def _md_inline_code_to_html(m: re.Match) -> str:
    return f"<code>{_html_escape(m.group(1))}</code>"


def to_telegram_html(text: str) -> tuple[str, str]:
    """Convert standard Markdown to Telegram HTML.

    Returns ``(rendered_html, parse_mode)`` where *parse_mode* is ``"HTML"``
    on success or ``""`` on failure (falls back to plain text).
    """
    try:
        result = _convert_to_telegram_html(text)
        return result[:_TG_LIMIT], "HTML"
    except Exception:
        return text[:_TG_LIMIT], ""


def _convert_to_telegram_html(text: str) -> str:
    # 1. Pull out code blocks so their content is not touched
    code_blocks: list[str] = []

    def save_fence(m: re.Match) -> str:
        rendered = _md_fence_to_html(m)
        code_blocks.append(rendered)
        return f"\x00TGC{len(code_blocks) - 1}\x00"

    def save_inline(m: re.Match) -> str:
        rendered = _md_inline_code_to_html(m)
        code_blocks.append(rendered)
        return f"\x00TGC{len(code_blocks) - 1}\x00"

    # Fenced blocks: ```lang\ncode\n``` — match lazily across newlines
    text = re.sub(r"```(\w*)\n?([\s\S]*?)```", save_fence, text)
    # Inline code: `...` — no newlines inside
    text = re.sub(r"`([^`\n]+)`", save_inline, text)

    # 2. HTML-escape everything outside code blocks
    text = _html_escape(text)

    # 3. Convert inline Markdown styles (order matters: bold before italic)
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)
    # Italic: *text* (single star, not double) or _text_ (single underscore)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)
    # Headings → bold on their own line
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 4. Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00TGC{i}\x00", block)

    return text


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD MARKDOWN
# ─────────────────────────────────────────────────────────────────────────────

_DC_LIMIT = 1990  # Discord message hard limit is 2000; leave 10 chars headroom


def to_discord_md(text: str) -> str:
    """Prepare text for Discord.

    Discord renders standard Markdown natively (**bold**, *italic*,
    ``inline``, triple-backtick blocks, ~~strike~~, > quote).
    LLM output is already in standard Markdown, so minimal conversion is
    needed.  We only strip any leaked HTML tags and ensure the text fits.
    """
    try:
        result = _convert_to_discord_md(text)
        return result[:_DC_LIMIT]
    except Exception:
        return text[:_DC_LIMIT]


def _convert_to_discord_md(text: str) -> str:
    # Strip any raw HTML tags that might have leaked from templates
    text = re.sub(r"</?(?:b|i|u|s|em|strong|code|pre|br|p)(?:\s[^>]*)?>", "", text)
    # Discord uses standard Markdown — nothing else to convert
    return text


# ─────────────────────────────────────────────────────────────────────────────
# SLACK MRKDWN
# ─────────────────────────────────────────────────────────────────────────────

_SL_LIMIT = 3000  # Slack section-block text limit; use file upload above this


def to_slack_mrkdwn(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn.

    Mapping:
      **bold**  / __bold__  → *bold*
      *italic* / _italic_  → _italic_   (Slack uses underscores)
      ~~strike~~            → ~strike~
      ## Heading            → *Heading*
      ```lang\\ncode\\n```  → kept (Slack renders triple-backtick blocks)
      `inline`              → kept
      &, <, >               → &amp; &lt; &gt;  (Slack requires HTML entities)
    """
    try:
        return _convert_to_slack_mrkdwn(text)
    except Exception:
        return text


def _convert_to_slack_mrkdwn(text: str) -> str:
    # 1. Protect code blocks from other substitutions
    text, saved = _extract_code_blocks(text)

    # 2. Bold: **text** → *text*,  __text__ → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)

    # 3. Italic: *text* (single) → _text_,  _text_ → _text_ (already correct)
    #    We only touch single stars that are not part of a bold pattern.
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", text)
    # _italic_ is already correct for Slack; leave it.

    # 4. Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text, flags=re.DOTALL)

    # 5. Headings → bold on their own line
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # 6. HTML-escape special chars that Slack treats as control characters
    #    (must come AFTER markdown conversions so * _ ~ are still literal)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 7. Restore code blocks (they are already in Slack-compatible format)
    text = _restore_code_blocks(text, saved)

    return text
